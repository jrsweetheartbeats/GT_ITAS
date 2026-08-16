"""add learning practice module

Revision ID: 0009_learning
Revises: 0008_timeliness
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_learning"
down_revision = "0008_timeliness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_weeks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("week_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("learning_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("courseware_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code", name="uq_training_weeks_code"),
        sa.UniqueConstraint("week_no", name="uq_training_weeks_week_no"),
    )
    op.create_index("ix_training_weeks_enabled_sort", "training_weeks", ["enabled", "sort_order"])
    op.create_table(
        "practice_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("training_week_id", sa.Integer(), sa.ForeignKey("training_weeks.id"), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("question_type", sa.String(40), nullable=False, server_default="sql"),
        sa.Column("project_scope", sa.String(40), nullable=False, server_default="general"),
        sa.Column("answer_guidance", sa.Text(), nullable=False, server_default=""),
        sa.Column("validation_rules_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("points", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code", name="uq_practice_questions_code"),
    )
    op.create_index("ix_practice_questions_week_sort", "practice_questions", ["training_week_id", "sort_order"])
    op.create_index("ix_practice_questions_enabled", "practice_questions", ["enabled"])
    op.create_table(
        "practice_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("practice_questions.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("answer_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("sql_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("validation_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("validation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("question_id", "user_id", "attempt_no", name="uq_practice_submission_attempt"),
    )
    op.create_index("ix_practice_submissions_question_user", "practice_submissions", ["question_id", "user_id"])
    op.create_index("ix_practice_submissions_status", "practice_submissions", ["status"])
    op.create_index("ix_practice_submissions_submitted_at", "practice_submissions", ["submitted_at"])


def downgrade() -> None:
    op.drop_table("practice_submissions")
    op.drop_table("practice_questions")
    op.drop_table("training_weeks")
