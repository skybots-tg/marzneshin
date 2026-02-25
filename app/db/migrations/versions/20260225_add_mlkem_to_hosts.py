"""add mlkem fields to hosts

Revision ID: 20260225_add_mlkem_to_hosts
Revises: 57eba0a293f2
Create Date: 2026-02-25

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260225_add_mlkem_to_hosts"
down_revision = "57eba0a293f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column(
            "mlkem_enabled",
            sa.Boolean(),
            server_default=sa.sql.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "hosts",
        sa.Column("mlkem_public_key", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "hosts",
        sa.Column("mlkem_private_key", sa.String(length=4096), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hosts", "mlkem_private_key")
    op.drop_column("hosts", "mlkem_public_key")
    op.drop_column("hosts", "mlkem_enabled")


