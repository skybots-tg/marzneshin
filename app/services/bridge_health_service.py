"""Read side of the bridge-health audit, plus the apply/queue actions.

The probing itself runs on the panel *host* (``tools/bridge_audit.py``): it
needs the node SSH keys and a spare xray process per probe, neither of which
belongs inside the API container. The two halves meet in
``/var/lib/marzneshin``, which is bind-mounted into the container:

    bridge_audit.json      the report the host runner writes
    bridge_audit.quick.json  the frequent watchdog's partial view
    bridge_audit.log       live progress of the current/last run
    bridge_audit.status    how the last run ended, and when
    bridge_state.json      the streak memory, and when a probe last decided
    bridge_audit.request   touched by the panel to ask for a scan

So the panel never shells out — it reads a report, writes a one-line request
file, and owns the only mutation that matters: flipping ``hosts.is_disabled``
so dead bridges disappear from every subscription.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import InboundHost

DATA_DIR = os.getenv("MARZ_DATA_DIR", "/var/lib/marzneshin")
REPORT_PATH = os.path.join(DATA_DIR, "bridge_audit.json")
QUICK_REPORT_PATH = os.path.join(DATA_DIR, "bridge_audit.quick.json")
LOG_PATH = os.path.join(DATA_DIR, "bridge_audit.log")
REQUEST_PATH = os.path.join(DATA_DIR, "bridge_audit.request")
STATUS_PATH = os.path.join(DATA_DIR, "bridge_audit.status")
STATE_PATH = os.path.join(DATA_DIR, "bridge_state.json")

# A run older than this is reported as stale so the page can nudge for a rescan.
STALE_AFTER_SEC = 24 * 3600
# Guard against acting on a report taken while the panel itself was offline.
# Measured against the hosts that are *visible*, because a mature fleet's report
# is mostly the graveyard: half of all probes failing is the normal state of
# affairs, while half of the visible ones failing never is.
MAX_FAIL_PCT = 30
# How long the watchdog may say nothing before the page calls it out. Hiding a
# host needs one confirmed failure and restoring it needs two clean runs, so a
# watchdog that has stopped is not neutral — it holds the fleet at its most
# hidden until somebody looks.
WATCHDOG_SILENT_SEC = 2 * 3600
# The full sweep runs daily. Missing its slot by another half cycle means it is
# not merely late, and it needs its own alarm: the quick checks keep
# ``scanned_at`` fresh, so a dead sweep leaves every timestamp the silence
# alarm reads looking perfectly healthy while the fleet's portrait ages.
FULL_SWEEP_SILENT_SEC = 36 * 3600


def _live_disabled(db: Session, host_ids: list[int]) -> dict[int, bool]:
    if not host_ids:
        return {}
    rows = (
        db.query(InboundHost.id, InboundHost.is_disabled)
        .filter(InboundHost.id.in_(host_ids))
        .all()
    )
    return {r[0]: bool(r[1]) for r in rows}


def read_report(db: Session) -> dict:
    """Return the last report reconciled against current host state.

    The report is a snapshot; ``is_disabled`` may have been changed by hand
    since. Recomputing the pending actions against live rows keeps the page
    from offering to hide something that is already hidden.
    """
    if not os.path.exists(REPORT_PATH):
        return {
            "available": False,
            "scan_running": scan_running(),
            "hint": (
                "No audit has run yet. Start one from this page, or on the "
                "panel host: cd /opt/marzneshin/tools && "
                "python3 bridge_audit.py scan --apply"
            ),
        }

    with open(REPORT_PATH, encoding="utf-8") as f:
        report = json.load(f)

    hosts = report.get("hosts", [])
    live = _live_disabled(db, [h["host_id"] for h in hosts])
    orphaned = [h["host_id"] for h in hosts if h["host_id"] not in live]
    if orphaned:
        hosts = [h for h in hosts if h["host_id"] not in orphaned]
        report["hosts"] = hosts
    for h in hosts:
        h["is_disabled"] = live[h["host_id"]]

    # Remarks currently on offer. A hidden host that shares a name with a
    # visible one was almost certainly retired on purpose (a replacement entry
    # node reuses the same remarks), and reviving it would show the same entry
    # twice in every subscription.
    visible: dict[str, list[int]] = {}
    for h in hosts:
        if not h["is_disabled"]:
            visible.setdefault(h["remark"], []).append(h["host_id"])

    # The scanner decided *what* to act on, using failure streaks and the
    # nodes' own traffic counters (see tools/bridge_state.py); a single failed
    # probe is deliberately not enough. Recomputing that here from per-host
    # verdicts would throw all of it away, so this only reconciles the saved
    # decision with rows as they stand now.
    by_id = {h["host_id"]: h for h in hosts}
    changes = report.get("changes") or {"disable": [], "enable": []}
    to_disable = [i for i in changes.get("disable", [])
                  if i in by_id and not by_id[i]["is_disabled"]]
    to_enable, shadowed = [], []
    for host_id in changes.get("enable", []):
        host = by_id.get(host_id)
        if host is None or not host["is_disabled"]:
            continue
        (shadowed if visible.get(host["remark"]) else to_enable).append(host_id)

    generated = report.get("generated_at", 0)
    failed, tested = visible_failure_rate(hosts)
    report.update({
        "available": True,
        "scan_running": scan_running(),
        "age_sec": max(0, int(time.time()) - generated),
        "stale": (int(time.time()) - generated) > STALE_AFTER_SEC,
        "pending": {"disable": to_disable, "enable": to_enable},
        "shadowed": shadowed,
        "duplicates": [{"remark": r, "host_ids": ids}
                       for r, ids in sorted(visible.items()) if len(ids) > 1],
        "apply_blocked": bool(tested) and failed * 100 // tested > MAX_FAIL_PCT,
        "visible_failed": failed,
        "visible_tested": tested,
        "removed_since_scan": orphaned,
        "quick": read_quick(),
        "watchdog": read_watchdog(),
    })
    return report


def visible_failure_rate(hosts: list[dict]) -> tuple[int, int]:
    """Failures among hosts users can currently see, and how many those are.

    Counting the whole report instead is what made the old guard useless: the
    hidden half fails by definition and grows over time, so the ratio drifted
    towards its own threshold while telling nobody anything about the fleet.
    """
    live = [h for h in hosts if not h.get("is_disabled")]
    return sum(1 for h in live if h.get("verdict") == "fail"), len(live)


def read_watchdog() -> dict:
    """Whether the thing that hides and restores hosts is actually running.

    Worth its own block on the page, because its failure does not look like a
    failure: the last report stays on screen, the numbers stay plausible, and
    the only visible symptom is that hosts which recovered never come back.
    """
    out: dict = {"silent": False, "last_rc": None, "last_kind": None}
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            status = json.load(f)
        out["last_rc"] = status.get("rc")
        out["last_kind"] = status.get("kind")
        out["finished_at"] = status.get("finished_at")
    except (FileNotFoundError, ValueError):
        pass
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, ValueError):
        return out
    decided = int(state.get("scanned_at") or state.get("updated_at") or 0)
    if decided:
        age = max(0, int(time.time()) - decided)
        out["decided_at"] = decided
        out["decided_age_sec"] = age
        out["silent"] = age > WATCHDOG_SILENT_SEC
    out["auto_hidden"] = len(state.get("auto_disabled") or {})
    return out


def read_quick() -> Optional[dict]:
    """Summary of the last quick watchdog run, if one has happened.

    The full report is the fleet's portrait and is redrawn once a day; the
    quick run probes one host per link every few minutes and is what actually
    catches a leg going down between sweeps. Surfacing its age and its actions
    is what stops the page from looking a day out of date when it is not.
    """
    try:
        with open(QUICK_REPORT_PATH, encoding="utf-8") as f:
            quick = json.load(f)
    except (FileNotFoundError, ValueError):
        return None
    generated = quick.get("generated_at", 0)
    changes = quick.get("changes") or {}
    return {
        "generated_at": generated,
        "age_sec": max(0, int(time.time()) - generated),
        "counts": quick.get("counts", {}),
        "links": len(quick.get("links") or []),
        "disabled": changes.get("disable", []),
        "enabled": changes.get("enable", []),
    }


def apply_pending(
    db: Session,
    disable_ids: Optional[list[int]] = None,
    enable_ids: Optional[list[int]] = None,
    force: bool = False,
) -> dict:
    """Hide dead hosts / restore recovered ones.

    Without explicit ids this applies everything the last report suggests.
    The mass-failure guard exists because a panel-side network blip makes
    *every* probe fail, and blindly applying that would empty every
    subscription at once.
    """
    report = read_report(db)
    if not report.get("available"):
        return {"error": "no report available"}
    if report["apply_blocked"] and not force:
        return {
            "error": (
                f"{report['visible_failed']} of {report['visible_tested']} "
                f"visible host(s) failed (>{MAX_FAIL_PCT}%). That normally "
                f"means the panel host lost egress during the scan, not that "
                f"the whole fleet died. Re-scan, or apply with force=true if "
                f"the outage is real."
            )
        }

    pending = report["pending"]
    disable_ids = pending["disable"] if disable_ids is None else disable_ids
    enable_ids = pending["enable"] if enable_ids is None else enable_ids
    # Never act on a host the report did not actually cover.
    known = {h["host_id"] for h in report["hosts"]}
    disable_ids = [i for i in disable_ids if i in known]
    enable_ids = [i for i in enable_ids if i in known]

    changed = 0
    for ids, value in ((disable_ids, True), (enable_ids, False)):
        if not ids:
            continue
        changed += (
            db.query(InboundHost)
            .filter(InboundHost.id.in_(ids))
            .update({InboundHost.is_disabled: value}, synchronize_session=False)
        )
    db.commit()
    return {"disabled": disable_ids, "enabled": enable_ids, "changed": changed}


def scan_running() -> bool:
    """A request file that the host runner has not consumed yet, or a live run."""
    if os.path.exists(REQUEST_PATH):
        return True
    if not os.path.exists(LOG_PATH):
        return False
    return (time.time() - os.path.getmtime(LOG_PATH)) < 30


def request_scan(tier: str = "universal", apply_fixes: bool = False) -> dict:
    """Ask the host runner for a scan by dropping a request file.

    The runner polls this path; the panel gets no direct shell access to the
    host on purpose.
    """
    if scan_running():
        return {"queued": False, "reason": "a scan is already in progress"}
    os.makedirs(DATA_DIR, exist_ok=True)
    payload = {"tier": tier, "apply": bool(apply_fixes),
               "requested_at": int(time.time())}
    tmp = REQUEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, REQUEST_PATH)
    return {"queued": True, **payload}


def read_log(tail_lines: int = 200) -> dict:
    if not os.path.exists(LOG_PATH):
        return {"running": scan_running(), "lines": []}
    with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    return {
        "running": scan_running(),
        "updated_at": int(os.path.getmtime(LOG_PATH)),
        "lines": lines[-tail_lines:],
    }
