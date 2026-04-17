"""Skill registry for the Marzneshin AI agent.

Skills are short markdown playbooks with YAML frontmatter. Source priority:

1. Built-in files shipped in `app/ai/skills/*.md`.
2. Rows in the `ai_skills` DB table — either:
   - `is_override=True`: replaces a built-in of the same `name`.
   - `is_override=False, enabled=True`: an admin-defined custom skill.
   - `enabled=False`: hides the built-in (disable without replacement).

The registry keeps a small in-process cache that is invalidated whenever
`/ai/skills` CRUD routes mutate a row. Reads are cheap (a single
`SELECT * FROM ai_skills`), so cache TTL is short and defensive.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from sqlalchemy.orm import Session

from app.db import GetDB
from app.db.crud.ai_skill import get_all_ai_skills

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent / "skills"
_CACHE_TTL_SECONDS = 30

SkillSource = Literal["builtin", "override", "custom"]


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    source: SkillSource
    enabled: bool = True


def _parse_markdown_with_frontmatter(
    text: str, *, path: Path | None = None
) -> tuple[dict, str]:
    """Split a markdown file into its YAML frontmatter and body.

    Returns `({}, text)` if there is no frontmatter, which lets callers
    fall back to the filename for `name` and an empty description.
    """
    stripped = text.lstrip("\ufeff")
    if not stripped.startswith("---"):
        return {}, text

    lines = stripped.splitlines()
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    header = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")

    try:
        data = yaml.safe_load(header) or {}
    except yaml.YAMLError as exc:
        logger.warning(
            "Malformed frontmatter in %s: %s", path or "<inline>", exc
        )
        return {}, text

    if not isinstance(data, dict):
        return {}, text
    return data, body


def _load_builtin_skills() -> dict[str, Skill]:
    """Load all markdown files under `app/ai/skills/` as skills."""
    result: dict[str, Skill] = {}
    if not SKILLS_DIR.is_dir():
        logger.info("Built-in skills directory missing: %s", SKILLS_DIR)
        return result

    for path in sorted(SKILLS_DIR.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Cannot read skill file %s: %s", path, exc)
            continue

        meta, body = _parse_markdown_with_frontmatter(text, path=path)
        name = str(meta.get("name") or path.stem).strip()
        description = str(meta.get("description") or "").strip()
        if not name:
            logger.warning("Skill file %s has no usable name", path)
            continue

        result[name] = Skill(
            name=name,
            description=description,
            body=body,
            source="builtin",
            enabled=True,
        )

    logger.info("Loaded %d built-in AI skill(s)", len(result))
    return result


class _Cache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expires_at: float = 0.0
        self._skills: dict[str, Skill] = {}

    def invalidate(self) -> None:
        with self._lock:
            self._expires_at = 0.0
            self._skills = {}

    def get(self, db: Session | None = None) -> dict[str, Skill]:
        now = time.monotonic()
        with self._lock:
            if now < self._expires_at and self._skills:
                return self._skills

        merged = _merge(db)
        with self._lock:
            self._skills = merged
            self._expires_at = now + _CACHE_TTL_SECONDS
        return merged


def _merge(db: Session | None) -> dict[str, Skill]:
    builtins = _load_builtin_skills()

    try:
        if db is not None:
            db_rows = get_all_ai_skills(db)
        else:
            with GetDB() as owned:
                db_rows = get_all_ai_skills(owned)
    except Exception as exc:
        logger.warning(
            "AI skills DB layer unavailable (%s); using built-ins only. "
            "Run `alembic upgrade head` to pick up the ai_skills table.",
            exc.__class__.__name__,
        )
        return {name: s for name, s in builtins.items() if s.enabled}

    overrides: dict[str, Skill] = {}
    for row in db_rows:
        builtin = builtins.get(row.name)
        if builtin is not None:
            overrides[row.name] = Skill(
                name=row.name,
                description=row.description or builtin.description,
                body=row.body or builtin.body,
                source="override",
                enabled=bool(row.enabled),
            )
        else:
            overrides[row.name] = Skill(
                name=row.name,
                description=row.description or "",
                body=row.body or "",
                source="custom",
                enabled=bool(row.enabled),
            )

    final: dict[str, Skill] = {}
    for name, skill in builtins.items():
        if name in overrides:
            final[name] = overrides[name]
        else:
            final[name] = skill
    for name, skill in overrides.items():
        final.setdefault(name, skill)

    return final


_cache = _Cache()


def invalidate() -> None:
    """Drop the in-memory cache. Call after DB mutations."""
    _cache.invalidate()


def list_all(db: Session | None = None) -> list[Skill]:
    """Return every skill, including disabled ones (for admin listing)."""
    return sorted(_cache.get(db).values(), key=lambda s: s.name)


def list_enabled(db: Session | None = None) -> list[Skill]:
    return [s for s in list_all(db) if s.enabled and s.body.strip()]


def get(name: str, db: Session | None = None) -> Skill | None:
    skill = _cache.get(db).get(name)
    if skill is None:
        return None
    return skill


def build_catalog_text(db: Session | None = None) -> str:
    """Return the compact catalog block injected into the system prompt.

    Only enabled skills with non-empty bodies are listed — disabled rows
    and empty built-ins are hidden from the agent entirely.
    """
    enabled = list_enabled(db)
    if not enabled:
        return "(no skills registered)"
    lines = [f"- {s.name}: {s.description}" for s in enabled]
    return "\n".join(lines)
