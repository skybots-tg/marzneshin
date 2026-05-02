"""add inbounds.exit_node_id (egress node for bridge inbounds)

Bridge inbounds accept traffic on one node (``inbounds.node_id``) and
tunnel it out through another node via xray outbound + routing rules.
The ingress / egress split was previously implicit (encoded in the
inbound tag like ``RU->FL Bridge``) and not query-able from SQL.

This migration adds an explicit ``exit_node_id`` foreign key. It is:

* nullable — direct (non-bridge) inbounds keep it ``NULL``;
* indexed — joins from ``inbounds`` to ``node_filtering_config`` are
  cheap (used by the runtime per-host adblock-suffix feature in
  ``app.utils.share``);
* ``ON DELETE SET NULL`` — removing an exit node should not cascade
  to inbound deletion; the bridge becomes effectively non-functional
  but the row stays for the operator to fix.

No data is back-filled here — that requires environment-specific
tag-to-node mapping (``RU->TR-1 Bridge`` -> the TR-1 node id, etc.)
and is left to the operator / a separate one-shot script.

Revision ID: 20260503_inbound_exit_node
Revises: 20260430_resize_mlkem_keys
Create Date: 2026-05-03
"""

import sqlalchemy as sa
from alembic import op


revision = "20260503_inbound_exit_node"
down_revision = "20260430_resize_mlkem_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inbounds",
        sa.Column("exit_node_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_inbounds_exit_node_id", "inbounds", ["exit_node_id"]
    )
    op.create_foreign_key(
        "fk_inbounds_exit_node",
        "inbounds",
        "nodes",
        ["exit_node_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_inbounds_exit_node", "inbounds", type_="foreignkey")
    op.drop_index("ix_inbounds_exit_node_id", table_name="inbounds")
    op.drop_column("inbounds", "exit_node_id")
