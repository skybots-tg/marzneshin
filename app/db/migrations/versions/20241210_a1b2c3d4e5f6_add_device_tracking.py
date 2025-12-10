"""add device tracking

Revision ID: a1b2c3d4e5f6
Revises: 57eba0a293f2
Create Date: 2024-12-10 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "57eba0a293f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop tables if they exist (cleanup from previous failed migration)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    if 'user_device_traffic' in inspector.get_table_names():
        op.drop_table('user_device_traffic')
    if 'user_device_ips' in inspector.get_table_names():
        op.drop_table('user_device_ips')
    if 'user_devices' in inspector.get_table_names():
        op.drop_table('user_devices')
    
    # ### Create user_devices table ###
    op.create_table(
        "user_devices",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("fingerprint_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("display_name", sa.String(length=64), nullable=True),
        sa.Column("client_name", sa.String(length=64), nullable=True),
        sa.Column("client_type", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_node_id", sa.Integer(), nullable=True),
        sa.Column("last_ip_id", sa.BigInteger(), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.sql.false()),
        sa.Column("trust_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_node_id"],
            ["nodes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "fingerprint", "fingerprint_version"),
    )
    op.create_index("ix_user_devices_user_id", "user_devices", ["user_id"])
    op.create_index("ix_user_devices_last_seen_at", "user_devices", ["last_seen_at"])
    op.create_index("ix_user_devices_is_blocked", "user_devices", ["is_blocked"])
    
    # ### Create user_device_ips table ###
    op.create_table(
        "user_device_ips",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("connect_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("upload_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("download_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("asn", sa.Integer(), nullable=True),
        sa.Column("asn_org", sa.String(length=128), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("city", sa.String(length=64), nullable=True),
        sa.Column("is_datacenter", sa.Boolean(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["user_devices.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "ip"),
    )
    op.create_index("ix_user_device_ips_device_id", "user_device_ips", ["device_id"])
    op.create_index("ix_user_device_ips_ip", "user_device_ips", ["ip"])
    op.create_index("ix_user_device_ips_last_seen_at", "user_device_ips", ["last_seen_at"])
    op.create_index("ix_user_device_ips_country_code", "user_device_ips", ["country_code"])
    # Index for is_datacenter (partial indexes not supported in MariaDB)
    op.create_index("ix_user_device_ips_is_datacenter", "user_device_ips", ["is_datacenter"])
    
    # ### Create user_device_traffic table ###
    op.create_table(
        "user_device_traffic",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("bucket_start", sa.DateTime(), nullable=False),
        sa.Column("bucket_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("upload_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("download_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("connect_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["user_devices.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["nodes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "node_id", "bucket_start"),
    )
    op.create_index("ix_user_device_traffic_device_id", "user_device_traffic", ["device_id"])
    op.create_index("ix_user_device_traffic_user_id", "user_device_traffic", ["user_id"])
    op.create_index("ix_user_device_traffic_node_id", "user_device_traffic", ["node_id"])
    op.create_index("ix_user_device_traffic_bucket_start", "user_device_traffic", ["bucket_start"])
    # Composite index for common queries
    op.create_index(
        "ix_device_traffic_user_time",
        "user_device_traffic",
        ["user_id", "bucket_start"]
    )
    op.create_index(
        "ix_device_traffic_node_time",
        "user_device_traffic",
        ["node_id", "bucket_start"]
    )


def downgrade() -> None:
    # ### Drop tables in reverse order ###
    op.drop_index("ix_device_traffic_node_time", table_name="user_device_traffic")
    op.drop_index("ix_device_traffic_user_time", table_name="user_device_traffic")
    op.drop_index("ix_user_device_traffic_bucket_start", table_name="user_device_traffic")
    op.drop_index("ix_user_device_traffic_node_id", table_name="user_device_traffic")
    op.drop_index("ix_user_device_traffic_user_id", table_name="user_device_traffic")
    op.drop_index("ix_user_device_traffic_device_id", table_name="user_device_traffic")
    op.drop_table("user_device_traffic")
    
    op.drop_index("ix_user_device_ips_is_datacenter", table_name="user_device_ips")
    op.drop_index("ix_user_device_ips_country_code", table_name="user_device_ips")
    op.drop_index("ix_user_device_ips_last_seen_at", table_name="user_device_ips")
    op.drop_index("ix_user_device_ips_ip", table_name="user_device_ips")
    op.drop_index("ix_user_device_ips_device_id", table_name="user_device_ips")
    op.drop_table("user_device_ips")
    
    op.drop_index("ix_user_devices_is_blocked", table_name="user_devices")
    op.drop_index("ix_user_devices_last_seen_at", table_name="user_devices")
    op.drop_index("ix_user_devices_user_id", table_name="user_devices")
    op.drop_table("user_devices")

