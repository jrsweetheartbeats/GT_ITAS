"""add courseware chapter notes and password-reset SMS challenges"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0034_notes_sms"
down_revision = "0033_project_directory_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "development_courseware_notes" not in tables:
        op.create_table(
            "development_courseware_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("development_training_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("chapter_key", sa.String(80), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("task_id", "employee_id", "chapter_key", name="uq_courseware_notes_task_employee_chapter"),
        )
        op.create_index(
            "ix_courseware_notes_employee_task",
            "development_courseware_notes",
            ["employee_id", "task_id"],
        )
    if "password_reset_challenges" not in tables:
        op.create_table(
            "password_reset_challenges",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("phone", sa.String(20), nullable=False),
            sa.Column("code_hash", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_password_reset_challenges_user_time", "password_reset_challenges", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_password_reset_challenges_user_time", table_name="password_reset_challenges")
    op.drop_table("password_reset_challenges")
    op.drop_index("ix_courseware_notes_employee_task", table_name="development_courseware_notes")
    op.drop_table("development_courseware_notes")
