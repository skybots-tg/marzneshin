from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.ai_skill import AISkill
from app.models.ai_skill import AISkillCreate, AISkillUpdate


def get_ai_skill(db: Session, name: str) -> AISkill | None:
    return db.query(AISkill).filter(AISkill.name == name).first()


def get_all_ai_skills(db: Session) -> list[AISkill]:
    return db.query(AISkill).order_by(AISkill.name).all()


def create_ai_skill(
    db: Session, payload: AISkillCreate, *, is_override: bool = False
) -> AISkill:
    skill = AISkill(
        name=payload.name,
        description=payload.description,
        body=payload.body,
        enabled=payload.enabled,
        is_override=is_override,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def update_ai_skill(
    db: Session, skill: AISkill, payload: AISkillUpdate
) -> AISkill:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(skill, field, value)
    skill.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(skill)
    return skill


def delete_ai_skill(db: Session, skill: AISkill) -> None:
    db.delete(skill)
    db.commit()
