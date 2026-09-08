"""add structured employee development cycle"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_development"
down_revision = "0010_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "development_employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("current_role", sa.String(120), nullable=False, server_default=""),
        sa.Column("hired_on", sa.Date(), nullable=True),
        sa.Column("mentor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("direction", sa.String(240), nullable=False, server_default=""),
        sa.Column("half_year_goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("year_goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("advantages", sa.Text(), nullable=False, server_default=""),
        sa.Column("weaknesses", sa.Text(), nullable=False, server_default=""),
        sa.Column("current_focus", sa.Text(), nullable=False, server_default=""),
        sa.Column("recent_issues", sa.Text(), nullable=False, server_default=""),
        sa.Column("mentor_observation", sa.Text(), nullable=False, server_default=""),
        sa.Column("development_intent", sa.Text(), nullable=False, server_default=""),
        sa.Column("questionnaire_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source_reference", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code", name="uq_development_employees_code"),
        sa.UniqueConstraint("user_id", name="uq_development_employees_user_id"),
    )
    op.create_index("ix_development_employees_status", "development_employees", ["status"])
    op.create_table(
        "competency_dimensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code", name="uq_competency_dimensions_code"),
    )
    op.create_table(
        "employee_competencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("competency_id", sa.Integer(), sa.ForeignKey("competency_dimensions.id"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("assessed_on", sa.Date(), nullable=False),
        sa.Column("source", sa.String(80), nullable=False, server_default="manual"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("assessor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_employee_competencies_employee_date", "employee_competencies", ["employee_id", "assessed_on"])
    op.create_index("ix_employee_competencies_dimension_date", "employee_competencies", ["competency_id", "assessed_on"])
    op.create_table(
        "development_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("plan_type", sa.String(40), nullable=False, server_default="annual"),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("half_year_goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("year_goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("source_type", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("source_reference", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_development_plans_employee_status", "development_plans", ["employee_id", "status"])
    op.create_table(
        "monthly_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("development_plan_id", sa.Integer(), sa.ForeignKey("development_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("month_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("month_goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("generation_basis", sa.Text(), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("expected_project", sa.Text(), nullable=False, server_default=""),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("generated_by", sa.String(80), nullable=False, server_default="manual"),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("development_plan_id", "month_no", name="uq_monthly_plans_plan_month"),
    )
    op.create_index("ix_monthly_plans_status", "monthly_plans", ["status"])
    op.create_table(
        "weekly_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("monthly_plan_id", sa.Integer(), sa.ForeignKey("monthly_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_no", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(240), nullable=False),
        sa.Column("learning_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("exercise_case", sa.Text(), nullable=False, server_default=""),
        sa.Column("deliverable", sa.Text(), nullable=False, server_default=""),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False, server_default=""),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="not_started"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_weekly_tasks_month_week", "weekly_tasks", ["monthly_plan_id", "week_no"])
    op.create_index("ix_weekly_tasks_status_due", "weekly_tasks", ["status", "due_date"])
    op.create_table(
        "development_exercises",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("weekly_task_id", sa.Integer(), sa.ForeignKey("weekly_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("exercise_type", sa.String(40), nullable=False, server_default="case"),
        sa.Column("topic", sa.String(240), nullable=False),
        sa.Column("difficulty", sa.String(40), nullable=False, server_default="medium"),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False, server_default=""),
        sa.Column("competency_codes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code", name="uq_development_exercises_code"),
    )
    op.create_table(
        "development_exercise_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exercise_id", sa.Integer(), sa.ForeignKey("development_exercises.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachment_reference", sa.Text(), nullable=False, server_default=""),
        sa.Column("used_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("exercise_id", "employee_id", "attempt_no", name="uq_development_submission_attempt"),
    )
    op.create_index("ix_development_submissions_status", "development_exercise_submissions", ["status"])
    op.create_table(
        "development_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submission_id", sa.Integer(), sa.ForeignKey("development_exercise_submissions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("weekly_task_id", sa.Integer(), sa.ForeignKey("weekly_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("needs_redo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_development_reviews_employee_status", "development_reviews", ["employee_id", "status"])
    op.create_table(
        "development_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_id", sa.Integer(), sa.ForeignKey("development_reviews.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source", sa.String(240), nullable=False, server_default=""),
        sa.Column("issue_type", sa.String(80), nullable=False, server_default="method"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(40), nullable=False, server_default="medium"),
        sa.Column("competency_code", sa.String(80), nullable=False, server_default=""),
        sa.Column("improvement_requirement", sa.Text(), nullable=False, server_default=""),
        sa.Column("fingerprint", sa.String(128), nullable=False, server_default=""),
        sa.Column("repeat_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_on", sa.Date(), nullable=True),
        sa.Column("last_seen_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column("verification_method", sa.Text(), nullable=False, server_default=""),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_development_issues_employee_status", "development_issues", ["employee_id", "status"])
    op.create_index("ix_development_issues_fingerprint", "development_issues", ["employee_id", "fingerprint"])
    op.create_table(
        "development_learning_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("development_employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekly_task_id", sa.Integer(), sa.ForeignKey("weekly_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("topic", sa.String(240), nullable=False),
        sa.Column("material_reference", sa.Text(), nullable=False, server_default=""),
        sa.Column("training_date", sa.Date(), nullable=True),
        sa.Column("attended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("self_rating", sa.Float(), nullable=True),
        sa.Column("mentor_rating", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_development_learning_employee_date", "development_learning_records", ["employee_id", "training_date"])
    op.create_table(
        "monthly_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("monthly_plan_id", sa.Integer(), sa.ForeignKey("monthly_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_self_review", sa.Text(), nullable=False, server_default=""),
        sa.Column("mentor_review", sa.Text(), nullable=False, server_default=""),
        sa.Column("completion_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("exercise_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unfamiliar_case_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("project_performance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("initiative_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("competency_changes_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("unresolved_issues_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("next_month_suggestion", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("assessed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("monthly_plan_id", name="uq_monthly_assessments_plan"),
    )
    op.create_table(
        "plan_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("monthly_plan_id", sa.Integer(), sa.ForeignKey("monthly_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("after_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_plan_adjustments_month_time", "plan_adjustments", ["monthly_plan_id", "created_at"])


def downgrade() -> None:
    op.drop_table("plan_adjustments")
    op.drop_table("monthly_assessments")
    op.drop_table("development_learning_records")
    op.drop_table("development_issues")
    op.drop_table("development_reviews")
    op.drop_table("development_exercise_submissions")
    op.drop_table("development_exercises")
    op.drop_table("weekly_tasks")
    op.drop_table("monthly_plans")
    op.drop_table("development_plans")
    op.drop_table("employee_competencies")
    op.drop_table("competency_dimensions")
    op.drop_table("development_employees")
