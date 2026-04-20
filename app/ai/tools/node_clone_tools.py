"""AI tools that turn the manual "onboard a new VPN node by mirroring a
donor" workflow into one or two confirmable tool calls.

The admin's manual procedure (kept here as the source of truth for what
this module must implement):

1. Copy the donor node's xray config wholesale onto the new (target)
   node — `clone_node_config` already does this and lives in
   ``node_tools.py``.
2. Replace the reality `privateKey`/`shortIds` on the target with
   freshly generated per-node values (security best practice — leak of
   one node's key does NOT compromise siblings) — `regenerate_reality_
   keys_on_node` below.
3. Add the target's inbounds to every service the donor was already in
   — `propagate_node_to_services` in ``service_tools.py``.
4. Mirror the donor's host entries onto the target: keep every field
   (port, sni, fragment, mux, mlkem, fingerprint, ...) but flip the
   `address` to the target's IP and the reality public_key/short_ids to
   the freshly rotated ones — `clone_donor_hosts_to_target` below.

The macro `onboard_node_from_donor` (``node_provision_tools.py``)
orchestrates all four steps in one confirmation. The two new tools
below are also valid standalone — handy when the admin wants to e.g.
just rotate keys on a single node without re-running the full
onboarding.
"""
from __future__ import annotations

import base64
import json
import logging
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)


# Marznode protobuf ConfigFormat enum: PLAIN=0, JSON=1, YAML=2.
_CONFIG_FORMAT_JSON = 1

# `add_default_hosts` (in app/db/crud/host.py) seeds every newly
# discovered inbound with a placeholder host whose address is the
# literal substitution token below. We need to be able to recognise
# and remove these so the panel doesn't end up with both the
# placeholder and our cloned host on the same target inbound.
_PLACEHOLDER_HOST_ADDRESS = "{SERVER_IP}"

# `flow=xtls-rprx-vision` is only valid for VLESS over raw TCP. Setting
# it on an xhttp/ws/grpc/etc. inbound makes the client reject the
# config silently — the link generator omits the host from
# subscriptions because the combination is invalid. Networks other
# than these strip the flow on clone.
_FLOWS_VALID_NETWORKS: frozenset[str] = frozenset({"tcp", "raw"})

# Fields of `InboundHost` that we copy verbatim from donor → target
# host. Excludes: id (autoincrement), inbound_id (set explicitly to
# target's inbound), remark/address (override per-call),
# reality_public_key/reality_short_ids (override per-tag from regen),
# inbound (relationship, set via inbound_id), services (handled
# separately), chain (cross-host references — out of scope, would need
# a second pass to remap chained_host_id and is rarely used in
# practice).
_CLONABLE_HOST_FIELDS: tuple[str, ...] = (
    "host_protocol",
    "host_network",
    "uuid",
    "password",
    "port",
    "path",
    "sni",
    "host",
    "security",
    "alpn",
    "fingerprint",
    "fragment",
    "udp_noises",
    "http_headers",
    "dns_servers",
    "mtu",
    "allowed_ips",
    "header_type",
    "flow",
    "shadowtls_version",
    "shadowsocks_method",
    "splithttp_settings",
    "mux_settings",
    "early_data",
    "mlkem_enabled",
    "mlkem_public_key",
    "mlkem_private_key",
    "allowinsecure",
    "is_disabled",
    "weight",
    "universal",
)


def _b64url_nopad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


async def _fetch_target_xray_inbound_map(
    target_node_id: int, backend: str
) -> tuple[dict[str, dict], Optional[str]]:
    """Read the target node's live xray config and return
    `{tag: {network, security, protocol, port}}`. Used to normalize
    host fields after cloning so e.g. an XHTTP inbound doesn't end up
    with `flow=xtls-rprx-vision` (TCP-only flow) inherited from a
    TCP donor host. Returns `({}, None)` quietly if the node is not
    in the registry — the macro will fall back to no normalization,
    which preserves the previous behaviour."""
    from app.marznode import node_registry

    node = node_registry.get(target_node_id)
    if not node:
        return {}, None
    try:
        config_str, config_format = await node.get_backend_config(name=backend)
    except Exception as exc:
        return {}, f"target xray config fetch failed: {exc}"
    if int(config_format) != _CONFIG_FORMAT_JSON:
        return {}, None
    try:
        parsed = json.loads(config_str)
    except Exception:
        return {}, None
    out: dict[str, dict] = {}
    for ib in (parsed.get("inbounds") or []):
        if not isinstance(ib, dict):
            continue
        tag = ib.get("tag")
        if not isinstance(tag, str) or not tag:
            continue
        stream = ib.get("streamSettings") or {}
        out[tag] = {
            "network": stream.get("network"),
            "security": stream.get("security"),
            "protocol": ib.get("protocol"),
            "port": ib.get("port"),
        }
    return out, None


def _normalize_host_kwargs_to_target(
    clone_kwargs: dict, xray_meta: Optional[dict]
) -> list[str]:
    """In-place: coerce host fields so they match the target inbound's
    actual transport. Returns a list of field names that were changed
    so the caller can report them. No-op when xray_meta is missing."""
    if not xray_meta:
        return []
    network = (xray_meta.get("network") or "").lower() or None
    protocol = (xray_meta.get("protocol") or "").lower() or None

    changes: list[str] = []
    if network and clone_kwargs.get("host_network") != network:
        clone_kwargs["host_network"] = network
        changes.append("host_network")
    if protocol and not clone_kwargs.get("host_protocol"):
        clone_kwargs["host_protocol"] = protocol
        changes.append("host_protocol")
    if (
        network
        and network not in _FLOWS_VALID_NETWORKS
        and clone_kwargs.get("flow")
    ):
        clone_kwargs["flow"] = None
        changes.append("flow")
    return changes


def _build_clone_remark(
    pattern: str,
    donor_remark: str,
    target_name: str,
    target_address: str,
    tag: str,
) -> str:
    """Apply the admin-supplied remark pattern. If empty, keep the
    donor's remark verbatim — the admin may want to edit them by hand
    afterwards."""
    if not pattern:
        return donor_remark
    return (
        pattern
        .replace("{donor_remark}", donor_remark)
        .replace("{target_name}", target_name)
        .replace("{target_address}", target_address)
        .replace("{tag}", tag)
    )


def _parse_reality_overrides(blob: str) -> tuple[dict[str, dict], Optional[str]]:
    """Accept either the list shape returned by
    `regenerate_reality_keys_on_node` (``[{"tag": "...",
    "reality_public_key": "...", "reality_short_ids": [...]}, ...]``)
    or a tag-keyed dict. Returns ``({}, error_msg)`` on parse failure."""
    if not blob:
        return {}, None
    try:
        parsed = json.loads(blob)
    except Exception as exc:
        return {}, f"reality_overrides_json is not valid JSON: {exc}"
    if isinstance(parsed, list):
        out: dict[str, dict] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            tag = item.get("tag")
            if isinstance(tag, str) and tag:
                out[tag] = item
        return out, None
    if isinstance(parsed, dict):
        return {k: v for k, v in parsed.items() if isinstance(v, dict)}, None
    return {}, "reality_overrides_json must be a JSON list or object"


@register_tool(
    name="regenerate_reality_keys_on_node",
    description=(
        "Rotate Reality `privateKey` and `shortIds` for every "
        "vless+reality inbound currently configured in xray on a "
        "node, then restart xray with the new config. "
        "Use right after `clone_node_config` when the freshly cloned "
        "target inherited the donor's reality keys and you want each "
        "node to have its own — leak of one node's private key does "
        "NOT compromise siblings then. "
        "Inputs: `node_id`. Optional `only_inbound_tags` (list of "
        "strings) limits rotation to specific inbounds; default "
        "rotates all eligible. Optional `backend` defaults to "
        "'xray'. "
        "Returns `regenerated`: a list of `{tag, "
        "reality_public_key, reality_short_ids}` per affected "
        "inbound — ready to be passed verbatim to "
        "`clone_donor_hosts_to_target.reality_overrides_json`. "
        "Skips non-vless or non-reality inbounds (reported in "
        "`skipped`). After this returns successfully the panel's "
        "automatic post-restart `_sync()` will refresh the target "
        "inbound rows in the DB with the new config — there is "
        "nothing else to do on the panel side. "
        "Subscriptions previously issued to clients pointing at this "
        "node will stop working until they re-import — make sure "
        "the admin actually wants the rotation. Requires confirmation."
    ),
    requires_confirmation=True,
)
async def regenerate_reality_keys_on_node(
    db: Session,
    node_id: int,
    only_inbound_tags: list = [],
    backend: str = "xray",
) -> dict:
    from nacl.public import PrivateKey

    from app.marznode import node_registry

    db.close()

    node = node_registry.get(node_id)
    if not node:
        return {
            "error": (
                f"Node {node_id} is not connected (not in registry). "
                f"Call enable_node({node_id}) first, wait ~15s, retry."
            )
        }

    try:
        config_str, config_format = await node.get_backend_config(name=backend)
    except Exception as exc:
        return {"error": f"Failed to fetch xray config: {exc}"}

    if int(config_format) != _CONFIG_FORMAT_JSON:
        return {
            "error": (
                "Reality regeneration requires a JSON xray config "
                f"(got config_format={int(config_format)}). Convert "
                "the node config to JSON first."
            )
        }

    try:
        config = json.loads(config_str)
    except Exception as exc:
        return {"error": f"Failed to parse xray config as JSON: {exc}"}

    only_tags_set = {t for t in (only_inbound_tags or []) if isinstance(t, str)}
    inbounds = config.get("inbounds") or []
    if not isinstance(inbounds, list):
        return {"error": "xray config has no `inbounds` array"}

    regenerated: list[dict] = []
    skipped: list[dict] = []
    for inbound in inbounds:
        if not isinstance(inbound, dict):
            continue
        tag = inbound.get("tag", "")
        if only_tags_set and tag not in only_tags_set:
            continue

        stream = inbound.get("streamSettings") or {}
        if (
            inbound.get("protocol") != "vless"
            or stream.get("security") != "reality"
        ):
            skipped.append({"tag": tag, "reason": "not vless+reality"})
            continue

        reality = stream.get("realitySettings") or {}
        old_short_ids = [
            s for s in (reality.get("shortIds") or []) if isinstance(s, str)
        ]
        target_short_ids_count = max(1, len([s for s in old_short_ids if s]) or 1)

        priv = PrivateKey.generate()
        new_priv = _b64url_nopad(bytes(priv))
        new_pub = _b64url_nopad(bytes(priv.public_key))
        new_sids = [secrets.token_hex(8) for _ in range(target_short_ids_count)]

        reality["privateKey"] = new_priv
        reality["shortIds"] = new_sids
        # Some xray builds echo the publicKey back in realitySettings —
        # remove the stale donor value so xray recomputes from the
        # privateKey we just set.
        reality.pop("publicKey", None)
        stream["realitySettings"] = reality
        inbound["streamSettings"] = stream

        regenerated.append({
            "tag": tag,
            "reality_public_key": new_pub,
            "reality_short_ids": new_sids,
        })

    if not regenerated:
        return {
            "node_id": node_id,
            "regenerated": [],
            "skipped": skipped,
            "warning": (
                "No vless+reality inbounds were touched — either the "
                "node has no reality inbounds, or only_inbound_tags "
                "filtered them all out."
            ),
        }

    new_config_str = json.dumps(config, ensure_ascii=False, indent=2)
    try:
        await node.restart_backend(
            name=backend,
            config=new_config_str,
            config_format=int(config_format),
        )
    except Exception as exc:
        return {
            "node_id": node_id,
            "error": (
                f"Generated new keys in memory but failed to apply "
                f"config to {backend} on the node: {exc}. The node "
                f"is still running with the OLD keys."
            ),
            "regenerated_in_memory": regenerated,
        }

    return {
        "success": True,
        "node_id": node_id,
        "regenerated": regenerated,
        "skipped": skipped,
        "config_size_bytes": len(new_config_str),
        "next_step_hint": (
            "Pass `regenerated` JSON-encoded into "
            "`clone_donor_hosts_to_target.reality_overrides_json` so "
            "the cloned host entries on this node embed the new keys."
        ),
    }


@register_tool(
    name="clone_donor_hosts_to_target",
    description=(
        "Replicate every host of `donor_node_id` onto the matching "
        "inbound (same tag) of `target_node_id`. The clone keeps "
        "every donor host field that defines the wire-level handshake "
        "(port, sni, host, network, fingerprint, alpn, fragment, "
        "udp_noises, http_headers, splithttp_settings, mux_settings, "
        "mlkem_*, flow, shadowtls_version, shadowsocks_method, "
        "header_type, allowinsecure, is_disabled, weight, universal, "
        "uuid, password, security, etc.) and overrides only:\n"
        " - `address` ← `host_address_override` if non-empty, else "
        "the target node's `nodes.address` from the DB,\n"
        " - `remark` ← rendered from `remark_pattern` if non-empty "
        "(supports `{donor_remark}`, `{target_name}`, "
        "`{target_address}`, `{tag}` placeholders), else the donor's "
        "remark verbatim,\n"
        " - `reality_public_key` / `reality_short_ids` ← lookup by "
        "tag in `reality_overrides_json` if provided. The expected "
        "shape is exactly what `regenerate_reality_keys_on_node` "
        "returns: `[{\"tag\": \"...\", \"reality_public_key\": "
        "\"...\", \"reality_short_ids\": [...]}, ...]`. Tags not "
        "listed there fall back to the donor host's own values.\n"
        " - `inbound_id` ← the target's inbound that has the same "
        "tag as the donor's inbound for this host.\n"
        " - `host_network` / `host_protocol` / `flow` ← coerced to "
        "match the target's LIVE xray inbound (when "
        "`normalize_to_target_xray=true`, default). Specifically: "
        "`host_network` is overwritten with xray's `streamSettings."
        "network` (e.g. donor `tcp` host cloned onto an `xhttp` "
        "target inbound becomes `xhttp`); `flow=xtls-rprx-vision` is "
        "stripped on non-tcp/non-raw networks (the flow is TCP-only "
        "and renders the host invalid in subscriptions otherwise — "
        "this was the root cause of new XHTTP hosts not appearing on "
        "UNIVERSAL 4 until they were patched by hand). The list of "
        "normalized fields is reported per-host in `created_hosts[]."
        "normalized_fields`. Disable with "
        "`normalize_to_target_xray=false` only if you want to "
        "preserve donor field values verbatim (rare).\n"
        "Service binding: each clone is attached to the SAME "
        "`InboundHost.services` rows as the donor host it was cloned "
        "from when `services_inherit=true` (default). Set false to "
        "leave the clone unbound from services directly (it will "
        "still be visible to a service through the inbound→service "
        "linkage if `propagate_node_to_services` ran).\n"
        "Cleanup: when `delete_placeholder_hosts=true` (default), "
        "removes default placeholder hosts on the target's inbounds "
        "(those whose address is literally `{SERVER_IP}`, seeded by "
        "`add_default_hosts` when a new inbound is first observed) "
        "so the panel does not end up with both a placeholder and a "
        "real clone for the same inbound. "
        "Returns `created_hosts` (per-clone summary), "
        "`skipped_donor_hosts` (donor tag had no matching target "
        "inbound), `unmatched_donor_tags`, "
        "`deleted_placeholder_host_ids`. Requires confirmation "
        "(writes hosts table)."
    ),
    requires_confirmation=True,
)
async def clone_donor_hosts_to_target(
    db: Session,
    donor_node_id: int,
    target_node_id: int,
    host_address_override: str = "",
    remark_pattern: str = "",
    reality_overrides_json: str = "",
    services_inherit: bool = True,
    delete_placeholder_hosts: bool = True,
    normalize_to_target_xray: bool = True,
    backend: str = "xray",
) -> dict:
    from app.db.models import Inbound, InboundHost, Node

    if donor_node_id == target_node_id:
        return {"error": "donor and target must differ"}

    target_node = db.query(Node).filter(Node.id == target_node_id).first()
    if not target_node:
        return {"error": f"Target node {target_node_id} not found"}
    donor_node = db.query(Node).filter(Node.id == donor_node_id).first()
    if not donor_node:
        return {"error": f"Donor node {donor_node_id} not found"}

    target_address = (host_address_override or "").strip() or target_node.address
    if not target_address:
        return {
            "error": (
                "Could not determine an address for the cloned hosts: "
                "host_address_override is empty AND the target node "
                "has no address set in the DB."
            )
        }
    target_name = target_node.name or f"node-{target_node_id}"

    overrides, ov_err = _parse_reality_overrides(reality_overrides_json)
    if ov_err:
        return {"error": ov_err}

    donor_inbounds = (
        db.query(Inbound).filter(Inbound.node_id == donor_node_id).all()
    )
    target_inbounds = (
        db.query(Inbound).filter(Inbound.node_id == target_node_id).all()
    )
    if not donor_inbounds:
        return {"error": f"Donor node {donor_node_id} has no inbounds"}
    if not target_inbounds:
        return {
            "error": (
                f"Target node {target_node_id} has no inbounds — run "
                f"clone_node_config({donor_node_id}, {target_node_id}) "
                "first so the target's xray learns the donor's "
                "inbound tags."
            )
        }

    target_by_tag = {i.tag: i for i in target_inbounds}
    donor_inbound_by_id = {i.id: i for i in donor_inbounds}
    unmatched_tags = sorted(
        {i.tag for i in donor_inbounds} - set(target_by_tag.keys())
    )

    target_xray_meta_by_tag: dict[str, dict] = {}
    target_xray_meta_error: Optional[str] = None
    if normalize_to_target_xray:
        target_xray_meta_by_tag, target_xray_meta_error = (
            await _fetch_target_xray_inbound_map(target_node_id, backend)
        )

    deleted_placeholder_ids: list[int] = []
    if delete_placeholder_hosts:
        target_inbound_ids = [i.id for i in target_inbounds]
        placeholders = (
            db.query(InboundHost)
            .filter(InboundHost.inbound_id.in_(target_inbound_ids))
            .filter(InboundHost.address == _PLACEHOLDER_HOST_ADDRESS)
            .all()
        )
        for ph in placeholders:
            deleted_placeholder_ids.append(ph.id)
            db.delete(ph)
        if placeholders:
            db.flush()

    donor_hosts = (
        db.query(InboundHost)
        .filter(InboundHost.inbound_id.in_(donor_inbound_by_id.keys()))
        .all()
    )
    if not donor_hosts:
        return {
            "donor_node_id": donor_node_id,
            "target_node_id": target_node_id,
            "target_address_used": target_address,
            "deleted_placeholder_host_ids": deleted_placeholder_ids,
            "created_hosts": [],
            "skipped_donor_hosts": [],
            "unmatched_donor_tags": unmatched_tags,
            "warning": (
                "Donor has no host entries — nothing to clone. The "
                "target's subscriptions will only show the default "
                "placeholder hosts unless you create real ones."
            ),
        }

    created: list[dict] = []
    skipped: list[dict] = []

    for dh in donor_hosts:
        donor_inbound = donor_inbound_by_id.get(dh.inbound_id)
        if donor_inbound is None:
            continue
        tag = donor_inbound.tag
        target_inbound = target_by_tag.get(tag)
        if target_inbound is None:
            skipped.append({
                "donor_host_id": dh.id,
                "donor_remark": dh.remark,
                "tag": tag,
                "reason": "no matching target inbound tag",
            })
            continue

        clone_kwargs: dict = {f: getattr(dh, f) for f in _CLONABLE_HOST_FIELDS}
        clone_kwargs["address"] = target_address
        clone_kwargs["remark"] = _build_clone_remark(
            pattern=remark_pattern,
            donor_remark=dh.remark or "",
            target_name=target_name,
            target_address=target_address,
            tag=tag,
        )
        clone_kwargs["inbound_id"] = target_inbound.id

        ov = overrides.get(tag)
        if ov:
            pubk = ov.get("reality_public_key") or ov.get("public_key")
            sids = ov.get("reality_short_ids") or ov.get("short_ids")
            clone_kwargs["reality_public_key"] = (
                pubk if pubk is not None else dh.reality_public_key
            )
            clone_kwargs["reality_short_ids"] = (
                sids if sids is not None else dh.reality_short_ids
            )
        else:
            clone_kwargs["reality_public_key"] = dh.reality_public_key
            clone_kwargs["reality_short_ids"] = dh.reality_short_ids

        normalized_fields = _normalize_host_kwargs_to_target(
            clone_kwargs, target_xray_meta_by_tag.get(tag)
        )

        clone = InboundHost(**clone_kwargs)
        if services_inherit and dh.services:
            clone.services = list(dh.services)
        db.add(clone)
        db.flush()
        created.append({
            "id": clone.id,
            "tag": tag,
            "remark": clone.remark,
            "address": clone.address,
            "port": clone.port,
            "reality_keys_overridden": tag in overrides,
            "services_count": len(clone.services or []),
            "normalized_fields": normalized_fields,
        })

    db.commit()

    return {
        "success": True,
        "donor_node_id": donor_node_id,
        "target_node_id": target_node_id,
        "target_address_used": target_address,
        "remark_pattern_used": remark_pattern or "(donor remark unchanged)",
        "deleted_placeholder_host_ids": deleted_placeholder_ids,
        "created_hosts": created,
        "skipped_donor_hosts": skipped,
        "unmatched_donor_tags": unmatched_tags,
        "normalize_to_target_xray": normalize_to_target_xray,
        "target_xray_inbound_count": len(target_xray_meta_by_tag),
        "target_xray_meta_warning": target_xray_meta_error,
    }
