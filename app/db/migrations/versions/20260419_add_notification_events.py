"""add notification_events column to settings table

Revision ID: 20260419_notif_events
Revises: 20260418_add_ai_skills
Create Date: 2026-04-19

Stores per-event toggles controlling which user lifecycle / warning
notifications get pushed to Telegram. Webhook delivery is unaffected.
NULL means "send everything" (backward compatible with existing
deployments).
"""

import sqlalchemy as sa
from alembic import op

revision = "20260419_notif_events"
down_revision = "20260418_add_ai_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("notification_events", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("notification_events")
