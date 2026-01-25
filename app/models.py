import datetime as dt
import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from app.db import Base


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    manager_names = Column(ARRAY(String(255)), nullable=True)
    manager_emails = Column(ARRAY(String(255)), nullable=True)
    department = Column(String(255), nullable=False)
    position= Column(String(255), nullable=False) 
    survey_names = Column(ARRAY(String(255)), nullable=True)
    invite_token_hash = Column(String(128), nullable=True)
    invited_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    assignments = relationship("SurveyAssignment", back_populates="employee", cascade="all, delete-orphan")
    submissions = relationship("EmployeeSubmission", back_populates="employee")

class SurveyAssignment(Base):
    """Tracks individual invitations for each manager"""
    __tablename__ = "survey_assignments"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    manager_email = Column(String(255), nullable=False)
    manager_name = Column(String(255), nullable=False)
    
    # Each manager gets their own unique token
    invite_token_hash = Column(String(128), unique=True, nullable=False)
    is_submitted = Column(Boolean, default=False)
    submitted_at = Column(DateTime, nullable=True)

    employee = relationship("Employee", back_populates="assignments")
    __table_args__ = (
        UniqueConstraint("employee_id", "manager_email", name="uq_emp_mgr_assignment"),
    )

class DepartmentHead(Base):
    __tablename__ = "department_heads"

    id = Column(Integer, primary_key=True)
    display_name = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)


class EmployeeSubmission(Base):
    __tablename__ = "employee_submissions"

    id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    manager_email = Column(String(255), nullable=False)
    submission_hash = Column(String(128), nullable=False)
    submitted_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)

    employee = relationship("Employee", back_populates="submissions")
    __table_args__ = (UniqueConstraint("employee_id", "submission_hash", name="uq_employee_submission"),)


class SurveyResponse(Base):
    __tablename__ = "survey_responses"

    id = Column(Integer, primary_key=True)
    submission_hash = Column(String(128), nullable=False)  # <- use hash
    department = Column(String(255), nullable=False)
    question_no = Column(Integer, nullable=False)
    score = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)


# class SurveyComment(Base):
#     __tablename__ = "survey_comments"

#     id = Column(Integer, primary_key=True)
#     submission_hash = Column(String, nullable=False, index=True)
#     department = Column(String, ForeignKey("employees.department", ondelete="CASCADE"), nullable=False)
#     comment = Column(String, nullable=True)
#     created_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)


class SMTPSettings(Base):
    __tablename__ = "smtp_settings"

    id = Column(Integer, primary_key=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False, default=587)
    username = Column(String(255), nullable=True)
    password = Column(String(255), nullable=True)
    use_tls = Column(Boolean, nullable=False, default=True)
    from_email = Column(String(255), nullable=False)
    from_name = Column(String(255), nullable=False)
    updated_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)
