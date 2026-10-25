"""Initial common and calculator schema; PostGIS indexes are created by GeoAlchemy.

Revision ID: 20261025_0001
Revises: none

Frozen schema: this migration deliberately does not import application models.
"""

import geoalchemy2
import sqlalchemy as sa

from alembic import op

revision = "20261025_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.execute("CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public")
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("totp_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False),
        sa.Column("backup_codes_hash", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_user")),
        sa.UniqueConstraint("login", name=op.f("uq_app_user_login")),
    )
    op.create_index(op.f("ix_app_user_email"), "app_user", ["email"], unique=True)
    op.create_table(
        "calc_deal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("project_type", sa.String(length=32), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=True),
        sa.Column("scale", sa.String(length=16), nullable=True),
        sa.Column("area_m2", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("project_level", sa.String(length=16), nullable=True),
        sa.Column("region_code", sa.String(length=32), nullable=True),
        sa.Column("cost_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("contract_value", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("outcome", sa.String(length=8), nullable=True),
        sa.Column("retro_price_basis", sa.String(length=16), nullable=False),
        sa.Column("financing_scheme", sa.String(length=32), nullable=True),
        sa.Column("payment_scheme", sa.String(length=16), nullable=True),
        sa.Column("closed_at", sa.Date(), nullable=True),
        sa.Column("scope_json", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_deal")),
        sa.UniqueConstraint("fingerprint", name=op.f("uq_calc_deal_fingerprint")),
    )
    op.create_index(op.f("ix_calc_deal_object_type"), "calc_deal", ["object_type"], unique=False)
    op.create_table(
        "calc_dictionary",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dict_code", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order_no", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_dictionary")),
    )
    op.create_index(
        op.f("ix_calc_dictionary_dict_code"), "calc_dictionary", ["dict_code"], unique=False
    )
    op.create_table(
        "calc_estimate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("investment_project_id", sa.Integer(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("price_min", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("price_optimum", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("price_max", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cost_total", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("margin_min", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("margin_optimum", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("margin_max", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("win_probability", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("estimator_mode", sa.String(length=16), nullable=False),
        sa.Column("optimum_method", sa.String(length=32), nullable=True),
        sa.Column("data_quality", sa.String(length=16), nullable=False),
        sa.Column("model_version", sa.String(length=48), nullable=False),
        sa.Column("comparables_json", sa.JSON(), nullable=True),
        sa.Column("adjustments_json", sa.JSON(), nullable=True),
        sa.Column("cost_json", sa.JSON(), nullable=True),
        sa.Column("curve_json", sa.JSON(), nullable=True),
        sa.Column("payment_json", sa.JSON(), nullable=True),
        sa.Column("approved_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_estimate")),
    )
    op.create_index(
        op.f("ix_calc_estimate_investment_project_id"),
        "calc_estimate",
        ["investment_project_id"],
        unique=False,
    )
    op.create_table(
        "calc_position",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("system_group", sa.String(length=64), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("complexity_coef", sa.Numeric(precision=5, scale=3), nullable=False),
        sa.Column("price_period", sa.String(length=16), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_position")),
        sa.UniqueConstraint("code", name=op.f("uq_calc_position_code")),
    )
    op.create_table(
        "calc_region",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("parent_code", sa.String(length=32), nullable=True),
        sa.Column("coefficient", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_region")),
        sa.UniqueConstraint("code", name=op.f("uq_calc_region_code")),
    )
    op.create_table(
        "dictionary_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dict_code", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dictionary_item")),
        sa.UniqueConstraint("code", "dict_code", name="uq_dictionary_item"),
    )
    op.create_index(
        op.f("ix_dictionary_item_dict_code"), "dictionary_item", ["dict_code"], unique=False
    )
    op.create_table(
        "industry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("group", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_industry")),
        sa.UniqueConstraint("code", name=op.f("uq_industry_code")),
    )
    op.create_index(op.f("ix_industry_group"), "industry", ["group"], unique=False)
    op.create_table(
        "region",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column("center_lon", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("center_lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["region.id"], name=op.f("fk_region_parent_id_region")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_region")),
        sa.UniqueConstraint("code", name=op.f("uq_region_code")),
    )
    op.create_index(op.f("ix_region_name"), "region", ["name"], unique=False)
    op.create_table(
        "scoring_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("factors_json", sa.JSON(), nullable=False),
        sa.Column("scoring_mode", sa.String(length=16), nullable=False),
        sa.Column("model_version", sa.String(length=48), nullable=False),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scoring_snapshot")),
    )
    op.create_index(
        op.f("ix_scoring_snapshot_subject_id"), "scoring_snapshot", ["subject_id"], unique=False
    )
    op.create_table(
        "source_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("processing_status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("license_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_record")),
    )
    op.create_index(
        op.f("ix_source_record_payload_hash"), "source_record", ["payload_hash"], unique=False
    )
    op.create_index(op.f("ix_source_record_source"), "source_record", ["source"], unique=False)
    op.create_index(
        "ix_source_source_external", "source_record", ["source", "external_id"], unique=False
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=True),
        sa.Column("object_id", sa.String(length=64), nullable=True),
        sa.Column("before_hash", sa.String(length=64), nullable=True),
        sa.Column("after_hash", sa.String(length=64), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_audit_log_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_user_id"), "audit_log", ["user_id"], unique=False)
    op.create_table(
        "company",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("name_normalized", sa.String(length=512), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=True),
        sa.Column("ogrn", sa.String(length=15), nullable=True),
        sa.Column("industry_id", sa.Integer(), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column(
            "coordinates",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("client_status", sa.String(length=16), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["industry_id"], ["industry.id"], name=op.f("fk_company_industry_id_industry")
        ),
        sa.ForeignKeyConstraint(
            ["region_id"], ["region.id"], name=op.f("fk_company_region_id_region")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company")),
    )
    op.create_index(op.f("ix_company_client_status"), "company", ["client_status"], unique=False)
    op.create_index(op.f("ix_company_inn"), "company", ["inn"], unique=False)
    op.create_index(op.f("ix_company_name"), "company", ["name"], unique=False)
    op.create_index(
        op.f("ix_company_name_normalized"), "company", ["name_normalized"], unique=False
    )
    op.create_index(op.f("ix_company_region_id"), "company", ["region_id"], unique=False)
    op.create_index(
        "ix_company_region_industry", "company", ["region_id", "industry_id"], unique=False
    )
    op.create_table(
        "customer_presence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("municipality", sa.String(length=255), nullable=True),
        sa.Column("service_type", sa.String(length=64), nullable=False),
        sa.Column("coverage_percent", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("contracts_count", sa.Integer(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["region_id"], ["region.id"], name=op.f("fk_customer_presence_region_id_region")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_record.id"],
            name=op.f("fk_customer_presence_source_id_source_record"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_presence")),
    )
    op.create_index(
        "ix_presence_region_service_date",
        "customer_presence",
        ["region_id", "service_type"],
        unique=False,
    )
    op.create_table(
        "deal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=True),
        sa.Column("input_params_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_id"], ["app_user.id"], name=op.f("fk_deal_author_id_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal")),
    )
    op.create_index(op.f("ix_deal_author_id"), "deal", ["author_id"], unique=False)
    op.create_table(
        "historical_deal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("project_type", sa.String(length=64), nullable=False),
        sa.Column("scale", sa.String(length=64), nullable=True),
        sa.Column("scope_json", sa.JSON(), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column("industry_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.Date(), nullable=True),
        sa.Column("contract_value", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("retro_price_basis", sa.String(length=16), nullable=False),
        sa.Column("financing_scheme", sa.String(length=64), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["industry_id"], ["industry.id"], name=op.f("fk_historical_deal_industry_id_industry")
        ),
        sa.ForeignKeyConstraint(
            ["region_id"], ["region.id"], name=op.f("fk_historical_deal_region_id_region")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_record.id"],
            name=op.f("fk_historical_deal_source_id_source_record"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historical_deal")),
    )
    op.create_index(
        op.f("ix_historical_deal_industry_id"), "historical_deal", ["industry_id"], unique=False
    )
    op.create_index(
        op.f("ix_historical_deal_project_type"), "historical_deal", ["project_type"], unique=False
    )
    op.create_index(
        op.f("ix_historical_deal_region_id"), "historical_deal", ["region_id"], unique=False
    )
    op.create_table(
        "notification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("related_object", sa.String(length=128), nullable=True),
        sa.Column("dedup_key", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_notification_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification")),
    )
    op.create_index(op.f("ix_notification_dedup_key"), "notification", ["dedup_key"], unique=False)
    op.create_index(op.f("ix_notification_user_id"), "notification", ["user_id"], unique=False)
    op.create_index(
        "ix_notification_user_read", "notification", ["user_id", "read_at"], unique=False
    )
    op.create_table(
        "okved_to_industry",
        sa.Column("okved_code", sa.String(length=8), nullable=False),
        sa.Column("industry_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.ForeignKeyConstraint(
            ["industry_id"], ["industry.id"], name=op.f("fk_okved_to_industry_industry_id_industry")
        ),
        sa.PrimaryKeyConstraint("okved_code", "industry_id", name=op.f("pk_okved_to_industry")),
    )
    op.create_table(
        "partial_auth",
        sa.Column("token_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_partial_auth_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("token_id", name=op.f("pk_partial_auth")),
    )
    op.create_index(op.f("ix_partial_auth_user_id"), "partial_auth", ["user_id"], unique=False)
    op.create_table(
        "position_price",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("price_min", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("price_max", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("price_typical", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column("price_period", sa.String(length=16), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["region_id"], ["region.id"], name=op.f("fk_position_price_region_id_region")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_record.id"],
            name=op.f("fk_position_price_source_id_source_record"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_position_price")),
    )
    op.create_index(op.f("ix_position_price_name"), "position_price", ["name"], unique=False)
    op.create_table(
        "refresh_token",
        sa.Column("jti", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_refresh_token_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("jti", name=op.f("pk_refresh_token")),
    )
    op.create_index(op.f("ix_refresh_token_user_id"), "refresh_token", ["user_id"], unique=False)
    op.create_table(
        "regional_coefficient",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("work_type", sa.String(length=64), nullable=False),
        sa.Column("coefficient", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["region_id"], ["region.id"], name=op.f("fk_regional_coefficient_region_id_region")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_record.id"],
            name=op.f("fk_regional_coefficient_source_id_source_record"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regional_coefficient")),
    )
    op.create_index(
        op.f("ix_regional_coefficient_region_id"),
        "regional_coefficient",
        ["region_id"],
        unique=False,
    )
    op.create_table(
        "saved_filter",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_saved_filter_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_filter")),
    )
    op.create_index(op.f("ix_saved_filter_user_id"), "saved_filter", ["user_id"], unique=False)
    op.create_table(
        "subscription",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("notify_frequency", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name=op.f("fk_subscription_user_id_app_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscription")),
    )
    op.create_index(op.f("ix_subscription_user_id"), "subscription", ["user_id"], unique=False)
    op.create_table(
        "company_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("alias_name", sa.String(length=512), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name=op.f("fk_company_alias_company_id_company")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_record.id"],
            name=op.f("fk_company_alias_source_id_source_record"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_alias")),
    )
    op.create_index(
        op.f("ix_company_alias_company_id"), "company_alias", ["company_id"], unique=False
    )
    op.create_table(
        "company_match",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("match_method", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name=op.f("fk_company_match_company_id_company")
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_company_match_source_record_id_source_record"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_match")),
    )
    op.create_index(
        op.f("ix_company_match_company_id"), "company_match", ["company_id"], unique=False
    )
    op.create_table(
        "company_metric",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("metric_code", sa.String(length=32), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("value", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name=op.f("fk_company_metric_company_id_company")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_record.id"],
            name=op.f("fk_company_metric_source_id_source_record"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_metric")),
        sa.UniqueConstraint(
            "company_id",
            "metric_code",
            "period_year",
            "source_id",
            name=op.f("uq_company_metric_company_id"),
        ),
    )
    op.create_index(
        op.f("ix_company_metric_company_id"), "company_metric", ["company_id"], unique=False
    )
    op.create_index(
        "ix_company_metric_industry_year",
        "company_metric",
        ["period_year", "metric_code"],
        unique=False,
    )
    op.create_table(
        "deal_estimate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("price_min", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("price_optimum", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("price_max", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("comparables_json", sa.JSON(), nullable=False),
        sa.Column("adjustments_json", sa.JSON(), nullable=False),
        sa.Column("price_period", sa.String(length=32), nullable=True),
        sa.Column("data_quality", sa.String(length=16), nullable=False),
        sa.Column("estimator_mode", sa.String(length=16), nullable=False),
        sa.Column("model_version", sa.String(length=48), nullable=False),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deal.id"], name=op.f("fk_deal_estimate_deal_id_deal")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_estimate")),
    )
    op.create_index(op.f("ix_deal_estimate_deal_id"), "deal_estimate", ["deal_id"], unique=False)
    op.create_table(
        "investment_project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("initiator_company_id", sa.Integer(), nullable=True),
        sa.Column("industry_id", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("planned_start", sa.Date(), nullable=True),
        sa.Column("planned_end", sa.Date(), nullable=True),
        sa.Column("estimated_budget", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column(
            "coordinates",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["industry_id"],
            ["industry.id"],
            name=op.f("fk_investment_project_industry_id_industry"),
        ),
        sa.ForeignKeyConstraint(
            ["initiator_company_id"],
            ["company.id"],
            name=op.f("fk_investment_project_initiator_company_id_company"),
        ),
        sa.ForeignKeyConstraint(
            ["region_id"], ["region.id"], name=op.f("fk_investment_project_region_id_region")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_record.id"],
            name=op.f("fk_investment_project_source_id_source_record"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investment_project")),
    )
    op.create_index(
        op.f("ix_investment_project_industry_id"),
        "investment_project",
        ["industry_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_investment_project_initiator_company_id"),
        "investment_project",
        ["initiator_company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_investment_project_region_id"), "investment_project", ["region_id"], unique=False
    )
    op.create_index(
        op.f("ix_investment_project_stage"), "investment_project", ["stage"], unique=False
    )
    op.create_index(
        op.f("ix_investment_project_title"), "investment_project", ["title"], unique=False
    )
    op.create_index(
        "ix_project_stage_start", "investment_project", ["stage", "planned_start"], unique=False
    )
    op.create_table(
        "market_entry_signal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column("signal_type", sa.String(length=32), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["company.id"], name=op.f("fk_market_entry_signal_company_id_company")
        ),
        sa.ForeignKeyConstraint(
            ["region_id"], ["region.id"], name=op.f("fk_market_entry_signal_region_id_region")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_record.id"],
            name=op.f("fk_market_entry_signal_source_id_source_record"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_entry_signal")),
    )
    op.create_index(
        op.f("ix_market_entry_signal_company_id"),
        "market_entry_signal",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_market_entry_signal_region_id"), "market_entry_signal", ["region_id"], unique=False
    )
    op.create_table(
        "tender",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("customer_company_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("deadline_date", sa.Date(), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_company_id"],
            ["company.id"],
            name=op.f("fk_tender_customer_company_id_company"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["source_record.id"], name=op.f("fk_tender_source_id_source_record")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender")),
    )
    op.create_index(
        op.f("ix_tender_customer_company_id"), "tender", ["customer_company_id"], unique=False
    )
    op.create_index("ix_tender_deadline", "tender", ["deadline_date"], unique=False)
    op.create_index(op.f("ix_tender_external_id"), "tender", ["external_id"], unique=False)
    op.create_table(
        "deal_breakdown",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_estimate_id", sa.Integer(), nullable=False),
        sa.Column("article", sa.String(length=48), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("basis", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["deal_estimate_id"],
            ["deal_estimate.id"],
            name=op.f("fk_deal_breakdown_deal_estimate_id_deal_estimate"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_breakdown")),
    )
    op.create_index(
        op.f("ix_deal_breakdown_deal_estimate_id"),
        "deal_breakdown",
        ["deal_estimate_id"],
        unique=False,
    )
    op.create_table(
        "investment_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("region_id", sa.Integer(), nullable=True),
        sa.Column("industry_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["industry_id"], ["industry.id"], name=op.f("fk_investment_event_industry_id_industry")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["investment_project.id"],
            name=op.f("fk_investment_event_project_id_investment_project"),
        ),
        sa.ForeignKeyConstraint(
            ["region_id"], ["region.id"], name=op.f("fk_investment_event_region_id_region")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investment_event")),
    )
    op.create_index(
        "ix_event_date_region", "investment_event", ["event_date", "region_id"], unique=False
    )
    op.create_index(
        op.f("ix_investment_event_project_id"), "investment_event", ["project_id"], unique=False
    )
    op.create_table(
        "project_milestone",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("actual_date", sa.Date(), nullable=True),
        sa.Column("evidence_url", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["investment_project.id"],
            name=op.f("fk_project_milestone_project_id_investment_project"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_milestone")),
    )
    op.create_index(
        op.f("ix_project_milestone_project_id"), "project_milestone", ["project_id"], unique=False
    )
    op.create_table(
        "project_need",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("need_category", sa.String(length=48), nullable=False),
        sa.Column("probability", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("rule_id", sa.String(length=48), nullable=True),
        sa.Column("model_version", sa.String(length=48), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["investment_project.id"],
            name=op.f("fk_project_need_project_id_investment_project"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_need")),
    )
    op.create_index(
        op.f("ix_project_need_need_category"), "project_need", ["need_category"], unique=False
    )
    op.create_index(
        op.f("ix_project_need_project_id"), "project_need", ["project_id"], unique=False
    )
    op.create_table(
        "project_tender",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("tender_id", sa.Integer(), nullable=False),
        sa.Column("link_method", sa.String(length=24), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"], ["app_user.id"], name=op.f("fk_project_tender_created_by_app_user")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["investment_project.id"],
            name=op.f("fk_project_tender_project_id_investment_project"),
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tender.id"], name=op.f("fk_project_tender_tender_id_tender")
        ),
        sa.PrimaryKeyConstraint("project_id", "tender_id", name=op.f("pk_project_tender")),
    )
    op.create_table(
        "proposal_export",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_estimate_id", sa.Integer(), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("file_ref", sa.String(length=1024), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"], ["app_user.id"], name=op.f("fk_proposal_export_created_by_app_user")
        ),
        sa.ForeignKeyConstraint(
            ["deal_estimate_id"],
            ["deal_estimate.id"],
            name=op.f("fk_proposal_export_deal_estimate_id_deal_estimate"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_export")),
    )
    op.create_index(
        op.f("ix_proposal_export_deal_estimate_id"),
        "proposal_export",
        ["deal_estimate_id"],
        unique=False,
    )


def downgrade() -> None:

    op.drop_table("proposal_export")
    op.drop_table("project_tender")
    op.drop_table("project_need")
    op.drop_table("project_milestone")
    op.drop_table("investment_event")
    op.drop_table("deal_breakdown")
    op.drop_table("tender")
    op.drop_table("market_entry_signal")
    op.drop_table("investment_project")
    op.drop_table("deal_estimate")
    op.drop_table("company_metric")
    op.drop_table("company_match")
    op.drop_table("company_alias")
    op.drop_table("subscription")
    op.drop_table("saved_filter")
    op.drop_table("regional_coefficient")
    op.drop_table("refresh_token")
    op.drop_table("position_price")
    op.drop_table("partial_auth")
    op.drop_table("okved_to_industry")
    op.drop_table("notification")
    op.drop_table("historical_deal")
    op.drop_table("deal")
    op.drop_table("customer_presence")
    op.drop_table("company")
    op.drop_table("audit_log")
    op.drop_table("source_record")
    op.drop_table("scoring_snapshot")
    op.drop_table("region")
    op.drop_table("industry")
    op.drop_table("dictionary_item")
    op.drop_table("calc_region")
    op.drop_table("calc_position")
    op.drop_table("calc_estimate")
    op.drop_table("calc_dictionary")
    op.drop_table("calc_deal")
    op.drop_table("app_user")
