"""Index the source lookup used on every imported company.

Without this index the provenance join scans CompanyMatch on each registry row.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261025_ml_source_match_index"
down_revision = "20261024_ml_details"
branch_labels = None
depends_on = None
NAME = "ix_company_match_source_record_id"


def upgrade():
    names = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("company_match")}
    if NAME not in names:
        op.create_index(NAME, "company_match", ["source_record_id"], unique=False)


def downgrade():
    names = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("company_match")}
    if NAME in names:
        op.drop_index(NAME, table_name="company_match")
