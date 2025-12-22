"""initial tables

Revision ID: 20240911_01
Revises: 
Create Date: 2024-09-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20240911_01'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'admin_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

    op.create_table(
        'department_heads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'employees',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('invite_token_hash', sa.String(length=128), nullable=True),
        sa.Column('invited_at', sa.DateTime(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

    op.create_table(
        'smtp_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('password', sa.String(length=255), nullable=True),
        sa.Column('use_tls', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('from_email', sa.String(length=255), nullable=False),
        sa.Column('from_name', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'employee_submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('submission_hash', sa.String(length=128), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('employee_id', 'submission_hash', name='uq_employee_submission')
    )

    op.create_table(
        'survey_responses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('submission_uuid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('dept_head_id', sa.Integer(), nullable=False),
        sa.Column('question_no', sa.Integer(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['dept_head_id'], ['department_heads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'survey_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('submission_uuid', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('dept_head_id', sa.Integer(), nullable=False),
        sa.Column('comment', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['dept_head_id'], ['department_heads.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('survey_comments')
    op.drop_table('survey_responses')
    op.drop_table('employee_submissions')
    op.drop_table('smtp_settings')
    op.drop_table('employees')
    op.drop_table('department_heads')
    op.drop_table('admin_users')
