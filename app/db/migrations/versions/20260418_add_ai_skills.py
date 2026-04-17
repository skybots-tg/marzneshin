"""Add ai_skills table for agent playbooks

Revision ID: 20260418_add_ai_skills
Revises: 20260415_daily_usage
Create Date: 2026-04-18

Stores admin-editable AI-agent skills. Built-in skills live on disk at
`app/ai/skills/*.md`; rows here either override a built-in (same name) or
add a brand-new custom skill. A disabled row with an empty body is used to
hide a built-in from the catalog without replacing it.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260418_add_ai_skills"
down_revision = "20260415_daily_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "is_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_ai_skills_name", "ai_skills", ["name"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_ai_skills_name", table_name="ai_skills")
    op.drop_table("ai_skills")
