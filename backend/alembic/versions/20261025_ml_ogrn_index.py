"""Index the OGRN fallback used for every new registry company."""

import sqlalchemy as sa

from alembic import op

revision = "20261025_ml_ogrn_index"
down_revision = "20261025_ml_source_match_index"
branch_labels = None
depends_on = None
NAME = "ix_company_ogrn"


def upgrade():
    if NAME not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("company")}:
        op.create_index(NAME, "company", ["ogrn"], unique=False)


def downgrade():
    if NAME in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("company")}:
        op.drop_index(NAME, table_name="company")
