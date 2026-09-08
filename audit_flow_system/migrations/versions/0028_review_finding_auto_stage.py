"""Initialize automatic review stages for existing findings."""

from alembic import op


revision = "0028_review_finding_auto_stage"
down_revision = "0027_review_finding_creator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE review_findings SET review_stage = '第一阶段' "
        "WHERE review_stage IS NULL OR TRIM(review_stage) = ''"
    )


def downgrade() -> None:
    # Existing blank values cannot be distinguished from stages assigned after upgrade.
    pass
