"""add timeliness fields

Revision ID: 0008_timeliness
Revises: 0007_rule_actions
Create Date: 2026-07-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_timeliness"
down_revision = "0007_rule_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_requests", sa.Column("requested_at", sa.Date(), nullable=True))
    op.add_column("document_requests", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("document_requests", sa.Column("reminder_sent_at", sa.DateTime(), nullable=True))
    op.create_index("ix_document_requests_due_date", "document_requests", ["due_date"])

    op.add_column("review_steps", sa.Column("entered_at", sa.DateTime(), nullable=True))
    op.add_column("review_steps", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("review_steps", sa.Column("sla_days", sa.Integer(), nullable=False, server_default="3"))
    op.create_index("ix_review_steps_due_date", "review_steps", ["due_date"])


def downgrade() -> None:
    op.drop_index("ix_review_steps_due_date", table_name="review_steps")
    op.drop_column("review_steps", "sla_days")
    op.drop_column("review_steps", "due_date")
    op.drop_column("review_steps", "entered_at")

    op.drop_index("ix_document_requests_due_date", table_name="document_requests")
    op.drop_column("document_requests", "reminder_sent_at")
    op.drop_column("document_requests", "due_date")
    op.drop_column("document_requests", "requested_at")
