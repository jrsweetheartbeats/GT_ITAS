"""add rule manual corrections

Revision ID: 0003_rule_manual_corrections
Revises: 0002_design_tables
Create Date: 2026-06-17
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_rule_manual_corrections"
down_revision = "0002_design_tables"
branch_labels = None
depends_on = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "rule_manual_corrections",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("workpaper_code", sa.String(120), nullable=False),
        sa.Column("workpaper_name", sa.String(240), nullable=False),
        sa.Column("rule_kind", sa.String(40), nullable=False),
        sa.Column("rule_id", sa.String(160), nullable=False),
        sa.Column("candidate_key", sa.String(255), nullable=False),
        sa.Column("correction_key", sa.String(64), nullable=False),
        sa.Column("sheet_or_section", sa.String(240), nullable=False),
        sa.Column("target_field", sa.String(240), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(120), nullable=False),
        sa.Column("original_payload", sa.Text(), nullable=False),
        sa.Column("manual_correction", sa.Text(), nullable=False),
        sa.Column("normalized_payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("conflict_message", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        *timestamp_columns(),
        sa.UniqueConstraint("project_id", "rule_kind", "correction_key", name="uq_rule_manual_corrections_project_key"),
    )
    op.create_index("ix_rule_manual_corrections_project_id", "rule_manual_corrections", ["project_id"])
    op.create_index("ix_rule_manual_corrections_rule_kind", "rule_manual_corrections", ["rule_kind"])
    op.create_index("ix_rule_manual_corrections_rule_id", "rule_manual_corrections", ["rule_id"])
    op.create_index("ix_rule_manual_corrections_candidate_key", "rule_manual_corrections", ["candidate_key"])
    op.create_index("ix_rule_manual_corrections_status", "rule_manual_corrections", ["status"])


def downgrade() -> None:
    for index_name in [
        "ix_rule_manual_corrections_status",
        "ix_rule_manual_corrections_candidate_key",
        "ix_rule_manual_corrections_rule_id",
        "ix_rule_manual_corrections_rule_kind",
        "ix_rule_manual_corrections_project_id",
    ]:
        op.drop_index(index_name, table_name="rule_manual_corrections")
    op.drop_table("rule_manual_corrections")
