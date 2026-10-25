"""Durable delivery, export jobs and materialized read models; preserve legacy rows."""

import sqlalchemy as sa

from alembic import op

revision = "20261025_0005"
down_revision = "20261025_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subscription",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.add_column("subscription", sa.Column("last_dispatch_at", sa.DateTime(timezone=True)))

    op.add_column("notification", sa.Column("delivery_key", sa.String(64)))
    op.create_unique_constraint("uq_notification_delivery_key", "notification", ["delivery_key"])
    op.add_column("market_entry_signal", sa.Column("event_key", sa.String(64)))
    op.create_unique_constraint(
        "uq_market_entry_signal_event_key", "market_entry_signal", ["event_key"]
    )
    op.create_table(
        "domain_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(64), nullable=False, unique=True),
        sa.Column("module", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_domain_event_module", "domain_event", ["module"])
    op.create_table(
        "notification_receipt",
        sa.Column(
            "subscription_id",
            sa.Integer(),
            sa.ForeignKey("subscription.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("domain_event.id"), primary_key=True),
    )
    op.create_table(
        "background_task",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("file_ref", sa.Text()),
        sa.Column("error", sa.String(255)),
    )
    op.create_index("ix_background_task_user_id", "background_task", ["user_id"])
    op.create_index("ix_background_task_status_lease", "background_task", ["status", "lease_until"])
    op.create_table(
        "data_revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_table(
        "read_model_snapshot",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
    )
    op.create_table(
        "model_artifact",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
    )
    for view, prefix in (
        ("mv_region_density", "radar:"),
        ("mv_white_space", "white:"),
        ("mv_investment_timeline", "timeline:"),
    ):
        op.execute(
            f"CREATE MATERIALIZED VIEW {view} AS SELECT key AS snapshot_key, payload, "
            "source_revision, calculated_at, version FROM read_model_snapshot "
            f"WHERE key LIKE '{prefix}%'"
        )
        op.execute(f"CREATE UNIQUE INDEX ix_{view}_key ON {view} (snapshot_key)")


def downgrade():
    for view in ("mv_region_density", "mv_white_space", "mv_investment_timeline"):
        op.execute(f"DROP MATERIALIZED VIEW {view}")
    for table in (
        "model_artifact",
        "read_model_snapshot",
        "data_revision",
        "background_task",
        "notification_receipt",
        "domain_event",
    ):
        op.drop_table(table)
    op.drop_constraint("uq_market_entry_signal_event_key", "market_entry_signal", type_="unique")
    op.drop_column("market_entry_signal", "event_key")
    op.drop_constraint("uq_notification_delivery_key", "notification", type_="unique")
    op.drop_column("notification", "delivery_key")
    op.drop_column("subscription", "last_dispatch_at")
    op.drop_column("subscription", "created_at")
