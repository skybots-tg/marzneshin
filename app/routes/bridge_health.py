"""Bridge health dashboard: which entry->exit routes actually carry traffic.

The audit itself runs on the panel host (``tools/bridge_audit.py``) because it
probes from RU vantage nodes over SSH. These endpoints expose its report and
the one action that matters operationally: hiding hosts that carry no traffic
so they stop appearing in subscriptions, and restoring the ones that recover.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.dependencies import DBDep, SudoAdminDep
from app.services import bridge_health_service as svc

router = APIRouter(prefix="/bridge-health", tags=["Bridge Health"])


class ApplyBody(BaseModel):
    disable_ids: list[int] | None = None
    enable_ids: list[int] | None = None
    force: bool = False


class ScanBody(BaseModel):
    tier: str = "universal"
    apply_fixes: bool = False


@router.get("")
def get_bridge_health(db: DBDep, admin: SudoAdminDep) -> dict:
    """Last audit report, reconciled against current host state."""
    return svc.read_report(db)


@router.post("/apply")
def apply_bridge_health(body: ApplyBody, db: DBDep, admin: SudoAdminDep) -> dict:
    """Hide dead hosts and restore recovered ones.

    With no ids, applies everything the last report suggests.
    """
    return svc.apply_pending(
        db,
        disable_ids=body.disable_ids,
        enable_ids=body.enable_ids,
        force=body.force,
    )


@router.post("/scan")
def start_bridge_scan(body: ScanBody, admin: SudoAdminDep) -> dict:
    """Queue a fresh audit for the host runner to pick up."""
    return svc.request_scan(tier=body.tier, apply_fixes=body.apply_fixes)


@router.get("/log")
def get_bridge_scan_log(admin: SudoAdminDep, tail: int = 200) -> dict:
    """Progress of the running (or last) audit."""
    return svc.read_log(tail_lines=tail)
