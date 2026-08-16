"""How the fleet names itself: tiers, exit slots, and entry->exit links.

The panel has no schema for "this host is UNIVERSAL 2's Romanian exit" -- that
knowledge lives in free-form host remarks like ``🇷🇴 🛜 UNIVERSAL 2 ♾️ RO`` and in
inbound tags like ``RU->RO Bridge``. Two separate readers used to parse them:
``app.services.topology_service`` for the dashboard and ``tools/bridge_lib.py``
for the host-side audit. They carried byte-identical copies of the same regexes,
so a remark convention could drift in one and not the other.

This module is the single parser. It is deliberately stdlib-only and free of any
``app`` imports, because ``tools/`` runs it outside the API container with no
sqlalchemy available.
"""

from __future__ import annotations

import re
from typing import Optional

__all__ = [
    "TIER_PATTERNS",
    "EGRESS_COUNTRY_OVERRIDES",
    "classify_tier",
    "egress_country",
    "flag_to_iso",
    "exit_label",
    "exit_slot",
    "entry_key",
    "link_key",
]

# Egress addresses the geo services get wrong, with the country the registry
# actually records. Only for cases checked against RIPE or ARIN — this exists
# to stop the audit crying wolf every night, not to paper over a mislabelled
# server. A host whose flag really is wrong should be renamed, not listed here.
#
#   85.204.107.56 — RIPE: RO, "ZetServers Bucharest". ip-api and ipinfo both
#                   place it in France.
EGRESS_COUNTRY_OVERRIDES = {
    "85.204.107.56": "RO",
}

# tier label -> regex capturing the tier index ("UNIVERSAL 2" -> 2). The index
# is optional: a handful of entries are named without one ("ELITE LUX - PL",
# "ELITE DE РАБОТАЕТ ВСЕГДА") and they are in real subscriptions, so refusing to
# classify them means never auditing them.
TIER_PATTERNS = {
    "universal": re.compile(r"UNIVERSAL\s+(\d+)?", re.IGNORECASE),
    "elite": re.compile(r"ELITE\s+(\d+)?", re.IGNORECASE),
    "fast": re.compile(r"FAST\s+(\d+)?", re.IGNORECASE),
}

# Separators remarks use between the tier and the exit it offers.
_EXIT_SEPARATORS = ("♾️", " - ", "—")

# Dropped when normalising a label into a slot: bracketed asides such as
# "[ 4G ]" or "(XHTTP)" describe the transport, not the exit server.
_SLOT_NOISE = re.compile(r"\[.*?\]|\(.*?\)|\bxhttp\b", re.IGNORECASE)


def classify_tier(remark: str) -> tuple[Optional[str], Optional[int]]:
    """``("universal", 2)`` for a UNIVERSAL 2 remark, ``(None, None)`` if none.

    The index is ``None`` for a tier named without one. Callers that group by
    entry — the topology dashboard — should skip those; callers that only need
    to know which tier a host belongs to should not.
    """
    for tier, pattern in TIER_PATTERNS.items():
        match = pattern.search(remark or "")
        if match:
            index = match.group(1)
            return tier, int(index) if index else None
    return None, None


def flag_to_iso(text: str) -> Optional[str]:
    """ISO2 of the first regional-indicator flag emoji in ``text``.

    Regional indicators live at U+1F1E6 (A) .. U+1F1FF (Z) and a flag is two of
    them, so ``"🇷🇴 UNIVERSAL 2"`` yields ``"RO"``.
    """
    indicators = [
        chr(ord(c) - 0x1F1E6 + ord("A"))
        for c in text or ""
        if 0x1F1E6 <= ord(c) <= 0x1F1FF
    ]
    return "".join(indicators[:2]) if len(indicators) >= 2 else None


def exit_label(remark: str) -> str:
    """The human exit label: whatever follows the last separator."""
    for sep in _EXIT_SEPARATORS:
        if sep in (remark or ""):
            return remark.rsplit(sep, 1)[-1].strip()
    return (remark or "").strip()


def exit_slot(remark: str) -> str:
    """The exit *slot* a remark advertises, e.g. ``FR-2``, ``DE``, ``RU``.

    Slot, not ISO: DE and DE-2 are distinct exit servers the user picks between,
    so a gap analysis has to treat them as separate columns. The transport
    variant is not part of the slot -- ``DE`` and ``DE xhttp`` are the same exit
    reached two ways.
    """
    text = exit_label(remark)
    text = re.sub(r"[^\x00-\x7f]", " ", text)
    text = _SLOT_NOISE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # "FAST 1 ♾️ - TR" splits on the ♾️ and leaves the dash behind, which then
    # rides along into every matrix column as "- TR".
    return text.lstrip("-—– ").strip().upper() or "?"


def egress_country(reported: Optional[str], egress_ip: Optional[str]) -> Optional[str]:
    """What country the traffic really surfaced in.

    Geo services are guesses over a database, and they are not always right;
    where the registry says otherwise, the registry wins.
    """
    if egress_ip and egress_ip in EGRESS_COUNTRY_OVERRIDES:
        return EGRESS_COUNTRY_OVERRIDES[egress_ip]
    return reported


def entry_key(tier: str, tier_index: Optional[int], node_id=None) -> str:
    """Stable id of an entry group, e.g. ``universal-2``.

    An entry named without an index falls back to its node (``elite-n33``) so
    that unnumbered entries on different servers stay distinct rather than
    piling into one row.
    """
    if tier_index is None:
        return f"{tier}-n{node_id}" if node_id is not None else f"{tier}-?"
    return f"{tier}-{tier_index}"


def link_key(entry_node_id: int, exit_ref, variant: str = "tcp") -> str:
    """Stable id of one entry->exit leg, e.g. ``25>FR-2/tcp``.

    ``exit_ref`` is the exit *slot* rather than a node id on purpose. Slots come
    from the remark and are stable, while ``inbounds.exit_node_id`` is still
    being backfilled and is NULL for exits that were never registered as nodes
    (the EE and FL servers, for two). Keying on the slot means a link keeps its
    identity -- and its failure streak -- across that backfill.

    ``variant`` keeps tcp and xhttp apart: they ride the same pair of servers
    but fail independently. A direct (non-bridge) inbound has no exit leg; it
    passes its own identity as ``exit_ref``, or ``None`` for the degenerate
    "the node itself" case.
    """
    exit_part = "direct" if exit_ref in (None, "") else str(exit_ref)
    return f"{entry_node_id}>{exit_part}/{variant}"
