"""Add a creation timestamp to notifications, including existing rows."""

import sqlalchemy as sa

from alembic import op

revision = "20261025_0002"
down_revision = "20261025_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_column("notification", "created_at")
