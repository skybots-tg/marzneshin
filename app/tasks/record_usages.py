import asyncio
import logging
from collections import defaultdict
from datetime import datetime

from sqlalchemy import and_, select, insert, update, bindparam

from app import marznode
from app.db import GetDB
from app.db.models import NodeUsage, NodeUserUsage, User
from app.marznode import MarzNodeBase
from app.tasks.data_usage_percent_reached import data_usage_percent_reached
from app.utils.device_tracker import track_user_connection

logger = logging.getLogger(__name__)


def record_user_usage_logs(
    params: list, node_id: int, consumption_factor: int = 1, db=None
):
    """Record user usage logs. Accepts optional db session to avoid opening new connections."""
    if not params:
        return

    created_at = datetime.fromisoformat(
        datetime.utcnow().strftime("%Y-%m-%dT%H:00:00")
    )

    # Use provided session or create new one
    should_close = db is None
    if should_close:
        from app.db import GetDB
        ctx = GetDB()
        db = ctx.__enter__()
    
    try:
        # make user usage row if it doesn't exist
        select_stmt = select(NodeUserUsage.user_id).where(
            and_(
                NodeUserUsage.node_id == node_id,
                NodeUserUsage.created_at == created_at,
            )
        )
        existings = [r[0] for r in db.execute(select_stmt).fetchall()]
        uids_to_insert = set()

        for p in params:
            uid = p["uid"]
            if uid in existings:
                continue
            uids_to_insert.add(uid)

        if uids_to_insert:
            stmt = insert(NodeUserUsage).values(
                user_id=bindparam("uid"),
                created_at=created_at,
                node_id=node_id,
                used_traffic=0,
            )
            db.execute(stmt, [{"uid": uid} for uid in uids_to_insert])

        # record
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
        
        # Only commit if we created the session
        if should_close:
            db.commit()
    finally:
        if should_close:
            ctx.__exit__(None, None, None)


def record_node_stats(node_id: int, usage: int, db=None):
    """Record node stats. Accepts optional db session to avoid opening new connections."""
    if not usage:
        return

    created_at = datetime.fromisoformat(
        datetime.utcnow().strftime("%Y-%m-%dT%H:00:00")
    )

    # Use provided session or create new one
    should_close = db is None
    if should_close:
        from app.db import GetDB
        ctx = GetDB()
        db = ctx.__enter__()
    
    try:
        # make node usage row if doesn't exist
        select_stmt = select(NodeUsage.node_id).where(
            and_(
                NodeUsage.node_id == node_id,
                NodeUsage.created_at == created_at,
            )
        )
        notfound = db.execute(select_stmt).first() is None
        if notfound:
            stmt = insert(NodeUsage).values(
                created_at=created_at, node_id=node_id, uplink=0, downlink=0
            )
            db.execute(stmt)

        # record
        stmt = (
            update(NodeUsage)
            .values(
                downlink=NodeUsage.downlink + usage,
            )
            .where(
                and_(
                    NodeUsage.node_id == node_id,
                    NodeUsage.created_at == created_at,
                )
            )
        )

        db.execute(stmt)
        
        # Only commit if we created the session
        if should_close:
            db.commit()
    finally:
        if should_close:
            ctx.__exit__(None, None, None)


async def get_users_stats(
    node_id: int, node: MarzNodeBase
) -> tuple[int, list[dict]]:
    try:
        params = list()
        for stat in await asyncio.wait_for(node.fetch_users_stats(), 10):
            if stat.usage:
                # Store additional connection metadata for device tracking
                # uplink/downlink are preferred if available, otherwise fall back to usage
                uplink = getattr(stat, "uplink", 0)
                downlink = getattr(stat, "downlink", 0)
                
                # If uplink/downlink not provided, use usage as downlink for backwards compatibility
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
    # usage_coefficient = {None: 1}  # default usage coefficient for the main api instance

    results = await asyncio.gather(
        *[
            get_users_stats(node_id, node)
            for node_id, node in marznode.nodes.items()
        ]
    )
    api_params = {node_id: params for node_id, params in list(results)}

    users_usage = defaultdict(int)
    bucket_start = datetime.utcnow()
    
    # Use a SINGLE session for all operations to reduce connection pool pressure
    with GetDB() as db:
        # Phase 1: Track device connections and record node stats
        for node_id, params in api_params.items():
            coefficient = (
                node.usage_coefficient
                if (node := marznode.nodes.get(node_id))
                else 1
            )
            node_usage = 0
            node_connections = 0
            node_tracked = 0
            
            for param in params:
                node_connections += 1
                
                users_usage[param["uid"]] += int(
                    param["value"] * coefficient
                )  # apply the usage coefficient
                node_usage += param["value"]
                
                # Debug logging for device tracking
                logger.debug(f"[Node {node_id}] uid={param['uid']}, remote_ip={param.get('remote_ip')}, "
                           f"client={param.get('client_name')}, traffic={param['value']}")
                
                # Track device connection if we have remote_ip (no auto-commit)
                if param.get("remote_ip"):
                    try:
                        device_id, ip_id = track_user_connection(
                            db=db,
                            user_id=param["uid"],
                            node_id=node_id,
                            remote_ip=param["remote_ip"],
                            client_name=param.get("client_name"),
                            user_agent=param.get("user_agent"),
                            upload_bytes=param.get("uplink", 0),
                            download_bytes=param.get("downlink", param["value"]),
                            bucket_start=bucket_start,
                            auto_commit=False,  # Batch commit later
                        )
                        if device_id:
                            node_tracked += 1
                            logger.info(f"[Node {node_id}] ✓ Tracked device {device_id} for user {param['uid']} from IP {param['remote_ip']}")
                    except Exception as e:
                        # Don't fail the entire task if device tracking fails
                        logger.warning(f"[Node {node_id}] Failed to track device for user {param['uid']}: {e}")
            
            # Log per-node statistics
            if node_connections > 0:
                tracking_rate = (node_tracked / node_connections) * 100 if node_tracked > 0 else 0
                if node_tracked == 0:
                    logger.warning(
                        f"[Node {node_id}] Device tracking: 0/{node_connections} (0%). "
                        f"This node is NOT sending remote_ip data."
                    )
                else:
                    logger.info(
                        f"[Node {node_id}] Device tracking: {node_tracked}/{node_connections} ({tracking_rate:.1f}%)"
                    )
            
            # Record node stats using the same session (no separate commit)
            record_node_stats(node_id, node_usage, db=db)
        
        # Commit all device tracking and node stats at once
        db.commit()
        
        # Phase 2: Record user usage logs (using the same session)
        for node_id, params in api_params.items():
            record_user_usage_logs(
                params,
                node_id,
                (
                    node.usage_coefficient
                    if (node := marznode.nodes.get(node_id))
                    else 1
                ),
                db=db,  # Pass existing session
            )
        
        # Commit user usage logs
        db.commit()

    users_usage = list(
        {"id": uid, "value": value} for uid, value in users_usage.items()
    )
    if not users_usage:
        return

    # Phase 3: Update user traffic totals (separate session is fine here)
    with GetDB() as db:
        await data_usage_percent_reached(db, users_usage)

        # Check which users are about to cross the limit
        user_ids = [u["id"] for u in users_usage]
        users_map = {
            u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()
        }
        users_to_check = []

        for u_usage in users_usage:
            uid = u_usage["id"]
            user = users_map.get(uid)
            # Check if user exists, has limit, and is currently UNDER limit
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

        # Refresh and check users who were under limit
        for user in users_to_check:
            db.refresh(user)
            if user.data_limit_reached:
                marznode.operations.update_user(user)
