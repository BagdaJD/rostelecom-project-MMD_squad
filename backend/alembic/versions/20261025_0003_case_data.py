"""Source and geography for companies; honest date precision for investment projects."""

import sqlalchemy as sa

from alembic import op

revision = "20261025_0003"
down_revision = "20261025_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("company", sa.Column("municipality", sa.String(255)))
    op.add_column("company", sa.Column("city", sa.String(255)))
    op.add_column("company", sa.Column("settlement", sa.String(255)))
    op.add_column("company", sa.Column("source_id", sa.Integer()))
    op.add_column(
        "company",
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("company", sa.Column("attributes_json", sa.JSON()))
    op.create_foreign_key(
        "fk_company_source_id_source_record", "company", "source_record", ["source_id"], ["id"]
    )
    op.create_index("ix_company_municipality", "company", ["municipality"])

    op.execute("""UPDATE company c SET source_id = (
        SELECT m.source_record_id FROM company_match m
        JOIN source_record s ON s.id = m.source_record_id
        WHERE m.company_id = c.id ORDER BY s.fetched_at DESC, m.id DESC LIMIT 1
    )""")
    op.execute("""UPDATE company c SET is_synthetic = TRUE FROM source_record s
        WHERE s.id = c.source_id AND (s.source = 'demo' OR s.source LIKE 'synthetic%')""")
    op.add_column("investment_project", sa.Column("municipality", sa.String(255)))
    op.create_index("ix_investment_project_municipality", "investment_project", ["municipality"])
    op.add_column(
        "investment_project",
        sa.Column("start_precision", sa.String(8), nullable=False, server_default="day"),
    )
    op.add_column(
        "investment_project",
        sa.Column("end_precision", sa.String(8), nullable=False, server_default="day"),
    )
    op.add_column(
        "investment_project",
        sa.Column("stage_method", sa.String(32), nullable=False, server_default="source"),
    )
    op.add_column("investment_project", sa.Column("stage_evidence", sa.Text()))
    op.add_column(
        "investment_project",
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("investment_project", sa.Column("attributes_json", sa.JSON()))
    op.execute("""UPDATE investment_project p SET is_synthetic = TRUE FROM source_record s
        WHERE s.id = p.source_id AND s.source IN ('demo', 'investregistry')
        AND s.raw_payload->>'source_url' LIKE 'https://example.com/%'""")
    for table in ("investment_event", "project_milestone"):
        op.add_column(
            table, sa.Column("date_precision", sa.String(8), nullable=False, server_default="day")
        )


def downgrade() -> None:
    for table in ("investment_event", "project_milestone"):
        op.drop_column(table, "date_precision")
    for name in (
        "attributes_json",
        "is_synthetic",
        "stage_evidence",
        "stage_method",
        "end_precision",
        "start_precision",
    ):
        op.drop_column("investment_project", name)
    op.drop_index("ix_investment_project_municipality", table_name="investment_project")
    op.drop_column("investment_project", "municipality")
    op.drop_constraint("fk_company_source_id_source_record", "company", type_="foreignkey")
    op.drop_index("ix_company_municipality", table_name="company")
    for name in (
        "attributes_json",
        "is_synthetic",
        "source_id",
        "settlement",
        "city",
        "municipality",
    ):
        op.drop_column("company", name)
