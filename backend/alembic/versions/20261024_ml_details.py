"""Add optional NLP metadata and allow abstaining scoring snapshots.

The repository has no baseline revision. Existing tables must be initialized before
applying this additive revision; fresh installations use metadata.create_all first.
No existing rows are removed or assigned invented evidence.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261024_ml_details"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("project_need") or not inspector.has_table("scoring_snapshot"):
        raise RuntimeError(
            "Нет исходной схемы: сначала создайте таблицы существующих Base.metadata"
        )
    if "details_json" not in {c["name"] for c in inspector.get_columns("project_need")}:
        op.add_column("project_need", sa.Column("details_json", sa.JSON(), nullable=True))
    op.alter_column("scoring_snapshot", "score", existing_type=sa.Float(), nullable=True)


def downgrade():
    count = (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM scoring_snapshot WHERE score IS NULL"))
        .scalar_one()
    )
    if count:
        raise RuntimeError("Нельзя вернуть NOT NULL: есть скоринги с недостаточными данными")
    op.alter_column("scoring_snapshot", "score", existing_type=sa.Float(), nullable=False)
    op.drop_column("project_need", "details_json")
