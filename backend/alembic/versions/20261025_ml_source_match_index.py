"""Index the source lookup used on every imported company.

Without this index the provenance join scans CompanyMatch on each registry row.
"""

from alembic import op

revision = "20261025_ml_source_match_index"
down_revision = "20261024_ml_details"
branch_labels = None
depends_on = None
NAME = "ix_company_match_source_record_id"


def upgrade():
    op.create_index(NAME, "company_match", ["source_record_id"], unique=False)


def downgrade():
    op.drop_index(NAME, table_name="company_match")
