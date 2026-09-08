"""add employee training plan hierarchy and assessment history"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_training_core"
down_revision = "0011_development"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "development_training_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("employee_code", sa.String(80), nullable=False),
        sa.Column("employee_name", sa.String(120), nullable=False),
        sa.Column("plan_type", sa.String(80), nullable=False, server_default="special_training"),
        sa.Column("period", sa.String(80), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("overall_goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("mentor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_development_training_plans_employee_status", "development_training_plans", ["employee_id", "status"])
    op.create_index("ix_development_training_plans_period", "development_training_plans", ["period"])

    op.create_table(
        "development_training_weeks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("training_plan_id", sa.Integer(), sa.ForeignKey("development_training_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("expected_deliverable", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.UniqueConstraint("training_plan_id", "week_no", name="uq_development_training_weeks_plan_no"),
    )
    op.create_index("ix_development_training_weeks_plan_sort", "development_training_weeks", ["training_plan_id", "sort_order"])

    op.create_table(
        "development_training_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("training_week_id", sa.Integer(), sa.ForeignKey("development_training_weeks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_code", sa.String(100), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("task_type", sa.String(40), nullable=False, server_default="learning"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("estimated_hours", sa.Float(), nullable=True),
        sa.Column("prerequisite_task_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("completion_criteria", sa.Text(), nullable=False, server_default=""),
        sa.Column("submission_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mentor_review_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(40), nullable=False, server_default="not_started"),
        *_timestamps(),
        sa.UniqueConstraint("training_week_id", "task_code", name="uq_development_training_tasks_week_code"),
    )
    op.create_index("ix_development_training_tasks_week_sort", "development_training_tasks", ["training_week_id", "sort_order"])
    op.create_index("ix_development_training_tasks_status_due", "development_training_tasks", ["status", "due_date"])

    op.create_table(
        "development_learning_materials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("development_training_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("material_type", sa.String(40), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
    )
    op.create_index("ix_development_learning_materials_task_sort", "development_learning_materials", ["task_id", "sort_order"])

    op.create_table(
        "development_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("development_training_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submission_type", sa.String(40), nullable=False, server_default="assignment"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachment", sa.Text(), nullable=False, server_default=""),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(40), nullable=False, server_default="submitted"),
        *_timestamps(),
        sa.UniqueConstraint("task_id", "employee_id", "version", name="uq_development_submissions_task_employee_version"),
    )
    op.create_index("ix_development_submissions_employee_submitted", "development_submissions", ["employee_id", "submitted_at"])
    op.create_index("ix_development_submissions_task_status", "development_submissions", ["task_id", "status"])

    op.create_table(
        "development_submission_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("development_submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("result", sa.String(40), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("comments", sa.Text(), nullable=False, server_default=""),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_development_submission_reviews_submission_time", "development_submission_reviews", ["submission_id", "reviewed_at"])
    op.create_index("ix_development_submission_reviews_reviewer", "development_submission_reviews", ["reviewer_id"])

    op.create_table(
        "development_blockers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("development_training_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("confirmed_facts", sa.Text(), nullable=False, server_default=""),
        sa.Column("materials_checked", sa.Text(), nullable=False, server_default=""),
        sa.Column("initial_judgment", sa.Text(), nullable=False, server_default=""),
        sa.Column("attempted_solutions", sa.Text(), nullable=False, server_default=""),
        sa.Column("missing_information", sa.Text(), nullable=False, server_default=""),
        sa.Column("mentor_question", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column("mentor_response", sa.Text(), nullable=False, server_default=""),
        *_timestamps(),
    )
    op.create_index("ix_development_blockers_employee_status", "development_blockers", ["employee_id", "status"])
    op.create_index("ix_development_blockers_task_status", "development_blockers", ["task_id", "status"])

    op.create_table(
        "development_monthly_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("training_plan_id", sa.Integer(), sa.ForeignKey("development_training_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("period", sa.String(80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("total_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("assessed_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("training_plan_id", "period", name="uq_development_monthly_assessments_plan_period"),
    )
    op.create_index("ix_development_monthly_assessments_employee_period", "development_monthly_assessments", ["employee_id", "period"])

    op.create_table(
        "development_assessment_dimensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("development_monthly_assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dimension_code", sa.String(80), nullable=False),
        sa.Column("dimension_name", sa.String(160), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("comments", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.UniqueConstraint("assessment_id", "dimension_code", name="uq_development_assessment_dimensions_code"),
    )
    op.create_index("ix_development_assessment_dimensions_assessment_sort", "development_assessment_dimensions", ["assessment_id", "sort_order"])


def downgrade() -> None:
    op.drop_table("development_assessment_dimensions")
    op.drop_table("development_monthly_assessments")
    op.drop_table("development_blockers")
    op.drop_table("development_submission_reviews")
    op.drop_table("development_submissions")
    op.drop_table("development_learning_materials")
    op.drop_table("development_training_tasks")
    op.drop_table("development_training_weeks")
    op.drop_table("development_training_plans")
