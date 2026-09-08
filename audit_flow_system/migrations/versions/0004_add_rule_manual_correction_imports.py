"""add rule manual correction imports

Revision ID: 0004_rule_imports
Revises: 0003_rule_manual_corrections
Create Date: 2026-06-18
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_rule_imports"
down_revision = "0003_rule_manual_corrections"
branch_labels = None
depends_on = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("rule_manual_correction_imports"):
        return
    op.create_table(
        "rule_manual_correction_imports",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("processed_rows", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("conflict_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("result_payload", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        *timestamp_columns(),
    )
    op.create_index(
        "ix_rule_manual_correction_imports_project_id",
        "rule_manual_correction_imports",
        ["project_id"],
    )
    op.create_index(
        "ix_rule_manual_correction_imports_status",
        "rule_manual_correction_imports",
        ["status"],
    )
    op.create_index(
        "ix_rule_manual_correction_imports_created_at",
        "rule_manual_correction_imports",
        ["created_at"],
    )


def downgrade() -> None:
    for index_name in [
        "ix_rule_manual_correction_imports_created_at",
        "ix_rule_manual_correction_imports_status",
        "ix_rule_manual_correction_imports_project_id",
    ]:
        op.drop_index(index_name, table_name="rule_manual_correction_imports")
    op.drop_table("rule_manual_correction_imports")
