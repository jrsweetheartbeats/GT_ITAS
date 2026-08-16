"""expand audit log detail storage

Revision ID: 0011_audit_longtext
Revises: 0010_audit_password
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT


revision = "0011_audit_longtext"
down_revision = "0010_audit_password"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("audit_logs", "detail_json", existing_type=sa.Text(), type_=LONGTEXT(), nullable=False)


def downgrade() -> None:
    op.alter_column("audit_logs", "detail_json", existing_type=LONGTEXT(), type_=sa.Text(), nullable=False)
