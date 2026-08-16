"""quality template lifecycle

Revision ID: 0006_quality_template
Revises: 0005_plan_source
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_quality_template"
down_revision = "0005_plan_source"
branch_labels = None
depends_on = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("review_findings", sa.Column("assignee_user_id", sa.Integer(), nullable=True))
    op.add_column("review_findings", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column(
        "review_findings",
        sa.Column("review_comment", sa.Text(), nullable=False, server_default=""),
    )
    op.create_foreign_key(
        "fk_review_findings_assignee_user_id",
        "review_findings",
        "users",
        ["assignee_user_id"],
        ["id"],
    )
    op.create_index("ix_review_findings_assignee_user_id", "review_findings", ["assignee_user_id"])
    op.create_index("ix_review_findings_due_date", "review_findings", ["due_date"])

    op.create_table(
        "review_finding_histories",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("review_findings.id"), nullable=False),
        sa.Column("operator_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("old_status", sa.String(40), nullable=False, server_default=""),
        sa.Column("new_status", sa.String(40), nullable=False, server_default=""),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("change_summary", sa.Text(), nullable=False, server_default=""),
        *timestamp_columns(),
    )
    op.create_index("ix_review_finding_histories_finding_id", "review_finding_histories", ["finding_id"])
    op.create_index(
        "ix_review_finding_histories_operator_user_id",
        "review_finding_histories",
        ["operator_user_id"],
    )

    op.add_column("workpaper_templates", sa.Column("applicable_year", sa.Integer(), nullable=True))
    op.add_column(
        "workpaper_templates",
        sa.Column("update_note", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "workpaper_templates",
        sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_workpaper_templates_applicable_year", "workpaper_templates", ["applicable_year"])
    op.create_index("ix_workpaper_templates_is_latest", "workpaper_templates", ["is_latest"])


def downgrade() -> None:
    op.drop_index("ix_workpaper_templates_is_latest", table_name="workpaper_templates")
    op.drop_index("ix_workpaper_templates_applicable_year", table_name="workpaper_templates")
    op.drop_column("workpaper_templates", "is_latest")
    op.drop_column("workpaper_templates", "update_note")
    op.drop_column("workpaper_templates", "applicable_year")

    op.drop_index("ix_review_finding_histories_operator_user_id", table_name="review_finding_histories")
    op.drop_index("ix_review_finding_histories_finding_id", table_name="review_finding_histories")
    op.drop_table("review_finding_histories")

    op.drop_index("ix_review_findings_due_date", table_name="review_findings")
    op.drop_index("ix_review_findings_assignee_user_id", table_name="review_findings")
    op.drop_constraint("fk_review_findings_assignee_user_id", "review_findings", type_="foreignkey")
    op.drop_column("review_findings", "review_comment")
    op.drop_column("review_findings", "due_date")
    op.drop_column("review_findings", "assignee_user_id")
