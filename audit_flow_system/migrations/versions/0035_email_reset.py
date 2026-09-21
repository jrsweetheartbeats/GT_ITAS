"""add email destination for password-reset challenges"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0035_email_reset"
down_revision = "0034_notes_sms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("password_reset_challenges")}
    if "email" not in columns:
        op.add_column(
            "password_reset_challenges",
            sa.Column("email", sa.String(255), nullable=False, server_default=""),
        )


def downgrade() -> None:
    op.drop_column("password_reset_challenges", "email")
