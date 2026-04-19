"""add node_tls_provisioning table

Revision ID: 20260420_node_tls
Revises: 20260419_notif_events
Create Date: 2026-04-20

Tracks per-node TLS+landing+gRPC provisioning state managed by the AI
TLS toolset (Caddy installer + Let's Encrypt + landing template +
unix-socket gRPC bridge). The cert material itself stays on the node;
this table only mirrors metadata (domain, template, expiry) so the
panel and AI can reason about it without an SSH round-trip.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260420_node_tls"
down_revision = "20260419_notif_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_tls_provisioning",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "node_id",
            sa.Integer(),
            sa.ForeignKey("nodes.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("landing_template", sa.String(64), nullable=False),
        sa.Column("grpc_service_name", sa.String(64), nullable=False),
        sa.Column("uds_path", sa.String(255), nullable=False),
        sa.Column("contact_email", sa.String(254), nullable=False),
        sa.Column("cert_issued_at", sa.DateTime(), nullable=True),
        sa.Column("cert_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_renew_attempt_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )


def downgrade() -> None:
    op.drop_table("node_tls_provisioning")
