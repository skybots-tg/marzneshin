import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


@register_tool(
    name="get_service_info",
    description=(
        "Get detailed information about a service: name, inbounds (with protocol and node), "
        "user count, and associated hosts. "
        "Relationship: User → Service → Inbound → Host."
    ),
    requires_confirmation=False,
)
async def get_service_info(db: Session, service_id: int) -> dict:
    from app.db import crud

    service = crud.get_service(db, service_id)
    if not service:
        return {"error": f"Service {service_id} not found"}

    return {
        "id": service.id,
        "name": service.name,
        "user_count": len(service.users) if service.users else 0,
        "inbounds": [
            {
                "id": i.id,
                "tag": i.tag,
                "protocol": str(i.protocol),
                "node_id": i.node_id,
                "host_count": len(i.hosts) if i.hosts else 0,
            }
            for i in service.inbounds
        ] if service.inbounds else [],
        "users_sample": [
            {"id": u.id, "username": u.username, "enabled": u.enabled}
            for u in (service.users[:20] if service.users else [])
        ],
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
