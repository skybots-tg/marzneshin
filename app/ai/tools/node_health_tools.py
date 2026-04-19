"""AI tools for the post-incident node-health checks.

The trio here exists because previous diagnostics had blind spots that
let real outages masquerade as the cosmetic
``AttributeError: '_write_appdata'`` for hours:

- `get_node_recent_errors` — read the in-memory ring buffer the
  `MarzNodeGRPCLIB` client now keeps for every node so the agent can
  see *why* a node is detached without grepping the panel's container
  logs (which it cannot reach from inside its own process).

- `verify_panel_certificate` — SSH onto the node, hash
  ``/var/lib/marznode/client.pem``, compare with the panel's current
  TLS cert (DB row). A mismatch is the textbook cause of a successful
  TLS handshake followed by an instant ``StreamTerminatedError`` with
  no log line on either side — exactly the shape of the outage we
  spent hours chasing on node 31.

- `xray_traffic_health` — SSH onto the node, parse the last
  ``window_minutes`` of ``/var/log/xray/access.log``. A high
  ``rejected`` ratio with mostly ``invalid request user id`` reasons
  means xray is *up* but doesn't know the user set — usually because
  the panel's ``RepopulateUsers`` call timed out (SQL timeout) or the
  marznode service ate it without restarting xray.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.session_context import get_current_session_id
from app.ai.ssh_runner import (
    decrypt_node_credentials,
    run_command_with_creds,
)
from app.ai.ssh_session import get_unlocked_pin, is_session_unlocked
from app.ai.tool_registry import register_tool
from app.ai.tools._common import canonical_panel_cert_bytes

logger = logging.getLogger(__name__)


# =============================================================================
# 1. Recent errors — no SSH needed, reads in-memory buffer of MarzNodeGRPCLIB
# =============================================================================


@register_tool(
    name="get_node_recent_errors",
    description=(
        "Return the most recent sync/connect/restart errors recorded by "
        "the panel's in-memory client for this node. This is the FIRST "
        "tool to call when a node is unhealthy — it tells you exactly "
        "what is failing on the panel-to-node channel without needing "
        "SSH or container log access. "
        "Each entry has `kind` (one of: 'sync', 'connect', 'ssl', "
        "'network', 'restart', 'resync'), `message` (short error "
        "string), and `seconds_ago` (how recent). "
        "Common patterns: \n"
        "  * `kind='sync'` with 'StreamTerminatedError' — node killed "
        "the gRPC stream; usually mTLS mismatch (run "
        "verify_panel_certificate next) or marznode service is "
        "crashing on first RPC.\n"
        "  * `kind='sync'` with 'OperationalError' / "
        "'max_statement_time exceeded' — the SQL query that builds "
        "the user payload for this node times out; raise "
        "SQLALCHEMY_STATEMENT_TIMEOUT in the panel .env.\n"
        "  * `kind='ssl'` — TLS-level failure (expired cert, mismatched "
        "key); check panel cert + node's server.cert.\n"
        "  * `kind='connect'` with 'timeout' / 'refused' — marznode is "
        "down or firewalled; SSH and check the container.\n"
        "Returns an empty `errors` list if the node has had no recent "
        "failures (clean slate after recovery), or `node_not_loaded=true` "
        "when the panel never managed to instantiate a client (panel "
        "restart hasn't picked up the row yet, or the node is disabled)."
    ),
    requires_confirmation=False,
)
async def get_node_recent_errors(
    db: Session, node_id: int, limit: int = 20
) -> dict:
    from app.db import crud
    from app.marznode import node_registry

    node_row = crud.get_node_by_id(db, node_id)
    if not node_row:
        return {"error": f"Node {node_id} not found"}
    node_name = node_row.name
    db.close()

    node = node_registry.get(node_id)
    if node is None:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "node_not_loaded": True,
            "hint": (
                "The panel has no in-memory client for this node — "
                "either it is disabled, just enabled but the panel "
                "hasn't picked it up yet, or the panel container was "
                "restarted after a config change. Wait ~15s and retry, "
                "or call enable_node."
            ),
        }

    buf = getattr(node, "recent_errors", None)
    if buf is None:
        # grpcio backend or older client without the ring buffer
        return {
            "node_id": node_id,
            "node_name": node_name,
            "errors": [],
            "buffer_supported": False,
            "hint": (
                "This node uses a backend without an error ring buffer. "
                "Use diagnose_node_issue + get_node_logs instead."
            ),
        }

    # Snapshot now (the deque mutates from another task)
    now = time.time()
    snapshot = list(buf)
    snapshot.reverse()  # newest first
    limit = max(1, min(int(limit or 20), 50))
    sliced = snapshot[:limit]

    return {
        "node_id": node_id,
        "node_name": node_name,
        "buffer_supported": True,
        "buffer_capacity": getattr(buf, "maxlen", None),
        "stored_total": len(snapshot),
        "errors": [
            {
                "kind": e.get("kind"),
                "message": e.get("message"),
                "seconds_ago": int(now - e.get("ts", now)),
            }
            for e in sliced
        ],
    }


# =============================================================================
# 2. mTLS certificate verification — SSH-based
# =============================================================================


_CERT_PROBE_SCRIPT = r"""set +e
echo '### marker'
echo 'OK'
echo '### client_pem_present'
if [ -r /var/lib/marznode/client.pem ]; then echo 'YES'; else echo 'NO'; fi
echo '### client_pem_size'
wc -c /var/lib/marznode/client.pem 2>/dev/null | awk '{print $1}'
echo '### client_pem_sha256'
sha256sum /var/lib/marznode/client.pem 2>/dev/null | awk '{print $1}'
echo '### server_cert_present'
if [ -r /var/lib/marznode/server.cert ]; then echo 'YES'; else echo 'NO'; fi
echo '### server_cert_subject'
if command -v openssl >/dev/null 2>&1; then
  openssl x509 -in /var/lib/marznode/server.cert -noout -subject -dates 2>/dev/null
else
  echo 'no-openssl'
fi
echo '### docker_ssl_envs'
if command -v docker >/dev/null 2>&1; then
  CID=$(docker ps --filter name=marznode --format '{{.ID}}' | head -n1)
  if [ -n "$CID" ]; then
    docker inspect "$CID" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep -E '^SSL_'
  else
    echo 'no-marznode-container'
  fi
else
  echo 'no-docker'
fi
echo '### end'
"""


def _split_marker_sections(stdout: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("### "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line[4:].strip()
            buf = []
        else:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _maybe_load_creds_for_node(node_id: int) -> Optional[dict]:
    from app.db import GetDB, crud

    session_id = get_current_session_id()
    if not session_id or not is_session_unlocked(session_id):
        return None
    pin = get_unlocked_pin(session_id)
    if not pin:
        return None
    with GetDB() as db:
        creds_row = crud.get_ssh_credentials(db, node_id)
        if not creds_row:
            return None
        try:
            return decrypt_node_credentials(creds_row, pin)
        except PermissionError:
            return None


@register_tool(
    name="verify_panel_certificate",
    description=(
        "Compare the panel's current TLS client certificate (the one "
        "the panel embeds when opening a gRPC channel to a node) "
        "against the certificate file the marznode service trusts on "
        "disk (`/var/lib/marznode/client.pem`). A mismatch is the "
        "single most common reason a node accepts the TLS handshake "
        "but instantly resets the gRPC stream — producing the "
        "infamous 'sync failed: AttributeError: _write_appdata' / "
        "'StreamTerminatedError: Connection lost' loop with no other "
        "clue in the logs. "
        "Requires SSH unlocked for this chat session — gracefully "
        "returns `ssh_available=false` otherwise so the agent can "
        "report what's missing instead of pretending. "
        "Returns: `match` (bool), `panel_cert_sha256`, "
        "`node_client_pem_sha256`, `node_client_pem_present`, "
        "`server_cert_summary` (subject + validity), and "
        "`marznode_ssl_envs` (the SSL_* env vars marznode is using, so "
        "you can spot a path override). "
        "If `match=false`, run `install_panel_certificate_on_node` "
        "(after the admin confirms) to fix it in one shot."
    ),
    requires_confirmation=False,
)
async def verify_panel_certificate(db: Session, node_id: int) -> dict:
    from app.db import crud, get_tls_certificate

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}
    node_address = node.address
    node_name = node.name

    tls = get_tls_certificate(db)
    if not tls or not tls.certificate:
        return {
            "node_id": node_id,
            "error": (
                "Panel has no TLS certificate row — run alembic "
                "migrations / regenerate via the admin tool."
            ),
        }
    panel_cert_bytes = canonical_panel_cert_bytes(tls)
    panel_cert_sha = hashlib.sha256(panel_cert_bytes).hexdigest()

    creds = _maybe_load_creds_for_node(node_id)
    if creds is None:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "ssh_available": False,
            "panel_cert_sha256": panel_cert_sha,
            "panel_cert_size": len(panel_cert_bytes),
            "reason": (
                "SSH is not unlocked or credentials are missing for "
                "this node. Call ssh_check_access to see what's missing."
            ),
        }

    db.close()

    try:
        result = await asyncio.to_thread(
            run_command_with_creds,
            host=node_address,
            creds=creds,
            command=_CERT_PROBE_SCRIPT,
            timeout=30,
        )
    except PermissionError as exc:
        return {
            "node_id": node_id,
            "ssh_available": False,
            "reason": f"SSH auth failed: {exc}",
        }
    except TimeoutError:
        return {
            "node_id": node_id,
            "ssh_available": True,
            "timeout": True,
        }
    except Exception as exc:
        return {
            "node_id": node_id,
            "ssh_available": False,
            "reason": f"SSH probe failed: {exc}",
        }

    sections = _split_marker_sections(result.stdout)
    pem_present = (sections.get("client_pem_present") or "").strip() == "YES"
    node_sha = (sections.get("client_pem_sha256") or "").strip().lower()
    pem_size_raw = (sections.get("client_pem_size") or "").strip()
    pem_size = int(pem_size_raw) if pem_size_raw.isdigit() else None
    server_cert_present = (
        (sections.get("server_cert_present") or "").strip() == "YES"
    )
    server_cert_summary_lines = [
        ln for ln in (sections.get("server_cert_subject") or "").splitlines()
        if ln.strip() and ln.strip() != "no-openssl"
    ]
    ssl_envs_raw = sections.get("docker_ssl_envs") or ""
    ssl_envs: dict[str, str] = {}
    for ln in ssl_envs_raw.splitlines():
        ln = ln.strip()
        if "=" in ln and ln.startswith("SSL_"):
            k, v = ln.split("=", 1)
            ssl_envs[k] = v

    match = bool(node_sha and node_sha == panel_cert_sha)

    advice = None
    if not pem_present:
        advice = (
            "Node has no /var/lib/marznode/client.pem — every gRPC "
            "request will be rejected at the TLS layer. Run "
            "install_panel_certificate_on_node to ship the panel cert."
        )
    elif not match:
        advice = (
            "Certificate fingerprint mismatch — the panel cert and the "
            "node's trusted client.pem are NOT the same. The TLS "
            "handshake itself may complete (depending on cipher/"
            "verify policy on the node), but marznode will reset the "
            "stream as soon as the first RPC arrives, producing "
            "'sync failed: ... StreamTerminatedError' loops on the "
            "panel. Run install_panel_certificate_on_node to fix in "
            "one shot."
        )
    else:
        advice = (
            "Certificates match — mTLS is not the cause of any sync "
            "failure here. Check get_node_recent_errors for other "
            "kinds (e.g. SQL timeout in 'sync')."
        )

    return {
        "node_id": node_id,
        "node_name": node_name,
        "ssh_available": True,
        "panel_cert_sha256": panel_cert_sha,
        "panel_cert_size": len(panel_cert_bytes),
        "node_client_pem_present": pem_present,
        "node_client_pem_size": pem_size,
        "node_client_pem_sha256": node_sha or None,
        "match": match,
        "server_cert_present": server_cert_present,
        "server_cert_summary": server_cert_summary_lines,
        "marznode_ssl_envs": ssl_envs or None,
        "recommendation": advice,
    }


# =============================================================================
# 3. xray traffic health — accepted/rejected ratio from access.log
# =============================================================================


# Build an awk script that windows the log to the last `WINDOW_MIN` minutes
# and counts accepted/rejected lines. Using awk is way cheaper than tailing
# the whole file and parsing it on the panel side.
_TRAFFIC_PROBE_TEMPLATE = r"""set +e
WINDOW_MIN={window_min}
LOG=/var/log/xray/access.log
echo '### marker'
echo 'OK'
echo '### log_present'
if [ -r "$LOG" ]; then echo 'YES'; else echo 'NO'; fi
echo '### log_size'
wc -c "$LOG" 2>/dev/null | awk '{{print $1}}'
echo '### counts'
if [ -r "$LOG" ]; then
  CUTOFF=$(date -u -d "-${{WINDOW_MIN}} min" '+%Y/%m/%d %H:%M:%S' 2>/dev/null \
    || date -u -v-${{WINDOW_MIN}}M '+%Y/%m/%d %H:%M:%S' 2>/dev/null)
  tail -n {tail_lines} "$LOG" \
    | awk -v cutoff="$CUTOFF" '
      function ts() {{ return $1 " " $2 }}
      ts() >= cutoff {{
        total++
        if ($0 ~ /accepted/) accepted++
        else if ($0 ~ /rejected/) rejected++
        else other++
      }}
      END {{
        printf "total=%d\naccepted=%d\nrejected=%d\nother=%d\ncutoff=%s\n", \
          total+0, accepted+0, rejected+0, other+0, cutoff
      }}'
else
  echo 'NO_LOG'
fi
echo '### top_rejected'
if [ -r "$LOG" ]; then
  tail -n {tail_lines} "$LOG" \
    | grep -E 'rejected|invalid request user id' \
    | grep -oE 'email: [^ ]+|user id: [^ ]+' \
    | sort | uniq -c | sort -rn | head -n 10
fi
echo '### sample_rejected'
if [ -r "$LOG" ]; then
  tail -n {tail_lines} "$LOG" | grep -E 'rejected' | tail -n 5
fi
echo '### end'
"""


_NUM_RE = re.compile(r"^([a-z_]+)=(.+)$")


def _parse_kv_block(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in block.splitlines():
        m = _NUM_RE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


@register_tool(
    name="xray_traffic_health",
    description=(
        "SSH onto the node, parse the last `window_minutes` minutes of "
        "/var/log/xray/access.log, and return a structured "
        "accepted/rejected breakdown. This is the canonical way to "
        "tell apart 'xray is dead' from 'xray is up but no users were "
        "pushed to it' (the latter shows up as 99% rejected with "
        "'invalid request user id' reasons — exactly what we saw on "
        "node 31 when marznode never replayed users into xray after "
        "a sync timeout). "
        "Defaults: window_minutes=10, tail_lines=20000 (cap on how "
        "many recent log lines to scan — keeps SSH output bounded). "
        "Returns: `total`, `accepted`, `rejected`, `other`, "
        "`rejected_ratio` (0..1), `top_rejected_subjects` (top 10 "
        "user ids/emails that fail), `sample_rejected_lines` (5 raw "
        "examples). When `rejected_ratio > 0.5`, the agent should "
        "next: (1) get_node_recent_errors to see if sync is failing, "
        "(2) verify_panel_certificate, (3) consider resync_node_users. "
        "Requires SSH unlocked; degrades gracefully with "
        "`ssh_available=false`."
    ),
    requires_confirmation=False,
)
async def xray_traffic_health(
    db: Session,
    node_id: int,
    window_minutes: int = 10,
    tail_lines: int = 20000,
) -> dict:
    from app.db import crud

    node = crud.get_node_by_id(db, node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}
    node_address = node.address
    node_name = node.name

    creds = _maybe_load_creds_for_node(node_id)
    if creds is None:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "ssh_available": False,
            "reason": (
                "SSH is not unlocked or credentials are missing for "
                "this node. Call ssh_check_access to see what's missing."
            ),
        }

    db.close()

    window_minutes = max(1, min(int(window_minutes or 10), 240))
    tail_lines = max(500, min(int(tail_lines or 20000), 100000))

    script = _TRAFFIC_PROBE_TEMPLATE.format(
        window_min=window_minutes, tail_lines=tail_lines
    )

    try:
        result = await asyncio.to_thread(
            run_command_with_creds,
            host=node_address,
            creds=creds,
            command=script,
            timeout=45,
        )
    except PermissionError as exc:
        return {
            "node_id": node_id,
            "ssh_available": False,
            "reason": f"SSH auth failed: {exc}",
        }
    except TimeoutError:
        return {
            "node_id": node_id,
            "ssh_available": True,
            "timeout": True,
            "reason": (
                "Probe exceeded 45s — the access.log might be huge. "
                "Lower `tail_lines` and retry."
            ),
        }
    except Exception as exc:
        return {
            "node_id": node_id,
            "ssh_available": False,
            "reason": f"SSH probe failed: {exc}",
        }

    sections = _split_marker_sections(result.stdout)
    log_present = (sections.get("log_present") or "").strip() == "YES"
    log_size_raw = (sections.get("log_size") or "").strip()
    log_size = int(log_size_raw) if log_size_raw.isdigit() else None

    if not log_present:
        return {
            "node_id": node_id,
            "node_name": node_name,
            "ssh_available": True,
            "log_present": False,
            "hint": (
                "/var/log/xray/access.log is missing or unreadable. "
                "Check that xray's `log.access` is configured and the "
                "log directory is writable. Without access.log we "
                "cannot judge accepted/rejected ratio."
            ),
        }

    counts = _parse_kv_block(sections.get("counts") or "")
    total = int(counts.get("total", "0") or 0)
    accepted = int(counts.get("accepted", "0") or 0)
    rejected = int(counts.get("rejected", "0") or 0)
    other = int(counts.get("other", "0") or 0)
    cutoff = counts.get("cutoff")
    rejected_ratio = round(rejected / total, 4) if total > 0 else None

    top_lines = [
        ln.strip() for ln in (sections.get("top_rejected") or "").splitlines()
        if ln.strip()
    ]
    top_subjects: list[dict] = []
    for ln in top_lines[:10]:
        # awk -c output: "  N  email: foo" or "  N  user id: bar"
        parts = ln.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            top_subjects.append({"count": int(parts[0]), "subject": parts[1]})

    sample_rejected = [
        ln.strip()
        for ln in (sections.get("sample_rejected") or "").splitlines()
        if ln.strip()
    ][:5]

    if total == 0:
        verdict = (
            "No xray traffic in the last "
            f"{window_minutes} min. Either no users are connecting "
            "(check from a client), or the log buffer hasn't "
            "rotated yet."
        )
    elif rejected_ratio is not None and rejected_ratio > 0.5:
        verdict = (
            f"HIGH REJECT RATIO: {rejected}/{total} "
            f"({rejected_ratio:.0%}) in last {window_minutes} min. "
            "Most likely xray is up but does NOT know the user set "
            "(panel-to-node user sync stuck or slow). Check "
            "get_node_recent_errors for sync failures, then "
            "verify_panel_certificate, then resync_node_users."
        )
    elif accepted > 0 and rejected_ratio is not None and rejected_ratio < 0.1:
        verdict = (
            f"Healthy: {accepted}/{total} accepted in last "
            f"{window_minutes} min ({rejected_ratio:.0%} rejected)."
        )
    else:
        verdict = (
            f"Mixed: {accepted}/{total} accepted, {rejected}/{total} "
            f"rejected in last {window_minutes} min. Investigate "
            "top_rejected_subjects to see whether a specific user "
            "is misconfigured."
        )

    return {
        "node_id": node_id,
        "node_name": node_name,
        "ssh_available": True,
        "log_present": True,
        "log_size_bytes": log_size,
        "window_minutes": window_minutes,
        "tail_lines_scanned": tail_lines,
        "cutoff_utc": cutoff,
        "total": total,
        "accepted": accepted,
        "rejected": rejected,
        "other": other,
        "rejected_ratio": rejected_ratio,
        "top_rejected_subjects": top_subjects,
        "sample_rejected_lines": sample_rejected,
        "verdict": verdict,
    }
