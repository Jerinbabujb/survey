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
from app.utils import QUESTIONS,hash_token, get_score_category,  CLIENT_QNS, TEAM_QNS, SCORES, management_score_category, management_score_description, client_score_category, client_score_description, team_score_category, team_score_description, SURVEY_MAPPING
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

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    # Define surveys and their question lists
    SURVEYS = {
        "MSES": QUESTIONS,
        "ICSES": CLIENT_QNS,
        "TSES": TEAM_QNS,
    }

    survey_stats = {}
    survey_name_display=''
    # Loop over each survey
    for survey_name, questions_list in SURVEYS.items():
        # Count employees who actually have this survey assigned
        stmt_total = select(func.count(Employee.id)).where(
            Employee.survey_names.contains([survey_name])  # assuming survey_names is list/array
        )
        total_for_survey = await session.scalar(stmt_total)
        if total_for_survey == 0:
            continue  # skip surveys not assigned to anyone
       
        survey_stats[survey_name] = {
            "total": total_for_survey,
            "submitted": 0,
            "pending": 0,
            "overall_avg": 0,
            "dept_avgs": [],
            "question_avgs": [],
            "questions": questions_list,
        }

    if not survey_stats:
        return templates.TemplateResponse(
            "admin/dashboard.html",
            {"request": request, "survey_stats": survey_stats},
        )

    # Fetch all submissions grouped by submission_hash
    stmt_submissions = select(
        SurveyResponse.submission_hash,
        SurveyResponse.department,
        func.count(SurveyResponse.question_no).label("question_count")
    ).group_by(SurveyResponse.submission_hash, SurveyResponse.department)
    submission_groups = (await session.execute(stmt_submissions)).all()

    # Track which submissions belong to which survey
    survey_hashes = {k: [] for k in survey_stats.keys()}

    for submission_hash, department, question_count in submission_groups:
        # determine survey type based on number of questions
        if question_count == 8:
            survey_name = "MSES"
        elif question_count == 7:
            survey_name = "ICSES"
        elif question_count == 16:
            survey_name = "TSES"
        else:
            continue  # unknown survey, skip

        if survey_name not in survey_stats:
            continue  # skip submissions for surveys not assigned to any employee

        survey_stats[survey_name]["submitted"] += 1
        survey_hashes[survey_name].append(submission_hash)

    # Compute pending per survey
    for survey_name, stats in survey_stats.items():
        stats["pending"] = stats["total"] - stats["submitted"]

    # Department and question averages per survey
    for survey_name, stats in survey_stats.items():
        if not survey_hashes[survey_name]:
            continue  # skip if no submissions

        # Overall survey average
        overall_avg_stmt = (
          select(func.coalesce(func.avg(SurveyResponse.score), 0))
          .where(SurveyResponse.submission_hash.in_(survey_hashes[survey_name]))
        
        )
        stats["overall_avg"] = round((await session.scalar(overall_avg_stmt)) or 0 ,2)

        # Department averages
        dept_avg_stmt = (
            select(
                SurveyResponse.department,
                func.coalesce(func.avg(SurveyResponse.score), 0).label("avg_score"),
                func.count(distinct(SurveyResponse.submission_hash)).label("submitted_count")
            )
            .where(SurveyResponse.submission_hash.in_(survey_hashes[survey_name]))
            .group_by(SurveyResponse.department)
            .order_by(SurveyResponse.department)
        )
        stats["dept_avgs"] = (await session.execute(dept_avg_stmt)).all()

        # Question averages
        question_avg_stmt = (
            select(
                SurveyResponse.question_no,
                func.coalesce(func.avg(SurveyResponse.score), 0).label("avg_score")
            )
            .where(SurveyResponse.submission_hash.in_(survey_hashes[survey_name]))
            .group_by(SurveyResponse.question_no)
            .order_by(SurveyResponse.question_no)
        )
        stats["question_avgs"] = (await session.execute(question_avg_stmt)).all()

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {"request": request, "survey_stats": survey_stats},
    )






@app.get("/admin/employees", response_class=HTMLResponse)
async def admin_employees(
    request: Request,
    session: AsyncSession = Depends(get_session),
    imported: int | None = None,
    added: int | None = None,
    skipped: int | None = None,
    added_single: int | None = None,
    invited: int | None = None,
    invited_count: int | None = None,
    reminded: int | None = None,
):
    # 1. Fetch Employees with Submissions and Assignments eagerly loaded
    stmt = (
        select(models.Employee)
        .options(
            selectinload(models.Employee.submissions),
            selectinload(models.Employee.assignments)
        )
        .order_by(models.Employee.id)
    )
    result = await session.execute(stmt)
    employees = result.scalars().all()

    # 2. Gather all submission hashes
    all_submission_hashes = []
    for emp in employees:
        for sub in emp.submissions:
            all_submission_hashes.append(sub.submission_hash)

    # 3. Fetch all SurveyResponses for these hashes in bulk
    response_map = {}
    if all_submission_hashes:
        resp_stmt = select(models.SurveyResponse).where(
            models.SurveyResponse.submission_hash.in_(all_submission_hashes)
        )
        resps_result = await session.execute(resp_stmt)
        for r in resps_result.scalars().all():
            response_map.setdefault(r.submission_hash, []).append(r)

    # 4. Process data into a format the template can easily read
    for employee in employees:
        # CHANGE: This is now { "manager@email.com": [survey_1_data, survey_2_data] }
        employee.submissions_by_manager = {}

        for submission in employee.submissions:
            h = submission.submission_hash
            responses = response_map.get(h, [])
            
            if not responses:
                continue

            manager_email_key = submission.manager_email.strip().lower()

            # Determine survey type
            num_questions = len(responses)
            if num_questions == 8: 
                survey_name = "MSES"
            elif num_questions == 7: 
                survey_name = "ICSES"
            elif num_questions == 16: 
                survey_name = "TSES"
            else: 
                survey_name = f"Survey ({num_questions} Qs)"

            # Get scoring helpers
            survey_questions = SURVEY_MAPPING.get(survey_name, [])
            category_func, desc_func = SURVEY_CATEGORY_FUNC.get(
                survey_name, (get_score_category, get_score_category_score)
            )

            # Sort responses and calculate scores
            responses_sorted = sorted(responses, key=lambda r: r.question_no)
            question_scores = []
            total_score = 0
            
            for idx, r in enumerate(responses_sorted, start=1):
                q_text = survey_questions[idx-1] if idx-1 < len(survey_questions) else f"Question {idx}"
                question_scores.append({
                    "question_no": idx,
                    "question": q_text,
                    "score": r.score,
                    "category": category_func(r.score),
                    "description": desc_func(r.score),
                })
                total_score += r.score

            # PREPARE DATA OBJECT
            submission_result = {
                "survey_name": survey_name,
                "total_score": total_score,
                "category": category_func(total_score),
                "description": desc_func(total_score),
                "question_scores": question_scores,
                "submitted_at": submission.submitted_at
            }

            # CHANGE: Append to the list instead of assigning directly
            if manager_email_key not in employee.submissions_by_manager:
                employee.submissions_by_manager[manager_email_key] = []
            
            employee.submissions_by_manager[manager_email_key].append(submission_result)

    return templates.TemplateResponse(
        "admin/employees.html",
        {
            "request": request,                                                         
            "employees": employees,
            "imported": imported,
            "added": added,
            "skipped": skipped,
            "added_single": added_single,
            "invited": invited,
            "invited_count": invited_count,
            "reminded": reminded,
        },
    )







from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.future import select
from typing import List

@app.post("/admin/employees/add")
async def add_employee(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    manager_names: List[str] = Form(...), # Changed to List
    manager_emails: List[str] = Form(...), # Changed to List
    department: str = Form(...),
    survey_names: List[str] = Form(...),
    position: str = Form(...),
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    # Clean and strip inputs
    email = email.strip()
    name = name.strip()
    department = department.strip()
    position = position.strip()
    
    # Process Lists (Arrays)
    survey_names = [s.strip() for s in survey_names if s.strip()]
    m_names = [m.strip() for m in manager_names if m.strip()]
    m_emails = [m.strip() for m in manager_emails if m.strip()]

    # Check if employee with the same email already exists
    result = await session.execute(select(models.Employee).where(models.Employee.email == email))
    existing_employee = result.scalar_one_or_none()

    if existing_employee:
        # Modern styled alert for duplicate email
        html_content = f"""
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    background-color: #f4f4f4;
                    margin: 0;
                }}
                .alert-box {{
                    background-color: #a99a68;
                    color: white;
                    padding: 20px 30px;
                    border-radius: 10px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.2);
                    text-align: center;
                    animation: slideDown 0.5s ease;
                }}
                .alert-box button {{
                    margin-top: 15px;
                    padding: 10px 20px;
                    border: none;
                    border-radius: 5px;
                    background-color: white;
                    color: #a99a68;
                    font-weight: bold;
                    cursor: pointer;
                }}
                @keyframes slideDown {{
                    from {{ transform: translateY(-50px); opacity: 0; }}
                    to {{ transform: translateY(0); opacity: 1; }}
                }}
            </style>
        </head>
        <body>
            <div class="alert-box">
                Employee with email <strong>{email}</strong> already exists!
                <br>
                <button onclick="window.location.href='/admin/employees'">Go Back</button>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)

    # Add new employee mapping to your specific ARRAY columns
    employee = models.Employee(
        name=name, 
        email=email, 
        department=department, 
        survey_names=survey_names, 
        position=position, 
        manager_names=m_names,    # Matches your table Column
        manager_emails=m_emails   # Matches your table Column
    )
    
    session.add(employee)
    await session.commit()

    return RedirectResponse(url="/admin/employees?added_single=1", status_code=303)


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
    if csv_file and csv_file.filename:
        csv_stream = TextIOWrapper(csv_file.file, encoding="utf-8")
    elif csv_rows and csv_rows.strip():
        csv_stream = StringIO(csv_rows)
    else:
        raise HTTPException(status_code=400, detail="No CSV data")

    reader = csv.reader(csv_stream)
    next(reader, None) # Skip header
    
    added_count = 0
    updated_count = 0

    for row in reader:
        if not row or len(row) < 7: continue

        # Parse data
        new_surveys = [s.strip() for s in row[0].split(",") if s.strip()]
        emp_name, pos, dept = row[1].strip(), row[2].strip(), row[3].strip()
        new_m_names = [m.strip() for m in row[4].split(",") if m.strip()]
        new_m_emails = [m.strip().lower() for m in row[5].split(",") if m.strip()]
        emp_email = row[6].strip().lower()

        # Check if exists
        stmt = select(models.Employee).where(models.Employee.email == emp_email)
        result = await session.execute(stmt)
        existing_emp = result.scalars().first()

        if existing_emp:
            # 1. Merge Surveys (avoid duplicates)
            s_set = set(existing_emp.survey_names or [])
            s_set.update(new_surveys)
            existing_emp.survey_names = list(s_set)

            # 2. Merge Managers
            cur_emails = list(existing_emp.manager_emails or [])
            cur_names = list(existing_emp.manager_names or [])
            for m_e, m_n in zip(new_m_emails, new_m_names):
                if m_e not in cur_emails:
                    cur_emails.append(m_e)
                    cur_names.append(m_n)
            
            existing_emp.manager_emails, existing_emp.manager_names = cur_emails, cur_names
            updated_count += 1
        else:
            # Create new record
            session.add(models.Employee(
                name=emp_name, email=emp_email, department=dept, position=pos,
                survey_names=new_surveys, manager_names=new_m_names, manager_emails=new_m_emails
            ))
            added_count += 1
    
    await session.commit()
    return RedirectResponse(f"/admin/employees?imported=1&added={added_count}&updated={updated_count}", 303)




async def invite_employee(session: AsyncSession, employee: models.Employee, smtp: models.SMTPSettings, base_url: str) -> None:
    # Use fallback to empty lists to avoid iteration errors
    names = employee.manager_names or []
    emails = employee.manager_emails or []
    
    # Use the first survey name or a default
    survey_count = len(employee.survey_names) if employee.survey_names else 0
    survey_title = ", ".join(employee.survey_names) if survey_count > 0 else "Evaluation Survey"

    # We loop through the managers and create a UNIQUE assignment for each
    for i in range(len(emails)):
        m_name = names[i] if i < len(names) else "Manager"
        m_email = emails[i]

        # 1. Generate a unique token for THIS specific manager's invitation
        token = secrets.token_urlsafe(32)
        token_hash = hash_token(token)
        
        # 2. Create a new Assignment record (this allows multiple submissions)
        new_assignment = models.SurveyAssignment(
            employee_id=employee.id,
            manager_email=m_email,
            manager_name=m_name,
            invite_token_hash=token_hash
        )
        session.add(new_assignment)
        
        # 3. Create the unique link for this manager
        link = f"{base_url}/survey/{token}"

        html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8" />
  <title>Survey Invitation</title>
</head>
<body style="margin:0; padding:0; background-color:#000000; font-family: Arial, Helvetica, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#000000; padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color:#a99a68; border-radius:8px; overflow:hidden; box-shadow:0 4px 12px rgba(0,0,0,0.08);">
          <tr>
            <td style="background-color:#000000; padding:24px; text-align:center;">
              <h1 style="margin:0; color:#a99a68; font-size:22px;">You’re Invited</h1>
            </td>
          </tr>
          <tr>
            <td style="padding:32px; color:#000000;">
              <p style="font-size:16px; line-height:1.6; margin-top:0;">
                Hello {m_name},
              </p>
              <p>You have been requested to fill out a <strong>{survey_title}</strong> 
              for <strong>{employee.name}</strong> ({employee.position}).</p>
              <div style="text-align:center; margin:32px 0;">
                <a href="{link}"
                   style="background-color:#000000; color:#a99a68; text-decoration:none; padding:14px 28px; font-size:16px; border-radius:6px; display:inline-block;">
                  Start Survey
                </a>
              </div>
              <p style="font-size:14px; color:#000000; line-height:1.6;">
                If the button above doesn’t work, please copy the link below:
              </p>
              <p style="font-size:14px; word-break:break-all;">
                <a href="{link}" style="color:#000000; text-decoration:underline;">{link}</a>
              </p>
            </td>
          </tr>
          <tr>
            <td style="background-color:#000000; padding:20px; text-align:center; font-size:12px; color:#a99a68;">
              <p style="margin:0;">
                © {dt.datetime.utcnow().year} InfinityCapital. All rights reserved.
              </p>
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
            to_email=m_email,
            subject=f"Survey Request: Evaluation for {employee.name}",
            html_content=html,
        )
    
    # 4. Mark the employee as invited (overall status)
    employee.invited_at = dt.datetime.utcnow()
    
    # Commit all assignments and the employee update at once
    await session.commit()


@app.post("/admin/employees/{employee_id}/resend")
async def resend_invite(
    request: Request,
    employee_id: int,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    employee = await session.get(models.Employee, employee_id)
    if not employee or not employee.is_active or employee.submitted_at:
        return RedirectResponse(url="/admin/employees", status_code=303)
    smtp = await get_smtp(session)
    base_url = str(request.base_url).rstrip("/")
    await invite_employee(session, employee, smtp, base_url)
    await session.commit()
    return RedirectResponse(url="/admin/employees", status_code=303)


@app.post("/admin/employees/{employee_id}/toggle")
async def toggle_employee(
    request: Request,
    employee_id: int,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    employee = await session.get(models.Employee, employee_id)
    if employee:
        employee.is_active = not employee.is_active
        await session.commit()
    return RedirectResponse(url="/admin/employees", status_code=303)


@app.post("/admin/send-invites")
async def send_invites(
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    smtp = await get_smtp(session)
    base_url = str(request.base_url).rstrip("/")

    result = await session.execute(
        select(models.Employee).where(
            and_(
                models.Employee.is_active.is_(True),
                models.Employee.submitted_at.is_(None),
            )
        )
    )
    employees = result.scalars().all()

    invited_count = 0
    skipped_count = 0

    for employee in employees:
        # Skip already invited employees
        if employee.invited_at:
            skipped_count += 1
            continue

        await invite_employee(session, employee, smtp, base_url)
        invited_count += 1

    await session.commit()

    return RedirectResponse(
        url=f"/admin/employees?invited=1&invited_count={invited_count}&skipped={skipped_count}",
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

    result = await session.execute(
        select(models.Employee).where(
            and_(
                models.Employee.submitted_at.is_(None),
                models.Employee.is_active.is_(True),
                models.Employee.invited_at.is_not(None),
            )
        )
    )
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


@app.get("/survey/{token}", response_class=HTMLResponse)
async def survey_page(
    request: Request,
    token: str,
    survey_index: int = 0,
    session: AsyncSession = Depends(get_session),
):
    # 1. Look up the specific assignment for THIS manager
    assignment = await get_assignment_by_token(session, token)
    
    if not assignment or not assignment.employee or not assignment.employee.is_active:
        raise HTTPException(status_code=404, detail="Invite link invalid or employee inactive")

    employee = assignment.employee

    # 2. Check if THIS SPECIFIC assignment is already submitted
    if assignment.is_submitted or not employee.survey_names or survey_index >= len(employee.survey_names):
        return templates.TemplateResponse(
            "survey/submitted.html",
            {"request": request, "employee": employee},
        )

    # Current survey logic remains similar, but uses the assignment context
    current_survey = employee.survey_names[survey_index]
    questions = SURVEY_MAPPING.get(current_survey)
    if not questions:
        raise HTTPException(status_code=400, detail="Invalid survey type")

    return templates.TemplateResponse(
        "survey/form.html",
        {
            "request": request,
            "employee": employee,
            "questions": questions,
            "scores": list(SCORES.keys()),
            "score_labels": SCORES,
            "token": token,
            "current_survey_name": current_survey,
            "survey_index": survey_index,
            "total_surveys": len(employee.survey_names),
        },
    )


@app.post("/survey/{token}")
async def submit_survey(
    request: Request,
    token: str,
    session: AsyncSession = Depends(get_session),
):
    # 1. Look up the specific assignment
    assignment = await get_assignment_by_token(session, token)
    if not assignment or not assignment.employee or not assignment.employee.is_active:
        raise HTTPException(status_code=404, detail="Invite not found")

    if assignment.is_submitted:
        raise HTTPException(status_code=400, detail="You have already submitted this feedback.")

    employee = assignment.employee
    form_data = await request.form()
    survey_index = int(form_data.get("survey_index", 0))

    # Get current survey details
    if survey_index >= len(employee.survey_names):
        return templates.TemplateResponse(
            "survey/submitted.html",
            {"request": request, "employee": employee},
        )

    current_survey = employee.survey_names[survey_index]
    questions = SURVEY_MAPPING.get(current_survey)
    if not questions:
        raise HTTPException(status_code=400, detail="Invalid survey type")

    # Collect scores from form
    question_scores = []
    for i, question in enumerate(questions, start=1):
        val = form_data.get(f"q{i}")
        try:
            val = int(val)
        except (TypeError, ValueError):
            val = None

        if val is None or val not in SCORES:
            return templates.TemplateResponse(
                "survey/form.html",
                {
                    "request": request,
                    "employee": employee,
                    "questions": questions,
                    "scores": list(SCORES.keys()),
                    "score_labels": SCORES,
                    "token": token,
                    "current_survey_name": current_survey,
                    "survey_index": survey_index,
                    "total_surveys": len(employee.survey_names),
                    "error": "All questions are required",
                },
                status_code=400,
            )

        # Apply weighting logic (e.g., score * number of questions)
        weighted_val = val * len(questions)
        question_scores.append({
            "question_no": i,
            "score": weighted_val,
        })

    # Generate unique hash for this specific submission
    submission_hash = secrets.token_hex(32)

    # Save individual responses
    for q in question_scores:
        session.add(
            models.SurveyResponse(
                submission_hash=submission_hash,
                department=employee.department,
                question_no=q["question_no"],
                score=q["score"],
            )
        )

    # --- THE CRITICAL FIX: TRACKING THE SUBMISSION ---
    # We now pass manager_email to satisfy the NotNull constraint
    session.add(models.EmployeeSubmission(
        employee_id=employee.id,
        manager_email=assignment.manager_email,  # <--- FIXED: No more Null error
        submission_hash=submission_hash,
        submitted_at=dt.datetime.utcnow()
    ))

    # Handle multi-survey logic (if manager has more than one survey to fill)
    next_index = survey_index + 1
    if next_index < len(employee.survey_names):
        await session.commit()
        return RedirectResponse(
            url=f"/survey/{token}?survey_index={next_index}",
            status_code=303
        )

    # Finalize the assignment status
    assignment.is_submitted = True
    assignment.submitted_at = dt.datetime.utcnow()
    
    await session.commit()

    return templates.TemplateResponse(
        "survey/submitted.html",
        {"request": request, "employee": employee},
    )



@app.get("/health")
async def healthcheck():
    return {"status": "ok"}
