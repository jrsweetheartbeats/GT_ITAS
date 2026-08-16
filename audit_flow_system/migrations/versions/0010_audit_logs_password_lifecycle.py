"""add audit logs and password lifecycle

Revision ID: 0010_audit_password
Revises: 0009_learning
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_audit_password"
down_revision = "0009_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("password_expires_at", sa.DateTime(), nullable=True))
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("username", sa.String(120), nullable=False, server_default=""),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ip_address", sa.String(80), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(500), nullable=False, server_default=""),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_logs_user_time", "audit_logs", ["user_id", "occurred_at"])
    op.create_index("ix_audit_logs_action_time", "audit_logs", ["action", "occurred_at"])
    op.create_index("ix_audit_logs_project_time", "audit_logs", ["project_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_column("users", "password_expires_at")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "must_change_password")
