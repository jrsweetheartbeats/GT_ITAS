"""add task purpose/self-check configuration and material read records"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_training_task_loop"
down_revision = "0014_training_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("development_training_tasks", sa.Column("purpose", sa.Text(), nullable=False, server_default=""))
    op.add_column("development_training_tasks", sa.Column("self_check_questions", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("development_submissions", sa.Column("self_check_answers", sa.Text(), nullable=False, server_default="{}"))
    op.create_table(
        "development_learning_material_reads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("development_learning_materials.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("material_id", "employee_id", name="uq_development_material_reads_employee"),
    )
    op.create_index("ix_development_learning_material_reads_employee", "development_learning_material_reads", ["employee_id", "read_at"])


def downgrade() -> None:
    op.drop_index("ix_development_learning_material_reads_employee", table_name="development_learning_material_reads")
    op.drop_table("development_learning_material_reads")
    op.drop_column("development_training_tasks", "self_check_questions")
    op.drop_column("development_training_tasks", "purpose")
    op.drop_column("development_submissions", "self_check_answers")
