"""Persist learner telemetry and per-question quiz history for monthly reviews."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0030_training_signals"
down_revision = "0029_session_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "development_learning_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("training_plan_id", sa.Integer(), sa.ForeignKey("development_training_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("training_week_id", sa.Integer(), sa.ForeignKey("development_training_weeks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("development_training_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("development_submissions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("material_id", sa.Integer(), sa.ForeignKey("development_learning_materials.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("skill_tag", sa.String(80), nullable=False, server_default=""),
        sa.Column("competency_code", sa.String(80), nullable=False, server_default=""),
        sa.Column("source", sa.String(40), nullable=False, server_default="system"),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_development_learning_events_employee_time", "development_learning_events", ["employee_id", "occurred_at"])
    op.create_index("ix_development_learning_events_plan_type_time", "development_learning_events", ["training_plan_id", "event_type", "occurred_at"])
    op.create_index("ix_development_learning_events_task_type_time", "development_learning_events", ["task_id", "event_type", "occurred_at"])

    op.create_table(
        "development_quiz_item_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("training_plan_id", sa.Integer(), sa.ForeignKey("development_training_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("development_training_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("development_submissions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("question_index", sa.Integer(), nullable=False),
        sa.Column("question_fingerprint", sa.String(40), nullable=False),
        sa.Column("knowledge_key", sa.String(80), nullable=False, server_default=""),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("skill_tag", sa.String(80), nullable=False, server_default=""),
        sa.Column("competency_code", sa.String(80), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("submitted_answer_json", sa.Text(), nullable=False, server_default="null"),
        sa.Column("correct_answer_json", sa.Text(), nullable=False, server_default="null"),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("passed_gate", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("employee_id", "task_id", "attempt_no", "question_index", name="uq_development_quiz_results_attempt"),
    )
    op.create_index("ix_development_quiz_results_employee_task", "development_quiz_item_results", ["employee_id", "task_id", "occurred_at"])
    op.create_index("ix_development_quiz_results_knowledge", "development_quiz_item_results", ["employee_id", "knowledge_key", "occurred_at"])
    op.create_index("ix_development_quiz_results_plan_skill", "development_quiz_item_results", ["training_plan_id", "skill_tag"])


def downgrade() -> None:
    op.drop_index("ix_development_quiz_results_plan_skill", table_name="development_quiz_item_results")
    op.drop_index("ix_development_quiz_results_knowledge", table_name="development_quiz_item_results")
    op.drop_index("ix_development_quiz_results_employee_task", table_name="development_quiz_item_results")
    op.drop_table("development_quiz_item_results")
    op.drop_index("ix_development_learning_events_task_type_time", table_name="development_learning_events")
    op.drop_index("ix_development_learning_events_plan_type_time", table_name="development_learning_events")
    op.drop_index("ix_development_learning_events_employee_time", table_name="development_learning_events")
    op.drop_table("development_learning_events")
