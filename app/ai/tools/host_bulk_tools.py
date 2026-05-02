"""Bulk substring operations on host `remark` fields.

These tools exist primarily to keep the LLM out of the emoji-retyping
business. When the admin asks "replace `Франция` with `FR` everywhere",
the agent must NOT print before/after pairs into chat by hand — its
tokenizer silently drops variation selectors (U+FE0F), zero-width
joiners, and skin-tone modifiers, so the visible string in chat looks
identical to the data but is, byte-for-byte, a different remark. The
admin notices because sorting, filtering, and copy-paste compare break.

`preview_remark_replace` returns the exact before/after strings straight
from the database, so the agent can show the diff to the admin without
ever touching the codepoints. `bulk_replace_in_remarks` performs the
write in a single transaction with one approval modal, so a fleet-wide
rename does not balloon into 70+ individual `modify_host` clicks.

Both tools accept a `scope` filter so the same rename can be safely
limited to universal hosts, a single inbound, or a single node — useful
when the convention only applies to part of the panel.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool

logger = logging.getLogger(__name__)

_MAX_PREVIEW_ROWS = 500
_VALID_SCOPES = {"all", "universal", "non_universal"}


def _scope_query(
    db: Session,
    scope: str,
    inbound_id: int,
    node_id: int,
):
    from app.db.models import Inbound, InboundHost

    query = db.query(InboundHost)

    if scope == "universal":
        query = query.filter(
            InboundHost.universal == True,  # noqa: E712
            InboundHost.inbound_id.is_(None),
        )
    elif scope == "non_universal":
        query = query.filter(InboundHost.inbound_id.isnot(None))

    if inbound_id > 0:
        query = query.filter(InboundHost.inbound_id == inbound_id)

    if node_id > 0:
        query = query.join(
            Inbound, InboundHost.inbound_id == Inbound.id
        ).filter(Inbound.node_id == node_id)

    return query.order_by(
        InboundHost.weight.desc(), InboundHost.id.desc()
    )


def _normalise_scope(scope: str) -> str:
    s = (scope or "all").strip().lower()
    if s not in _VALID_SCOPES:
        return ""
    return s


def _match(haystack: str, needle: str, case_sensitive: bool) -> bool:
    if case_sensitive:
        return needle in haystack
    return needle.lower() in haystack.lower()


def _replace(
    haystack: str, old: str, new: str, case_sensitive: bool
) -> str:
    """Substring replace.

    Case-insensitive mode preserves the original casing of non-matching
    parts (only the matched substring is rewritten as `new`). Implemented
    by walking the string instead of using `re.sub` so the admin's
    literal `old`/`new` are never reinterpreted as regex metacharacters.
    """
    if case_sensitive:
        return haystack.replace(old, new)

    if not old:
        return haystack

    lower_hay = haystack.lower()
    lower_old = old.lower()
    if lower_old not in lower_hay:
        return haystack

    out_parts: list[str] = []
    start = 0
    n = len(haystack)
    step = len(old)
    while start <= n - step:
        if lower_hay[start : start + step] == lower_old:
            out_parts.append(new)
            start += step
        else:
            out_parts.append(haystack[start])
            start += 1
    out_parts.append(haystack[start:])
    return "".join(out_parts)


@register_tool(
    name="preview_remark_replace",
    description=(
        "READ-ONLY preview of a bulk substring replace in host `remark` fields. "
        "Use this BEFORE `bulk_replace_in_remarks` whenever the admin asks to "
        "rename / sed-style replace something across many hosts (e.g. shorten "
        "country names: 'Франция' -> 'FR', 'Финляндия' -> 'FI'). "
        "Returns each affected host's exact `before` and `after` strings "
        "straight from the database — DO NOT retype these in chat from your "
        "own output, the tool result is the source of truth (emoji variation "
        "selectors and ZWJ are preserved only in the tool result, not in your "
        "tokenized text). "
        "Args: `old` (substring to find, required), `new` (replacement, "
        "required, may be empty to delete the substring), `scope` "
        "('all'|'universal'|'non_universal', default 'all'), `inbound_id` "
        "(0 = any), `node_id` (0 = any), `case_sensitive` (default true). "
        "Caps the matches list at 500 rows; if more match, `truncated=true` "
        "and the admin should narrow the scope or use `bulk_replace_in_remarks` "
        "directly (it has no preview cap)."
    ),
    requires_confirmation=False,
)
async def preview_remark_replace(
    db: Session,
    old: str,
    new: str,
    scope: str = "all",
    inbound_id: int = 0,
    node_id: int = 0,
    case_sensitive: bool = True,
) -> dict:
    if not old:
        return {"error": "old must be a non-empty substring"}

    norm = _normalise_scope(scope)
    if not norm:
        return {
            "error": (
                f"Invalid scope '{scope}'. Allowed: {sorted(_VALID_SCOPES)}"
            )
        }

    query = _scope_query(db, norm, inbound_id, node_id)
    total_scanned = query.count()
    rows = query.all()

    matches: list[dict] = []
    for h in rows:
        remark = h.remark or ""
        if not _match(remark, old, case_sensitive):
            continue
        after = _replace(remark, old, new, case_sensitive)
        if after == remark:
            continue
        matches.append({
            "host_id": h.id,
            "before": remark,
            "after": after,
            "universal": bool(h.universal),
            "inbound_id": h.inbound_id,
        })

    truncated = len(matches) > _MAX_PREVIEW_ROWS
    capped = matches[:_MAX_PREVIEW_ROWS] if truncated else matches

    return {
        "old": old,
        "new": new,
        "scope": norm,
        "case_sensitive": bool(case_sensitive),
        "matches": capped,
        "total_matches": len(matches),
        "total_scanned": int(total_scanned),
        "truncated": truncated,
        "preview_cap": _MAX_PREVIEW_ROWS,
    }


@register_tool(
    name="bulk_replace_in_remarks",
    description=(
        "Replace a literal substring inside `remark` for every host that "
        "matches the scope filter, in a SINGLE transaction with ONE approval "
        "modal. Prefer this over firing 50+ individual `modify_host` calls "
        "for fleet-wide renames (e.g. 'Франция' -> 'FR' across all hosts). "
        "Strongly recommended workflow: call `preview_remark_replace` with "
        "the same args first, show the admin the diff, then call this. "
        "Args: `old` (required, literal substring — NOT regex), `new` "
        "(required, may be empty to delete `old`), `scope` "
        "('all'|'universal'|'non_universal', default 'all'), `inbound_id` "
        "(0 = any), `node_id` (0 = any), `case_sensitive` (default true), "
        "`max_changes` (safety cap, default 200; the call refuses to run if "
        "more rows would change — re-run with a tighter scope or a higher "
        "cap if that is intentional). "
        "Returns the list of `{host_id, before, after}` rows that were "
        "actually written, plus how many rows in scope were untouched."
    ),
    requires_confirmation=True,
)
async def bulk_replace_in_remarks(
    db: Session,
    old: str,
    new: str,
    scope: str = "all",
    inbound_id: int = 0,
    node_id: int = 0,
    case_sensitive: bool = True,
    max_changes: int = 200,
) -> dict:
    if not old:
        return {"error": "old must be a non-empty substring"}

    norm = _normalise_scope(scope)
    if not norm:
        return {
            "error": (
                f"Invalid scope '{scope}'. Allowed: {sorted(_VALID_SCOPES)}"
            )
        }

    if max_changes is None or max_changes <= 0:
        max_changes = 200

    query = _scope_query(db, norm, inbound_id, node_id)
    rows = query.all()
    total_scanned = len(rows)

    planned: list[tuple[object, str, str]] = []
    for h in rows:
        remark = h.remark or ""
        if not _match(remark, old, case_sensitive):
            continue
        after = _replace(remark, old, new, case_sensitive)
        if after == remark:
            continue
        planned.append((h, remark, after))

    if len(planned) > max_changes:
        return {
            "error": (
                f"Refusing to apply: {len(planned)} hosts would change, "
                f"which exceeds max_changes={max_changes}. Tighten the "
                f"scope (universal_only / inbound_id / node_id) or raise "
                f"max_changes if this is intentional."
            ),
            "would_change": len(planned),
            "max_changes": int(max_changes),
            "scope": norm,
            "total_scanned": int(total_scanned),
        }

    updated: list[dict] = []
    try:
        for host, before, after in planned:
            host.remark = after
            updated.append({
                "host_id": host.id,
                "before": before,
                "after": after,
            })
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("bulk_replace_in_remarks failed")
        return {"error": f"Failed to apply replacement: {exc}"}

    return {
        "success": True,
        "old": old,
        "new": new,
        "scope": norm,
        "case_sensitive": bool(case_sensitive),
        "updated": updated,
        "updated_count": len(updated),
        "skipped_count": total_scanned - len(updated),
        "total_scanned": int(total_scanned),
    }
