"""add standardized review finding fields

Revision ID: 0009_findings
Revises: 0008_timeliness
Create Date: 2026-08-18
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_findings"
down_revision = "0008_timeliness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_findings", sa.Column("issue_no", sa.String(length=80), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"))
    op.add_column("review_findings", sa.Column("c22_related", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("review_findings", sa.Column("workpaper_file", sa.Text(), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("location", sa.Text(), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("recommendation", sa.Text(), nullable=False, server_default=""))
    op.create_index("ix_review_findings_issue_no", "review_findings", ["issue_no"])


def downgrade() -> None:
    op.drop_index("ix_review_findings_issue_no", table_name="review_findings")
    op.drop_column("review_findings", "recommendation")
    op.drop_column("review_findings", "location")
    op.drop_column("review_findings", "workpaper_file")
    op.drop_column("review_findings", "c22_related")
    op.drop_column("review_findings", "source")
    op.drop_column("review_findings", "issue_no")
