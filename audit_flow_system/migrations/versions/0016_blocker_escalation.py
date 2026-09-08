"""add structured blocker escalation and resolution fields"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0016_blocker_escalation"
down_revision = "0015_training_task_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("development_blockers", sa.Column("blocker_type", sa.String(80), nullable=False, server_default="general"))
    op.add_column("development_blockers", sa.Column("self_analysis_complete", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("development_blockers", sa.Column("resolution_action", sa.String(40), nullable=False, server_default=""))
    op.add_column("development_blockers", sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.add_column("development_blockers", sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("development_blockers", "resolved_by_user_id")
    op.drop_column("development_blockers", "resolved_at")
    op.drop_column("development_blockers", "resolution_action")
    op.drop_column("development_blockers", "self_analysis_complete")
    op.drop_column("development_blockers", "blocker_type")
