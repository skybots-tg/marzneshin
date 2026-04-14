"""move ssh pin to global settings

Revision ID: 20260414_global_ssh_pin
Revises: 20260414_add_node_filtering
Create Date: 2026-04-14

"""

import sqlalchemy as sa
from alembic import op

revision = "20260414_global_ssh_pin"
down_revision = "20260414_add_node_filtering"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("ssh_pin_hash", sa.String(256), nullable=True),
    )

    op.execute("DELETE FROM node_ssh_credentials")

    with op.batch_alter_table("node_ssh_credentials") as batch_op:
        batch_op.drop_column("pin_hash")


def downgrade() -> None:
    with op.batch_alter_table("node_ssh_credentials") as batch_op:
        batch_op.add_column(
            sa.Column("pin_hash", sa.String(256), nullable=False, server_default=""),
        )

    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("ssh_pin_hash")
