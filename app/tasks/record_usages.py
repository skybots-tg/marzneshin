import asyncio
import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy import and_, select, insert, update, bindparam

from app import marznode
from app.db import GetDB
from app.db.models import NodeUsage, NodeUserUsage, User
from app.marznode import MarzNodeBase
from app.models.notification import UserNotification
from app.models.user import UserResponse
from app.notification.notifiers import notify
from app.tasks.data_usage_percent_reached import data_usage_percent_reached
from app.config.env import DISABLE_RECORDING_NODE_USAGE
from app.utils.async_utils import fire_and_forget
from app.utils.device_tracker import track_user_connection

logger = logging.getLogger(__name__)


def _get_hour_bucket():
    return datetime.fromisoformat(
        datetime.utcnow().strftime("%Y-%m-%dT%H:00:00")
    )


def _do_record_usage_logs(db, params, node_id, consumption_factor, created_at):
    """Core logic for recording usage logs into an existing session."""
    select_stmt = select(NodeUserUsage.user_id).where(
        and_(
            NodeUserUsage.node_id == node_id,
            NodeUserUsage.created_at == created_at,
        )
    )
    existing_set = set(r[0] for r in db.execute(select_stmt).fetchall())
    uids_to_insert = set()

    for p in params:
        uid = p["uid"]
        if uid not in existing_set:
            uids_to_insert.add(uid)

    if uids_to_insert:
        stmt = insert(NodeUserUsage).values(
            user_id=bindparam("uid"),
            created_at=created_at,
            node_id=node_id,
            used_traffic=0,
        )
        db.execute(stmt, [{"uid": uid} for uid in uids_to_insert])

    stmt = (
        update(NodeUserUsage)
        .values(
            used_traffic=NodeUserUsage.used_traffic + bindparam("value")
        )
        .where(
            and_(
                NodeUserUsage.user_id == bindparam("uid"),
                NodeUserUsage.node_id == node_id,
                NodeUserUsage.created_at == created_at,
            )
        )
    )
    db.connection().execute(
        stmt,
        [
            {**usage, "value": int(usage["value"] * consumption_factor)}
            for usage in params
        ],
        execution_options={"synchronize_session": None},
    )


def record_user_usage_logs(
    params: list, node_id: int, consumption_factor: int = 1, db=None
):
    """Record user usage logs. Accepts optional db session to avoid opening new connections."""
    if not params:
        return

    created_at = _get_hour_bucket()

    if db is not None:
        _do_record_usage_logs(db, params, node_id, consumption_factor, created_at)
    else:
        with GetDB() as own_db:
            _do_record_usage_logs(own_db, params, node_id, consumption_factor, created_at)
            own_db.commit()


def record_all_node_stats(node_usages: dict[int, int], db):
    """Record stats for ALL nodes in batch (2 queries total instead of 2 per node)."""
    if DISABLE_RECORDING_NODE_USAGE:
        return
    if not node_usages:
        return

    created_at = _get_hour_bucket()
    active_ids = list(node_usages.keys())

    existing_ids = set(
        r[0]
        for r in db.execute(
            select(NodeUsage.node_id).where(
                and_(
                    NodeUsage.node_id.in_(active_ids),
                    NodeUsage.created_at == created_at,
                )
            )
        ).fetchall()
    )

    to_insert = [nid for nid in active_ids if nid not in existing_ids]
    if to_insert:
        db.execute(
            insert(NodeUsage),
            [
                {"created_at": created_at, "node_id": nid, "uplink": 0, "downlink": 0}
                for nid in to_insert
            ],
        )

    for nid, usage in node_usages.items():
        if not usage:
            continue
        db.execute(
            update(NodeUsage)
            .values(downlink=NodeUsage.downlink + usage)
            .where(
                and_(
                    NodeUsage.node_id == nid,
                    NodeUsage.created_at == created_at,
                )
            )
        )


async def get_users_stats(
    node_id: int, node: MarzNodeBase
) -> tuple[int, list[dict]]:
    try:
        params = list()
        for stat in await asyncio.wait_for(node.fetch_users_stats(), 10):
            if stat.usage:
                uplink = getattr(stat, "uplink", 0)
                downlink = getattr(stat, "downlink", 0)
                
                if uplink == 0 and downlink == 0 and stat.usage > 0:
                    downlink = stat.usage
                
                params.append({
                    "uid": stat.uid,
                    "value": stat.usage,
                    "uplink": uplink,
                    "downlink": downlink,
                    "remote_ip": getattr(stat, "remote_ip", None) or None,
                    "client_name": getattr(stat, "client_name", None) or None,
                    "user_agent": getattr(stat, "user_agent", None) or None,
                })
        return node_id, params
    except:
        return node_id, []


async def record_user_usages():
    """
    Main task for recording user usages.
    
    Optimized to use a single database session for all operations
    to reduce connection pool pressure and improve performance.
    """
    results = await asyncio.gather(
        *[
            get_users_stats(node_id, node)
            for node_id, node in marznode.nodes.items()
        ]
    )
    api_params = {node_id: params for node_id, params in list(results)}

    users_usage = defaultdict(int)
    bucket_start = datetime.utcnow()
    node_usages: dict[int, int] = {}
    
    with GetDB() as db:
        # Phase 1: Accumulate usage + device tracking.
        # Commit after every node to release DB locks quickly and let the
        # pool breathe — a single giant transaction across all nodes held
        # locks on Device/DeviceIP/DeviceTraffic for too long.
        for node_id, params in api_params.items():
            coefficient = (
                node.usage_coefficient
                if (node := marznode.nodes.get(node_id))
                else 1
            )
            node_usage = 0
            node_tracked = 0
            
            for param in params:
                users_usage[param["uid"]] += int(param["value"] * coefficient)
                node_usage += param["value"]
                
                if param.get("remote_ip"):
                    try:
                        device_id, _ = track_user_connection(
                            db=db,
                            user_id=param["uid"],
                            node_id=node_id,
                            remote_ip=param["remote_ip"],
                            client_name=param.get("client_name"),
                            user_agent=param.get("user_agent"),
                            upload_bytes=param.get("uplink", 0),
                            download_bytes=param.get("downlink", param["value"]),
                            bucket_start=bucket_start,
                            auto_commit=False,
                        )
                        if device_id:
                            node_tracked += 1
                    except Exception as e:
                        logger.warning(f"[Node {node_id}] Failed to track device for user {param['uid']}: {e}")
            
            node_usages[node_id] = node_usage
            db.commit()
            
            if params:
                tracking_rate = (node_tracked / len(params)) * 100 if node_tracked else 0
                if node_tracked == 0:
                    logger.warning(
                        f"[Node {node_id}] Device tracking: 0/{len(params)} (0%). "
                        f"This node is NOT sending remote_ip data."
                    )
                else:
                    logger.debug(
                        f"[Node {node_id}] Device tracking: {node_tracked}/{len(params)} ({tracking_rate:.1f}%)"
                    )
        
        record_all_node_stats(node_usages, db)
        db.commit()
        
        # Phase 2: Record user usage logs
        for node_id, params in api_params.items():
            record_user_usage_logs(
                params,
                node_id,
                (
                    node.usage_coefficient
                    if (node := marznode.nodes.get(node_id))
                    else 1
                ),
                db=db,
            )
        db.commit()

    users_usage = list(
        {"id": uid, "value": value} for uid, value in users_usage.items()
    )
    if not users_usage:
        return

    # Phase 3: Update user traffic totals
    with GetDB() as db:
        await data_usage_percent_reached(db, users_usage)

        user_ids = [u["id"] for u in users_usage]
        users_map = {
            u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()
        }
        users_to_check = []

        for u_usage in users_usage:
            uid = u_usage["id"]
            user = users_map.get(uid)
            if user and user.data_limit and user.used_traffic < user.data_limit:
                users_to_check.append(user)

        stmt = update(User).values(
            used_traffic=User.used_traffic + bindparam("value"),
            lifetime_used_traffic=User.lifetime_used_traffic
            + bindparam("value"),
            online_at=datetime.utcnow(),
        )

        db.execute(
            stmt, users_usage, execution_options={"synchronize_session": None}
        )
        db.commit()

        for user in users_to_check:
            db.refresh(user)
            if user.data_limit_reached:
                marznode.operations.update_user(user, db=db)
                fire_and_forget(
                    notify(
                        action=UserNotification.Action.data_limit_exhausted,
                        user=UserResponse.model_validate(user),
                    )
                )