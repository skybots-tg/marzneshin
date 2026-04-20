"""End-to-end verification tools for node inbounds.

Closes the long-standing gap that caused the "pingable but nothing
opens" incidents on UNIVERSAL 4 / UNIVERSAL 5: external TLS handshake
returned 200 (port was open), but xray had ZERO clients pushed to that
inbound because the inbound row in the panel had no service binding,
so `RepopulateUsers` skipped it. There was no single tool that
correlated all four layers (panel DB ↔ xray live config ↔ marznode
client push ↔ external reachability) so diagnosis required
hand-rolled scripts every time.

Tools here:

- `diagnose_node_users` — quick: fetch xray live config and return the
  number of clients in each inbound. If a tag shows `clients_count=0`
  while the panel has hosts pointing at it, the user push is broken
  for that tag.

- `verify_inbound_e2e` — comprehensive single-inbound check across
  all four layers. Returns a structured `checks` array with per-layer
  pass/fail + remedy hint for the first failing layer.

- `verify_donor_target_parity` — cross-node diff of live xray configs:
  inbounds (by tag + port), outbounds (by tag + endpoint signature),
  routing rules (multiset of compact signatures). Catches the silent
  drift `clone_node_config` itself can't see — donor was edited
  after the clone, or one side was hand-tweaked.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import ssl
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


_CONFIG_FORMAT_JSON = 1
_EXTERNAL_PROBE_TIMEOUT_S = 4.0


def _derive_reality_public_key(private_key_b64: str) -> Optional[str]:
    """Derive the X25519 public key from a base64url-no-pad reality
    privateKey. Returns base64url-no-pad public key, or None if the
    input cannot be parsed."""
    if not private_key_b64 or not isinstance(private_key_b64, str):
        return None
    try:
        from nacl.public import PrivateKey
        pad = "=" * (-len(private_key_b64) % 4)
        raw = base64.urlsafe_b64decode(private_key_b64 + pad)
        if len(raw) != 32:
            return None
        priv = PrivateKey(raw)
        pub = bytes(priv.public_key)
        return base64.urlsafe_b64encode(pub).rstrip(b"=").decode("ascii")
    except Exception:
        return None


def _normalize_short_id(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _xray_inbound_summary(xray_inbound: dict) -> dict:
    stream = xray_inbound.get("streamSettings") or {}
    reality = stream.get("realitySettings") or {}
    settings = xray_inbound.get("settings") or {}
    clients = settings.get("clients") if isinstance(settings, dict) else None
    return {
        "tag": xray_inbound.get("tag"),
        "protocol": xray_inbound.get("protocol"),
        "port": xray_inbound.get("port"),
        "listen": xray_inbound.get("listen"),
        "network": stream.get("network"),
        "security": stream.get("security"),
        "reality_server_names": reality.get("serverNames") or [],
        "reality_short_ids": [
            _normalize_short_id(s) for s in (reality.get("shortIds") or [])
        ],
        "reality_public_key": _derive_reality_public_key(
            reality.get("privateKey") or ""
        ),
        "clients_count": (
            len(clients) if isinstance(clients, list) else None
        ),
    }


async def _fetch_xray_inbounds(node_id: int, backend: str) -> tuple[Optional[list], Optional[str]]:
    """Returns (inbounds_list, error_message). On success error is None."""
    from app.marznode import node_registry

    node = node_registry.get(node_id)
    if not node:
        return None, (
            f"Node {node_id} is not connected (not in panel registry). "
            f"Call enable_node({node_id}) first."
        )
    try:
        config_str, config_format = await node.get_backend_config(name=backend)
    except Exception as exc:
        return None, f"Failed to fetch live xray config: {exc}"
    if int(config_format) != _CONFIG_FORMAT_JSON:
        return None, (
            f"Live config is not JSON (format={int(config_format)}); "
            f"cannot inspect inbounds."
        )
    try:
        parsed = json.loads(config_str)
    except Exception as exc:
        return None, f"Live xray config is not valid JSON: {exc}"
    inbounds = parsed.get("inbounds")
    if not isinstance(inbounds, list):
        return None, "Live xray config has no `inbounds` array."
    return inbounds, None


async def _tcp_probe(address: str, port: int) -> dict:
    """Open a TCP connection to `address:port` with a short timeout.
    Returns `{reachable: bool, error?: str, elapsed_ms: int}`. Does
    NOT attempt a TLS handshake — the caller wants to know if the port
    even accepts SYN, which is what the previous incidents bisected on."""
    import time

    started = time.monotonic()
    try:
        fut = asyncio.open_connection(address, port)
        reader, writer = await asyncio.wait_for(fut, timeout=_EXTERNAL_PROBE_TIMEOUT_S)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return {
            "reachable": True,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except asyncio.TimeoutError:
        return {
            "reachable": False,
            "error": f"timeout after {_EXTERNAL_PROBE_TIMEOUT_S:.1f}s",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except (ConnectionRefusedError, socket.gaierror, OSError, ssl.SSLError) as exc:
        return {
            "reachable": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


@register_tool(
    name="diagnose_node_users",
    description=(
        "Fetch the live xray config from the node and report the "
        "number of clients (`settings.clients`) currently configured "
        "in EACH inbound. This is the canonical fast check after a "
        "`resync_node_users` or `clone_node_config` call: if any "
        "inbound has `clients_count=0` while the panel has hosts "
        "pointing at it, the user push from marznode is silently "
        "broken for that tag (typical cause: the inbound row in the "
        "panel has no service binding, so `RepopulateUsers` filters "
        "it out — fix with `propagate_node_to_services` "
        "`bind_orphan_target_inbounds=true`).\n"
        "Returns: `inbounds` (per-tag list of `{tag, protocol, port, "
        "network, security, clients_count}`), "
        "`zero_client_inbound_tags` (sorted list of tags with 0 "
        "clients — the suspects), `total_inbounds`. "
        "Cheap (~one gRPC call), safe (no writes). No confirmation "
        "needed."
    ),
    requires_confirmation=False,
)
async def diagnose_node_users(
    db: Session, node_id: int, backend: str = "xray"
) -> dict:
    db.close()
    inbounds, err = await _fetch_xray_inbounds(node_id, backend)
    if err:
        return {"node_id": node_id, "error": err}

    summaries = [_xray_inbound_summary(ib) for ib in inbounds if isinstance(ib, dict)]
    zero_tags = sorted(
        s["tag"] for s in summaries
        if s.get("clients_count") == 0 and s.get("tag")
    )
    return {
        "node_id": node_id,
        "backend": backend,
        "total_inbounds": len(summaries),
        "zero_client_inbound_tags": zero_tags,
        "inbounds": [
            {
                "tag": s["tag"],
                "protocol": s["protocol"],
                "port": s["port"],
                "network": s["network"],
                "security": s["security"],
                "clients_count": s["clients_count"],
            }
            for s in summaries
        ],
    }


def _build_e2e_check(name: str, ok: bool, **payload) -> dict:
    return {"name": name, "ok": ok, **payload}


def _outbound_signature(outbound: dict) -> tuple:
    """Compact signature of an outbound's externally-observable shape:
    protocol + first server address/port (when applicable). Used to
    decide whether two outbounds with the same tag actually route to
    the same place."""
    proto = outbound.get("protocol")
    settings = outbound.get("settings") or {}
    servers: list[tuple] = []
    vnext = settings.get("vnext") if isinstance(settings, dict) else None
    if isinstance(vnext, list):
        for s in vnext:
            if not isinstance(s, dict):
                continue
            servers.append((s.get("address"), s.get("port")))
    plain_servers = settings.get("servers") if isinstance(settings, dict) else None
    if isinstance(plain_servers, list):
        for s in plain_servers:
            if not isinstance(s, dict):
                continue
            servers.append((s.get("address"), s.get("port")))
    return (proto, tuple(sorted(servers, key=lambda x: (str(x[0] or ""), x[1] or 0))))


def _routing_rule_signature(rule: dict) -> tuple:
    """Compact, order-independent signature of a routing rule. We
    compare these as multisets between donor and target to detect
    routing drift after a clone."""
    if not isinstance(rule, dict):
        return ("invalid",)
    inbound_tag = rule.get("inboundTag")
    if isinstance(inbound_tag, list):
        inbound_tag = tuple(sorted(str(t) for t in inbound_tag))
    elif inbound_tag is not None:
        inbound_tag = (str(inbound_tag),)
    else:
        inbound_tag = ()
    return (
        rule.get("type"),
        inbound_tag,
        rule.get("outboundTag") or rule.get("balancerTag") or None,
        tuple(sorted(rule.get("domain") or [])) if isinstance(rule.get("domain"), list) else None,
        tuple(sorted(rule.get("ip") or [])) if isinstance(rule.get("ip"), list) else None,
        rule.get("network"),
        rule.get("protocol") if not isinstance(rule.get("protocol"), list)
        else tuple(sorted(rule.get("protocol"))),
    )


@register_tool(
    name="verify_donor_target_parity",
    description=(
        "Diff the LIVE xray configs of donor and target nodes after a "
        "clone, surfacing the gaps that `clone_node_config` itself "
        "cannot detect (it just ships the donor blob — if a per-node "
        "tweak landed on one side later, parity is silently broken).\n"
        "Three groups are compared:\n"
        "  * inbounds — by `tag`. Reports `inbound_tags_only_on_donor`, "
        "`inbound_tags_only_on_target`, "
        "`inbound_tag_port_mismatches` (same tag, different "
        "`port` — clients pointed at the donor's port will time out "
        "on the target).\n"
        "  * outbounds — by `tag` AND signature (protocol + server "
        "address/port). Reports `outbound_tags_only_on_donor` (donor "
        "has a bridge target lacks — routing rules pointing at it "
        "will silently fall through to `direct`), "
        "`outbound_tags_only_on_target`, and "
        "`outbound_signature_mismatches` (same tag, different "
        "endpoint).\n"
        "  * routing rules — order-independent multiset comparison. "
        "Reports `routing_rules_only_on_donor` and "
        "`routing_rules_only_on_target` as compact signature tuples. "
        "Drift here usually means `clone_node_config` did its job "
        "but a hand-edit on one side wasn't replayed.\n"
        "Cheap (two gRPC reads, no writes), no confirmation. Use "
        "right after `clone_node_config` and again any time the "
        "admin reports 'this node was working yesterday'."
    ),
    requires_confirmation=False,
)
async def verify_donor_target_parity(
    db: Session, donor_node_id: int, target_node_id: int, backend: str = "xray"
) -> dict:
    if donor_node_id == target_node_id:
        return {"error": "donor and target must differ"}

    db.close()

    from app.marznode import node_registry

    donor_node = node_registry.get(donor_node_id)
    target_node = node_registry.get(target_node_id)
    if donor_node is None:
        return {"error": f"Donor node {donor_node_id} is not in registry"}
    if target_node is None:
        return {"error": f"Target node {target_node_id} is not in registry"}

    async def _read(node, label: str) -> tuple[Optional[dict], Optional[str]]:
        try:
            cfg_str, cfg_format = await node.get_backend_config(name=backend)
        except Exception as exc:
            return None, f"{label} get_backend_config failed: {exc}"
        if int(cfg_format) != _CONFIG_FORMAT_JSON:
            return None, f"{label} config is not JSON (format={int(cfg_format)})"
        try:
            return json.loads(cfg_str), None
        except Exception as exc:
            return None, f"{label} config parse failed: {exc}"

    donor_cfg, derr = await _read(donor_node, "donor")
    if derr:
        return {"error": derr}
    target_cfg, terr = await _read(target_node, "target")
    if terr:
        return {"error": terr}

    donor_inbounds = {
        ib.get("tag"): ib
        for ib in (donor_cfg.get("inbounds") or [])
        if isinstance(ib, dict) and ib.get("tag")
    }
    target_inbounds = {
        ib.get("tag"): ib
        for ib in (target_cfg.get("inbounds") or [])
        if isinstance(ib, dict) and ib.get("tag")
    }

    inbounds_only_donor = sorted(set(donor_inbounds) - set(target_inbounds))
    inbounds_only_target = sorted(set(target_inbounds) - set(donor_inbounds))
    inbound_port_mismatches = []
    for tag in sorted(set(donor_inbounds) & set(target_inbounds)):
        d_port = donor_inbounds[tag].get("port")
        t_port = target_inbounds[tag].get("port")
        if d_port != t_port:
            inbound_port_mismatches.append({
                "tag": tag,
                "donor_port": d_port,
                "target_port": t_port,
            })

    donor_outbounds = {
        ob.get("tag"): ob
        for ob in (donor_cfg.get("outbounds") or [])
        if isinstance(ob, dict) and ob.get("tag")
    }
    target_outbounds = {
        ob.get("tag"): ob
        for ob in (target_cfg.get("outbounds") or [])
        if isinstance(ob, dict) and ob.get("tag")
    }
    outbounds_only_donor = sorted(set(donor_outbounds) - set(target_outbounds))
    outbounds_only_target = sorted(set(target_outbounds) - set(donor_outbounds))
    outbound_signature_mismatches = []
    for tag in sorted(set(donor_outbounds) & set(target_outbounds)):
        ds = _outbound_signature(donor_outbounds[tag])
        ts = _outbound_signature(target_outbounds[tag])
        if ds != ts:
            outbound_signature_mismatches.append({
                "tag": tag,
                "donor_signature": list(ds),
                "target_signature": list(ts),
            })

    donor_rules = (donor_cfg.get("routing") or {}).get("rules") or []
    target_rules = (target_cfg.get("routing") or {}).get("rules") or []
    donor_rule_sigs = [_routing_rule_signature(r) for r in donor_rules]
    target_rule_sigs = [_routing_rule_signature(r) for r in target_rules]

    from collections import Counter
    donor_counter = Counter(map(lambda s: json.dumps(s, default=list), donor_rule_sigs))
    target_counter = Counter(map(lambda s: json.dumps(s, default=list), target_rule_sigs))
    rules_only_donor = []
    rules_only_target = []
    for sig, count in donor_counter.items():
        diff = count - target_counter.get(sig, 0)
        if diff > 0:
            rules_only_donor.append({"signature": json.loads(sig), "count": diff})
    for sig, count in target_counter.items():
        diff = count - donor_counter.get(sig, 0)
        if diff > 0:
            rules_only_target.append({"signature": json.loads(sig), "count": diff})

    in_sync = (
        not inbounds_only_donor
        and not inbounds_only_target
        and not inbound_port_mismatches
        and not outbounds_only_donor
        and not outbounds_only_target
        and not outbound_signature_mismatches
        and not rules_only_donor
        and not rules_only_target
    )

    return {
        "donor_node_id": donor_node_id,
        "target_node_id": target_node_id,
        "in_sync": in_sync,
        "inbound_tags_only_on_donor": inbounds_only_donor,
        "inbound_tags_only_on_target": inbounds_only_target,
        "inbound_tag_port_mismatches": inbound_port_mismatches,
        "outbound_tags_only_on_donor": outbounds_only_donor,
        "outbound_tags_only_on_target": outbounds_only_target,
        "outbound_signature_mismatches": outbound_signature_mismatches,
        "routing_rules_only_on_donor": rules_only_donor[:50],
        "routing_rules_only_on_target": rules_only_target[:50],
        "donor_summary": {
            "inbound_count": len(donor_inbounds),
            "outbound_count": len(donor_outbounds),
            "rule_count": len(donor_rules),
        },
        "target_summary": {
            "inbound_count": len(target_inbounds),
            "outbound_count": len(target_outbounds),
            "rule_count": len(target_rules),
        },
    }


@register_tool(
    name="verify_inbound_e2e",
    description=(
        "Single-inbound end-to-end gate: panel DB ↔ xray live config "
        "↔ marznode user push ↔ external reachability, all in one "
        "call. The post-deploy check that catches every silent "
        "failure mode `onboard_node_from_donor` and the panel's auto-"
        "sync used to miss.\n"
        "Inputs: `node_id` + EITHER `inbound_tag` OR `inbound_id` "
        "(tag is preferred — it survives cross-node onboarding). "
        "Optional `external_probe=true` (default): TCP-connect to the "
        "first non-disabled host's `address:port` to confirm the port "
        "actually accepts SYN from the public internet (NOT a TLS "
        "handshake — the goal is to bisect the firewall vs xray "
        "layer). Optional `backend='xray'`.\n"
        "Returns `ok` (bool) and a per-layer `checks` array. Each "
        "check has `name`, `ok`, layer-specific fields, and (on "
        "failure) a `remedy` hint pointing at the next tool to call. "
        "Layers in order:\n"
        "  1. `panel_inbound_exists` — Inbound row found by node+tag.\n"
        "  2. `panel_service_binding` — Inbound is attached to ≥1 "
        "service. If 0, `RepopulateUsers` filters it out — call "
        "`propagate_node_to_services(bind_orphan_target_inbounds=true)` "
        "or `add_inbounds_to_service`.\n"
        "  3. `panel_hosts` — at least one non-disabled InboundHost "
        "rows exist. If 0, the inbound is invisible to subscriptions.\n"
        "  4. `xray_inbound_present` — same `tag` exists in the "
        "node's LIVE xray config.\n"
        "  5. `port_consistency` — every host's `port` matches "
        "xray's `port` for that inbound.\n"
        "  6. `reality_consistency` — every reality host's "
        "`reality_public_key` matches the public key derived from "
        "xray's current `realitySettings.privateKey`, AND each host "
        "shortId is in xray's `shortIds`.\n"
        "  7. `xray_clients_pushed` — `len(xray.settings.clients) > "
        "0` for vless/vmess/trojan inbounds. If 0, marznode never "
        "received users for this tag — most likely the service "
        "binding (check 2) was missing during the last "
        "`resync_node_users`.\n"
        "  8. `external_tcp_probe` (when enabled) — TCP connect to "
        "the sample host's `address:port`. A 'connection refused' or "
        "timeout points at firewall/UFW; a successful connect means "
        "xray is at least listening.\n"
        "Cheap (one gRPC + a few DB selects + one TCP probe), no "
        "writes, no confirmation."
    ),
    requires_confirmation=False,
)
async def verify_inbound_e2e(
    db: Session,
    node_id: int,
    inbound_tag: str = "",
    inbound_id: int = 0,
    backend: str = "xray",
    external_probe: bool = True,
) -> dict:
    from app.db.models import Inbound, InboundHost

    inbound_tag = (inbound_tag or "").strip()
    if not inbound_tag and not inbound_id:
        return {
            "error": (
                "Provide either `inbound_tag` (preferred) or "
                "`inbound_id`."
            )
        }

    query = db.query(Inbound).filter(Inbound.node_id == node_id)
    if inbound_tag:
        query = query.filter(Inbound.tag == inbound_tag)
    else:
        query = query.filter(Inbound.id == int(inbound_id))
    panel_inbound = query.first()

    checks: list[dict] = []

    if not panel_inbound:
        checks.append(_build_e2e_check(
            "panel_inbound_exists",
            ok=False,
            remedy=(
                "No Inbound row for this node+tag in the panel. "
                "Either the tag is wrong, or xray hasn't been "
                "synced yet. Call `get_node_config(node_id, "
                "summary=true)` to list available tags, or "
                "`restart_node_backend` to force a sync."
            ),
        ))
        return {
            "node_id": node_id,
            "inbound_tag": inbound_tag or None,
            "inbound_id_input": inbound_id or None,
            "ok": False,
            "checks": checks,
        }

    actual_tag = panel_inbound.tag
    panel_inbound_id = panel_inbound.id
    services = list(panel_inbound.services or [])
    hosts = list(panel_inbound.hosts or [])

    checks.append(_build_e2e_check(
        "panel_inbound_exists",
        ok=True,
        inbound_id=panel_inbound_id,
        tag=actual_tag,
        protocol=str(panel_inbound.protocol),
    ))

    services_ok = len(services) > 0
    checks.append(_build_e2e_check(
        "panel_service_binding",
        ok=services_ok,
        services_count=len(services),
        service_ids=[s.id for s in services],
        remedy=None if services_ok else (
            "Inbound has 0 service bindings — `RepopulateUsers` "
            "skips it, so xray will never receive any clients for "
            "this tag. Call `propagate_node_to_services(from_node_id="
            "<some-other-node-with-services>, to_node_id="
            f"{node_id}, bind_orphan_target_inbounds=true)` to bind "
            "every orphan inbound on this node to the union of "
            "services touched by the donor."
        ),
    ))

    active_hosts = [h for h in hosts if not h.is_disabled]
    hosts_ok = len(active_hosts) > 0
    checks.append(_build_e2e_check(
        "panel_hosts",
        ok=hosts_ok,
        active_hosts_count=len(active_hosts),
        disabled_hosts_count=len(hosts) - len(active_hosts),
        sample_host_ids=[h.id for h in active_hosts[:5]],
        remedy=None if hosts_ok else (
            "No active hosts pointing at this inbound — "
            "subscriptions will not include it. Either run "
            "`clone_donor_hosts_to_target` (mirror from a working "
            "node), or create hosts manually."
        ),
    ))

    db.close()

    inbounds, err = await _fetch_xray_inbounds(node_id, backend)
    if err:
        checks.append(_build_e2e_check(
            "xray_inbound_present",
            ok=False,
            error=err,
            remedy=(
                "Cannot read live xray config. Fix node connectivity "
                "first (`get_node_recent_errors`, `enable_node`)."
            ),
        ))
        return {
            "node_id": node_id,
            "inbound_tag": actual_tag,
            "inbound_id": panel_inbound_id,
            "ok": False,
            "checks": checks,
        }

    xray_inbound = next(
        (ib for ib in inbounds if isinstance(ib, dict) and ib.get("tag") == actual_tag),
        None,
    )
    if xray_inbound is None:
        all_tags = [ib.get("tag") for ib in inbounds if isinstance(ib, dict)]
        checks.append(_build_e2e_check(
            "xray_inbound_present",
            ok=False,
            available_tags=all_tags,
            remedy=(
                f"Live xray config has no inbound with tag "
                f"{actual_tag!r}. Either xray was restarted with a "
                "stale config, or the tag drifted. Call "
                "`restart_node_backend` to re-sync, or "
                "`clone_node_config` from a donor with the right tag."
            ),
        ))
        return {
            "node_id": node_id,
            "inbound_tag": actual_tag,
            "inbound_id": panel_inbound_id,
            "ok": False,
            "checks": checks,
        }

    summary = _xray_inbound_summary(xray_inbound)
    checks.append(_build_e2e_check(
        "xray_inbound_present",
        ok=True,
        xray=summary,
    ))

    xray_port = summary.get("port")
    port_mismatches = [
        {"host_id": h.id, "host_port": h.port, "xray_port": xray_port}
        for h in active_hosts
        if h.port and xray_port and int(h.port) != int(xray_port)
    ]
    port_ok = not port_mismatches
    checks.append(_build_e2e_check(
        "port_consistency",
        ok=port_ok,
        xray_port=xray_port,
        mismatches=port_mismatches,
        remedy=None if port_ok else (
            "Some hosts point at a different port than xray is "
            "listening on — clients will see TLS handshake failures. "
            "Either fix the hosts (`update host port`) or "
            "re-clone xray config from the donor that defines the "
            "intended port."
        ),
    ))

    expected_pub = summary.get("reality_public_key")
    xray_short_ids = set(summary.get("reality_short_ids") or [])
    reality_issues: list[dict] = []
    reality_check_applies = bool(expected_pub) or bool(xray_short_ids)
    if reality_check_applies:
        for h in active_hosts:
            host_pub = (h.reality_public_key or "").strip()
            host_sids = [
                _normalize_short_id(s) for s in (h.reality_short_ids or [])
            ]
            if not host_pub and not host_sids:
                continue
            if expected_pub and host_pub and host_pub != expected_pub:
                reality_issues.append({
                    "host_id": h.id,
                    "issue": "public_key_mismatch",
                    "host_value": host_pub,
                    "xray_value": expected_pub,
                })
            for sid in host_sids:
                if not sid:
                    continue
                if xray_short_ids and sid not in xray_short_ids:
                    reality_issues.append({
                        "host_id": h.id,
                        "issue": "short_id_not_in_xray",
                        "host_value": sid,
                        "xray_values": sorted(xray_short_ids),
                    })
    reality_ok = not reality_issues
    checks.append(_build_e2e_check(
        "reality_consistency",
        ok=reality_ok,
        applies=reality_check_applies,
        xray_public_key=expected_pub,
        xray_short_ids=sorted(xray_short_ids),
        issues=reality_issues,
        remedy=None if reality_ok else (
            "Host reality keys/shortIds don't match the live xray "
            "config — clients will fail the reality check silently "
            "(handshake completes, no traffic). Re-run "
            "`regenerate_reality_keys_on_node` and pipe the output "
            "into `clone_donor_hosts_to_target`, or update host "
            "fields manually."
        ),
    ))

    clients_count = summary.get("clients_count")
    needs_clients = (summary.get("protocol") or "").lower() in {
        "vless", "vmess", "trojan"
    }
    clients_ok = (
        clients_count is None
        or clients_count > 0
        or not needs_clients
    )
    checks.append(_build_e2e_check(
        "xray_clients_pushed",
        ok=clients_ok,
        clients_count=clients_count,
        applies=needs_clients,
        remedy=None if clients_ok else (
            "Xray inbound has 0 clients — marznode never pushed "
            "users to this tag. The most common cause is the "
            "missing service binding flagged in "
            "`panel_service_binding`. Once that is fixed, run "
            f"`resync_node_users({node_id})` to replay users."
        ),
    ))

    if external_probe and active_hosts and xray_port:
        sample = active_hosts[0]
        if sample.address and not sample.address.startswith("{"):
            probe = await _tcp_probe(sample.address, int(xray_port))
            checks.append(_build_e2e_check(
                "external_tcp_probe",
                ok=probe["reachable"],
                host_id=sample.id,
                host_address=sample.address,
                host_port=xray_port,
                **{k: v for k, v in probe.items() if k != "reachable"},
                remedy=None if probe["reachable"] else (
                    "Cannot open a TCP connection to "
                    f"{sample.address}:{xray_port} from the panel "
                    "host. Either xray is not listening (check "
                    "`get_node_stats`), the firewall blocks the "
                    "port (UFW: `ufw allow <port>/tcp` on the "
                    "node), or `nodes.address` in the DB points at "
                    "a NAT'd internal IP. Bisect via SSH."
                ),
            ))

    overall_ok = all(c.get("ok", True) for c in checks)
    return {
        "node_id": node_id,
        "inbound_tag": actual_tag,
        "inbound_id": panel_inbound_id,
        "ok": overall_ok,
        "checks": checks,
    }
