"""Add bi-weekly cold-storage aggregation tables for traffic usage

Revision ID: 20260601_biweekly_usage
Revises: 20260503_inbound_exit_node
Create Date: 2026-06-01

Introduces the coarsest retention tier for node / user traffic:

    hourly (node_user_usages)      kept ``usage_retention_days`` days (30d)
      -> daily (node_user_usages_daily)   kept up to ``usage_max_retention_days`` (180d)
        -> bi-weekly (node_user_usages_biweekly)   retained indefinitely

Previously daily rows older than ``usage_max_retention_days`` were simply
purged, losing all history past ~6 months. The background aggregation task
now compresses them into fixed 2-week buckets instead and keeps them, so
historical traffic stays queryable through the same read paths at coarser
resolution.

The composite ``(user_id, period_start)`` / ``(node_id, period_start)``
indexes match the read-path filter (one user/node over a date range).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260601_biweekly_usage"
down_revision = "20260503_inbound_exit_node"
branch_labels = None
depends_on = None


def _table_exists(connection, table_name: str) -> bool:
    return inspect(connection).has_table(table_name)


def _index_exists(connection, table_name: str, index_name: str) -> bool:
    if not _table_exists(connection, table_name):
        return False
    return any(
        idx["name"] == index_name
        for idx in inspect(connection).get_indexes(table_name)
    )


def upgrade() -> None:
    connection = op.get_bind()

    if not _table_exists(connection, "node_user_usages_biweekly"):
        op.create_table(
            "node_user_usages_biweekly",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("period_start", sa.Date, nullable=False, index=True),
            sa.Column(
                "user_id", sa.Integer, sa.ForeignKey("users.id"), index=True
            ),
            sa.Column(
                "node_id", sa.Integer, sa.ForeignKey("nodes.id"), index=True
            ),
            sa.Column("used_traffic", sa.BigInteger, default=0),
            sa.UniqueConstraint("period_start", "user_id", "node_id"),
        )

    if not _table_exists(connection, "node_usages_biweekly"):
        op.create_table(
            "node_usages_biweekly",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("period_start", sa.Date, nullable=False, index=True),
            sa.Column(
                "node_id", sa.Integer, sa.ForeignKey("nodes.id"), index=True
            ),
            sa.Column("uplink", sa.BigInteger, default=0),
            sa.Column("downlink", sa.BigInteger, default=0),
            sa.UniqueConstraint("period_start", "node_id"),
        )

    # Composite indexes matching the read-path access pattern
    # (single user/node filtered over a period_start range).
    if not _index_exists(
        connection,
        "node_user_usages_biweekly",
        "ix_nuub_user_period",
    ):
        op.create_index(
            "ix_nuub_user_period",
            "node_user_usages_biweekly",
            ["user_id", "period_start"],
        )
    if not _index_exists(
        connection,
        "node_user_usages_biweekly",
        "ix_nuub_node_period",
    ):
        op.create_index(
            "ix_nuub_node_period",
            "node_user_usages_biweekly",
            ["node_id", "period_start"],
        )

    # Composite index on the daily user table accelerates the daily read
    # branch and the daily->biweekly aggregation scan.
    if _table_exists(connection, "node_user_usages_daily") and not _index_exists(
        connection,
        "node_user_usages_daily",
        "ix_nuud_user_date",
    ):
        op.create_index(
            "ix_nuud_user_date",
            "node_user_usages_daily",
            ["user_id", "date"],
        )


def downgrade() -> None:
    connection = op.get_bind()

    if _index_exists(
        connection, "node_user_usages_daily", "ix_nuud_user_date"
    ):
        op.drop_index("ix_nuud_user_date", table_name="node_user_usages_daily")
    if _index_exists(
        connection, "node_user_usages_biweekly", "ix_nuub_node_period"
    ):
        op.drop_index(
            "ix_nuub_node_period", table_name="node_user_usages_biweekly"
        )
    if _index_exists(
        connection, "node_user_usages_biweekly", "ix_nuub_user_period"
    ):
        op.drop_index(
            "ix_nuub_user_period", table_name="node_user_usages_biweekly"
        )

    if _table_exists(connection, "node_usages_biweekly"):
        op.drop_table("node_usages_biweekly")
    if _table_exists(connection, "node_user_usages_biweekly"):
        op.drop_table("node_user_usages_biweekly")
