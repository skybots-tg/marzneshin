"""resize mlkem key columns for hybrid encryption strings

The original schema sized ``mlkem_public_key`` for a single Curve25519
public key (32 bytes -> ~44 base64 chars). The hybrid VLESS post-quantum
``encryption`` string we now store there (``mlkem768x25519plus.<mode>.<rtt>.
<x25519_pub>.<mlkem_client_eK>``) is around 1620 characters because the
ML-KEM-768 client encapsulation key alone is 1184 bytes.

This migration grows the column to 4096 chars, matching the
``mlkem_private_key`` column. Both decryption and encryption strings now
fit comfortably with room to spare.

Revision ID: 20260430_resize_mlkem_keys
Revises: 20260420_node_tls
Create Date: 2026-04-30
"""

import sqlalchemy as sa
from alembic import op


revision = "20260430_resize_mlkem_keys"
down_revision = "20260420_node_tls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hosts") as batch_op:
        batch_op.alter_column(
            "mlkem_public_key",
            existing_type=sa.String(length=512),
            type_=sa.String(length=4096),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("hosts") as batch_op:
        batch_op.alter_column(
            "mlkem_public_key",
            existing_type=sa.String(length=4096),
            type_=sa.String(length=512),
            existing_nullable=True,
        )
