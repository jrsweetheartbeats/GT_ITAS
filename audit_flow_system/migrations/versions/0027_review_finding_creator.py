"""Track the user who added each review finding."""

from alembic import op
import sqlalchemy as sa


revision = "0027_review_finding_creator"
down_revision = "0026_review_record_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_findings", sa.Column("created_by_user_id", sa.Integer(), nullable=True))
    op.create_index("ix_review_findings_created_by_user_id", "review_findings", ["created_by_user_id"])
    op.create_foreign_key(
        "fk_review_findings_created_by_user_id_users",
        "review_findings",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_review_findings_created_by_user_id_users", "review_findings", type_="foreignkey")
    op.drop_index("ix_review_findings_created_by_user_id", table_name="review_findings")
    op.drop_column("review_findings", "created_by_user_id")
