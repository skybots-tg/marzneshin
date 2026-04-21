import asyncio
import json
import logging
import time
from typing import Annotated

import sqlalchemy
from fastapi import APIRouter, Body, Depends, Query
from fastapi import HTTPException, WebSocket
from fastapi_pagination import Params
from fastapi_pagination.ext.sqlalchemy import paginate
from fastapi_pagination.links import Page
from starlette.responses import StreamingResponse
from starlette.websockets import WebSocketDisconnect, WebSocketState
from grpclib.exceptions import StreamTerminatedError, GRPCError

from app import marznode
from app.db import crud, get_tls_certificate, GetDB
from app.db.models import Node
from app.utils.share import SERVER_IP
from app.dependencies import (
    DBDep,
    SudoAdminDep,
    EndDateDep,
    StartDateDep,
    get_admin,
)
from app.models.node import (
    NodeCreate,
    NodeModify,
    NodeResponse,
    NodeSettings,
    NodeStatus,
    BackendConfig,
    BackendStats,
    DeviceInfo,
    DeviceInfoWithUser,
    UserDevicesResponse,
    AllUsersDevicesResponse,
)
from app.models.system import TrafficUsageSeries

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/nodes", tags=["Node"])


@router.get("", response_model=Page[NodeResponse])
def get_nodes(
    db: DBDep,
    admin: SudoAdminDep,
    status: list[NodeStatus] = Query(None),
    name: str = Query(None),
):
    query = db.query(Node)

    if name:
        query = query.filter(Node.name.ilike(f"%{name}%"))

    if status:
        query = query.filter(Node.status.in_(status))

    page = paginate(db, query)
    if page.items:
        flags = crud.get_nodes_address_in_hosts(
            db, [n.id for n in page.items], SERVER_IP
        )
        for item in page.items:
            item.address_in_hosts = flags.get(item.id, True)
    return page


@router.post("", response_model=NodeResponse)
async def add_node(new_node: NodeCreate, db: DBDep, admin: SudoAdminDep):
    def _db_work():
        try:
            db_node = crud.create_node(db, new_node)
        except sqlalchemy.exc.IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409, detail=f'Node "{new_node.name}" already exists'
            )
        certificate = get_tls_certificate(db)
        flags = crud.get_nodes_address_in_hosts(db, [db_node.id], SERVER_IP)
        db_node.address_in_hosts = flags.get(db_node.id, True)
        response = NodeResponse.model_validate(db_node)
        db.close()
        return db_node, certificate, response

    db_node, certificate, response = await asyncio.to_thread(_db_work)
    await marznode.operations.add_node(db_node, certificate)

    logger.info("New node `%s` added", db_node.name)
    return response


@router.get("/settings", response_model=NodeSettings)
def get_node_settings(db: DBDep, admin: SudoAdminDep):
    tls = crud.get_tls_certificate(db)

    return NodeSettings(certificate=tls.certificate)


@router.get("/{node_id}", response_model=NodeResponse)
def get_node(node_id: int, db: DBDep, admin: SudoAdminDep):
    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")

    flags = crud.get_nodes_address_in_hosts(db, [db_node.id], SERVER_IP)
    db_node.address_in_hosts = flags.get(db_node.id, True)
    return db_node


@router.websocket("/{node_id}/{backend}/logs")
async def node_logs(
    node_id: int,
    backend: str,
    websocket: WebSocket,
    include_buffer: bool = True,
):
    token = websocket.query_params.get("token", "") or websocket.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ")

    with GetDB() as db:
        admin = get_admin(db, token)

    if not admin or not admin.is_sudo:
        return await websocket.close(reason="You're not allowed", code=4403)

    if not marznode.nodes.get(node_id):
        return await websocket.close(reason="Node not found", code=4404)

    await websocket.accept()
    try:
        async for line in marznode.nodes[node_id].get_logs(
            name=backend, include_buffer=include_buffer
        ):
            await websocket.send_text(line)
    except WebSocketDisconnect:
        logger.debug("websocket disconnected")
    except (StreamTerminatedError, GRPCError):
        logger.info("node %i detached", node_id)
    finally:
        if websocket.state == WebSocketState.CONNECTED:
            await websocket.close()


@router.put("/{node_id}", response_model=NodeResponse)
async def modify_node(
    node_id: int, modified_node: NodeModify, db: DBDep, admin: SudoAdminDep
):
    def _db_work():
        db_node = crud.get_node_by_id(db, node_id)
        if not db_node:
            raise HTTPException(status_code=404, detail="Node not found")
        db_node = crud.update_node(db, db_node, modified_node)
        certificate = get_tls_certificate(db) if db_node.status != NodeStatus.disabled else None
        flags = crud.get_nodes_address_in_hosts(db, [db_node.id], SERVER_IP)
        db_node.address_in_hosts = flags.get(db_node.id, True)
        response = NodeResponse.model_validate(db_node)
        db.close()
        return db_node, certificate, response

    db_node, certificate, response = await asyncio.to_thread(_db_work)

    await marznode.operations.remove_node(db_node.id)
    if certificate:
        await marznode.operations.add_node(db_node, certificate)

    logger.info("Node `%s` modified", db_node.name)
    return response


@router.delete("/{node_id}")
async def remove_node(node_id: int, db: DBDep, admin: SudoAdminDep):
    def _db_work():
        db_node = crud.get_node_by_id(db, node_id)
        if not db_node:
            raise HTTPException(status_code=404, detail="Node not found")
        node_name = db_node.name
        removed_id = db_node.id
        crud.remove_node(db, db_node)
        db.close()
        return node_name, removed_id

    node_name, removed_id = await asyncio.to_thread(_db_work)
    await marznode.operations.remove_node(removed_id)

    logger.info("Node `%s` deleted", node_name)
    return {}


# Порядок и человекочитаемые имена шагов для SSE-удаления.
# Detach идёт ПЕРВЫМ: иначе фоновый монитор узла продолжает дёргать
# те же usage-таблицы (set_status / list_users / store_backends),
# конкурируя за ``_node_db_sem`` и блокируя batched-deletes ниже.
# Ключи id совпадают с tablename в crud.remove_node + один виртуальный шаг.
_DELETE_STEPS: list[dict] = [
    {"id": "marznode_detach", "name": "Detach from marznode"},
    {"id": "node_user_usages_daily", "name": "Per-user daily usage"},
    {"id": "node_usages_daily", "name": "Node daily usage"},
    {"id": "node_user_usages", "name": "Per-user hourly usage"},
    {"id": "node_usages", "name": "Node hourly usage"},
    {"id": "nodes", "name": "Node record"},
]

_SSE_HEARTBEAT_SECONDS = 10
_MARZNODE_DETACH_TIMEOUT = 30


@router.post("/{node_id}/delete-stream")
async def remove_node_stream(node_id: int, admin: SudoAdminDep):
    """Delete a node while streaming per-step progress over SSE.

    Порядок: detach gRPC-соединения → батч-удаление usage-таблиц
    → удаление самой записи. Каждая фаза эмитит step_start / progress /
    step_done, плюс между ними идёт SSE-heartbeat, чтобы прокси не
    закрывали idle-соединение во время длинных батчей.
    """

    def _preload() -> str | None:
        with GetDB() as db:
            db_node = crud.get_node_by_id(db, node_id)
            return db_node.name if db_node else None

    node_name = await asyncio.to_thread(_preload)
    if node_name is None:
        raise HTTPException(status_code=404, detail="Node not found")

    def _send(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _step(step_id: str, status: str, *, done: int = 0, total: int = 0) -> str:
        return _send(
            "step_update",
            {
                "step": {
                    "id": step_id,
                    "status": status,
                    "done": done,
                    "total": total,
                }
            },
        )

    async def event_generator():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def put(evt: dict | None) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, evt)

        steps = [
            {**step, "status": "pending", "done": 0, "total": 0}
            for step in _DELETE_STEPS
        ]
        yield _send("steps", {"steps": steps})

        # --- Step 1: detach the node from the gRPC pool first. -------
        # Stops the background monitor so it can't update_node_status /
        # list_users / store_backends concurrently with the deletes.
        yield _step("marznode_detach", "in_progress")
        try:
            await asyncio.wait_for(
                marznode.operations.remove_node(node_id),
                timeout=_MARZNODE_DETACH_TIMEOUT,
            )
            yield _step("marznode_detach", "success")
        except asyncio.TimeoutError:
            logger.warning(
                "Node %s: marznode detach exceeded %ds; continuing with DB delete",
                node_id, _MARZNODE_DETACH_TIMEOUT,
            )
            yield _step("marznode_detach", "error")
            yield _send(
                "log",
                {"message": f"marznode detach timed out after {_MARZNODE_DETACH_TIMEOUT}s"},
            )
        except Exception as exc:
            logger.warning(
                "Node %s: marznode detach failed: %s", node_id, exc,
            )
            yield _step("marznode_detach", "error")
            yield _send("log", {"message": f"marznode detach failed: {exc}"})

        # --- Step 2: delete DB rows in a worker thread. --------------
        # A fresh GetDB() session is opened inside the thread so we
        # never share a SQLAlchemy session across threads (it isn't
        # thread-safe and was a likely source of the earlier hangs).
        def _db_work() -> None:
            try:
                with GetDB() as db:
                    db_node = crud.get_node_by_id(db, node_id)
                    if not db_node:
                        put({"kind": "fatal", "message": "Node not found"})
                        return
                    crud.remove_node(db, db_node, on_progress=put)
            except Exception as exc:
                logger.exception("Failed to remove node %s from DB", node_id)
                put({"kind": "fatal", "message": str(exc)})
            finally:
                put(None)

        task = asyncio.create_task(asyncio.to_thread(_db_work))

        db_success = True

        try:
            while True:
                # Heartbeat: yield an SSE comment if no event for a
                # while, so intermediate proxies don't kill the idle
                # connection during long batched deletes.
                try:
                    evt = await asyncio.wait_for(
                        queue.get(), timeout=_SSE_HEARTBEAT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                if evt is None:
                    break

                kind = evt.get("kind")
                if kind == "step_start":
                    yield _step(
                        evt["table"], "in_progress",
                        done=0, total=evt.get("total", 0),
                    )
                elif kind == "progress":
                    yield _step(
                        evt["table"], "in_progress",
                        done=evt.get("done", 0), total=evt.get("total", 0),
                    )
                elif kind == "step_done":
                    yield _step(
                        evt["table"], "success",
                        done=evt.get("done", 0), total=evt.get("total", 0),
                    )
                elif kind == "step_error":
                    db_success = False
                    yield _step(evt["table"], "error")
                elif kind == "fatal":
                    db_success = False
                    yield _send("error", {"message": evt.get("message", "")})

            await task
        except Exception:
            task.cancel()
            raise

        if not db_success:
            yield _send(
                "complete",
                {
                    "success": False,
                    "message": f"Failed to delete node {node_name}",
                },
            )
            return

        logger.info("Node `%s` deleted", node_name)
        yield _send(
            "complete",
            {
                "success": True,
                "message": f"Node {node_name} deleted",
                "node_id": node_id,
                "node_name": node_name,
            },
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{node_id}/resync")
async def resync_node_users(node_id: int, db: DBDep, admin: SudoAdminDep):
    """
    Force resync all users with the specified node.

    This will repopulate all users on the node, ensuring the node has
    up-to-date user data including device limits and allowed fingerprints.
    """
    db_node = crud.get_node_by_id(db, node_id)
    if not db_node:
        raise HTTPException(status_code=404, detail="Node not found")
    node_name = db_node.name
    db.close()

    node = marznode.nodes.get(node_id)
    if not node:
        raise HTTPException(status_code=503, detail="Node is not connected")

    if not node.synced:
        raise HTTPException(status_code=503, detail="Node is not synced")

    try:
        await node.resync_users()
    except Exception as e:
        logger.error(f"Failed to resync users on node {node_id}: {e}")
        raise HTTPException(status_code=502, detail="Failed to resync users with node")

    logger.info("Users resynced on node `%s`", node_name)
    return {"status": "ok", "message": f"Users resynced on node {node_name}"}


@router.get("/{node_id}/usage", response_model=TrafficUsageSeries)
def get_usage(
    node_id: int,
    db: DBDep,
    admin: SudoAdminDep,
    start_date: StartDateDep,
    end_date: EndDateDep,
):
    """
    Get nodes usage
    """
    node = crud.get_node_by_id(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    return crud.get_node_usage(db, start_date, end_date, node)


@router.get("/{node_id}/{backend}/stats", response_model=BackendStats)
async def get_backend_stats(
    node_id: int, backend: str, db: DBDep, admin: SudoAdminDep
):
    db.close()
    if not (node := marznode.nodes.get(node_id)):
        raise HTTPException(status_code=404, detail="Node not found")

    try:
        stats = await node.get_backend_stats(backend)
    except Exception:
        raise HTTPException(502)
    else:
        return BackendStats(running=stats.running)


@router.get("/{node_id}/{backend}/config", response_model=BackendConfig)
async def get_node_xray_config(
    node_id: int, backend: str, admin: SudoAdminDep
):
    if not (node := marznode.nodes.get(node_id)):
        raise HTTPException(status_code=404, detail="Node not found")

    try:
        config, config_format = await node.get_backend_config(name=backend)
    except Exception:
        raise HTTPException(status_code=502, detail="Node isn't responsive")
    else:
        return {"config": config, "format": config_format}


@router.put("/{node_id}/{backend}/config")
async def alter_node_xray_config(
    node_id: int,
    backend: str,
    admin: SudoAdminDep,
    config: Annotated[BackendConfig, Body()],
):
    if not (node := marznode.nodes.get(node_id)):
        raise HTTPException(status_code=404, detail="Node not found")

    start_time = time.time()
    timeout_seconds = 60

    try:
        await asyncio.wait_for(
            node.restart_backend(
                name=backend,
                config=config.config,
                config_format=config.format.value,
            ),
            timeout_seconds,
        )
        elapsed = time.time() - start_time
        logger.info(
            f"Successfully restarted backend '{backend}' on node {node_id} in {elapsed:.2f}s"
        )
    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        error_msg = f"Timeout ({timeout_seconds}s) waiting for node {node_id} to restart backend '{backend}' (elapsed: {elapsed:.2f}s)"
        logger.error(error_msg)
        raise HTTPException(
            status_code=502, detail=error_msg
        )
    except (GRPCError, StreamTerminatedError) as e:
        error_msg = f"gRPC error from node {node_id} when restarting backend '{backend}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(
            status_code=502, detail=f"Connection error: {str(e)}"
        )
    except ConnectionError as e:
        error_msg = f"Connection error with node {node_id} when restarting backend '{backend}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(
            status_code=502, detail=f"Connection refused: {str(e)}"
        )
    except Exception as e:
        error_msg = f"Failed to restart backend '{backend}' on node {node_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(
            status_code=502, detail=f"Failed to update config: {str(e)}"
        )
    return {}


@router.get("/{node_id}/devices/{user_id}", response_model=UserDevicesResponse)
async def get_user_devices(
    node_id: int,
    user_id: int,
    admin: SudoAdminDep,
    active_only: bool = Query(False, description="Return only active devices"),
):
    """
    Get device history for a specific user on a node.

    This endpoint fetches the device connection history from the node's internal storage.
    Each device is identified by a unique combination of IP address and client name.

    - **node_id**: ID of the node to query
    - **user_id**: ID of the user whose devices to fetch
    - **active_only**: If True, return only devices active in the last 5 minutes

    Returns device information including:
    - Connection times (first_seen, last_seen)
    - Traffic statistics (upload, download, total)
    - Device metadata (IP, client name, user agent, protocol, TLS fingerprint)
    - Activity status
    """
    if not (node := marznode.nodes.get(node_id)):
        raise HTTPException(status_code=404, detail="Node not found")

    try:
        response = await node.fetch_user_devices(uid=user_id, active_only=active_only)
    except NotImplementedError as e:
        logger.warning(f"Node {node_id} does not support device listing: {e}")
        raise HTTPException(
            status_code=501,
            detail="This node does not support device listing. Update the node software.",
        )
    except Exception as e:
        logger.error(f"Failed to fetch user devices from node {node_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch device history from node"
        )

    devices = [
        DeviceInfo(
            remote_ip=device.remote_ip,
            client_name=device.client_name,
            user_agent=device.user_agent if device.user_agent else None,
            protocol=device.protocol if device.protocol else None,
            tls_fingerprint=device.tls_fingerprint if device.tls_fingerprint else None,
            first_seen=device.first_seen,
            last_seen=device.last_seen,
            total_usage=device.total_usage,
            uplink=device.uplink,
            downlink=device.downlink,
            is_active=device.is_active,
        )
        for device in response.devices
    ]

    return UserDevicesResponse(uid=response.uid, devices=devices)


@router.get("/{node_id}/devices", response_model=Page[DeviceInfoWithUser])
async def get_all_devices(
    node_id: int,
    admin: SudoAdminDep,
    params: Params = Depends(),
    search: str | None = Query(None, description="Search in IP, client name, user agent"),
    active_only: bool = Query(False, description="Return only active devices"),
    uid: int | None = Query(None, description="Filter by user ID"),
    protocol: str | None = Query(None, description="Filter by protocol"),
    sort_by: str = Query("last_seen", description="Sort field"),
    descending: bool = Query(True, description="Sort direction"),
):
    """
    Get paginated device history for all users on a node.
    Supports search, filtering by status/user/protocol, and sorting.
    """
    if not (node := marznode.nodes.get(node_id)):
        raise HTTPException(status_code=404, detail="Node not found")

    try:
        response = await node.fetch_all_devices()
    except NotImplementedError as e:
        logger.warning(f"Node {node_id} does not support device listing: {e}")
        raise HTTPException(
            status_code=501,
            detail="This node does not support device listing. Update the node software.",
        )
    except Exception as e:
        logger.error(f"Failed to fetch all devices from node {node_id}: {e}")
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch device history from node"
        )

    flat: list[DeviceInfoWithUser] = []
    for user_devices in response.users:
        for device in user_devices.devices:
            flat.append(DeviceInfoWithUser(
                uid=user_devices.uid,
                remote_ip=device.remote_ip,
                client_name=device.client_name,
                user_agent=device.user_agent if device.user_agent else None,
                protocol=device.protocol if device.protocol else None,
                tls_fingerprint=device.tls_fingerprint if device.tls_fingerprint else None,
                first_seen=device.first_seen,
                last_seen=device.last_seen,
                total_usage=device.total_usage,
                uplink=device.uplink,
                downlink=device.downlink,
                is_active=device.is_active,
            ))

    if active_only:
        flat = [d for d in flat if d.is_active]
    if uid is not None:
        flat = [d for d in flat if d.uid == uid]
    if protocol:
        proto_lower = protocol.lower()
        flat = [d for d in flat if d.protocol and proto_lower in d.protocol.lower()]
    if search:
        q = search.lower()
        flat = [
            d for d in flat
            if q in d.remote_ip.lower()
            or q in d.client_name.lower()
            or (d.user_agent and q in d.user_agent.lower())
        ]

    sort_field = sort_by if hasattr(DeviceInfoWithUser, sort_by) else "last_seen"
    flat.sort(
        key=lambda d: getattr(d, sort_field) or 0,
        reverse=descending,
    )

    start = (params.page - 1) * params.size
    end = start + params.size

    return Page(
        items=flat[start:end],
        total=len(flat),
        page=params.page,
        size=params.size,
    )
