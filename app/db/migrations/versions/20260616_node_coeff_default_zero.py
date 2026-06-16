"""Default node usage_coefficient to 0 for newly created nodes

Revision ID: 20260616_node_coeff_zero
Revises: 20260601_biweekly_usage
Create Date: 2026-06-16

New nodes previously inherited a usage_coefficient of 1.0 (the column
server_default), which silently started billing traffic the moment a node
came online. That caused freshly added nodes to mistakenly accrue traffic
before the operator had a chance to configure them. The default is now 0 so
a new node never bills traffic until the coefficient is raised explicitly.

Only the column default changes — existing nodes keep their current
coefficient.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260616_node_coeff_zero"
down_revision = "20260601_biweekly_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "nodes",
        "usage_coefficient",
        existing_type=sa.Float(),
        existing_nullable=False,
        server_default=sa.text("0"),
    )


def downgrade() -> None:
    op.alter_column(
        "nodes",
        "usage_coefficient",
        existing_type=sa.Float(),
        existing_nullable=False,
        server_default=sa.text("1.0"),
    )
