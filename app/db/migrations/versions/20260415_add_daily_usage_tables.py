"""Add daily aggregation tables for traffic usage

Revision ID: 20260415_daily_usage
Revises: 20260414_add_ai_settings
Create Date: 2026-04-15

Adds node_user_usages_daily and node_usages_daily tables that store
compressed daily summaries of hourly traffic data. A background task
periodically aggregates old hourly records into these tables and
removes the originals, keeping the main tables small.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260415_daily_usage"
down_revision = "20260414_add_ai_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_user_usages_daily",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date", sa.Date, nullable=False, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), index=True),
        sa.Column("node_id", sa.Integer, sa.ForeignKey("nodes.id"), index=True),
        sa.Column("used_traffic", sa.BigInteger, default=0),
        sa.UniqueConstraint("date", "user_id", "node_id"),
    )

    op.create_table(
        "node_usages_daily",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("date", sa.Date, nullable=False, index=True),
        sa.Column("node_id", sa.Integer, sa.ForeignKey("nodes.id"), index=True),
        sa.Column("uplink", sa.BigInteger, default=0),
        sa.Column("downlink", sa.BigInteger, default=0),
        sa.UniqueConstraint("date", "node_id"),
    )


def downgrade() -> None:
    op.drop_table("node_usages_daily")
    op.drop_table("node_user_usages_daily")
