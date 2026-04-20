import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="get_service_info",
    description=(
        "Get detailed information about a service: name, inbounds (with protocol and node), "
        "user count, and a short user sample. "
        "Counts are computed via aggregate queries, so safe on installs with 10k+ users. "
        "Relationship: User → Service → Inbound → Host."
    ),
    requires_confirmation=False,
)
async def get_service_info(db: Session, service_id: int) -> dict:
    from sqlalchemy import func
    from app.db.models import Service
    from app.db.models.core import User
    from app.db.models.associations import users_services

    service = (
        db.query(Service).filter(Service.id == service_id).first()
    )
    if not service:
        return {"error": f"Service {service_id} not found"}

    user_count = (
        db.query(func.count(users_services.c.user_id))
        .join(User, User.id == users_services.c.user_id)
        .filter(
            users_services.c.service_id == service_id,
            User.removed == False,  # noqa: E712
        )
        .scalar()
        or 0
    )
    users_sample = (
        db.query(User)
        .join(users_services, users_services.c.user_id == User.id)
        .filter(
            users_services.c.service_id == service_id,
            User.removed == False,  # noqa: E712
        )
        .order_by(User.id.desc())
        .limit(20)
        .all()
    )

    return {
        "id": service.id,
        "name": service.name,
        "user_count": int(user_count),
        "inbounds": [
            {
                "id": i.id,
                "tag": i.tag,
                "protocol": str(i.protocol),
                "node_id": i.node_id,
                "host_count": len(i.hosts) if i.hosts else 0,
            }
            for i in (service.inbounds or [])
        ],
        "users_sample": [
            {"id": u.id, "username": u.username, "enabled": u.enabled}
            for u in users_sample
        ],
    }


@register_tool(
    name="add_inbounds_to_service",
    description=(
        "Add one or more inbound IDs to a service WITHOUT replacing its existing inbounds. "
        "Use this when onboarding a new node and you want its inbounds to be available to "
        "users of an existing service. Idempotent: inbounds already attached are skipped and "
        "reported. Missing inbound IDs are reported, not errored."
    ),
    requires_confirmation=True,
)
async def add_inbounds_to_service(
    db: Session, service_id: int, inbound_ids: list = []
) -> dict:
    from app.db.models import Service, Inbound

    if not inbound_ids:
        return {"error": "inbound_ids must be a non-empty list of integers"}
    try:
        ids = [int(i) for i in inbound_ids]
    except (TypeError, ValueError):
        return {"error": "inbound_ids must contain integers only"}

    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        return {"error": f"Service {service_id} not found"}

    found = db.query(Inbound).filter(Inbound.id.in_(ids)).all()
    found_ids = {i.id for i in found}
    missing = [i for i in ids if i not in found_ids]

    existing_ids = {i.id for i in (service.inbounds or [])}
    to_add = [i for i in found if i.id not in existing_ids]
    already = sorted(existing_ids & set(ids))

    if to_add:
        service.inbounds = list(service.inbounds or []) + to_add
        db.commit()
        db.refresh(service)

    return {
        "success": True,
        "service": {"id": service.id, "name": service.name},
        "added_inbound_ids": [i.id for i in to_add],
        "already_attached_inbound_ids": already,
        "missing_inbound_ids": missing,
        "final_inbound_ids": [i.id for i in (service.inbounds or [])],
    }


@register_tool(
    name="remove_inbounds_from_service",
    description=(
        "Remove one or more inbound IDs from a service without touching the rest of its "
        "inbounds. Idempotent: inbound IDs that are not currently attached are reported "
        "in `not_present_inbound_ids` but do not fail the call."
    ),
    requires_confirmation=True,
)
async def remove_inbounds_from_service(
    db: Session, service_id: int, inbound_ids: list = []
) -> dict:
    from app.db.models import Service

    if not inbound_ids:
        return {"error": "inbound_ids must be a non-empty list of integers"}
    try:
        ids = {int(i) for i in inbound_ids}
    except (TypeError, ValueError):
        return {"error": "inbound_ids must contain integers only"}

    service = db.query(Service).filter(Service.id == service_id).first()
    if not service:
        return {"error": f"Service {service_id} not found"}

    before_ids = {i.id for i in (service.inbounds or [])}
    removed = sorted(before_ids & ids)
    not_present = sorted(ids - before_ids)

    if removed:
        service.inbounds = [
            i for i in (service.inbounds or []) if i.id not in ids
        ]
        db.commit()
        db.refresh(service)

    return {
        "success": True,
        "service": {"id": service.id, "name": service.name},
        "removed_inbound_ids": removed,
        "not_present_inbound_ids": not_present,
        "final_inbound_ids": [i.id for i in (service.inbounds or [])],
    }


@register_tool(
    name="propagate_node_to_services",
    description=(
        "Propagate the target node's inbounds into every service the donor was in. "
        "Two passes, both idempotent:\n"
        "  (1) tag-mapping: for every service that currently contains at least one "
        "inbound of `from_node_id`, add the `to_node_id` inbound with the SAME tag. "
        "Donor tags with no counterpart on the target are reported in `unmatched_donor_tags`.\n"
        "  (2) orphan-binding (when `bind_orphan_target_inbounds=true`, default): every "
        "target inbound that ended up with ZERO service bindings after pass 1 is bound "
        "to the FULL union of services touched in pass 1. This catches inbounds that "
        "exist on the target but have NO matching tag on the donor (e.g. you added a "
        "new XHTTP variant directly on the target — there is no donor tag to map from, "
        "but the new inbound still must reach users of those services).\n"
        "Without pass (2), orphan target inbounds end up invisible to user sync — xray "
        "is configured but `marznode.RepopulateUsers` pushes 0 clients to them, so "
        "external probes see TLS but no traffic flows. This was the root cause of the "
        "'pingable but nothing opens' incidents on UNIVERSAL 4.\n"
        "Returns: `services_updated`, `services_already_up_to_date`, "
        "`unmatched_donor_tags`, `orphan_target_inbounds_bound` (per-inbound report of "
        "what pass 2 attached), `orphan_target_inbounds_skipped` (still unbound after "
        "both passes — pass 2 had no union services to bind to)."
    ),
    requires_confirmation=True,
)
async def propagate_node_to_services(
    db: Session,
    from_node_id: int,
    to_node_id: int,
    bind_orphan_target_inbounds: bool = True,
) -> dict:
    from app.db.models import Service, Inbound

    if from_node_id == to_node_id:
        return {"error": "from_node_id and to_node_id must differ"}

    donor = db.query(Inbound).filter(Inbound.node_id == from_node_id).all()
    target = db.query(Inbound).filter(Inbound.node_id == to_node_id).all()
    if not donor:
        return {"error": f"Donor node {from_node_id} has no inbounds"}
    if not target:
        return {"error": f"Target node {to_node_id} has no inbounds"}

    target_by_tag = {i.tag: i for i in target}
    donor_tags = [i.tag for i in donor]
    donor_ids = {i.id for i in donor}
    unmatched_tags = sorted({t for t in donor_tags if t not in target_by_tag})

    services = (
        db.query(Service)
        .join(Service.inbounds)
        .filter(Inbound.id.in_(donor_ids))
        .distinct()
        .all()
    )

    updated: list[dict] = []
    already: list[dict] = []
    any_change = False
    for svc in services:
        existing_ids = {i.id for i in (svc.inbounds or [])}
        donor_tags_here = [
            i.tag for i in (svc.inbounds or []) if i.node_id == from_node_id
        ]
        to_add = [
            target_by_tag[t]
            for t in donor_tags_here
            if t in target_by_tag and target_by_tag[t].id not in existing_ids
        ]
        if to_add:
            svc.inbounds = list(svc.inbounds or []) + to_add
            any_change = True
            updated.append({
                "service_id": svc.id,
                "service_name": svc.name,
                "added_inbound_ids": [i.id for i in to_add],
                "added_inbound_tags": [i.tag for i in to_add],
            })
        else:
            already.append({
                "service_id": svc.id,
                "service_name": svc.name,
            })

    orphans_bound: list[dict] = []
    orphans_skipped: list[dict] = []
    if bind_orphan_target_inbounds:
        if any_change:
            db.flush()
        union_services = list(services)
        union_service_ids = {s.id for s in union_services}
        for inb in target:
            current_service_ids = {s.id for s in (inb.services or [])}
            if current_service_ids:
                continue
            if not union_service_ids:
                orphans_skipped.append({
                    "inbound_id": inb.id,
                    "inbound_tag": inb.tag,
                    "reason": (
                        "no donor services to bind to (donor inbounds "
                        "were not attached to any service either)"
                    ),
                })
                continue
            inb.services = list(union_services)
            any_change = True
            orphans_bound.append({
                "inbound_id": inb.id,
                "inbound_tag": inb.tag,
                "bound_to_service_ids": sorted(union_service_ids),
            })

    if any_change:
        db.commit()

    return {
        "success": True,
        "from_node_id": from_node_id,
        "to_node_id": to_node_id,
        "donor_inbound_tags": donor_tags,
        "target_inbound_tags": list(target_by_tag.keys()),
        "unmatched_donor_tags": unmatched_tags,
        "services_updated": updated,
        "services_already_up_to_date": already,
        "orphan_target_inbounds_bound": orphans_bound,
        "orphan_target_inbounds_skipped": orphans_skipped,
    }


@register_tool(
    name="create_service",
    description=(
        "Create a new service with a name and list of inbound IDs. "
        "Inbounds define which protocols/nodes users of this service can access."
    ),
    requires_confirmation=True,
)
async def create_service(
    db: Session, name: str, inbound_ids: list = []
) -> dict:
    from app.db import crud
    from app.models.service import ServiceCreate

    try:
        service_data = ServiceCreate(name=name, inbound_ids=inbound_ids)
        db_service = crud.create_service(db, service_data)
    except Exception as e:
        return {"error": str(e)}

    return {
        "success": True,
        "service": {
            "id": db_service.id,
            "name": db_service.name,
            "inbound_ids": [i.id for i in db_service.inbounds],
        },
    }


@register_tool(
    name="modify_service",
    description=(
        "Modify a service: change name or update associated inbound IDs. "
        "Only provided fields are updated."
    ),
    requires_confirmation=True,
)
async def modify_service(
    db: Session, service_id: int, name: str = "", inbound_ids: list = []
) -> dict:
    from app.db import crud
    from app.models.service import Service as ServiceModify

    db_service = crud.get_service(db, service_id)
    if not db_service:
        return {"error": f"Service {service_id} not found"}

    kwargs = {}
    if name:
        kwargs["name"] = name
    if inbound_ids:
        kwargs["inbound_ids"] = inbound_ids

    try:
        modification = ServiceModify(**kwargs)
        db_service = crud.update_service(db, db_service, modification)
    except Exception as e:
        return {"error": str(e)}

    return {
        "success": True,
        "service": {
            "id": db_service.id,
            "name": db_service.name,
            "inbound_ids": [i.id for i in db_service.inbounds],
        },
    }


@register_tool(
    name="delete_service",
    description="Delete a service. Users will lose access to inbounds provided by this service.",
    requires_confirmation=True,
)
async def delete_service(db: Session, service_id: int) -> dict:
    from app.db import crud

    db_service = crud.get_service(db, service_id)
    if not db_service:
        return {"error": f"Service {service_id} not found"}

    name = db_service.name
    try:
        crud.remove_service(db, db_service)
    except Exception as e:
        return {"error": str(e)}

    return {"success": True, "message": f"Service '{name}' (id={service_id}) deleted"}
