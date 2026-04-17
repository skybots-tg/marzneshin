"""Skill-catalog access tools for the AI agent.

The agent sees a short `name: description` catalog in its system prompt
and uses these tools to load the full playbook text on demand — exactly
the Cursor / Claude-Code model.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai import skills_registry
from app.ai.tool_registry import register_tool


@register_tool(
    name="list_skills",
    description=(
        "Return every AI skill registered on this installation "
        "(`name`, `description`, `source`). Use this if the catalog in "
        "the system prompt looks stale, OR if the user asks which "
        "playbooks are available. Each item can be loaded in full via "
        "`read_skill(name)`. Disabled skills are excluded."
    ),
    requires_confirmation=False,
)
async def list_skills(db: Session) -> dict:
    db.close()
    skills = skills_registry.list_enabled()
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "source": s.source,
            }
            for s in skills
        ],
        "total": len(skills),
    }


@register_tool(
    name="read_skill",
    description=(
        "Return the full markdown body of a skill — the step-by-step "
        "playbook the agent should follow for a particular multi-step "
        "task. Call this FIRST whenever the user's request matches the "
        "description of a skill in the catalog, BEFORE starting to "
        "execute the task. The body includes the checklist, expected "
        "tool calls with argument shapes, and stop criteria. If the "
        "skill does not exist, returns an error — do not fabricate "
        "steps."
    ),
    requires_confirmation=False,
)
async def read_skill(db: Session, name: str) -> dict:
    db.close()
    skill = skills_registry.get(name)
    if skill is None:
        return {
            "error": f"Skill '{name}' not found",
            "hint": "Call list_skills() to see available skill names.",
        }
    if not skill.enabled or not skill.body.strip():
        return {
            "error": f"Skill '{name}' is disabled or empty",
        }
    return {
        "name": skill.name,
        "description": skill.description,
        "source": skill.source,
        "body": skill.body,
    }
