"""store homepage project directory fields as real columns"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from audit_flow_system.services.project_directory_fields import HOME_DIRECTORY_FIELDS, split_project_description

revision = "0033_project_directory_columns"
down_revision = "0032_project_member_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("department", sa.String(240), nullable=False, server_default=""))
    op.add_column("projects", sa.Column("scope_description", sa.Text(), nullable=False, server_default=""))
    op.add_column("projects", sa.Column("business_revenue", sa.String(240), nullable=False, server_default=""))
    op.add_column("projects", sa.Column("charge_with_tax", sa.String(80), nullable=False, server_default=""))
    op.add_column("projects", sa.Column("charge_without_tax", sa.String(80), nullable=False, server_default=""))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, description FROM projects")).mappings().all()
    for row in rows:
        fields, leftover = split_project_description(row["description"])
        bind.execute(
            sa.text(
                "UPDATE projects SET department = :department, scope_description = :scope_description, "
                "business_revenue = :business_revenue, charge_with_tax = :charge_with_tax, "
                "charge_without_tax = :charge_without_tax, description = :description WHERE id = :id"
            ),
            {
                "id": int(row["id"]),
                "description": leftover,
                **{key: fields[key] for key in HOME_DIRECTORY_FIELDS},
            },
        )


def downgrade() -> None:
    op.drop_column("projects", "charge_without_tax")
    op.drop_column("projects", "charge_with_tax")
    op.drop_column("projects", "business_revenue")
    op.drop_column("projects", "scope_description")
    op.drop_column("projects", "department")
