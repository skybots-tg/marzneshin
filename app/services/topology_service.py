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

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.models import Inbound, InboundHost, Node
from app.utils.fleet_taxonomy import (
    classify_tier,
    entry_key,
    exit_label,
    flag_to_iso,
)

__all__ = ["build_topology", "flag_to_iso"]


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
        return entry_key(self.tier, self.index)


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
        tier, idx = classify_tier(host.remark)
        if tier is None:
            continue
        iso = flag_to_iso(host.remark)
        label = exit_label(host.remark)
        if iso:
            all_isos.add(iso)

        if tier == "fast":
            if iso:
                fast_isos.setdefault(
                    iso, {"iso": iso, "label": label, "node_ids": set()}
                )["node_ids"].add(node.id)
            continue

        key = entry_key(tier, idx)
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
