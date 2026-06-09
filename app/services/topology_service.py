"""Read-side helpers for the UNIVERSAL/ELITE/FAST topology dashboard.

The panel models its multi-tier VPN fleet implicitly through host
*remarks* (e.g. ``🇷🇴 🛜 UNIVERSAL 2 ♾️ RO``). This module turns those
free-form remarks into a structured view the dashboard can render:

- which entry nodes serve which tier (UNIVERSAL N / ELITE N),
- which exit countries each entry currently offers,
- which exit countries exist anywhere in the fleet, and
- the gaps (entry × country combinations that are missing).

It is intentionally pure-read and side-effect free; the orchestration
that *fills* the gaps lives in ``app.routes.topology``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import Inbound, InboundHost, Node

# tier label -> (regex capturing the tier index)
_TIER_PATTERNS = {
    "universal": re.compile(r"UNIVERSAL\s+(\d+)", re.IGNORECASE),
    "elite": re.compile(r"ELITE\s+(\d+)", re.IGNORECASE),
    "fast": re.compile(r"FAST\s+(\d+)", re.IGNORECASE),
}


def flag_to_iso(text: str) -> Optional[str]:
    """Extract the first regional-indicator flag emoji and return its ISO2.

    Regional indicator symbols live at U+1F1E6 (A) .. U+1F1FF (Z); a flag
    is two of them. Returns e.g. ``"RO"`` or ``None`` if no flag present.
    """
    indicators = [
        chr(ord(c) - 0x1F1E6 + ord("A"))
        for c in text
        if 0x1F1E6 <= ord(c) <= 0x1F1FF
    ]
    if len(indicators) >= 2:
        return "".join(indicators[:2])
    return None


def _exit_label(remark: str) -> str:
    """Best-effort human exit label = text after the last separator."""
    # remarks use ♾️ (universal), - (elite/fast) or similar as separators
    for sep in ("♾️", " - ", "—"):
        if sep in remark:
            return remark.rsplit(sep, 1)[-1].strip()
    return remark.strip()


@dataclass
class EntryNode:
    node_id: int
    name: str
    address: str
    status: str
    tier: str  # "universal" | "elite"
    index: int
    exit_isos: set[str] = field(default_factory=set)
    exit_labels: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.tier}-{self.index}"


def _classify_remark(remark: str):
    for tier, pat in _TIER_PATTERNS.items():
        m = pat.search(remark or "")
        if m:
            return tier, int(m.group(1))
    return None, None


def build_topology(db: Session) -> dict:
    """Return the structured topology view used by the dashboard."""
    rows = (
        db.query(InboundHost, Inbound, Node)
        .join(Inbound, InboundHost.inbound_id == Inbound.id)
        .join(Node, Inbound.node_id == Node.id)
        .all()
    )

    entries: dict[str, EntryNode] = {}
    fast_isos: dict[str, dict] = {}
    all_isos: set[str] = set()

    for host, inbound, node in rows:
        if host.is_disabled:
            continue
        tier, idx = _classify_remark(host.remark)
        if tier is None:
            continue
        iso = flag_to_iso(host.remark)
        label = _exit_label(host.remark)
        if iso:
            all_isos.add(iso)

        if tier == "fast":
            if iso:
                fast_isos.setdefault(
                    iso, {"iso": iso, "label": label, "node_ids": set()}
                )["node_ids"].add(node.id)
            continue

        key = f"{tier}-{idx}"
        entry = entries.get(key)
        if entry is None:
            entry = EntryNode(
                node_id=node.id,
                name=node.name,
                address=node.address,
                status=str(getattr(node.status, "value", node.status)),
                tier=tier,
                index=idx,
            )
            entries[key] = entry
        if iso:
            entry.exit_isos.add(iso)
            entry.exit_labels[iso] = label

    sorted_isos = sorted(all_isos)
    entry_list = sorted(
        entries.values(), key=lambda e: (e.tier, e.index)
    )

    entries_out = []
    for e in entry_list:
        missing = [iso for iso in sorted_isos if iso not in e.exit_isos]
        entries_out.append({
            "node_id": e.node_id,
            "name": e.name,
            "address": e.address,
            "status": e.status,
            "tier": e.tier,
            "index": e.index,
            "key": e.key,
            "exit_isos": sorted(e.exit_isos),
            "missing_isos": missing,
            "exit_count": len(e.exit_isos),
        })

    # nodes not classified as any entry → candidates to promote
    classified_node_ids = {e.node_id for e in entry_list}
    all_nodes = db.query(Node).all()
    candidates = [
        {
            "node_id": n.id,
            "name": n.name,
            "address": n.address,
            "status": str(getattr(n.status, "value", n.status)),
        }
        for n in all_nodes
        if n.id not in classified_node_ids
    ]

    return {
        "exit_countries": sorted_isos,
        "entries": entries_out,
        "fast": [
            {"iso": v["iso"], "label": v["label"],
             "node_count": len(v["node_ids"])}
            for v in sorted(fast_isos.values(), key=lambda x: x["iso"])
        ],
        "promote_candidates": candidates,
        "donor_nodes": [
            {"node_id": e.node_id, "name": e.name, "tier": e.tier,
             "index": e.index, "key": e.key, "exit_count": len(e.exit_isos)}
            for e in entry_list
        ],
    }
