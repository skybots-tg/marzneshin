from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db.base import Base


class AISkill(Base):
    """Persisted AI-agent skill.

    Row kinds:
    - custom: skill created entirely in DB (no file counterpart).
    - override: row whose `name` matches a built-in skill file; replaces it.
    - disable: row with `enabled=False` for a built-in `name`, empty body —
      hides the built-in from the catalog without providing a replacement.

    The on-disk library at `app/ai/skills/*.md` is the source of truth for
    built-ins; DB rows layer on top.
    """

    __tablename__ = "ai_skills"

    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False, default="")
    body = Column(Text, nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    is_override = Column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
