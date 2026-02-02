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
from app.utils import QUESTIONS,hash_token, get_score_category,  CLIENT_QNS, TEAM_QNS, SCORES, management_score_category, management_score_description, client_score_category, client_score_description, team_score_category, team_score_description
from fastapi import Query

from app.models import Employee, EmployeeSubmission, SurveyResponse
from app.utils import weighted_score, get_score_category, get_score_category_score
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


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    # 1. Configuration for Grading Logic
    GRADING_MAP = {
        "MSES": management_score_category,
        "ICSES": client_score_category,
        "TSES": team_score_category,
    }

    survey_stats = {}

    # 2. Global Submission Count (Avoids N+1 queries)
    sub_count_stmt = (
        select(
            models.EmployeeSubmission.survey_name, 
            func.count(func.distinct(models.EmployeeSubmission.employee_id))
        ).group_by(models.EmployeeSubmission.survey_name)
    )
    submission_results = (await session.execute(sub_count_stmt)).all()
    submission_map = {name: count for name, count in submission_results}

    # 3. Process each survey type defined in your constants
    for s_key, s_info in SURVEY_DETAILS.items():
        try:
            # Get total assigned employees
            stmt_total = select(func.count(func.distinct(models.SurveyAssignment.employee_id))).where(
                or_(
                    models.SurveyAssignment.survey_name == s_key,
                    models.SurveyAssignment.survey_name == s_info["full_name"]
                )
            )
            total_unique = await session.scalar(stmt_total) or 0
            
            if total_unique == 0:
                continue

            # Calculate submitted count (checks both short key and full name)
            submitted = submission_map.get(s_key, 0) + submission_map.get(s_info["full_name"], 0)
            grading_func = GRADING_MAP.get(s_key)

            # Initialize survey data structure
            survey_stats[s_key] = {
                "display_name": s_info["full_name"],
                "total_employees": total_unique,
                "submitted_employees": submitted,
                "pending_employees": max(0, total_unique - submitted),
                "questions": s_info["questions"],
                "overall_avg": {"score": 0, "category": "N/A"},
                "dept_avgs": [],
                "pos_avgs": [],
                "question_avgs": []
            }

            # Filter for retrieving response data
            base_filter = or_(
                models.SurveyResponse.survey_name == s_key,
                models.SurveyResponse.survey_name == s_info["full_name"]
            )

            # --- A. Overall Average & Category ---
            avg_score = await session.scalar(select(func.avg(models.SurveyResponse.score)).where(base_filter)) or 0
            survey_stats[s_key]["overall_avg"] = {
                "score": round(avg_score, 2),
                "category": grading_func(int(avg_score)) if (grading_func and avg_score > 0) else "N/A"
            }

            # --- B. Department Averages & Category ---
            dept_stmt = (
                select(models.SurveyResponse.department, func.avg(models.SurveyResponse.score))
                .where(base_filter)
                .group_by(models.SurveyResponse.department)
            )
            dept_res = (await session.execute(dept_stmt)).all()
            survey_stats[s_key]["dept_avgs"] = [
                {
                    "name": r[0],
                    "score": round(r[1], 2),
                    "category": grading_func(int(r[1])) if grading_func else "N/A"
                } for r in dept_res
            ]

            # --- C. Position Averages & Category ---
            pos_stmt = (
                select(models.Employee.position, func.avg(models.SurveyResponse.score))
                .join(models.EmployeeSubmission, models.SurveyResponse.submission_hash == models.EmployeeSubmission.submission_hash)
                .join(models.Employee, models.EmployeeSubmission.employee_id == models.Employee.id)
                .where(base_filter)
                .group_by(models.Employee.position)
            )
            pos_res = (await session.execute(pos_stmt)).all()
            survey_stats[s_key]["pos_avgs"] = [
                {
                    "name": r[0],
                    "score": round(r[1], 2),
                    "category": grading_func(int(r[1])) if grading_func else "N/A"
                } for r in pos_res
            ]

            # --- D. Individual Question Averages & Category ---
            q_avg_stmt = (
                select(models.SurveyResponse.question_no, func.avg(models.SurveyResponse.score))
                .where(base_filter)
                .group_by(models.SurveyResponse.question_no)
            )
            q_res = (await session.execute(q_avg_stmt)).all()
            survey_stats[s_key]["question_avgs"] = [
                {
                    "question_no": r[0],
                    "score": round(r[1], 2),
                    "category": grading_func(int(r[1])) if grading_func else "N/A"
                } for r in q_res
            ]

        except Exception as e:
            print(f"Error processing stats for {s_key}: {e}")
            continue

    return templates.TemplateResponse(
        "admin/dashboard.html", 
        {"request": request, "survey_stats": survey_stats}
    )


from sqlalchemy import select
from sqlalchemy.orm import selectinload
import datetime as dt

from app.utils import (
    SURVEY_DETAILS, 
    management_score_category, 
    client_score_category, 
    team_score_category
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
    # 1. Fetch Employees with their assignments
    stmt = (
        select(models.Employee)
        .options(selectinload(models.Employee.assignments))
        .order_by(models.Employee.id)
    )
    result = await session.execute(stmt)
    employees = result.scalars().all()

    # 2. Fetch all submissions related to these employees
    emp_ids = [e.id for e in employees]
    submissions = []
    if emp_ids:
        sub_stmt = select(models.EmployeeSubmission).where(
            models.EmployeeSubmission.employee_id.in_(emp_ids)
        )
        sub_result = await session.execute(sub_stmt)
        submissions = sub_result.scalars().all()

    # 3. Fetch all raw SurveyResponses
    all_hashes = [sub.submission_hash for sub in submissions]
    response_map = {}
    if all_hashes:
        resp_stmt = select(models.SurveyResponse).where(
            models.SurveyResponse.submission_hash.in_(all_hashes)
        )
        resp_result = await session.execute(resp_stmt)
        for resp in resp_result.scalars().all():
            response_map.setdefault(resp.submission_hash, []).append(resp)

    # 4. Define the Mapping for Grading Functions
    QUESTION_GRADING_FUNCTIONS = {
        "MSES": management_score_category,
        "ICSES": client_score_category,
        "TSES": team_score_category,
    }

    processed_results_lookup = {}

    # 5. Process each submission
    for sub in submissions:
        responses = response_map.get(sub.submission_hash, [])
        s_code = sub.survey_name.strip()
        
        # Pull details from SURVEY_DETAILS in utils.py
        survey_info = SURVEY_DETAILS.get(s_code, {})
        full_name = survey_info.get("full_name", s_code)
        q_text_list = survey_info.get("questions", [])
        num_q = len(q_text_list)
        
        grading_func = QUESTION_GRADING_FUNCTIONS.get(s_code)

        detailed_scores = []
        for r in sorted(responses, key=lambda x: x.question_no):
            q_idx = r.question_no - 1
            q_text = q_text_list[q_idx] if q_idx < num_q else f"Question {r.question_no}"
            
            # Use original grading function
            q_category = "N/A"
            if grading_func:
                q_category = grading_func(int(r.score))
            
            detailed_scores.append({
                "question": q_text,
                "score": r.score,
                "category": q_category
            })

        # Store in lookup using a unique key
        key = (sub.employee_id, sub.manager_email.strip().lower(), s_code)
        processed_results_lookup[key] = {
            "survey_name": s_code,
            "full_survey_name": full_name, # Added full name for modal/display
            "question_scores": detailed_scores,
            "submitted_at": sub.submitted_at
        }

    # 6. Group Data for the Frontend
    for emp in employees:
        emp.manager_summary = {}
        for assignment in emp.assignments:
            m_email = assignment.manager_email.strip().lower()
            if m_email not in emp.manager_summary:
                emp.manager_summary[m_email] = {
                    "manager_name": assignment.manager_name,
                    "surveys": [],
                    "is_submitted": assignment.is_submitted,
                }
            
            res_data = processed_results_lookup.get((emp.id, m_email, assignment.survey_name))
            
            # Fetch full name for the list display
            display_name = SURVEY_DETAILS.get(assignment.survey_name, {}).get("full_name", assignment.survey_name)

            emp.manager_summary[m_email]["surveys"].append({
                "survey_name": assignment.survey_name,
                "display_name": display_name, # Added display_name
                "is_submitted": assignment.is_submitted,
                "result": res_data
            })

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
            "reminded": reminded
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


@app.post("/admin/employees/import")
async def import_employees(
    request: Request,
    csv_rows: Optional[str] = Form(default=None),
    csv_file: Optional[UploadFile] = File(default=None),
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    # 1. Determine Source
    if csv_file and csv_file.filename:
        csv_stream = TextIOWrapper(csv_file.file, encoding="utf-8")
    elif csv_rows and csv_rows.strip():
        csv_stream = StringIO(csv_rows)
    else:
        raise HTTPException(status_code=400, detail="No CSV data provided")

    reader = csv.reader(csv_stream)
    next(reader, None)  # Skip header row

    added_count = 0
    updated_count = 0

    for row in reader:
        # Expected CSV: SurveyNames, EmpName, Position, Dept, MgrNames, MgrEmails, EmpEmail
        if not row or len(row) < 7:
            continue

        # Parse and clean data
        survey_names = [s.strip() for s in row[0].split(",") if s.strip()]
        emp_name = row[1].strip()
        pos = row[2].strip()
        dept = row[3].strip()
        manager_names = [m.strip() for m in row[4].split(",") if m.strip()]
        manager_emails = [m.strip().lower() for m in row[5].split(",") if m.strip()]
        emp_email = row[6].strip().lower()

        if not emp_email:
            continue

        # 2. Upsert Employee (Find existing or create new)
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
            await session.flush()  # Get employee.id for the assignments below
            added_count += 1
        else:
            # Sync metadata if it changed in the CSV
            employee.name = emp_name
            employee.position = pos
            employee.department = dept
            updated_count += 1

        # 3. Create SurveyAssignments for each manager-survey combination
        for survey in survey_names:
            for i, mgr_email in enumerate(manager_emails):
                # Fallback to "Manager" if the names list is shorter than the emails list
                mgr_name = manager_names[i] if i < len(manager_names) else "Manager"

                # Check if this specific assignment already exists (Relational Unique Check)
                assignment_stmt = select(models.SurveyAssignment).where(
                    models.SurveyAssignment.employee_id == employee.id,
                    models.SurveyAssignment.manager_email == mgr_email,
                    models.SurveyAssignment.survey_name == survey
                )
                existing_assignment = (await session.execute(assignment_stmt)).scalars().first()
                
                if existing_assignment:
                    continue  # Skip if this manager is already assigned this survey for this employee

                # Generate a new unique token for this specific assignment
                token = secrets.token_urlsafe(32)
                token_hash = hash_token(token) 
                
                new_assignment = models.SurveyAssignment(
                    employee_id=employee.id,
                    manager_email=mgr_email,
                    manager_name=mgr_name,
                    survey_name=survey,
                    invite_token_hash=token_hash
                )
                session.add(new_assignment)

    await session.commit()
    
    return RedirectResponse(
        url=f"/admin/employees?imported=1&added={added_count}&updated={updated_count}",
        status_code=303
    )

SURVEY_EMAIL_CONTENT = {
    "TSES": {
        "subject": "Team Satisfaction Survey – Feedback Request",
        "intro": (
            "As part of our ongoing efforts to encourage feedback on non-KPI parameters, "
            "we kindly request your participation in providing feedback about your line manager, "
            "<strong>{employee_name}</strong>."
        ),
        "value": (
            "Your feedback is invaluable in helping us identify areas where individuals "
            "can further improve and grow."
        ),
    },
    "MSES": {
        "subject": "Management Satisfaction Survey – Feedback Request",
        "intro": (
            "As part of our ongoing efforts to encourage feedback on non-KPI parameters, "
            "we kindly request your participation in providing feedback on your team member, "
            "<strong>{employee_name}</strong>."
        ),
        "value": (
            "Your feedback plays an important role in identifying individual strengths, "
            "areas for development, and supporting the overall growth of the team."
        ),
    },
    "ICSES": {
        "subject": "Internal Customer Satisfaction Survey – Feedback Request",
        "intro": (
            "As part of our ongoing efforts to encourage feedback on non-KPI parameters, "
            "we kindly request your participation in providing feedback on your colleague, "
            "<strong>{employee_name}</strong>."
        ),
        "value": (
            "This feedback is invaluable in identifying areas where individuals "
            "can further improve and enhance collaboration across teams."
        ),
    },
}



import secrets
import datetime as dt
from sqlalchemy.future import select
from app.security import hash_token
# Assuming send_email is imported from your mail utility
# from app.utils.mail import send_email 

from app.utils import SURVEY_DETAILS, normalize_survey_name, hash_token

async def invite_employee(
    session: AsyncSession,
    employee: models.Employee,
    smtp: models.SMTPSettings,
    base_url: str
) -> None:
    stmt = (
        select(models.SurveyAssignment)
        .where(models.SurveyAssignment.employee_id == employee.id)
        .where(models.SurveyAssignment.is_submitted == False)
    )
    result = await session.execute(stmt)
    assignments = result.scalars().all()

    for assignment in assignments:
        # Normalize survey name
        survey_code = normalize_survey_name(assignment.survey_name)
        survey_info = SURVEY_DETAILS.get(survey_code, {})
        email_cfg = SURVEY_EMAIL_CONTENT.get(survey_code)

        if not email_cfg:
            continue  # Safety fallback

        token = secrets.token_urlsafe(32)
        assignment.invite_token_hash = hash_token(token)
        assignment.invited_at = dt.datetime.utcnow()

        link = f"{base_url}/survey/{token}"
        deadline = "12th Feb 2026"

        # Build email HTML (same design, updated content)
        html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8" />
  <title>{email_cfg['subject']}</title>
</head>
<body style="margin:0; padding:0; background-color:#000000; font-family: Arial, Helvetica, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#000000; padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background-color:#a99a68; border-radius:8px; overflow:hidden; box-shadow:0 4px 12px rgba(0,0,0,0.08);">
          
          <tr>
            <td style="background-color:#000000; padding:24px; text-align:center;">
              <h1 style="margin:0; color:#a99a68; font-size:22px;">Survey Invitation</h1>
            </td>
          </tr>

          <tr>
            <td style="padding:32px; color:#000000;">
              <p style="font-size:16px;">Dear {assignment.manager_name},</p>

              <p style="font-size:15px; line-height:1.6;">
                {email_cfg['intro'].format(employee_name=employee.name)}
              </p>

              <p style="font-size:15px; line-height:1.6;">
                {email_cfg['value']}
              </p>

              <p style="font-size:14px;">
                <strong>Please note:</strong> All responses are completely anonymous, and no
                individual-level details will be shared.
              </p>

              <p style="font-size:14px;">
                Kindly ensure that the survey is completed by <strong>{deadline}</strong>.
              </p>

              <div style="text-align:center; margin:32px 0;">
                <a href="{link}"
                   style="background-color:#000000; color:#a99a68; text-decoration:none;
                          padding:14px 28px; font-size:16px; border-radius:6px; display:inline-block;">
                  Start Survey
                </a>
              </div>

              <p style="font-size:13px;">
                If the button above doesn’t work, please copy the link below:
              </p>

              <p style="font-size:13px; word-break:break-all;">
                <a href="{link}" style="color:#000000;">{link}</a>
              </p>
            </td>
          </tr>

          <tr>
            <td style="background-color:#000000; padding:20px; text-align:center;
                       font-size:12px; color:#a99a68;">
              © {dt.datetime.utcnow().year} InfinityCapital. All rights reserved.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

        await send_email(
            host=smtp.host,
            port=smtp.port,
            username=smtp.username,
            password=smtp.password,
            use_tls=smtp.use_tls,
            from_email=smtp.from_email,
            from_name=smtp.from_name,
            to_email=assignment.manager_email,
            subject=email_cfg["subject"],
            html_content=html,
        )

    await session.commit()




from sqlalchemy import select, and_, exists

@app.post("/admin/employees/{employee_id}/resend")
async def resend_invite(
    request: Request,
    employee_id: int,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    employee = await session.get(models.Employee, employee_id)
    if not employee or not employee.is_active:
        return RedirectResponse(url="/admin/employees", status_code=303)
    
    # Check if there are any pending assignments to resend
    stmt = select(models.SurveyAssignment).where(
        models.SurveyAssignment.employee_id == employee_id,
        models.SurveyAssignment.is_submitted == False
    )
    result = await session.execute(stmt)
    if not result.scalars().first():
        # All surveys for this person are already submitted
        return RedirectResponse(url="/admin/employees", status_code=303)

    smtp = await get_smtp(session)
    base_url = str(request.base_url).rstrip("/")
    
    # invite_employee now handles looping through specific assignments
    await invite_employee(session, employee, smtp, base_url)
    
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

    # Fetch ONLY this specific employee
    stmt = select(models.Employee).where(models.Employee.id == employee_id)
    result = await session.execute(stmt)
    employee = result.scalar_one_or_none()

    if not employee:
        return RedirectResponse(url="/admin/employees?error=Employee+not+found", status_code=303)

    # Trigger the email for just this person
    await invite_employee(session, employee, smtp, base_url)
    await session.commit()

    return RedirectResponse(
        url=f"/admin/employees?invited=1&invited_count=1", 
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

    # Fetch employees who have at least one assignment that has NEVER been invited
    stmt = select(models.Employee).where(
        models.Employee.is_active == True,
        exists().where(
            and_(
                models.SurveyAssignment.employee_id == models.Employee.id,
                models.SurveyAssignment.invited_at != None
            )
        )
    )
    result = await session.execute(stmt)
    employees = result.scalars().all()

    invited_count = 0
    for employee in employees:
        await invite_employee(session, employee, smtp, base_url)
        invited_count += 1

    await session.commit()
    return RedirectResponse(
        url=f"/admin/employees?invited=1&invited_count={invited_count}",
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

    # Fetch employees who have assignments that ARE invited but NOT submitted
    stmt = select(models.Employee).where(
        models.Employee.is_active == True,
        exists().where(
            and_(
                models.SurveyAssignment.employee_id == models.Employee.id,
                models.SurveyAssignment.invited_at != None,
                models.SurveyAssignment.is_submitted == False
            )
        )
    )
    result = await session.execute(stmt)
    employees = result.scalars().all()

    invited_count = 0
    for employee in employees:
        await invite_employee(session, employee, smtp, base_url)
        invited_count += 1

    await session.commit()
    return RedirectResponse(
        url=f"/admin/employees?reminded=1&invited_count={invited_count}",
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
from app.utils import SURVEY_DETAILS, SCORES, weighted_score

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

    # Use flexible lookup to handle short/long names stored in DB
    survey_code, survey_info = get_survey_data(assignment.survey_name)
    if not survey_info:
        raise HTTPException(status_code=400, detail="Survey configuration not found")

    employee = assignment.employee
    questions_list = survey_info["questions"]
    full_name = survey_info["full_name"]
    
    form_data = await request.form()
    submission_hash = secrets.token_hex(32)

    # Validate and Save Responses
    for i in range(1, len(questions_list) + 1):
        raw_val = form_data.get(f"q{i}")
        try:
            score = int(raw_val)
            if score not in SCORES: raise ValueError
        except (TypeError, ValueError):
            return templates.TemplateResponse("survey/form.html", {
                "request": request, 
                "employee": employee, 
                "questions": questions_list,
                "scores": sorted(list(SCORES.keys()), reverse=True), 
                "score_labels": SCORES, 
                "token": token,
                "current_survey_name": full_name, 
                "error": "All questions are required"
            }, status_code=400)

        # Apply weighting logic
        final_score = weighted_score(score, questions_list) 

        session.add(models.SurveyResponse(
            submission_hash=submission_hash,
            department=employee.department,
            survey_name=survey_code, # Standardize to code when saving results
            question_no=i,
            score=final_score
        ))

    # Record the submission
    session.add(models.EmployeeSubmission(
        employee_id=employee.id,
        manager_email=assignment.manager_email,
        survey_name=survey_code, # Save standardized code
        submission_hash=submission_hash,
        submitted_at=dt.datetime.utcnow()
    ))

    assignment.is_submitted = True
    assignment.submitted_at = dt.datetime.utcnow()
    await session.commit()

    return templates.TemplateResponse("survey/submitted.html", {"request": request, "employee": employee})

@app.get("/health")
async def healthcheck():
    return {"status": "ok"}