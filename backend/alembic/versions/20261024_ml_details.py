"""Add optional NLP metadata and allow abstaining scoring snapshots.

The integration adds an explicit dependency on the application migration chain:
the original ML-only branch required an already initialized schema. Revision IDs
are preserved; the dependency makes fresh installation ordering deterministic.
No existing rows are removed or assigned invented evidence.
"""

import sqlalchemy as sa

from alembic import context, op

revision = "20261024_ml_details"
down_revision = None
branch_labels = None
depends_on = "20261025_0005"


def upgrade():
    op.add_column("project_need", sa.Column("details_json", sa.JSON(), nullable=True))
    op.alter_column("scoring_snapshot", "score", existing_type=sa.Float(), nullable=True)


def downgrade():
    if not context.is_offline_mode():
        count = (
            op.get_bind()
            .execute(sa.text("SELECT COUNT(*) FROM scoring_snapshot WHERE score IS NULL"))
            .scalar_one()
        )
        if count:
            raise RuntimeError("Нельзя вернуть NOT NULL: есть скоринги с недостаточными данными")
    op.alter_column("scoring_snapshot", "score", existing_type=sa.Float(), nullable=False)
    op.drop_column("project_need", "details_json")
