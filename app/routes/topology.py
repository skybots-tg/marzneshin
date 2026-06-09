"""Fleet topology dashboard + guided multi-tier operations.

Endpoints (all sudo-admin only):

- ``GET  /api/topology`` — structured UNIVERSAL/ELITE/FAST × exit-country
  matrix used by the dashboard overview and to drive the wizards.
- ``POST /api/topology/promote-universal`` — SSE stream that turns an
  unclassified node into a full UNIVERSAL/ELITE entry by cloning an
  existing entry node end-to-end. Thin wrapper over the proven
  ``onboard_node_from_donor`` orchestration tool (gRPC config clone +
  reality-key rotation + service propagation + host clone + user resync
  + e2e gate).
- ``POST /api/topology/plan-exit-country`` — read-only planner for adding
  a new exit country across the fleet. Reads the exit node's reality
  listener parameters over gRPC and reports exactly which entry nodes
  would receive a new ``RU->XX`` bridge, plus the verified CLI command
  to apply it (the apply path stays in ``tools/add_exit_country.py``
  because, unlike gRPC ``restart_backend``, it gates every change behind
  ``xray -test`` before swapping the live config).
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from app.dependencies import DBDep, SudoAdminDep
from app.services.topology_service import build_topology, flag_to_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/topology", tags=["Topology"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("")
def get_topology(db: DBDep, admin: SudoAdminDep) -> dict:
    """Return the UNIVERSAL/ELITE/FAST × exit-country matrix."""
    return build_topology(db)


# =============================================================================
# Promote a node to a UNIVERSAL / ELITE entry (full orchestration via SSE)
# =============================================================================


class PromoteBody(BaseModel):
    donor_node_id: int
    target_node_id: int
    regenerate_reality_keys: bool = True
    clone_hosts: bool = True
    host_address_override: str = ""
    host_remark_pattern: str = ""
    sample_username: str = ""


@router.post("/promote-universal")
async def promote_universal(
    body: PromoteBody, admin: SudoAdminDep
) -> StreamingResponse:
    """Clone a donor entry node onto the target, streaming progress as SSE.

    Reuses ``onboard_node_from_donor`` so the panel runs the exact same,
    battle-tested sequence the AI assistant uses.
    """

    async def gen():
        from app.ai.tools.node_provision_tools import onboard_node_from_donor
        from app.db import GetDB

        if body.donor_node_id == body.target_node_id:
            yield _sse("error", {"message": "donor and target must differ"})
            yield _sse("complete", {"success": False})
            return

        yield _sse("log", {
            "message": (
                f"Promoting node {body.target_node_id} by cloning donor "
                f"node {body.donor_node_id}..."
            )
        })
        yield _sse("log", {
            "message": (
                "Steps: clone xray config → rotate reality keys → "
                "propagate services → clone hosts → resync users → "
                "e2e gate."
            )
        })

        try:
            with GetDB() as db:
                result = await onboard_node_from_donor(
                    db=db,
                    donor_node_id=body.donor_node_id,
                    target_node_id=body.target_node_id,
                    sample_username=body.sample_username,
                    regenerate_reality_keys=body.regenerate_reality_keys,
                    clone_hosts=body.clone_hosts,
                    host_address_override=body.host_address_override,
                    host_remark_pattern=body.host_remark_pattern,
                    open_firewall=False,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("promote_universal failed")
            yield _sse("error", {"message": f"orchestration crashed: {exc}"})
            yield _sse("complete", {"success": False})
            return

        if result.get("error"):
            yield _sse("error", {"message": result["error"]})
            yield _sse("complete", {"success": False})
            return

        steps = result.get("steps") or []
        for s in steps:
            ok = s.get("ok", True)
            name = s.get("name", "step")
            detail = {k: v for k, v in s.items() if k not in ("name", "ok")}
            yield _sse("step", {
                "name": name,
                "ok": ok,
                "detail": detail,
            })
            await asyncio.sleep(0)  # flush

        success = bool(result.get("success"))
        yield _sse("complete", {
            "success": success,
            "failed_step": result.get("failed_step"),
        })

    return StreamingResponse(gen(), media_type="text/event-stream")


# =============================================================================
# Plan adding a new exit country across the fleet (read-only)
# =============================================================================


class PlanExitBody(BaseModel):
    exit_node_id: int = Field(..., description="node that hosts the exit reality listener")
    flag_iso: str = Field("", description="ISO2 for the flag, e.g. RO (optional, derived if empty)")
    label: str = Field("", description="short exit label, e.g. RO")
    include_universal: bool = True
    include_elite: bool = True


@router.post("/plan-exit-country")
async def plan_exit_country(
    body: PlanExitBody, db: DBDep, admin: SudoAdminDep
) -> dict:
    """Compute (read-only) the plan to add an exit country to the fleet.

    Reads the exit node's live xray config over gRPC to locate a reality
    listener (the egress endpoint bridges will target) and lists every
    entry node that would receive a new ``RU->XX`` bridge.
    """
    from app.db import crud
    from app.marznode import node_registry

    exit_node = crud.get_node_by_id(db, body.exit_node_id)
    if not exit_node:
        return {"error": f"Exit node {body.exit_node_id} not found"}

    topo = build_topology(db)
    iso = (body.flag_iso or body.label or "").upper()[:2]

    # locate reality listener on the exit node (over gRPC)
    listeners: list[dict] = []
    reg = node_registry.get(body.exit_node_id)
    grpc_ok = reg is not None
    if grpc_ok:
        try:
            cfg_str, cfg_fmt = await reg.get_backend_config(name="xray")
            if int(cfg_fmt) == 1:
                cfg = json.loads(cfg_str)
                for ib in cfg.get("inbounds", []):
                    ss = (ib.get("streamSettings") or {})
                    if (ss.get("security") == "reality"
                            and (ss.get("network") in ("tcp", None))):
                        rs = ss.get("realitySettings") or {}
                        listeners.append({
                            "tag": ib.get("tag"),
                            "port": ib.get("port"),
                            "serverNames": rs.get("serverNames")
                            or ([rs["dest"].split(":")[0]]
                                if rs.get("dest") else []),
                            "shortIds": rs.get("shortIds") or [],
                        })
        except Exception as exc:  # noqa: BLE001
            logger.warning("plan_exit_country: gRPC read failed: %s", exc)
            grpc_ok = False

    targets = [
        e for e in topo["entries"]
        if (e["tier"] == "universal" and body.include_universal)
        or (e["tier"] == "elite" and body.include_elite)
    ]
    already = [e for e in targets if iso and iso in e["exit_isos"]]
    pending = [e for e in targets if not (iso and iso in e["exit_isos"])]

    cli = (
        f"# on the panel host, in tools/:\n"
        f"python3 add_exit_country.py {iso or '<ISO>'} --apply"
    )

    return {
        "exit_node": {
            "node_id": exit_node.id,
            "name": exit_node.name,
            "address": exit_node.address,
            "status": str(getattr(exit_node.status, "value", exit_node.status)),
        },
        "iso": iso,
        "exit_already_in_fleet": iso in topo["exit_countries"] if iso else False,
        "grpc_reachable": grpc_ok,
        "reality_listeners": listeners,
        "targets_total": len(targets),
        "already_have": [e["key"] for e in already],
        "pending": [
            {"key": e["key"], "node_id": e["node_id"], "name": e["name"]}
            for e in pending
        ],
        "apply_command": cli,
        "note": (
            "Apply runs from the panel-host CLI (tools/add_exit_country.py): "
            "it gates every node change behind `xray -test` before swapping "
            "the live config — a safety step gRPC restart_backend does not "
            "provide. Register the new country in COUNTRIES first."
        ),
    }
