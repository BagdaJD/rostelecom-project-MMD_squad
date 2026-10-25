"""Mandatory MFA, replay protection and revocable sessions with hashed refresh secrets."""

import sqlalchemy as sa

from alembic import op

revision = "20261025_0004"
down_revision = "20261025_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("app_user", sa.Column("totp_last_counter", sa.BigInteger()))
    op.alter_column("refresh_token", "jti", existing_type=sa.String(36), type_=sa.String(64))
    op.add_column(
        "refresh_token",
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("refresh_token", sa.Column("csrf_hash", sa.String(64)))
    op.add_column("refresh_token", sa.Column("family_id", sa.String(36)))
    op.create_index("ix_refresh_token_family_id", "refresh_token", ["family_id"])
    op.add_column(
        "partial_auth",
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "partial_auth",
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("partial_auth", sa.Column("secret_encrypted", sa.Text()))

    op.execute("UPDATE refresh_token SET revoked_at = now() WHERE revoked_at IS NULL")
    op.execute("DELETE FROM partial_auth")


def downgrade() -> None:

    op.execute("DELETE FROM refresh_token")
    op.execute("DELETE FROM partial_auth")
    for column in ("secret_encrypted", "failed_attempts", "auth_version"):
        op.drop_column("partial_auth", column)
    op.drop_column("refresh_token", "csrf_hash")
    op.drop_index("ix_refresh_token_family_id", table_name="refresh_token")
    op.drop_column("refresh_token", "family_id")
    op.drop_column("refresh_token", "auth_version")
    op.alter_column("refresh_token", "jti", existing_type=sa.String(64), type_=sa.String(36))
    op.drop_column("app_user", "totp_last_counter")
    op.drop_column("app_user", "auth_version")
