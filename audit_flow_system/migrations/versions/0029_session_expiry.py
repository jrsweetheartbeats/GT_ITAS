"""Expire all existing login tokens and require expiry for new sessions."""

from alembic import op
import sqlalchemy as sa


revision = "0029_session_expiry"
down_revision = "0028_review_finding_auto_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"]: column for column in inspector.get_columns("login_sessions")}
    if "expires_at" not in columns:
        op.add_column("login_sessions", sa.Column("expires_at", sa.DateTime(), nullable=True))
    # Existing bearer tokens predate expiry enforcement and must not survive the
    # upgrade without an explicit re-login.
    op.execute("UPDATE login_sessions SET expires_at = UTC_TIMESTAMP() WHERE expires_at IS NULL")
    columns = {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns("login_sessions")}
    if columns["expires_at"]["nullable"]:
        op.alter_column("login_sessions", "expires_at", existing_type=sa.DateTime(), nullable=False)
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("login_sessions")}
    if "ix_login_sessions_expires_at" not in indexes:
        op.create_index("ix_login_sessions_expires_at", "login_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_login_sessions_expires_at", table_name="login_sessions")
    op.drop_column("login_sessions", "expires_at")
