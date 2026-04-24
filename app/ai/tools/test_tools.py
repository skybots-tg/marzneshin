"""Connectivity / diagnostic tools for the AI agent.

Three tools are exposed:

- `test_host_reachability` — plain TCP handshake from the panel to any
  `address:port`. Fast sanity check that rules out "node DNS doesn't
  resolve / port is firewalled at the network layer" before reaching
  for SSH.
- `test_node_xray` — SSH-backed focused check of the node's Xray
  process, listening ports, binary and recent logs. Bundles what would
  otherwise be 4–5 separate `ssh_run_command` calls into one and
  returns a single structured report.
- `diagnose_node_issue` — the loop-breaker. Combines panel-side
  signals (gRPC status, TCP reachability, traffic baseline) with the
  optional SSH probe and synthesizes a verdict with a confidence
  level. The agent is instructed (in the system prompt) to STOP and
  report the verdict rather than keep retrying once this tool returns
  `LIKELY_DPI` or `INCONCLUSIVE`.

All three are read-only and therefore do NOT require confirmation.
SSH-dependent logic here gracefully degrades when SSH is not unlocked
— it annotates the report with `ssh_available=false` and moves on.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.session_context import get_current_session_id
from app.ai.ssh_runner import decrypt_node_credentials, run_command_with_creds
from app.ai.ssh_session import get_unlocked_pin, is_session_unlocked
from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


# =============================================================================
# Public tools
# =============================================================================


@register_tool(
    name="test_host_reachability",
    description=(
        "Attempt a plain TCP handshake from the panel to `address:port`. "
        "Returns `reachable` (bool), `error_code` ('timeout' | 'refused' | "
        "'dns' | 'other' when not reachable), elapsed_ms. "
        "Use this to cheaply rule out network-layer blocks before digging "
        "into Xray logs. Default timeout 5s (max 15s). Takes a raw address "
        "(hostname or IP) so you can test arbitrary endpoints, not just "
        "registered nodes — e.g. 'www.google.com:443' from a node's outbound, "
        "or a host entry address:port from the panel's outbound."
    ),
    requires_confirmation=False,
)
async def test_host_reachability(
    db: Session, address: str, port: int, timeout_sec: int = 5
) -> dict:
    db.close()
    if not address or not address.strip():
        return {"error": "address must not be empty"}
    if port <= 0 or port > 65535:
        return {"error": f"Port out of range: {port}"}

    timeout_sec = max(1, min(int(timeout_sec or 5), 15))
    return await _tcp_probe(address.strip(), int(port), timeout_sec)


@register_tool(
    name="test_node_xray",
    description=(
        "SSH-backed focused check of a node's Xray backend. "
        "Requires SSH to be unlocked for this chat session (see ssh_check_access); "
        "degrades gracefully if not — returns a minimal report with "
        "`ssh_available=false` so you can still reason without ssh. "
        "When ssh is available it collects, in one connection: "
        "(1) `xray -version` from `/usr/local/bin/xray`, "
        "(2) whether the xray process is running (`pidof xray`), "
        "(3) its listening TCP ports (`ss -H -ltn`), "
        "(4) the last marznode log slice filtered for errors. "
        "Returns a structured report; the agent should NOT re-run the same "
        "commands via ssh_run_command after calling this."
    ),
    requires_confirmation=False,
)
async def test_node_xray(db: Session, node_id: int) -> dict:
    from app.db import crud

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}

    node_address = node.address
    node_name = node.name

    creds = _maybe_load_ssh_creds(db, node_id)
    if creds is None:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "ssh_available": False,
            "reason": (
                "SSH is not unlocked or credentials are missing for this node. "
                "Call ssh_check_access to see what's missing."
            ),
        }

    return await asyncio.to_thread(_run_xray_probe, node_address, creds, node_id, node_name)


@register_tool(
    name="diagnose_node_issue",
    description=(
        "Top-level diagnostic that distinguishes a real node problem from "
        "likely external interference (DPI / ISP-level blocking). "
        "Combines panel-side signals (gRPC connection, TCP reachability from "
        "panel to node) with a traffic baseline (compares traffic over the "
        "last `window_hours` hours to the same window one day earlier and to "
        "other healthy nodes) and — when SSH is unlocked — the output of "
        "`test_node_xray`. "
        "Returns a structured report with a `verdict` field: "
        "'NODE_UNREACHABLE' (panel cannot even TCP-connect to gRPC port), "
        "'NODE_DISCONNECTED' (panel was connected but gRPC dropped — fix "
        "with `enable_node` first, SSH only as fallback), "
        "'PANEL_REGISTRY_DESYNC' (TCP works AND DB says healthy AND UI shows "
        "healthy, but THIS panel worker has no in-memory client — almost "
        "always multi-worker UVICORN_WORKERS>1; fix with `enable_node`, "
        "NEVER SSH), "
        "'XRAY_DOWN' (ssh shows xray process missing), "
        "'CONFIG_ERROR' (xray logs show parse/listen errors), "
        "'LIKELY_DPI' (everything on the node is healthy but traffic has "
        "collapsed relative to baseline), 'INCONCLUSIVE' (not enough signal), "
        "or 'HEALTHY' (no anomalies detected). "
        "CRITICAL: once this tool returns LIKELY_DPI or INCONCLUSIVE, STOP — "
        "do not loop on more ssh_run_command attempts hoping to 'fix' it. "
        "Report the verdict and signals to the admin; the issue is infra-level "
        "(DPI/ISP) or genuinely unprovable remotely."
    ),
    requires_confirmation=False,
)
async def diagnose_node_issue(
    db: Session, node_id: int, window_hours: int = 2
) -> dict:
    from app.db import crud
    from app.db.models import Node, NodeUsage
    from app.marznode import node_registry
    from app.models.node import NodeStatus
    from sqlalchemy import func

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}

    node_name = node.name
    node_address = node.address
    node_port = node.port
    panel_status = str(node.status)
    last_status_change = (
        str(node.last_status_change) if node.last_status_change else None
    )

    panel_grpc_connected = node_registry.get(node_id) is not None

    window_hours = max(1, min(int(window_hours or 2), 24))
    now = datetime.utcnow()
    window_start = now - timedelta(hours=window_hours)
    prev_start = window_start - timedelta(hours=24)
    prev_end = now - timedelta(hours=24)

    this_window_traffic = int(
        db.query(
            func.coalesce(
                func.sum(NodeUsage.uplink + NodeUsage.downlink), 0
            )
        )
        .filter(
            NodeUsage.node_id == node_id,
            NodeUsage.created_at >= window_start,
        )
        .scalar()
        or 0
    )
    yesterday_window_traffic = int(
        db.query(
            func.coalesce(
                func.sum(NodeUsage.uplink + NodeUsage.downlink), 0
            )
        )
        .filter(
            NodeUsage.node_id == node_id,
            NodeUsage.created_at >= prev_start,
            NodeUsage.created_at < prev_end,
        )
        .scalar()
        or 0
    )

    other_healthy_ids = [
        row[0]
        for row in db.query(Node.id)
        .filter(Node.id != node_id, Node.status == NodeStatus.healthy)
        .all()
    ]
    other_traffic_rows = []
    if other_healthy_ids:
        other_traffic_rows = (
            db.query(
                NodeUsage.node_id,
                func.coalesce(
                    func.sum(NodeUsage.uplink + NodeUsage.downlink), 0
                ),
            )
            .filter(
                NodeUsage.node_id.in_(other_healthy_ids),
                NodeUsage.created_at >= window_start,
            )
            .group_by(NodeUsage.node_id)
            .all()
        )
    other_traffic_values = [int(t or 0) for _, t in other_traffic_rows]
    other_traffic_median = _median(other_traffic_values)

    inbounds_count = len([i for i in (node.inbounds or [])])

    db.close()

    reachability = await _tcp_probe(node_address, int(node_port), timeout_sec=5)

    ssh_report: Optional[dict] = None
    creds = _maybe_load_ssh_creds_fresh(node_id)
    if creds is not None:
        ssh_report = await asyncio.to_thread(
            _run_xray_probe, node_address, creds, node_id, node_name
        )

    signals = {
        "panel_status": panel_status,
        "panel_grpc_connected": panel_grpc_connected,
        "last_status_change": last_status_change,
        "panel_to_node_tcp": reachability,
        "inbounds_count": inbounds_count,
        "traffic_window_hours": window_hours,
        "traffic_this_window_bytes": this_window_traffic,
        "traffic_same_window_24h_ago_bytes": yesterday_window_traffic,
        "traffic_drop_ratio_vs_yesterday": _ratio(this_window_traffic, yesterday_window_traffic),
        "other_healthy_nodes_traffic_median_bytes": other_traffic_median,
        "traffic_ratio_vs_peers": _ratio(this_window_traffic, other_traffic_median),
        "ssh_available": ssh_report is not None and ssh_report.get("ssh_available"),
        "ssh_report": ssh_report,
    }

    verdict, confidence, recommendation = _synthesize_verdict(panel_status, signals)

    return {
        "node_id": node_id,
        "node_name": node_name,
        "verdict": verdict,
        "confidence": confidence,
        "recommendation": recommendation,
        "signals": signals,
    }


# =============================================================================
# Helpers
# =============================================================================


async def _tcp_probe(address: str, port: int, timeout_sec: int) -> dict:
    """Open a raw TCP connection to (address, port), close immediately."""
    import time

    started = time.monotonic()
    try:
        fut = asyncio.open_connection(address, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout_sec)
    except asyncio.TimeoutError:
        return {
            "reachable": False,
            "error_code": "timeout",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "address": address,
            "port": port,
        }
    except ConnectionRefusedError:
        return {
            "reachable": False,
            "error_code": "refused",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "address": address,
            "port": port,
        }
    except OSError as exc:
        code = "dns" if "name" in str(exc).lower() or "resolve" in str(exc).lower() else "other"
        return {
            "reachable": False,
            "error_code": code,
            "error": str(exc),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "address": address,
            "port": port,
        }

    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return {
        "reachable": True,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "address": address,
        "port": port,
    }


def _maybe_load_ssh_creds(db: Session, node_id: int) -> Optional[dict]:
    """Load + decrypt SSH creds for this node in the current chat session."""
    from app.db import crud

    session_id = get_current_session_id()
    if not session_id or not is_session_unlocked(session_id):
        return None
    pin = get_unlocked_pin(session_id)
    if not pin:
        return None
    creds_row = crud.get_ssh_credentials(db, node_id)
    if not creds_row:
        return None
    try:
        return decrypt_node_credentials(creds_row, pin)
    except PermissionError:
        return None


def _maybe_load_ssh_creds_fresh(node_id: int) -> Optional[dict]:
    """Same as `_maybe_load_ssh_creds` but opens its own DB session."""
    from app.db import GetDB

    with GetDB() as db:
        return _maybe_load_ssh_creds(db, node_id)


# Probe script: stays under ~64KiB output, one SSH connection, bounded output.
_XRAY_PROBE_SCRIPT = r"""set +e
echo '### xray_version'
if [ -x /usr/local/bin/xray ]; then
  /usr/local/bin/xray -version 2>&1 | head -n 3
else
  echo 'MISSING'
fi
echo '### xray_pid'
pidof xray || echo 'NONE'
echo '### listen'
ss -H -ltn 2>/dev/null | head -n 40
echo '### errors'
if command -v journalctl >/dev/null 2>&1; then
  journalctl -u marznode --since '30 min ago' --no-pager 2>/dev/null \
    | grep -iE 'panic|error|failed|denied' | tail -n 30
else
  echo 'no-journalctl'
fi
echo '### docker'
if command -v docker >/dev/null 2>&1; then
  docker ps --filter name=marznode --format '{{.Names}} {{.Status}}' | head -n 5
else
  echo 'no-docker'
fi
echo '### end'
"""


def _run_xray_probe(
    host: str, creds: dict, node_id: int, node_name: str
) -> dict:
    """Execute the bundled probe script and parse sections."""
    try:
        result = run_command_with_creds(
            host=host, creds=creds, command=_XRAY_PROBE_SCRIPT, timeout=30
        )
    except PermissionError as exc:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "ssh_available": False,
            "reason": f"SSH auth failed: {exc}",
        }
    except TimeoutError:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "ssh_available": True,
            "timeout": True,
            "reason": "Probe exceeded 30s timeout",
        }
    except Exception as exc:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "ssh_available": False,
            "reason": f"SSH probe failed: {exc}",
        }

    sections = _split_probe_output(result.stdout)

    xray_version_raw = (sections.get("xray_version") or "").strip()
    xray_binary_present = xray_version_raw not in ("", "MISSING")
    xray_pid_raw = (sections.get("xray_pid") or "").strip()
    xray_process_running = xray_pid_raw not in ("", "NONE")

    listen_lines = [
        line.strip() for line in (sections.get("listen") or "").splitlines() if line.strip()
    ]
    listening_ports = _extract_listening_ports(listen_lines)

    error_lines = [
        line.strip()
        for line in (sections.get("errors") or "").splitlines()
        if line.strip() and line.strip() != "no-journalctl"
    ]

    docker_lines = [
        line.strip()
        for line in (sections.get("docker") or "").splitlines()
        if line.strip() and line.strip() != "no-docker"
    ]

    return {
        "node_id": node_id,
        "node_name": node_name,
        "ssh_available": True,
        "exit_code": result.exit_code,
        "xray_binary_present": xray_binary_present,
        "xray_version": xray_version_raw if xray_binary_present else None,
        "xray_process_running": xray_process_running,
        "xray_pids": xray_pid_raw if xray_process_running else None,
        "listening_ports": listening_ports,
        "listening_lines_sample": listen_lines[:10],
        "recent_error_lines": error_lines[:15],
        "recent_error_count": len(error_lines),
        "docker_marznode": docker_lines,
        "truncated": result.truncated,
    }


def _split_probe_output(stdout: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = None
    buffer: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("### "):
            if current is not None:
                sections[current] = "\n".join(buffer)
            current = line[4:].strip()
            buffer = []
        else:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer)
    return sections


_LISTEN_PORT_RE = re.compile(r":(\d+)\s")


def _extract_listening_ports(lines: list[str]) -> list[int]:
    ports: set[int] = set()
    for line in lines:
        # ss output: "LISTEN  0  128  0.0.0.0:443  0.0.0.0:*"
        parts = line.split()
        for p in parts:
            if ":" in p:
                tail = p.rsplit(":", 1)[-1]
                if tail.isdigit():
                    ports.add(int(tail))
                    break
    return sorted(ports)


def _median(values: list[int]) -> int:
    if not values:
        return 0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return int(sorted_vals[mid])
    return int((sorted_vals[mid - 1] + sorted_vals[mid]) / 2)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _synthesize_verdict(
    panel_status: str, signals: dict
) -> tuple[str, str, str]:
    """Return (verdict, confidence, recommendation).

    Logic is a simple decision cascade, not ML — we fall through to the
    first matching rule.
    """
    tcp = signals.get("panel_to_node_tcp") or {}
    panel_grpc_connected = signals.get("panel_grpc_connected", False)
    ssh_report = signals.get("ssh_report") or {}
    ssh_available = bool(signals.get("ssh_available"))

    if not tcp.get("reachable") and not panel_grpc_connected:
        code = tcp.get("error_code")
        return (
            "NODE_UNREACHABLE",
            "high",
            (
                f"Panel cannot TCP-connect to {tcp.get('address')}:{tcp.get('port')} "
                f"(error={code}). Check the node host is up, its firewall allows "
                "inbound on the gRPC port, and DNS resolves."
            ),
        )

    if tcp.get("reachable") and not panel_grpc_connected:
        # The panel's in-memory NodeRegistry has no client for this node,
        # but the gRPC port is reachable. This is almost ALWAYS a panel-
        # side state issue, not a marznode crash:
        #
        #   * Right after panel startup before nodes_startup finished
        #     reconciling this row;
        #   * After a transient `disable_node` → `enable_node` round-trip
        #     left the registry empty in this worker;
        #   * Multi-worker deploy (UVICORN_WORKERS > 1): each worker has
        #     its OWN NodeRegistry singleton (Python module-level dict);
        #     the AI request landed on a worker that doesn't have a
        #     client for this node, while the worker that handles UI
        #     requests does (so DB shows healthy and UI shows healthy).
        #
        # The deterministic, no-SSH fix is `enable_node(node_id)`. Only
        # if THAT does not bring the node back is SSH justified.
        if panel_status == "healthy":
            return (
                "PANEL_REGISTRY_DESYNC",
                "high",
                (
                    "DB status is `healthy` (UI agrees) but THIS panel "
                    "worker has no in-memory gRPC client for the node — "
                    "the registry and the DB disagree. Almost always "
                    "means the panel is running multi-worker "
                    "(UVICORN_WORKERS > 1) and you hit a worker whose "
                    "NodeRegistry is missing this row, while another "
                    "worker holds it. Marznode itself is fine — TCP to "
                    "the gRPC port works and DB status came from a "
                    "successful sync done by the other worker. "
                    "Fix in this order, NO SSH needed: "
                    "(1) `enable_node(node_id)` — re-instantiates the "
                    "gRPC client on the worker handling this request "
                    "(may have to be retried a few times to hit each "
                    "worker, since each call lands on whichever worker "
                    "the load balancer picks). "
                    "(2) If `enable_node` does not stick across calls, "
                    "ask the admin to set `UVICORN_WORKERS=1` (the "
                    "panel's NodeRegistry is in-process and not "
                    "designed to be shared across workers) and restart "
                    "the panel container. "
                    "Do NOT propose SSH for this verdict — the node "
                    "isn't broken."
                ),
            )
        return (
            "NODE_DISCONNECTED",
            "high",
            (
                "gRPC port is reachable but THIS panel worker's "
                "NodeRegistry has no client for the node, and DB "
                "status is not `healthy` either. "
                "Fix in this order: "
                "(1) `enable_node(node_id)` FIRST — this is the "
                "panel-side, no-SSH fix that re-instantiates the gRPC "
                "client with the current cert/key. Wait ~15 s, then "
                "re-check `get_node_info` and `get_node_recent_errors`. "
                "It resolves the common 'panel didn't fully reload "
                "this node after restart / a previous "
                "disable→enable cycle' case. "
                "(2) Only if `enable_node` does NOT bring the node up "
                "(`get_node_recent_errors` then shows real `kind=sync` "
                "/ `kind=ssl` failures, not `node_not_loaded`), THEN "
                "SSH is justified — call `test_node_xray` to look at "
                "marznode/xray on the host. "
                "Do NOT ask the admin to unlock SSH before trying "
                "`enable_node`."
            ),
        )

    if ssh_available and ssh_report:
        if not ssh_report.get("xray_binary_present"):
            return (
                "CONFIG_ERROR",
                "high",
                (
                    "Xray binary is missing at /usr/local/bin/xray on the node. "
                    "Re-run the xray installer on this node."
                ),
            )
        if not ssh_report.get("xray_process_running"):
            return (
                "XRAY_DOWN",
                "high",
                (
                    "Xray process is not running. Check recent_error_lines in the "
                    "ssh_report — restart via update_node_config or "
                    "restart_node_backend once the cause is fixed."
                ),
            )
        if ssh_report.get("recent_error_count", 0) >= 5:
            return (
                "CONFIG_ERROR",
                "medium",
                (
                    "Xray is running but marznode logs show repeated errors. "
                    "Inspect ssh_report.recent_error_lines; the usual culprits are "
                    "port conflicts, bad Reality keys, or missing certs."
                ),
            )

    drop = signals.get("traffic_drop_ratio_vs_yesterday")
    peers = signals.get("traffic_ratio_vs_peers")
    healthy_on_node = (
        panel_grpc_connected
        and panel_status == "healthy"
        and (not ssh_available or (
            ssh_report.get("xray_process_running")
            and ssh_report.get("xray_binary_present")
        ))
    )

    if healthy_on_node and drop is not None and drop < 0.1:
        conf = "high" if (peers is not None and peers < 0.2) else "medium"
        return (
            "LIKELY_DPI",
            conf,
            (
                "The node looks healthy (panel connected, Xray running, no "
                "recent errors) yet traffic has collapsed to <10% of the "
                "same window yesterday. This is the signature of upstream "
                "DPI/ISP-level blocking — it cannot be fixed server-side. "
                "Possible responses: (a) rotate the Reality/TLS SNI to a "
                "different fronting domain, (b) switch that inbound's "
                "protocol (e.g. VLESS+Reality → Hysteria2), (c) change the "
                "node's listening port, (d) tell users to switch to another "
                "node. STOP diagnosing further — more ssh commands will not "
                "reveal anything new."
            ),
        )

    if not healthy_on_node:
        return (
            "INCONCLUSIVE",
            "low",
            (
                "Node is not fully healthy but we don't have enough signal "
                "to pin down the cause. Ask the admin to unlock SSH "
                "(ssh_check_access) so the next diagnose_node_issue call "
                "includes an xray probe, or check get_node_logs / "
                "get_node_info manually."
            ),
        )

    if drop is None and peers is None:
        return (
            "INCONCLUSIVE",
            "low",
            (
                "No traffic baseline available yet (new node or no prior "
                "usage rows). Wait for at least one previous 24h window "
                "before drawing conclusions, or compare against another "
                "node manually."
            ),
        )

    return (
        "HEALTHY",
        "medium",
        (
            "No anomalies detected on the node side. If users still report "
            "issues, the problem is likely client-side (wrong subscription "
            "URL, outdated app, local network) — ask them to reimport their "
            "subscription and try a different network."
        ),
    )
