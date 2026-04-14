"""add node filtering config and ssh credentials

Revision ID: 20260414_add_node_filtering
Revises: 20260225_add_mlkem_to_hosts
Create Date: 2026-04-14

"""

import sqlalchemy as sa
from alembic import op

revision = "20260414_add_node_filtering"
down_revision = "20260225_add_mlkem_to_hosts"
branch_labels = None
depends_on = None

DNS_PROVIDER_ENUM_VALUES = (
    "adguard_home_local",
    "adguard_dns_public",
    "nextdns",
    "cloudflare_security",
    "custom",
)


def upgrade() -> None:
    dns_enum = sa.Enum(*DNS_PROVIDER_ENUM_VALUES, name="dnsprovider")

    op.create_table(
        "node_filtering_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "node_id",
            sa.Integer(),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "adblock_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "dns_provider",
            dns_enum,
            nullable=False,
            server_default="adguard_dns_public",
        ),
        sa.Column("dns_address", sa.String(512), nullable=True),
        sa.Column(
            "adguard_home_port",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5353"),
        ),
        sa.Column(
            "adguard_home_installed",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_table(
        "node_ssh_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "node_id",
            sa.Integer(),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("encrypted_data", sa.Text(), nullable=False),
        sa.Column("encryption_salt", sa.String(128), nullable=False),
        sa.Column("pin_hash", sa.String(256), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("node_ssh_credentials")
    op.drop_table("node_filtering_config")
    sa.Enum(name="dnsprovider").drop(op.get_bind(), checkfirst=True)
