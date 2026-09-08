"""add autofill rule actions

Revision ID: 0007_rule_actions
Revises: 0006_quality_template
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_rule_actions"
down_revision = "0006_quality_template"
branch_labels = None
depends_on = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "autofill_rule_actions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("action_key", sa.String(64), nullable=False),
        sa.Column("rule_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("workpaper_code", sa.String(120), nullable=False, server_default=""),
        sa.Column("workpaper_name", sa.String(240), nullable=False, server_default=""),
        sa.Column("target_field", sa.String(240), nullable=False, server_default=""),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("action_status", sa.String(40), nullable=False, server_default="pending_confirm"),
        sa.Column("action_note", sa.Text(), nullable=False),
        sa.Column("source_verification_status", sa.String(40), nullable=False, server_default=""),
        sa.Column("conflict_message", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        *timestamp_columns(),
        sa.UniqueConstraint("project_id", "action_key", name="uq_autofill_rule_actions_project_key"),
    )
    op.create_index("ix_autofill_rule_actions_project_id", "autofill_rule_actions", ["project_id"])
    op.create_index("ix_autofill_rule_actions_rule_id", "autofill_rule_actions", ["rule_id"])
    op.create_index("ix_autofill_rule_actions_workpaper_code", "autofill_rule_actions", ["workpaper_code"])
    op.create_index("ix_autofill_rule_actions_status", "autofill_rule_actions", ["action_status"])


def downgrade() -> None:
    for index_name in [
        "ix_autofill_rule_actions_status",
        "ix_autofill_rule_actions_workpaper_code",
        "ix_autofill_rule_actions_rule_id",
        "ix_autofill_rule_actions_project_id",
    ]:
        op.drop_index(index_name, table_name="autofill_rule_actions")
    op.drop_table("autofill_rule_actions")
