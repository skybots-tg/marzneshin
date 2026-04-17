from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SkillSource(StrEnum):
    builtin = "builtin"
    override = "override"
    custom = "custom"


NAME_PATTERN = r"^[a-z0-9][a-z0-9\-_]{1,126}$"


class AISkillSummary(BaseModel):
    """Light skill info for list views / agent catalog."""

    name: str
    description: str
    source: SkillSource
    enabled: bool = True

    model_config = ConfigDict(from_attributes=True)


class AISkillDetail(AISkillSummary):
    body: str
    updated_at: datetime | None = None


class AISkillCreate(BaseModel):
    """Payload for creating a custom skill or overriding a built-in.

    Validation of markdown body is intentionally minimal — admins are
    trusted. Name must be kebab/snake lower-case so it is safe for
    filenames and tool arguments.
    """

    name: str = Field(min_length=2, max_length=128, pattern=NAME_PATTERN)
    description: str = Field(min_length=1, max_length=2000)
    body: str = Field(min_length=1, max_length=64_000)
    enabled: bool = True


class AISkillUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=2000)
    body: str | None = Field(default=None, max_length=64_000)
    enabled: bool | None = None
