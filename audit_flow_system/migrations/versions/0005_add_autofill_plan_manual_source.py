"""add autofill plan manual source

Revision ID: 0005_plan_source
Revises: 0004_rule_imports
Create Date: 2026-06-18
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_plan_source"
down_revision = "0004_rule_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "autofill_plan_items",
        sa.Column("value_source", sa.String(80), nullable=False, server_default="rule"),
    )
    op.add_column(
        "autofill_plan_items",
        sa.Column("manual_correction_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "autofill_plan_items",
        sa.Column("original_rule_value", sa.Text(), nullable=False, server_default=""),
    )
    op.create_foreign_key(
        "fk_autofill_plan_items_manual_correction_id",
        "autofill_plan_items",
        "rule_manual_corrections",
        ["manual_correction_id"],
        ["id"],
    )
    op.create_index(
        "ix_autofill_plan_items_manual_correction_id",
        "autofill_plan_items",
        ["manual_correction_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_autofill_plan_items_manual_correction_id", table_name="autofill_plan_items")
    op.drop_constraint(
        "fk_autofill_plan_items_manual_correction_id",
        "autofill_plan_items",
        type_="foreignkey",
    )
    op.drop_column("autofill_plan_items", "original_rule_value")
    op.drop_column("autofill_plan_items", "manual_correction_id")
    op.drop_column("autofill_plan_items", "value_source")
