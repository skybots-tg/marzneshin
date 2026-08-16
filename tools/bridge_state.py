#!/usr/bin/env python3
"""Decide what to hide and what to bring back, across runs.

A single probe is a weak thing to hang a subscription on. A vantage hiccups, a
provider drops one handshake, ip-api rate-limits, and a perfectly good server
disappears for everyone. So nothing here acts on one observation:

* the unit is the **link** -- one entry node's leg to one exit slot -- because
  that is what actually breaks when two servers stop talking. A single dead host
  on a link whose siblings work is a config problem for a human, not an outage,
  and is left alone;
* a link has to fail twice in a row before it is hidden, and pass twice in a row
  before it comes back;
* the probe is cross-checked against ``node_usages``, which counts bytes real
  users moved. A node sitting at a flat zero while its status is unhealthy is
  hidden immediately -- no streak needed, the evidence is already in. And when
  *every* link on a node fails at once while that node is visibly carrying
  traffic, nothing is hidden at all: fifteen legs do not die in the same second,
  so the probe lost its footing rather than the fleet. That is not
  hypothetical -- node 43 once refused TLS from the panel and from two RU
  vantages while node 30 and real subscribers were using it perfectly well;
* only hosts this module hid are ever un-hidden. Hosts hidden by hand stay
  hidden -- most were retired on purpose while a node was being replaced.

State lives next to the audit report in ``/var/lib/marzneshin`` and is pure JSON;
this module never touches the database.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

DATA_DIR = os.getenv("MARZ_DATA_DIR", "/var/lib/marzneshin")
STATE_PATH = os.path.join(DATA_DIR, "bridge_state.json")

# Consecutive runs a link must fail before it is hidden, and pass before it is
# restored. Two is enough to ride out a single bad vantage without leaving a
# genuinely dead link in subscriptions for long.
FAIL_STREAK_TO_HIDE = 2
PASS_STREAK_TO_RESTORE = 2

# How far back to ask node_usages, and how few bytes counts as "nothing". The
# table is written in hourly buckets, so the window has to span several of them
# to be meaningful; 1 MiB is noise-level for a node with any user on it at all.
TRAFFIC_WINDOW_HOURS = 6
SILENT_NODE_BYTES = 1 << 20

# Verdicts that mean traffic reached the far end. wrong_geo is a labelling bug,
# not an outage -- the tunnel works, it just surfaces somewhere unexpected.
LIVE_VERDICTS = ("pass", "wrong_geo")


@dataclass
class LinkView:
    """Every host riding one entry->exit leg, plus how that leg tested."""
    key: str
    entry_node_id: int
    entry_node_name: str
    entry_node_status: str
    exit_node_id: int | None
    slot: str
    variant: str
    entry_key: str
    is_bridge: bool
    host_ids: list[int] = field(default_factory=list)
    enabled_host_ids: list[int] = field(default_factory=list)
    live_host_ids: list[int] = field(default_factory=list)
    dead_host_ids: list[int] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """``up`` if anything got through, ``down`` if nothing did, else ``skip``."""
        if self.live_host_ids:
            return "up"
        if self.dead_host_ids:
            return "down"
        return "skip"

    def brief(self) -> dict:
        return {
            "link": self.key, "entry_key": self.entry_key, "slot": self.slot,
            "variant": self.variant, "entry_node_id": self.entry_node_id,
            "entry_node_name": self.entry_node_name,
            "exit_node_id": self.exit_node_id, "is_bridge": self.is_bridge,
            "verdict": self.verdict, "host_ids": sorted(self.host_ids),
            "enabled": len(self.enabled_host_ids),
            "live": len(self.live_host_ids), "dead": len(self.dead_host_ids),
        }


def roll_up(targets) -> dict[str, LinkView]:
    """Group probed targets into links."""
    links: dict[str, LinkView] = {}
    for t in targets:
        link = links.get(t.link_key)
        if link is None:
            link = LinkView(
                key=t.link_key, entry_node_id=t.node_id,
                entry_node_name=t.node_name, entry_node_status=t.node_status,
                exit_node_id=t.exit_node_id, slot=t.slot, variant=t.variant,
                entry_key=t.entry_key, is_bridge=t.is_bridge,
            )
            links[t.link_key] = link
        # exit_node_id is backfilled per inbound, so the first sibling that
        # knows its exit teaches the whole link.
        if link.exit_node_id is None and t.exit_node_id is not None:
            link.exit_node_id = t.exit_node_id
        link.host_ids.append(t.host_id)
        if not t.is_disabled:
            link.enabled_host_ids.append(t.host_id)
        verdict = (t.result or {}).get("verdict")
        if verdict in LIVE_VERDICTS:
            link.live_host_ids.append(t.host_id)
        elif verdict == "fail":
            link.dead_host_ids.append(t.host_id)
    return links


def load(path: str = STATE_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, ValueError):
        state = {}
    state.setdefault("links", {})
    state.setdefault("auto_disabled", {})
    return state


def save(state: dict, path: str = STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    state["updated_at"] = int(time.time())
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _verdicts_by_node(links: dict[str, LinkView]) -> dict[int, list[str]]:
    """entry node -> the verdict of each of its links that was probed at all."""
    out: dict[int, list[str]] = {}
    for link in links.values():
        if link.verdict != "skip":
            out.setdefault(link.entry_node_id, []).append(link.verdict)
    return out


def _node_is_silent(node_id, traffic: dict[int, int], status: str) -> bool:
    """No bytes over the window *and* the panel cannot reach it either.

    Both halves matter. Silence alone can mean a location nobody picked today;
    an unhealthy status alone can mean one flaky gRPC poll. Together they are
    as close to proof of a dead node as this side of the wire gets.
    """
    if node_id is None:
        return False
    return (traffic.get(int(node_id), 0) < SILENT_NODE_BYTES
            and status != "healthy")


def decide(links: dict[str, LinkView], state: dict, traffic: dict[int, int],
           node_status: dict[int, str], visible_by_remark=None,
           remark_of=None, confirmed_links=None, node_wide_rule=True) -> dict:
    """Fold this run into the state and return the actions it justifies.

    ``visible_by_remark``/``remark_of`` implement the long-standing rule that a
    host never comes back while another visible host already answers to its
    name -- un-hiding those puts two identical entries in every subscription.

    ``confirmed_links`` names the links whose failure was established the
    thorough way. ``None`` means all of them, which is what a full sweep gets.
    A quick run passes only the ones it re-probed, so an unconfirmed failure
    can start a streak but never finish one -- otherwise a cold start would
    record a fleet's worth of hasty verdicts and the very next run would act on
    them.

    ``node_wide_rule`` is off for scans narrowed to a few hosts, where "every
    link on this node failed" is a property of the filter, not the node.
    """
    visible_by_remark = visible_by_remark or {}
    remark_of = remark_of or {}
    link_state = state["links"]
    auto = state["auto_disabled"]
    verdicts_by_node = _verdicts_by_node(links)

    disable: list[int] = []
    enable: list[int] = []
    notes: dict[str, dict] = {}

    for key, link in sorted(links.items()):
        prev = link_state.get(key, {"fail_streak": 0, "pass_streak": 0})
        verdict = link.verdict
        if verdict == "skip":
            # Not probed anywhere this run: leave the streaks exactly as they
            # were, so an unreachable vantage cannot age a link into hiding.
            notes[key] = {"verdict": "skip", **prev}
            continue

        entry_silent = _node_is_silent(
            link.entry_node_id, traffic,
            node_status.get(link.entry_node_id, link.entry_node_status))
        exit_silent = _node_is_silent(
            link.exit_node_id, traffic,
            node_status.get(link.exit_node_id, "healthy"))
        entry_bytes = traffic.get(link.entry_node_id, 0)

        if verdict == "down":
            fail_streak = prev.get("fail_streak", 0) + 1
            pass_streak = 0
            silent = entry_silent or exit_silent
            # Everything on this node failed, yet the node is moving real
            # traffic: believe the users, not the probe.
            probed = verdicts_by_node.get(link.entry_node_id, [])
            contested = (node_wide_rule
                         and not silent
                         and entry_bytes >= SILENT_NODE_BYTES
                         and len(probed) > 1
                         and all(v == "down" for v in probed))
            confirmed = confirmed_links is None or key in confirmed_links
            should_hide = not contested and confirmed and (
                silent or fail_streak >= FAIL_STREAK_TO_HIDE)
            reason = ("node_unreachable_but_busy" if contested else
                      "unconfirmed" if not confirmed else
                      "node_silent" if silent else
                      "link_down" if should_hide else "link_down_pending")
            if should_hide:
                for host_id in link.enabled_host_ids:
                    disable.append(host_id)
                    auto[str(host_id)] = {
                        "link": key, "reason": reason, "at": int(time.time()),
                    }
            notes[key] = {
                "verdict": "down", "fail_streak": fail_streak,
                "pass_streak": 0, "reason": reason, "contested": contested,
                "confirmed": confirmed, "entry_bytes": entry_bytes,
            }
        else:
            fail_streak = 0
            pass_streak = prev.get("pass_streak", 0) + 1
            # Refuse to restore into silence: if nothing is moving through the
            # node, a passing probe is the only witness and that is not enough.
            quiet = entry_silent or exit_silent
            ready = pass_streak >= PASS_STREAK_TO_RESTORE and not quiet
            restored = []
            if ready:
                for host_id in link.host_ids:
                    record = auto.get(str(host_id))
                    if record is None:
                        continue  # hidden by hand, or never hidden: leave it
                    remark = remark_of.get(host_id)
                    if remark and visible_by_remark.get(remark):
                        continue  # a visible twin already carries this name
                    enable.append(host_id)
                    restored.append(host_id)
            for host_id in restored:
                auto.pop(str(host_id), None)
            notes[key] = {
                "verdict": "up", "fail_streak": 0, "pass_streak": pass_streak,
                "reason": "restored" if restored else
                          ("held_no_traffic" if quiet else "up"),
                "contested": quiet,
                "entry_bytes": entry_bytes,
            }

        link_state[key] = {
            "fail_streak": notes[key]["fail_streak"],
            "pass_streak": notes[key]["pass_streak"],
            "verdict": verdict,
            "confirmed": notes[key].get("confirmed", True),
            "reason": notes[key]["reason"],
            "updated_at": int(time.time()),
        }

    # Links that vanished from the fleet should not keep state forever.
    for gone in set(link_state) - set(links):
        link_state.pop(gone, None)

    return {"disable": sorted(set(disable)), "enable": sorted(set(enable)),
            "links": notes}
