"""store the firm-wide IMS address book locally"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0031_ims_contacts"
down_revision = "0030_training_signals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ims_contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("lastname", sa.String(120), nullable=False, server_default=""),
        sa.Column("workcode", sa.String(80), nullable=False, server_default=""),
        sa.Column("sex", sa.String(20), nullable=False, server_default=""),
        sa.Column("department", sa.String(240), nullable=False, server_default=""),
        sa.Column("department_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("subcompany", sa.String(240), nullable=False, server_default=""),
        sa.Column("subcompany_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("job_title", sa.String(240), nullable=False, server_default=""),
        sa.Column("job_activity", sa.String(240), nullable=False, server_default=""),
        sa.Column("job_group", sa.String(240), nullable=False, server_default=""),
        sa.Column("rank_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(80), nullable=False, server_default=""),
        sa.Column("location", sa.String(240), nullable=False, server_default=""),
        sa.Column("mobile", sa.String(80), nullable=False, server_default=""),
        sa.Column("telephone", sa.String(80), nullable=False, server_default=""),
        sa.Column("email", sa.String(255), nullable=False, server_default=""),
        sa.Column("fax", sa.String(80), nullable=False, server_default=""),
        sa.Column("extension", sa.String(80), nullable=False, server_default=""),
        sa.Column("manager", sa.String(120), nullable=False, server_default=""),
        sa.Column("manager_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("dsporder", sa.String(40), nullable=False, server_default=""),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_ims_contacts_workcode", "ims_contacts", ["workcode"])
    op.create_index("ix_ims_contacts_lastname", "ims_contacts", ["lastname"])
    op.create_index("ix_ims_contacts_email", "ims_contacts", ["email"])


def downgrade() -> None:
    op.drop_index("ix_ims_contacts_email", table_name="ims_contacts")
    op.drop_index("ix_ims_contacts_lastname", table_name="ims_contacts")
    op.drop_index("ix_ims_contacts_workcode", table_name="ims_contacts")
    op.drop_table("ims_contacts")
