"""add per-task learner notes"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "0022_development_task_notes"
down_revision = "0021_personnel_profiles"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("development_task_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["development_training_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("task_id", "employee_id", name="uq_development_task_notes_task_employee"),
    )

def downgrade() -> None:
    op.drop_table("development_task_notes")
