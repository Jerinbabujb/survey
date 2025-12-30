import asyncio
import secrets
import uuid
from datetime import datetime
from typing import Optional

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
from app.utils import QUESTIONS,hash_token, get_score_category


from app.models import Employee, EmployeeSubmission, SurveyResponse
from app.utils import calculate_total_score, get_score_category
from sqlalchemy import join


app = FastAPI(title="Anonymous Survey")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="admin_session", https_only=False)

# app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


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


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, session: AsyncSession = Depends(get_session), admin_id: int = Depends(require_admin)):
    total_employees = (await session.execute(select(func.count(models.Employee.id)))).scalar_one()
    submitted = (await session.execute(select(func.count(models.Employee.id)).where(models.Employee.submitted_at.is_not(None)))).scalar_one()
    pending = total_employees - submitted

    dept_avg_stmt = (
        select(
            models.DepartmentHead.id,
            models.DepartmentHead.display_name,
            func.avg(models.SurveyResponse.score).label("avg_score"),
        )
        .join(models.SurveyResponse, models.SurveyResponse.dept_head_id == models.DepartmentHead.id)
        .group_by(models.DepartmentHead.id)
        .order_by(models.DepartmentHead.display_name)
    )
    dept_avgs = (await session.execute(dept_avg_stmt)).all()

    question_avg_stmt = (
        select(
            models.SurveyResponse.question_no,
            func.avg(models.SurveyResponse.score*10).label("avg_score"),
        )
        .group_by(models.SurveyResponse.question_no)
        .order_by(models.SurveyResponse.question_no)
    )
    question_avgs = (await session.execute(question_avg_stmt)).all()

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "counts": {"total": total_employees, "submitted": submitted, "pending": pending},
            "dept_avgs": dept_avgs,
            "question_avgs": question_avgs,
        },
    )


@app.get("/admin/employees", response_class=HTMLResponse)
async def admin_employees(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Employee).options(selectinload(Employee.submissions))
    )
    employees = result.scalars().all()

    for employee in employees:
        total_score = None
        category = None
        question_scores = []

        if employee.submissions:
            # Get all submission hashes for this employee
            submission_hashes = [s.submission_hash for s in employee.submissions]

            # Query SurveyResponse by submission_hash
            stmt = select(SurveyResponse).where(SurveyResponse.submission_hash.in_(submission_hashes))
            responses = (await session.execute(stmt)).scalars().all()

            if responses:
                for r in responses:
                    score_multiplied = r.score
                    question_scores.append({
                        "question_no": r.question_no,
                        "score": score_multiplied,
                        "category": get_score_category(score_multiplied)
                    })

                # Total score
                total_score = sum(q["score"] for q in question_scores)
                category = get_score_category(total_score)

        employee.total_score = total_score
        employee.category = category
        employee.question_scores = question_scores

    return templates.TemplateResponse(
        "admin/employees.html",
        {
            "request": request,
            "employees": employees,
        },
    )






@app.post("/admin/employees/add")
async def add_employee(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    employee = models.Employee(name=name.strip(), email=email.strip())
    session.add(employee)
    await session.commit()
    return RedirectResponse(url="/admin/employees", status_code=303)


@app.post("/admin/employees/import")
async def import_employees(
    request: Request,
    csv_rows: str = Form(...),
    session: AsyncSession = Depends(get_session),
    admin_id: int = Depends(require_admin),
):
    lines = [line.strip() for line in csv_rows.splitlines() if line.strip()]
    for line in lines:
        if "," not in line:
            continue
        name, email = [part.strip() for part in line.split(",", 1)]
        if not name or not email:
            continue
        exists = await session.execute(select(models.Employee).where(models.Employee.email == email))
        if exists.scalars().first():
            continue
        session.add(models.Employee(name=name, email=email))
    await session.commit()
    return RedirectResponse(url="/admin/employees", status_code=303)


async def invite_employee(session: AsyncSession, employee: models.Employee, smtp: models.SMTPSettings, base_url: str) -> None:
    token = secrets.token_urlsafe(32)
    employee.invite_token_hash = hash_token(token)
    employee.invited_at = datetime.utcnow()
    link = f"{base_url}/survey/{token}"
    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8" />
  <title>Survey Invitation</title>
</head>
<body style="margin:0; padding:0; background-color:#f4f6f8; font-family: Arial, Helvetica, sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f6f8; padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:8px; overflow:hidden; box-shadow:0 4px 12px rgba(0,0,0,0.08);">
          
          <!-- Header -->
          <tr>
            <td style="background-color:#2563eb; padding:24px; text-align:center;">
              <h1 style="margin:0; color:#ffffff; font-size:22px;">
                You’re Invited
              </h1>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px; color:#1f2937;">
              <p style="font-size:16px; line-height:1.6; margin-top:0;">
                Hello,
              </p>

              <p style="font-size:16px; line-height:1.6;">
                You have been invited to participate in an <strong>anonymous survey</strong>.
                Your honest feedback is important and will help us improve.
              </p>

              <!-- Button -->
              <div style="text-align:center; margin:32px 0;">
                <a href="{link}"
                   style="background-color:#2563eb;
                          color:#ffffff;
                          text-decoration:none;
                          padding:14px 28px;
                          font-size:16px;
                          border-radius:6px;
                          display:inline-block;">
                  Start Survey
                </a>
              </div>

              <p style="font-size:14px; color:#4b5563; line-height:1.6;">
                If the button above doesn’t work, copy and paste this link into your browser:
              </p>

              <p style="font-size:14px; word-break:break-all;">
                <a href="{link}" style="color:#2563eb;">{link}</a>
              </p>

              <p style="font-size:14px; color:#6b7280; line-height:1.6; margin-bottom:0;">
                This invitation is unique to you. Please do not share it with others.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background-color:#f9fafb; padding:20px; text-align:center; font-size:12px; color:#9ca3af;">
              <p style="margin:0;">
                © {datetime.utcnow().year} Your Company. All rights reserved.
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
        to_email=employee.email,
        subject="Your anonymous survey invite",
        html_content=html,
    )


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
async def send_invites(request: Request, session: AsyncSession = Depends(get_session), admin_id: int = Depends(require_admin)):
    smtp = await get_smtp(session)
    base_url = str(request.base_url).rstrip("/")
    result = await session.execute(
        select(models.Employee).where(and_(models.Employee.is_active.is_(True), models.Employee.submitted_at.is_(None)))
    )
    employees = result.scalars().all()
    for employee in employees:
        await invite_employee(session, employee, smtp, base_url)
    await session.commit()
    return RedirectResponse(url="/admin/employees", status_code=303)


@app.post("/admin/send-reminders")
async def send_reminders(request: Request, session: AsyncSession = Depends(get_session), admin_id: int = Depends(require_admin)):
    smtp = await get_smtp(session)
    base_url = str(request.base_url).rstrip("/")
    result = await session.execute(
        select(models.Employee).where(and_(models.Employee.submitted_at.is_(None), models.Employee.is_active.is_(True)))
    )
    employees = result.scalars().all()
    for employee in employees:
        await invite_employee(session, employee, smtp, base_url)
    await session.commit()
    return RedirectResponse(url="/admin/employees", status_code=303)


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


@app.get("/survey/{token}", response_class=HTMLResponse)
async def survey_page(request: Request, token: str, session: AsyncSession = Depends(get_session)):
    employee = await get_employee_by_token(session, token)
    if not employee or not employee.is_active:
        raise HTTPException(status_code=404, detail="Invite not found")

    if employee.submitted_at:
        return templates.TemplateResponse("survey/submitted.html", {"request": request, "employee": employee})

    heads = await session.execute(select(models.DepartmentHead).where(models.DepartmentHead.is_active.is_(True)))
    dept_heads = heads.scalars().all()
    return templates.TemplateResponse(
        "survey/form.html",
        {
            "request": request,
            "questions": QUESTIONS,
            "dept_heads": dept_heads,
            "scores": [5, 4, 3, 2, 1],
            "score_labels": {
                5: "Strongly Agree",
                4: "Agree",
                3: "Satisfactory",
                2: "Disagree",
                1: "Strongly Disagree",
            },
            "token": token,
        },
    )


async def get_employee_by_token(session: AsyncSession, token: str) -> Optional[models.Employee]:
    token_hash = hash_token(token)
    result = await session.execute(select(models.Employee).where(models.Employee.invite_token_hash == token_hash))
    return result.scalars().first()


@app.post("/survey/{token}")
async def submit_survey(
    request: Request,
    token: str,
    dept_head_id: int = Form(...),
    comment: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
):
    # Lookup employee by token
    employee = await get_employee_by_token(session, token)
    if not employee or not employee.is_active:
        raise HTTPException(status_code=404, detail="Invite not found")

    if employee.submitted_at:
        return templates.TemplateResponse(
            "survey/submitted.html", {"request": request, "employee": employee}
        )

    # Validate department head
    head = await session.get(models.DepartmentHead, dept_head_id)
    if not head or not head.is_active:
        raise HTTPException(status_code=400, detail="Invalid department head")

    # Collect scores from form
    form_data = await request.form()
    question_scores = []

    for i in range(1, 11):
        try:
            val = int(form_data.get(f"q{i}"))
        except (TypeError, ValueError):
            val = None
        if val is None or val not in {1, 2, 3, 4, 5}:
            # Re-render form with error
            heads = await session.execute(
                select(models.DepartmentHead).where(models.DepartmentHead.is_active.is_(True))
            )
            dept_heads = heads.scalars().all()
            return templates.TemplateResponse(
                "survey/form.html",
                {
                    "request": request,
                    "questions": QUESTIONS,
                    "dept_heads": dept_heads,
                    "scores": [5, 4, 3, 2, 1],
                    "score_labels": {
                        5: "Strongly Agree",
                        4: "Agree",
                        3: "Satisfactory",
                        2: "Disagree",
                        1: "Strongly Disagree",
                    },
                    "token": token,
                    "error": "All questions are required",
                },
                status_code=400,
            )

        scaled_score = val * 10
        category = get_score_category(scaled_score)

        question_scores.append({
            "question_no": i,
            "score": scaled_score,
            "category": category
        })

    # Generate submission hash
    submission_hash = hash_token(str(uuid.uuid4()))

    # Save survey responses
    for q in question_scores:
        session.add(
            models.SurveyResponse(
                submission_hash=submission_hash,
                dept_head_id=dept_head_id,
                question_no=q["question_no"],
                score=q["score"]
            )
        )

    # Save optional comment
    if comment:
        session.add(
            models.SurveyComment(
                submission_hash=submission_hash,
                dept_head_id=dept_head_id,
                comment=comment
            )
        )

    # Track employee submission
    session.add(models.EmployeeSubmission(employee_id=employee.id, submission_hash=submission_hash))
    employee.submitted_at = datetime.utcnow()

    await session.commit()

    return templates.TemplateResponse(
        "survey/submitted.html",
        {"request": request, "employee": employee, "question_scores": question_scores}
    )


@app.get("/health")
async def healthcheck():
    return {"status": "ok"}
