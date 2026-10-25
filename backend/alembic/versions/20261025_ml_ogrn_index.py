"""Index the OGRN fallback used for every new registry company."""

from alembic import op

revision = "20261025_ml_ogrn_index"
down_revision = "20261025_ml_source_match_index"
branch_labels = None
depends_on = None
NAME = "ix_company_ogrn"


def upgrade():
    op.create_index(NAME, "company", ["ogrn"], unique=False)


def downgrade():
    op.drop_index(NAME, table_name="company")
