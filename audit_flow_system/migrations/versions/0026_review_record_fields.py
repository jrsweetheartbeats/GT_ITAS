"""add workbook-style review record fields

Revision ID: 0026_review_record_fields
Revises: 0025_project_alternate_quality
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0026_review_record_fields"
down_revision = "0025_project_alternate_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_findings", sa.Column("standard_index_code", sa.String(length=40), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("audit_stage", sa.String(length=40), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("finding_type", sa.String(length=80), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("issue_step", sa.String(length=80), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("issue_category", sa.String(length=240), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("project_reply", sa.Text(), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("resolution_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("review_findings", sa.Column("review_stage", sa.String(length=80), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("field_lead", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("project_reviewer", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("review_findings", sa.Column("note", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    for column in (
        "note", "project_reviewer", "field_lead", "review_stage", "resolution_confirmed",
        "project_reply", "issue_category", "issue_step", "finding_type", "audit_stage", "standard_index_code",
    ):
        op.drop_column("review_findings", column)
