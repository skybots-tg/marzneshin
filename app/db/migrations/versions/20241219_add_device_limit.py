"""add device_limit to users

Revision ID: 20241219_add_device_limit
Revises: a1b2c3d4e5f6
Create Date: 2024-12-19 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20241219_add_device_limit"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add device_limit column to users table
    # NULL = no limit, 0 = no devices allowed, positive number = max devices
    op.add_column(
        "users",
        sa.Column(
            "device_limit",
            sa.Integer(),
            nullable=True,
            comment="Maximum number of devices allowed for user. NULL = no limit",
        ),
    )


def downgrade() -> None:
    # Remove device_limit column from users table
    op.drop_column("users", "device_limit")






