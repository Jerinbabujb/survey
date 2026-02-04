import asyncio
import secrets
import uuid
from datetime import datetime
from sqlalchemy.orm import joinedload
import datetime as dt
from typing import Optional, List

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import selectinload

from app import models
from app.config import settings
from app.db import Base, engine, get_session
from app.email import send_email
from app.security import get_password_hash, hash_token, verify_password
from app.utils import QUESTIONS,hash_token,  CLIENT_QNS, TEAM_QNS, SCORES, management_score_category, management_score_description, client_score_category, client_score_description, team_score_category, team_score_description
from fastapi import Query

from app.models import Employee, EmployeeSubmission, SurveyResponse
from sqlalchemy import join
from sqlalchemy import distinct
from fastapi import UploadFile, File, Form, HTTPException



app = FastAPI(title="Anonymous Survey")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="admin_session", https_only=False)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


SURVEY_CATEGORY_FUNC = {
    "MSES": (management_score_category, management_score_description),
    "ICSES": (client_score_category, client_score_description),
    "TSES": (team_score_category, team_score_description),
}

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.on_event("startup")
async def startup_event():
    await init_db()
    async with AsyncSession(engine) as session:
        await ensure_admin_user(session)
        await ensure_smtp_settings(session)
        await ensure_department_heads(session)
        await session.commit()


async def ensure_admin_user(session: AsyncSession) -> None:
    result = await session.execute(select(models.AdminUser))
    admin = result.scalars().first()
    if admin:
        return
    admin_user = models.AdminUser(
        email=settings.admin_email,
        password_hash=get_password_hash(settings.admin_password),
    )
    session.add(admin_user)


async def ensure_smtp_settings(session: AsyncSession) -> None:
    result = await session.execute(select(models.SMTPSettings))
    settings_row = result.scalars().first()
    if settings_row:
        return
    settings_row = models.SMTPSettings(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
        from_email=settings.smtp_from_email,
        from_name=settings.smtp_from_name,
    )
    session.add(settings_row)


async def ensure_department_heads(session: AsyncSession) -> None:
    result = await session.execute(select(func.count(models.DepartmentHead.id)))
    count = result.scalar_one()
    if count > 0:
        return
    session.add_all(
        [
            models.DepartmentHead(display_name="Operations"),
            models.DepartmentHead(display_name="Engineering"),
            models.DepartmentHead(display_name="People"),
        ]
    )


def get_admin_user(request: Request) -> Optional[int]:
    return request.session.get("admin_user_id")


def require_admin(request: Request) -> int:
    admin_id = get_admin_user(request)
    if not admin_id:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/admin/login"})
    return admin_id


async def get_smtp(session: AsyncSession) -> models.SMTPSettings:
    result = await session.execute(select(models.SMTPSettings).limit(1))
    settings_row = result.scalars().first()
    if not settings_row:
        raise HTTPException(status_code=500, detail="SMTP settings not initialized")
    return settings_row


@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse("/admin/login")


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": None})


@app.post("/admin/login")
async def admin_login(request: Request, email: str = Form(...), password: str = Form(...), session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(models.AdminUser).where(models.AdminUser.email == email))
    admin = result.scalars().first()
    error = None
    if not admin or not verify_password(password, admin.password_hash):
        error = "Invalid credentials"
        return templates.TemplateResponse("admin/login.html", {"request": request, "error": error}, status_code=400)
    request.session["admin_user_id"] = admin.id
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


from sqlalchemy import select, func, distinct
from app.models import Employee, EmployeeSubmission, SurveyResponse, DepartmentHead

from sqlalchemy import func, distinct, select

from app.utils import SURVEY_DETAILS, management_score_category, client_score_category, team_score_category

from sqlalchemy import or_

from sqlalchemy import select, func, or_
from app.utils import SURVEY_DETAILS, normalize_survey_name
from app.utils import (
    SURVEY_DETAILS, 
    management_score_category, 
    client_score_category, 
    team_score_category
)


from fastapi import Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from app import models
from app.utils import management_score_category, client_score_category, team_score_category


from sqlalchemy import select, func
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app import models
from app.utils import SURVEY_DETAILS, management_score_category, client_score_category, team_score_category

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    GRADING_MAP = {
        "MSES": management_score_category,
        "ICSES": client_score_category,
        "TSES": team_score_category,
    }

    survey_stats = {}

    for s_key, s_info in SURVEY_DETAILS.items():
        grading_func = GRADING_MAP.get(s_key)

        # 1. Get Assignment Stats (Total assigned vs Pending)
        assign_stmt = select(models.SurveyAssignment).where(models.SurveyAssignment.survey_name == s_key)
        assignments = (await session.execute(assign_stmt)).scalars().all()
        if not assignments: 
            continue

        # 2. Results Query: Grouping by Employee to handle multiple submissions
        # STEP A: Get total score for EACH unique submission_hash
        sub_stmt = (
            select(
                models.EmployeeSubmission.employee_id,
                func.sum(models.SurveyResponse.score).label("submission_total")
            )
            .join(models.SurveyResponse, models.EmployeeSubmission.submission_hash == models.SurveyResponse.submission_hash)
            .where(models.EmployeeSubmission.survey_name == s_key)
            .group_by(models.EmployeeSubmission.submission_hash, models.EmployeeSubmission.employee_id)
        ).subquery()

        # STEP B: Average those totals for each Employee
        stmt = (
            select(
                models.Employee.name,
                models.Employee.department,
                models.Employee.position,
                func.avg(sub_stmt.c.submission_total).label("avg_total_score"),
                func.count(sub_stmt.c.employee_id).label("submission_count")
            )
            .join(sub_stmt, models.Employee.id == sub_stmt.c.employee_id)
            .group_by(models.Employee.id, models.Employee.name, models.Employee.department, models.Employee.position)
        )
        
        results = (await session.execute(stmt)).all()
        
        all_scores = []
        dept_data = {}
        pos_data = {}
        individual_scores = []

        for r in results:
            score = float(r.avg_total_score)
            all_scores.append(score)
            dept_data.setdefault(r.department, []).append(score)
            pos_data.setdefault(r.position, []).append(score)
            
            individual_scores.append({
                "name": r.name,
                "department": r.department,
                "position": r.position,
                "score": score,
                "submission_count": r.submission_count,
                "category": grading_func(score) if grading_func else "N/A"
            })

        overall_avg_val = sum(all_scores) / len(all_scores) if all_scores else 0

        # 3. Question Stats (Average score per question across all submissions)
        q_avg_stmt = (
            select(models.SurveyResponse.question_no, func.avg(models.SurveyResponse.score))
            .where(models.SurveyResponse.survey_name == s_key)
            .group_by(models.SurveyResponse.question_no)
        )
        q_results = (await session.execute(q_avg_stmt)).all()

        survey_stats[s_key] = {
            "display_name": s_info["full_name"],
            "total_employees": len(assignments),
            "submitted_employees": sum(1 for a in assignments if a.is_submitted),
            "pending_employees": len(assignments) - sum(1 for a in assignments if a.is_submitted),
            "questions": s_info["questions"],
            "overall_avg": {"score": overall_avg_val, "category": grading_func(overall_avg_val)},
            "dept_avgs": [{"name": d, "score": sum(s)/len(s), "category": grading_func(sum(s)/len(s))} for d, s in dept_data.items()],
            "pos_avgs": [{"name": p, "score": sum(s)/len(s), "category": grading_func(sum(s)/len(s))} for p, s in pos_data.items()],
            "question_avgs": sorted([{"question_no": qno, "score": avg, "category": grading_func(avg)} for qno, avg in q_results], key=lambda x: x["question_no"]),
            "individual_scores": sorted(individual_scores, key=lambda x: x['score'], reverse=True)
        }

    return templates.TemplateResponse("admin/dashboard.html", {"request": request, "survey_stats": survey_stats})


from fastapi import Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app import models
from app.utils import (
    SURVEY_DETAILS, 
    management_score_category, 
    client_score_category, 
    team_score_category,
    aggregate_employee_scores
)

@app.get("/admin/employees", response_class=HTMLResponse)
async def admin_employees(
    request: Request,
    session: AsyncSession = Depends(get_session),
    imported: int | None = None,
    added: int | None = None,
    updated: int | None = None,
    added_single: int | None = None,
    invited: int | None = None,
    invited_count: int | None = None,
    reminded: int | None = None,
):
    # --- 1. Fetch employees ---
    stmt = select(models.Employee).options(selectinload(models.Employee.assignments)).order_by(models.Employee.id)
    result = await session.execute(stmt)
    employees = result.scalars().all()

    # --- 2. Fetch submissions ---
    emp_ids = [e.id for e in employees]
    submissions = []
    if emp_ids:
        sub_stmt = select(models.EmployeeSubmission).where(models.EmployeeSubmission.employee_id.in_(emp_ids))
        sub_result = await session.execute(sub_stmt)
        submissions = sub_result.scalars().all()

    # --- 3. Fetch survey responses ---
    all_hashes = [sub.submission_hash for sub in submissions]
    response_map = {}
    if all_hashes:
        resp_stmt = select(models.SurveyResponse).where(models.SurveyResponse.submission_hash.in_(all_hashes))
        resp_result = await session.execute(resp_stmt)
        for resp in resp_result.scalars().all():
            response_map.setdefault(resp.submission_hash, []).append(resp)

    # --- 4. Grading functions ---
    QUESTION_GRADING_FUNCTIONS = {
        "MSES": management_score_category,
        "ICSES": client_score_category,
        "TSES": team_score_category,
    }

    processed_results_lookup = {}

    # --- 5. Process each submission ---
    for sub in submissions:
        responses = response_map.get(sub.submission_hash, [])
        s_code = sub.survey_name.strip()
        survey_info = SURVEY_DETAILS.get(s_code, {})
        full_name = survey_info.get("full_name", s_code)
        q_text_list = survey_info.get("questions", [])
        num_q = len(q_text_list)
        grading_func = QUESTION_GRADING_FUNCTIONS.get(s_code)

        detailed_scores = []
        total_score = 0

        for r in sorted(responses, key=lambda x: x.question_no):
            q_idx = r.question_no - 1
            q_text = q_text_list[q_idx] if q_idx < num_q else f"Question {r.question_no}"
            score = int(r.score)
            total_score += score
            category = grading_func(score) if grading_func else "N/A"

            detailed_scores.append({
                "question": q_text,
                "score": score,
                "category": category
            })

        # Compute final category for total score
        final_category = grading_func(total_score) if grading_func else "N/A"

        # Store processed data
        key = (sub.employee_id, sub.manager_email.strip().lower(), s_code)
        processed_results_lookup[key] = {
            "survey_name": s_code,
            "full_survey_name": full_name,
            "question_scores": detailed_scores,
            "total_score": total_score,
            "category": final_category,
            "submitted_at": sub.submitted_at
        }

    # --- 6. Attach manager_summary to employees ---
    for emp in employees:
        emp.manager_summary = {}
        for assignment in emp.assignments:
            m_email = assignment.manager_email.strip().lower()
            if m_email not in emp.manager_summary:
                emp.manager_summary[m_email] = {
                    "manager_name": assignment.manager_name,
                    "surveys": [],
                    "is_submitted": assignment.is_submitted
                }

            res_data = processed_results_lookup.get((emp.id, m_email, assignment.survey_name))
            display_name = SURVEY_DETAILS.get(assignment.survey_name, {}).get("full_name", assignment.survey_name)

            emp.manager_summary[m_email]["surveys"].append({
                "survey_name": assignment.survey_name,
                "display_name": display_name,
                "is_submitted": assignment.is_submitted,
                "result": res_data
            })

    # --- 7. Return template ---
    return templates.TemplateResponse(
        "admin/employees.html",
        {
            "request": request,
            "employees": employees,
            "imported": imported,
            "added": added,
            "updated": updated,
            "added_single": added_single,
            "invited": invited,
            "invited_count": invited_count,
            "reminded": reminded,
            "aggregate_employee_scores": aggregate_employee_scores,
            "SURVEY_DETAILS": SURVEY_DETAILS
        }
    )






from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.future import select
from typing import List

import secrets
from app.security import hash_token
from sqlalchemy import select, and_

@app.post("/admin/employees/add")
async def add_employee(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    manager_names: List[str] = Form(...),
    manager_emails: List[str] = Form(...),
    department: str = Form(...),
    survey_names: List[str] = Form(...),
    position: str = Form(...),
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    # Clean and normalize inputs 
    name = name.strip()
    email = email.strip().lower()
    department = department.strip()
    position = position.strip()
    
    # Filter out empty strings from lists
    survey_names = [s.strip() for s in survey_names if s.strip()]
    mgr_names = [m.strip() for m in manager_names if m.strip()]
    mgr_emails = [m.strip().lower() for m in manager_emails if m.strip()]

    # 1. Check if employee already exists (Upsert Logic)
    result = await session.execute(select(models.Employee).where(models.Employee.email == email))
    employee = result.scalars().first()

    if not employee:
        # Create new Employee record
        employee = models.Employee(
            name=name,
            email=email,
            department=department,
            position=position,
        )
        session.add(employee)
        await session.flush()  # To get the employee.id for assignments
    else:
        # Update existing employee details if they've changed
        employee.name = name
        employee.department = department
        employee.position = position

    # 2. Create SurveyAssignments for each survey AND each manager
    # This matches your new SurveyAssignment model structure
    for survey in survey_names:
        for i, m_email in enumerate(mgr_emails):
            m_name = mgr_names[i] if i < len(mgr_names) else "Manager"

            # Check if this specific assignment already exists to prevent unique constraint errors
            assignment_stmt = select(models.SurveyAssignment).join(models.Employee).where(
              and_(
                   models.Employee.email == employee.email,
                   models.SurveyAssignment.manager_email == m_email,
                   models.SurveyAssignment.survey_name == survey
                 )
            )
            existing_assign = (await session.execute(assignment_stmt)).scalars().first()


            if not existing_assign:
                # Generate a unique token for the email link
                token = secrets.token_urlsafe(32)
                assignment = models.SurveyAssignment(
                    employee_id=employee.id,
                    manager_email=m_email,
                    manager_name=m_name,
                    survey_name=survey,
                    invite_token_hash=hash_token(token),
                )
                session.add(assignment)
    await session.flush()
    await session.commit()
    
    # Redirect back to directory with success flag
    return RedirectResponse(url=f"/admin/employees?added_single=1&new_id={employee.id}", status_code=303)



from fastapi import UploadFile, File, Form, HTTPException
from typing import Optional
from io import StringIO, TextIOWrapper
import csv

from fastapi import Request, Form, File, UploadFile, Depends, HTTPException
from fastapi.responses import RedirectResponse
from io import StringIO, TextIOWrapper
import csv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional


from fastapi import APIRouter, Request, Form, File, UploadFile, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from io import StringIO, TextIOWrapper
import csv
import secrets

from app import models
from app.utils import hash_token, normalize_survey_name

@app.post("/admin/employees/import")
async def import_employees(
    request: Request,
    csv_rows: Optional[str] = Form(default=None),
    csv_file: Optional[UploadFile] = File(default=None),
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    """
    Import employees from CSV.
    Expected CSV columns:
    SurveyNames, EmpName, Position, Dept, MgrNames, MgrEmails, EmpEmail
    SurveyNames can be either:
      - Short codes: MSES, ICSES, TSES
      - Full names: Management Satisfaction Survey, Internal Customer Satisfaction, Team Satisfaction
    """
    # 1️⃣ Determine CSV source
    if csv_file and csv_file.filename:
        csv_stream = TextIOWrapper(csv_file.file, encoding="utf-8")
    elif csv_rows and csv_rows.strip():
        csv_stream = StringIO(csv_rows)
    else:
        raise HTTPException(status_code=400, detail="No CSV data provided")

    reader = csv.reader(csv_stream)
    next(reader, None)  # Skip header row if present

    added_count = 0
    updated_count = 0
    skipped_rows = 0

    for row in reader:
        if not row or len(row) < 7:
            skipped_rows += 1
            continue

        # 2️⃣ Parse and normalize survey names
        raw_survey_names = [s.strip() for s in row[0].split(",") if s.strip()]
        survey_names = []
        for s in raw_survey_names:
            norm = normalize_survey_name(s)
            if norm in ("MSES", "ICSES", "TSES"):
                survey_names.append(norm)

        if not survey_names:
            skipped_rows += 1
            continue  # Skip row if no valid survey

        # 3️⃣ Parse employee and manager info
        emp_name = row[1].strip()
        pos = row[2].strip()
        dept = row[3].strip()
        manager_names = [m.strip() for m in row[4].split(",") if m.strip()]
        manager_emails = [m.strip().lower() for m in row[5].split(",") if m.strip()]
        emp_email = row[6].strip().lower()

        if not emp_email:
            skipped_rows += 1
            continue

        # 4️⃣ Upsert Employee
        stmt = select(models.Employee).where(models.Employee.email == emp_email)
        result = await session.execute(stmt)
        employee = result.scalars().first()

        if not employee:
            employee = models.Employee(
                name=emp_name,
                email=emp_email,
                department=dept,
                position=pos
            )
            session.add(employee)
            await session.flush()  # Get employee.id
            added_count += 1
        else:
            # Update existing employee
            employee.name = emp_name
            employee.position = pos
            employee.department = dept
            updated_count += 1

        # 5️⃣ Create SurveyAssignments for each manager-survey combination
        for survey in survey_names:
            for i, mgr_email in enumerate(manager_emails):
                mgr_name = manager_names[i] if i < len(manager_names) else "Manager"

                # Skip if assignment already exists
                assignment_stmt = select(models.SurveyAssignment).where(
                    models.SurveyAssignment.employee_id == employee.id,
                    models.SurveyAssignment.manager_email == mgr_email,
                    models.SurveyAssignment.survey_name == survey
                )
                existing_assignment = (await session.execute(assignment_stmt)).scalars().first()
                if existing_assignment:
                    continue

                # Create new assignment with unique token
                token = secrets.token_urlsafe(32)
                new_assignment = models.SurveyAssignment(
                    employee_id=employee.id,
                    manager_email=mgr_email,
                    manager_name=mgr_name,
                    survey_name=survey,
                    invite_token_hash=hash_token(token)
                )
                session.add(new_assignment)

    await session.commit()

    return RedirectResponse(
        url=f"/admin/employees?imported=1&added={added_count}&updated={updated_count}&skipped={skipped_rows}",
        status_code=303
    )



SURVEY_EMAIL_CONTENT = {
    "TSES": {
        "subject": "Team Satisfaction Survey – Feedback Request",
        "intro": (
            "As part of our ongoing efforts to encourage feedback, "
            "we kindly request your participation in providing feedback about your line manager, "
            "<strong>{employee_name}</strong>."
        ),
        "value": (
            "This feedback is invaluable in providing inputs on areas where individuals can do better. "
        ),
    },
    "MSES": {
        "subject": "Management Satisfaction Survey – Feedback Request",
        "intro": (
            "As part of our ongoing efforts to encourage feedback, "
            "we kindly request your participation in providing feedback on your team member, "
            "<strong>{employee_name}</strong>."
        ),
        "value": (
            "Your feedback is essential in identifying individual strengths, areas for development, and supporting the overall growth of your team. "
        ),
    },
    "ICSES": {
        "subject": "Internal Customer Satisfaction Survey – Feedback Request",
        "intro": (
            "As part of our ongoing efforts to encourage feedback, "
            "we kindly request your participation in providing feedback on your colleague, "
            "<strong>{employee_name}</strong>."
        ),
        "value": (
            "This feedback is invaluable in providing inputs on areas where individuals can do better. "
        ),
    },
}



from collections import defaultdict
import secrets
import datetime as dt
from sqlalchemy.future import select
from app.utils import SURVEY_DETAILS, normalize_survey_name, hash_token
from typing import Dict, List


import secrets
import datetime as dt
from collections import defaultdict
from typing import Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.utils import SURVEY_DETAILS, normalize_survey_name, hash_token



async def invite_employee(
    *,
    session: AsyncSession,
    smtp: models.SMTPSettings,
    base_url: str,
    manager_email: str,
    manager_name: str,
    employee_map: Dict[str, List[models.SurveyAssignment]],
) -> None:
    """
    Sends survey invitations to a manager, batching by survey.
    
    employee_map = {
        "Alice": [assignment1, assignment2],
        "Bob":   [assignment3]
    }
    """

    deadline = "10th Feb 2026"

    # --- 1️⃣ Group assignments by survey_code ---
    survey_map: defaultdict[str, List[Dict]] = defaultdict(list)
    for employee_name, assignments in employee_map.items():
        for assignment in assignments:
            survey_code = normalize_survey_name(assignment.survey_name)
            survey_map[survey_code].append({
                "employee_name": employee_name,
                "assignment": assignment
            })

    # --- 2️⃣ Send one email per survey_code ---
    for survey_code, items in survey_map.items():
        email_cfg = SURVEY_EMAIL_CONTENT.get(survey_code)
        survey_info = SURVEY_DETAILS.get(survey_code)

        if not email_cfg or not survey_info:
            continue

        body_html = ""
        for item in items:
            employee_name = item["employee_name"]
            assignment = item["assignment"]

            # Generate unique token per assignment
            token = secrets.token_urlsafe(32)
            assignment.invite_token_hash = hash_token(token)
            assignment.invited_at = dt.datetime.utcnow()
            link = f"{base_url}/survey/{token}"

            body_html += f"""
            <div style="margin-bottom:32px; padding-bottom:24px;
                        border-bottom:1px solid #00000033;">
              
              <p style="font-size:15px; line-height:1.6; color:#000;">
                <strong>{survey_info['full_name']}</strong>
              </p>

              <p style="font-size:15px; line-height:1.6; color:#000;">
                {email_cfg['intro'].format(employee_name=employee_name)}
              </p>

              <p style="font-size:15px; line-height:1.6; color:#000;">
                {email_cfg['value']}
              </p>

              <div style="text-align:center; margin:16px 0;">
                <a href="{link}"
                   style="display:inline-block;
                          background:#000;
                          color:#a99a68;
                          padding:14px 28px;
                          border-radius:6px;
                          text-decoration:none;
                          font-weight:bold;">
                  Start {survey_info['full_name']}
                </a>
              </div>

              <p style="font-size:13px; color:#333; word-break:break-all;">
                If the button above doesn’t work, please copy the link below:<br>
                <a href="{link}" style="color:#000; text-decoration:underline;">
                  {link}
                </a>
              </p>

            </div>
            """

        # --- 3️⃣ Wrap in full email template ---
        html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>{survey_info['full_name']} Invitation</title>
</head>
<body style="margin:0; padding:40px; background:#000;
             font-family:Arial, Helvetica, sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:#a99a68; border-radius:8px;
                      overflow:hidden;">

          <tr>
            <td style="background:#000; color:#a99a68;
                       padding:20px; text-align:center;">
              <h2 style="margin:0;">Survey Invitation</h2>
            </td>
          </tr>

          <tr>
            <td style="padding:32px;">
              <p style="font-size:16px;">Dear {manager_name},</p>

              {body_html}

              <p style="font-size:14px; margin-top:24px;">
                <strong>All responses are anonymous.</strong>
              </p>

              <p style="font-size:14px;">
                Please complete the survey by
                <strong>{deadline}</strong>.
              </p>
            </td>
          </tr>

          <tr>
            <td style="background:#000; color:#a99a68;
                       padding:16px; text-align:center;
                       font-size:12px;">
              © {dt.datetime.utcnow().year} InfinityCapital.
              All rights reserved.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>
"""

        # --- 4️⃣ Send the email ---
        await send_email(
            host=smtp.host,
            port=smtp.port,
            username=smtp.username,
            password=smtp.password,
            use_tls=smtp.use_tls,
            from_email=smtp.from_email,
            from_name=smtp.from_name,
            to_email=manager_email,
            subject=f"Pending Feedback Survey – {survey_info['full_name']}",
            html_content=html,
        )

    # --- 5️⃣ Commit assignments with token updates ---
    await session.commit()



async def invite_managers(
    session: AsyncSession,
    smtp: models.SMTPSettings,
    base_url: str,
    employee_id: int | None = None,
    reminders_only: bool = False,
):
    stmt = (
        select(models.SurveyAssignment)
        .options(joinedload(models.SurveyAssignment.employee))
        .where(models.SurveyAssignment.is_submitted == False)
    )

    if reminders_only:
        stmt = stmt.where(models.SurveyAssignment.invited_at != None)
    else:
        stmt = stmt.where(models.SurveyAssignment.invited_at == None)

    if employee_id:
        stmt = stmt.where(models.SurveyAssignment.employee_id == employee_id)

    assignments = (await session.execute(stmt)).scalars().all()
    if not assignments:
        return 0

    manager_map = defaultdict(lambda: defaultdict(list))

    for a in assignments:
        manager_map[a.manager_email][a.employee.name].append(a)

    for manager_email, emp_map in manager_map.items():
        manager_name = next(iter(emp_map.values()))[0].manager_name

        await invite_employee(
            session=session,
            smtp=smtp,
            base_url=base_url,
            manager_email=manager_email,
            manager_name=manager_name,
            employee_map=emp_map,
        )

    await session.commit()
    return len(manager_map)


from sqlalchemy import select, and_, exists

@app.post("/admin/employees/{employee_id}/resend")
async def resend_invite(
    request: Request,
    employee_id: int,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    smtp = await get_smtp(session)
    base_url = str(request.base_url).rstrip("/")

    await invite_managers(
        session,
        smtp,
        base_url,
        employee_id=employee_id,
        reminders_only=True
    )

    return RedirectResponse(url="/admin/employees", status_code=303)

from sqlalchemy import delete

from sqlalchemy import delete, select

@app.post("/admin/employees/{employee_id}/toggle")
async def toggle_employee(
    request: Request,
    employee_id: int,
    session: AsyncSession = Depends(get_session),
):
    # 1. Define the subquery to find all hashes linked to this employee
    # We do this first because once we delete the submissions, the hashes are gone!
    hashes_stmt = select(models.EmployeeSubmission.submission_hash).where(
        models.EmployeeSubmission.employee_id == employee_id
    )

    # 2. Delete survey responses where the hash matches any of the employee's hashes
    await session.execute(
        delete(models.SurveyResponse).where(
            models.SurveyResponse.submission_hash.in_(hashes_stmt)
        )
    )

    # 3. Delete from employee_submissions 
    # (Your model doesn't have ondelete="CASCADE" here, so we do it manually)
    await session.execute(
        delete(models.EmployeeSubmission).where(
            models.EmployeeSubmission.employee_id == employee_id
        )
    )

    # 4. Delete the employee (This will cascade to SurveyAssignment)
    await session.execute(
        delete(models.Employee).where(models.Employee.id == employee_id)
    )

    await session.commit()
    return RedirectResponse(url="/admin/employees", status_code=303)

@app.post("/admin/employees/{employee_id}/send-invite")
async def send_single_invite(
    employee_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    smtp = await get_smtp(session)
    base_url = str(request.base_url).rstrip("/")

    await invite_managers(
        session,
        smtp,
        base_url,
        employee_id=employee_id,
        reminders_only=False
    )

    return RedirectResponse(
        url="/admin/employees?invited=1",
        status_code=303
    )



@app.post("/admin/send-invites")
async def send_invites(
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    smtp = await get_smtp(session)
    base_url = str(request.base_url).rstrip("/")

    count = await invite_managers(
        session,
        smtp,
        base_url,
        reminders_only=False
    )

    return RedirectResponse(
        url=f"/admin/employees?invited=1&invited_count={count}",
        status_code=303,
    )


@app.post("/admin/send-reminders")
async def send_reminders(
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    smtp = await get_smtp(session)
    base_url = str(request.base_url).rstrip("/")

    count = await invite_managers(
        session,
        smtp,
        base_url,
        reminders_only=True
    )

    return RedirectResponse(
        url=f"/admin/employees?reminded=1&invited_count={count}",
        status_code=303,
    )

@app.get("/admin/department-heads", response_class=HTMLResponse)
async def department_heads(request: Request, session: AsyncSession = Depends(get_session), admin_id: int = Depends(require_admin)):
    result = await session.execute(select(models.DepartmentHead).order_by(models.DepartmentHead.display_name))
    heads = result.scalars().all()
    return templates.TemplateResponse("admin/department_heads.html", {"request": request, "heads": heads})


@app.post("/admin/department-heads/add")
async def add_department_head(
    request: Request,
    display_name: str = Form(...),
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    session.add(models.DepartmentHead(display_name=display_name.strip()))
    await session.commit()
    return RedirectResponse(url="/admin/department-heads", status_code=303)


@app.post("/admin/department-heads/{head_id}/toggle")
async def toggle_department_head(
    request: Request,
    head_id: int,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    head = await session.get(models.DepartmentHead, head_id)
    if head:
        head.is_active = not head.is_active
        await session.commit()
    return RedirectResponse(url="/admin/department-heads", status_code=303)


@app.get("/admin/smtp", response_class=HTMLResponse)
async def smtp_page(request: Request, session: AsyncSession = Depends(get_session), admin_id: int = Depends(require_admin)):
    smtp = await get_smtp(session)
    return templates.TemplateResponse("admin/smtp.html", {"request": request, "smtp": smtp, "message": None})


@app.post("/admin/smtp")
async def save_smtp(
    request: Request,
    host: str = Form(...),
    port: int = Form(...),
    username: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
    use_tls: Optional[bool] = Form(False),
    from_email: str = Form(...),
    from_name: str = Form(...),
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    smtp = await get_smtp(session)
    smtp.host = host
    smtp.port = port
    smtp.username = username or None
    smtp.password = password or None
    smtp.use_tls = bool(use_tls)
    smtp.from_email = from_email
    smtp.from_name = from_name
    smtp.updated_at = datetime.utcnow()
    await session.commit()
    return RedirectResponse(url="/admin/smtp", status_code=303)


@app.post("/admin/smtp/test", response_class=HTMLResponse)
async def test_smtp(
    request: Request,
    to_email: str = Form(...),
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    smtp = await get_smtp(session)
    html = "<p>This is a test email from the survey system.</p>"
    try:
        await send_email(
            host=smtp.host,
            port=smtp.port,
            username=smtp.username,
            password=smtp.password,
            use_tls=smtp.use_tls,
            from_email=smtp.from_email,
            from_name=smtp.from_name,
            to_email=to_email,
            subject="SMTP test",
            html_content=html,
        )
        message = "Test email sent"
    except Exception as exc:  # noqa: BLE001
        message = f"Failed to send: {exc}"
    return templates.TemplateResponse("admin/smtp.html", {"request": request, "smtp": smtp, "message": message})

async def get_assignment_by_token(session: AsyncSession, token: str) -> Optional[models.SurveyAssignment]:
    token_hash = hash_token(token)
    # Join with employee to get names/department/etc in one query
    result = await session.execute(
        select(models.SurveyAssignment)
        .options(joinedload(models.SurveyAssignment.employee))
        .where(models.SurveyAssignment.invite_token_hash == token_hash)
    )
    return result.scalars().first()



from sqlalchemy.orm import joinedload

async def get_assignment_by_token(session: AsyncSession, token: str):
    h = hash_token(token)
    stmt = (
        select(models.SurveyAssignment)
        .options(joinedload(models.SurveyAssignment.employee)) # Crucial for your code
        .where(models.SurveyAssignment.invite_token_hash == h)
    )
    result = await session.execute(stmt)
    return result.scalars().first()

import secrets
import datetime as dt
from app.utils import SURVEY_DETAILS, SCORES

def get_survey_data(stored_name: str):
    if not stored_name:
        return None
    # 1. Try direct key (MSES, TSES, ICSES)
    if stored_name in SURVEY_DETAILS:
        return stored_name, SURVEY_DETAILS[stored_name]
    # 2. Try full name match
    for key, data in SURVEY_DETAILS.items():
        if stored_name.strip().upper() == data["full_name"].upper():
            return key, data
    return None, None

@app.get("/survey/{token}", response_class=HTMLResponse)
async def survey_page(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
):
    assignment = await get_assignment_by_token(session, token)
    
    if not assignment or not assignment.employee or not assignment.employee.is_active:
        raise HTTPException(status_code=404, detail="Invite link invalid or employee inactive")

    if assignment.is_submitted:
        return templates.TemplateResponse(
            "survey/submitted.html",
            {"request": request, "employee": assignment.employee},
        )

    # Use the flexible lookup
    survey_code, survey_info = get_survey_data(assignment.survey_name)
    
    if not survey_info:
        raise HTTPException(status_code=400, detail="Invalid survey type")

    return templates.TemplateResponse(
        "survey/form.html",
        {
            "request": request,
            "employee": assignment.employee,
            "questions": survey_info["questions"],
            "scores": sorted(list(SCORES.keys()), reverse=True),
            "score_labels": SCORES,
            "token": token,
            "current_survey_name": survey_info["full_name"], # Display full name
            "survey_code": survey_code,
            "survey_index": 0, 
            "total_surveys": 1,
        },
    )


@app.post("/survey/{token}")
async def submit_survey(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
):
    assignment = await get_assignment_by_token(session, token)
    if not assignment or not assignment.employee or not assignment.employee.is_active:
        raise HTTPException(status_code=404, detail="Invite link invalid")

    if assignment.is_submitted:
        raise HTTPException(status_code=400, detail="Already submitted.")

    # Lookup survey info
    survey_code, survey_info = get_survey_data(assignment.survey_name)
    if not survey_info:
        raise HTTPException(status_code=400, detail="Survey configuration not found")

    employee = assignment.employee
    questions_list = survey_info["questions"]
    full_name = survey_info["full_name"]

    form_data = await request.form()
    submission_hash = secrets.token_hex(32)

    total_score = 0  # Initialize total score

    # Validate and Save Responses
    for i in range(1, len(questions_list) + 1):
        raw_val = form_data.get(f"q{i}")
        try:
            score = int(raw_val)
            if score not in SCORES:
                raise ValueError
        except (TypeError, ValueError):
            return templates.TemplateResponse(
                "survey/form.html",
                {
                    "request": request,
                    "employee": employee,
                    "questions": questions_list,
                    "scores": sorted(list(SCORES.keys()), reverse=True),
                    "score_labels": SCORES,
                    "token": token,
                    "current_survey_name": full_name,
                    "error": "All questions are required"
                },
                status_code=400
            )

        total_score += score  # **just sum the scores**

        # Save individual response
        session.add(models.SurveyResponse(
            submission_hash=submission_hash,
            department=employee.department,
            survey_name=survey_code,
            question_no=i,
            score=score  # store actual score
        ))

    # Record the submission
    session.add(models.EmployeeSubmission(
        employee_id=employee.id,
        manager_email=assignment.manager_email,
        survey_name=survey_code,
        submission_hash=submission_hash,
        submitted_at=dt.datetime.utcnow()
    ))

    assignment.is_submitted = True
    assignment.submitted_at = dt.datetime.utcnow()
    await session.commit()

    # Optionally, you can pass total_score to the template for display
    return templates.TemplateResponse(
        "survey/submitted.html",
        {
            "request": request,
            "employee": employee,
            "total_score": total_score,  # NEW: total score
            "survey_name": full_name
        }
    )


@app.get("/health")
async def healthcheck():
    return {"status": "ok"}