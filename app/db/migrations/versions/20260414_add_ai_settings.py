"""add ai settings column to settings table

Revision ID: 20260414_add_ai_settings
Revises: 20260414_global_ssh_pin
Create Date: 2026-04-14

"""

import sqlalchemy as sa
from alembic import op

revision = "20260414_add_ai_settings"
down_revision = "20260414_global_ssh_pin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("ai", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("ai")
