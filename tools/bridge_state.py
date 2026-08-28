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
  hidden immediately -- no streak needed -- but only when more than one vantage
  saw it fail. Both of those signals reach the panel down the same gRPC
  connection, so a node the panel merely cannot *route* to reports zero bytes
  and unhealthy while serving its users perfectly well; nodes 24, 33 and 41 sat
  in exactly that state, answering from elsewhere while the panel called them
  dead. One witness is never enough to act quickly on;
* and when *every* link on a node fails at once while that node is visibly
  carrying traffic, nothing is hidden at all: fifteen legs do not die in the
  same second, so the probe lost its footing rather than the fleet. That is not
  hypothetical -- node 43 once refused TLS from the panel and from two RU
  vantages while node 30 and real subscribers were using it perfectly well;
* the same reasoning applies to the far end of a bridge. One exit node dying
  breaks every entry's leg to it at once, and since each leg is judged on its
  own, a single dead exit used to walk out of the subscription eight hosts at a
  time with nothing noticing the shape of it. An exit still carrying its usual
  traffic is therefore believed over the probe, exactly like an entry;
* nothing hides faster than the fleet can be reviewed: an automatic hide costs
  budget, and the last visible host of an entry or of a country is never taken
  quietly. Whatever exceeds the budget is *deferred*, not dropped -- it comes
  back as a suggestion on the next run and is printed in full;
* only hosts this module hid are ever un-hidden. Hosts hidden by hand stay
  hidden -- most were retired on purpose while a node was being replaced;
* and a hide is a lease rather than a verdict. Hiding takes one run, restoring
  takes two, so anything that stops the audit freezes the fleet at its most
  hidden -- the failure is not symmetric and cannot be left to sort itself out.
  ``hides_to_release`` names the recent hides to give back when the audit has
  gone quiet for too long to stand behind them.

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

# When only one vantage could speak for a link -- which is every FAST host,
# since the panel is the only foreign viewpoint we have -- its word alone is
# thin. A routing fault on that one machine is indistinguishable from the
# server being down. Waiting for four runs, roughly an hour, is long enough
# for a transient path problem to clear and still short enough that a genuinely
# dead server does not stay in subscriptions for the day.
FAIL_STREAK_SINGLE_WITNESS = 4

# How far back to ask node_usages, and how few bytes counts as "nothing". The
# table is written in hourly buckets, so the window has to span several of them
# to be meaningful; 1 MiB is noise-level for a node with any user on it at all.
TRAFFIC_WINDOW_HOURS = 6
SILENT_NODE_BYTES = 1 << 20

# Verdicts that mean traffic reached the far end. wrong_geo is a labelling bug,
# not an outage -- the tunnel works, it just surfaces somewhere unexpected.
LIVE_VERDICTS = ("pass", "wrong_geo")

# How an exit node's recent hours compare with the same hours of its own past
# week. Ratios rather than absolute bytes, because an exit that normally moves
# five gigabytes an hour and now moves twenty megabytes is plainly broken while
# still clearing any fixed "is it silent" bar by a wide margin -- that is how a
# whole country left the subscription overnight and looked like a healthy node
# the entire time. Above the busy line the exit is believed over the probe;
# below the collapse line the probe has independent corroboration and the hides
# it asks for are treated as one proven event.
EXIT_BUSY_RATIO = 0.5
EXIT_COLLAPSE_RATIO = 0.1
# Failing links to one exit before its own state is worth consulting. One leg
# says nothing about the far end; two legs from different entries do.
EXIT_WIDE_MIN_LINKS = 2

# Reasons whose evidence does not come from the probe alone. These are exempt
# from the rate limit: holding back a hide that traffic counters already confirm
# only leaves a dead server in subscriptions for longer.
CORROBORATED_REASONS = ("node_silent", "exit_down")

# Consecutive failures after which a hide is no longer up for review. The two
# mechanisms below both exist to protect a working server from a thin verdict:
# the daily allowance keeps a systemic misjudgement from costing the catalogue,
# and the release hands back hides a stalled probe can no longer stand behind.
# Neither argument survives a leg that has failed this many runs in a row --
# there the only thing being protected is a server nobody can reach. Both of
# those went wrong in production: 31>FI/tcp stayed visible at twenty-two
# consecutive failures because the day's allowance was spent, and 19>TR/tcp was
# handed back dead by the release and re-hidden a day later.
HIDE_CONFIDENT_STREAK = 4 * FAIL_STREAK_TO_HIDE

# How much of the visible fleet the automation may hide on its own initiative.
# The point is not to be right in the individual case -- the streak rules
# already are -- but to make a wrong *systemic* verdict cost minutes instead of
# a whole catalogue, and to put a human in front of the rest.
DEFAULT_LIMITS = {
    "per_run": 6,
    "per_day_pct": 15,
    "keep_per_entry": 1,
    "keep_per_slot": 1,
}

# An audit that has said nothing for this long cannot be trusted to undo its
# own work, so its recent hides are handed back (``hides_to_release``). Older
# ones stand: they were re-confirmed on every run for as long as the audit was
# healthy, and most of them are servers that really are gone. "Recent" is
# measured against the last verdict the audit produced, so the set of doubtful
# hides does not shrink to nothing as the outage drags on.
STALE_STATE_SEC = 2 * 3600
HIDE_LEASE_SEC = 12 * 3600


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
    witnesses: int = 0

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
            "link": self.key, "witnesses": self.witnesses,
            "entry_key": self.entry_key, "slot": self.slot,
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
        if verdict != "skip":
            link.witnesses = max(link.witnesses,
                                 int((t.result or {}).get("witnesses") or 0))
    return links


def load(path: str = STATE_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (FileNotFoundError, ValueError):
        state = {}
    state.setdefault("links", {})
    state.setdefault("auto_disabled", {})
    # A file written before scanned_at existed: the only timestamp it has was
    # written by a scan anyway, so adopt it once. Without this the first
    # liveness check on an upgraded host reads "never scanned" and the first
    # bit of housekeeping would overwrite the real answer with its own.
    if "scanned_at" not in state and state.get("updated_at"):
        state["scanned_at"] = state["updated_at"]
    return state


def save(state: dict, path: str = STATE_PATH, scanned: bool = False) -> None:
    """Persist the state; ``scanned`` marks it as the fruit of a real audit.

    The two timestamps answer different questions. ``updated_at`` is when the
    file last changed, which housekeeping does too; ``scanned_at`` is when a
    probe last got far enough to have an opinion, and that is the one the
    liveness check has to read -- otherwise tidying the file would be enough to
    make a dead watchdog look alive.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    now = int(time.time())
    state["updated_at"] = now
    if scanned:
        state["scanned_at"] = now
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def scan_age(state: dict, now: float | None = None) -> int:
    """Seconds since a probe last produced a verdict, or a very large number.

    Only ``scanned_at`` counts. Falling back to ``updated_at`` would let the
    release below silence the very alarm that triggered it: it writes the file,
    the file looks fresh, and the audit looks alive again for as long as it
    keeps failing. ``load`` adopts the old timestamp once so upgraded hosts do
    not read as never-scanned.
    """
    stamp = int(state.get("scanned_at") or 0)
    if not stamp:
        return 10 ** 9
    return max(0, int((now or time.time()) - stamp))


def hides_to_release(state: dict, now: float | None = None,
                     lease: int = HIDE_LEASE_SEC,
                     stale_after: int = STALE_STATE_SEC) -> dict[int, dict]:
    """Recent automatic hides to give back, when the audit has gone quiet.

    Hiding is one confirmed failure away; restoring needs two clean runs. So
    anything that stops the audit -- a wedged vantage, a crash loop, a full disk
    -- leaves the fleet pinned at its most hidden and keeps it there. This is
    the way out that does not need the probe to work: after
    ``stale_after`` without a verdict, hides younger than ``lease`` are released
    on the grounds that nothing can currently stand behind them.

    Older hides are left alone deliberately. They were re-examined on every run
    for as long as the audit was healthy, so they are the ones most likely to be
    real; and a wholesale un-hiding would put a fleet's worth of dead servers
    into every subscription at once.

    Recent is not the only test. A hide only becomes doubtful if the probe was
    the sole witness *and* it acted early; one the byte counters corroborated,
    or one the probe reached after watching the leg fail
    ``HIDE_CONFIDENT_STREAK`` runs running, is evidence the audit's silence does
    not touch. Handing those back is how a dead leg re-enters every
    subscription and stays there until the next full sweep.
    """
    now = now or time.time()
    if scan_age(state, now) < stale_after:
        return {}
    # The lease runs from the audit's last verdict, not from now. What earns a
    # hide its trust is having been re-confirmed by a working audit, so the
    # question is how long it stood *while the probe was still answering* --
    # not how long the outage has run since. Measured from now, the window
    # closed as the outage grew: past twelve hours nothing was ever handed back
    # again, and the fleet stayed pinned at its most hidden for as long as the
    # audit stayed down. That is the opposite of what this function is for, and
    # it is the state it was found in after a three-day wedge.
    reference = float(state.get("scanned_at") or now)
    links = state.get("links") or {}
    out = {}
    for host_id, record in state.get("auto_disabled", {}).items():
        if reference - int(record.get("at") or 0) > lease:
            continue
        if record.get("reason") in CORROBORATED_REASONS:
            continue
        link = links.get(record.get("link")) or {}
        if int(link.get("fail_streak") or 0) >= HIDE_CONFIDENT_STREAK:
            continue
        out[int(host_id)] = record
    return out


def release(state: dict, host_ids, by: str, now: float | None = None) -> None:
    """Move hosts out of the automation's ledger, keeping the trail."""
    now = int(now or time.time())
    trail = state.setdefault("released", {})
    for host_id in host_ids:
        record = state.get("auto_disabled", {}).pop(str(host_id), None)
        trail[str(host_id)] = dict(record or {}, released_at=now,
                                   released_by=by)


def _verdicts_by_node(links: dict[str, LinkView]) -> dict[int, list[str]]:
    """entry node -> the verdict of each of its links that was probed at all."""
    out: dict[int, list[str]] = {}
    for link in links.values():
        if link.verdict != "skip":
            out.setdefault(link.entry_node_id, []).append(link.verdict)
    return out


def _exit_conditions(links: dict[str, LinkView], traffic: dict[int, int],
                     node_status: dict[int, str],
                     traffic_ratio: dict[int, float]) -> dict[int, str]:
    """What each exit node's own numbers say, where its every leg just failed.

    Only exits whose *entire* probed set of legs came back down are considered:
    one leg failing says nothing about the far end, and this is the mirror of
    the rule that protects a busy entry node. The answer is deliberately
    three-valued -- an exit is believed to be alive (``busy``) or believed to be
    gone (``broken``) only on the strength of its own traffic, and ``unclear``
    otherwise, which simply leaves the ordinary streak rules in charge.
    """
    by_exit: dict[int, list[str]] = {}
    for link in links.values():
        if link.exit_node_id is None or link.verdict == "skip":
            continue
        by_exit.setdefault(int(link.exit_node_id), []).append(link.verdict)

    out: dict[int, str] = {}
    for exit_id, verdicts in by_exit.items():
        down = [v for v in verdicts if v == "down"]
        if len(down) < EXIT_WIDE_MIN_LINKS or len(down) != len(verdicts):
            continue
        status = node_status.get(exit_id, "healthy")
        ratio = traffic_ratio.get(exit_id)
        if _node_is_silent(exit_id, traffic, status):
            out[exit_id] = "broken"
        elif ratio is None:
            # No baseline to compare against -- a new exit, or one the panel
            # has no history for. Neither belief is earned.
            out[exit_id] = "unclear"
        elif ratio < EXIT_COLLAPSE_RATIO:
            out[exit_id] = "broken"
        elif ratio >= EXIT_BUSY_RATIO:
            out[exit_id] = "busy"
        else:
            out[exit_id] = "unclear"
    return out


def _rate_limit(candidates: list[dict], state: dict, visible_counts,
                limits: dict, now: int) -> tuple[list[dict], list[dict]]:
    """Split the hides this run wants into what it may do and what waits.

    Two different brakes. The floors refuse to take the last visible host of an
    entry or of a country without a human looking, because that is the shape of
    an outage report ("my server disappeared") rather than of a tidy-up. The
    rate limits cap how much of the catalogue the automation may remove per run
    and per day at all, so a systemically wrong verdict costs minutes of a few
    locations instead of most of them.

    Neither applies to a hide that the nodes' own traffic counters already
    corroborate: there the probe is not the only witness, and delaying only
    keeps a dead server in subscriptions for longer.
    """
    visible_counts = visible_counts or {}
    per_entry = dict(visible_counts.get("entry") or {})
    per_slot = dict(visible_counts.get("slot") or {})
    # Whether a floor can be judged at all is decided once, up front: the
    # running tallies below go negative as hides are allowed, and reading their
    # emptiness later would turn "the caller supplied no counts" into "this
    # entry has fewer than none left".
    know_entries = bool(per_entry)
    know_slots = bool(per_slot)
    keep_entry = int(limits.get("keep_per_entry") or 0)
    keep_slot = int(limits.get("keep_per_slot") or 0)
    per_run = int(limits.get("per_run") or 0)

    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    budget = state.setdefault("budget", {})
    if budget.get("day") != day:
        budget.clear()
        budget.update({"day": day, "hidden": 0})
    per_day = 0
    total = visible_counts.get("total")
    if total and limits.get("per_day_pct"):
        per_day = max(1, int(total) * int(limits["per_day_pct"]) // 100)

    allowed: list[dict] = []
    deferred: list[dict] = []
    used = 0
    for cand in sorted(candidates, key=lambda c: c["key"]):
        link = cand["link"]
        count = len(link.enabled_host_ids)
        if cand["reason"] in CORROBORATED_REASONS:
            allowed.append(cand)
            continue
        # A streak this long is not the systemic misjudgement the day's
        # allowance is there to make cheap, so the allowance does not get to
        # hold it back. The per-run cap and the last-visible floors still do:
        # they bound how much of the catalogue moves at once, which is worth
        # bounding however sure the verdict is.
        confident = (cand.get("fail_streak") or 0) >= HIDE_CONFIDENT_STREAK
        held = None
        if keep_entry and know_entries and \
                per_entry.get(link.entry_key, 0) - count < keep_entry:
            held = "last_visible_entry"
        elif keep_slot and know_slots and \
                per_slot.get(link.slot, 0) - count < keep_slot:
            held = "last_visible_slot"
        elif per_run and used + count > per_run:
            held = "rate_limit_run"
        elif per_day and not confident and \
                budget.get("hidden", 0) + count > per_day:
            held = "rate_limit_day"
        if held:
            deferred.append(dict(cand, deferred=held))
            continue
        used += count
        budget["hidden"] = budget.get("hidden", 0) + count
        per_entry[link.entry_key] = per_entry.get(link.entry_key, 0) - count
        per_slot[link.slot] = per_slot.get(link.slot, 0) - count
        allowed.append(cand)
    return allowed, deferred


def _node_is_silent(node_id, traffic: dict[int, int], status: str) -> bool:
    """The node is reachable, and nobody has moved a byte through it.

    The reachability half is what makes the byte count mean anything. Usage is
    collected by the panel over gRPC, so a node the panel cannot talk to always
    reads zero — the number stops being a measurement of the node and becomes a
    measurement of the connection to it. Only a *healthy* node's silence is its
    own.
    """
    if node_id is None or status != "healthy":
        return False
    return traffic.get(int(node_id), 0) < SILENT_NODE_BYTES


def decide(links: dict[str, LinkView], state: dict, traffic: dict[int, int],
           node_status: dict[int, str], visible_by_remark=None,
           remark_of=None, confirmed_links=None, node_wide_rule=True,
           traffic_ratio=None, exit_wide_rule=True, visible_counts=None,
           limits=None, now=None) -> dict:
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

    ``node_wide_rule`` and ``exit_wide_rule`` are off for scans narrowed to a
    few hosts, where "every link on this node failed" is a property of the
    filter, not of the node.

    ``traffic_ratio`` maps a node id to how its recent hours compare with the
    same hours of its own past week (see ``marz_common.node_traffic_ratio``); it
    is what lets an exit node's own numbers overrule, or corroborate, a probe.
    ``visible_counts`` and ``limits`` cap how much of the catalogue one run may
    remove -- see ``_rate_limit``.
    """
    visible_by_remark = visible_by_remark or {}
    remark_of = remark_of or {}
    traffic_ratio = traffic_ratio or {}
    limits = DEFAULT_LIMITS if limits is None else limits
    now = int(now or time.time())
    link_state = state["links"]
    auto = state["auto_disabled"]
    verdicts_by_node = _verdicts_by_node(links)
    exit_condition = (_exit_conditions(links, traffic, node_status,
                                       traffic_ratio)
                      if exit_wide_rule else {})

    enable: list[int] = []
    notes: dict[str, dict] = {}
    wants_hiding: list[dict] = []

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
            node_contested = (node_wide_rule
                              and not silent
                              and entry_bytes >= SILENT_NODE_BYTES
                              and len(probed) > 1
                              and all(v == "down" for v in probed))
            # The same argument at the far end: every leg into this exit failed,
            # and the exit is carrying about as much as it always does.
            far_end = exit_condition.get(link.exit_node_id)
            exit_contested = not silent and far_end == "busy"
            contested = node_contested or exit_contested
            confirmed = confirmed_links is None or key in confirmed_links
            # Silence is only evidence when someone other than the panel saw
            # the failure too — the byte counter and the health flag both come
            # down the panel's own connection to the node.
            alone = link.witnesses <= 1
            threshold = (FAIL_STREAK_SINGLE_WITNESS if alone
                         else FAIL_STREAK_TO_HIDE)
            should_hide = not contested and confirmed and (
                (silent and not alone) or fail_streak >= threshold)
            reason = ("node_unreachable_but_busy" if node_contested else
                      "exit_unreachable_but_busy" if exit_contested else
                      "unconfirmed" if not confirmed else
                      "node_silent" if silent and not alone else
                      "exit_down" if should_hide and far_end == "broken" else
                      "link_down" if should_hide else
                      "link_down_pending_alone" if alone else
                      "link_down_pending")
            notes[key] = {
                "verdict": "down", "fail_streak": fail_streak,
                "pass_streak": 0, "reason": reason, "contested": contested,
                "confirmed": confirmed, "entry_bytes": entry_bytes,
                "witnesses": link.witnesses,
                "exit_ratio": traffic_ratio.get(link.exit_node_id),
                "exit_condition": far_end,
            }
            # A link whose hosts are already hidden has nothing to contribute:
            # letting it through would spend budget on a no-op and report a
            # deferral nobody asked for.
            if should_hide and link.enabled_host_ids:
                wants_hiding.append({"key": key, "link": link,
                                     "reason": reason,
                                     "fail_streak": fail_streak})
        else:
            fail_streak = 0
            pass_streak = prev.get("pass_streak", 0) + 1
            # Refuse to restore into silence: if nothing is moving through a
            # node the panel can otherwise see, a passing probe is the only
            # witness and that is not enough. A node the panel cannot see at
            # all reports silence it has not earned, so that does not count.
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
                # Deliberately not `contested`: that word is reserved for a
                # failure the traffic contradicts. A passing link on a silent
                # node is only barred from being *restored*, which is a
                # different thing and belongs under its own name — a new node
                # that has not carried a byte yet trips this on every link.
                "restore_held": quiet,
                "contested": False,
                "entry_bytes": entry_bytes,
            }

    allowed, deferred = _rate_limit(wants_hiding, state, visible_counts,
                                    limits, now)
    disable: list[int] = []
    for cand in allowed:
        for host_id in cand["link"].enabled_host_ids:
            disable.append(host_id)
            auto[str(host_id)] = {"link": cand["key"],
                                  "reason": cand["reason"], "at": now}
    for cand in deferred:
        # The streak is left standing: the link really did fail, and the next
        # run gets to ask again with a fresh budget.
        notes[cand["key"]]["deferred"] = cand["deferred"]

    for key, note in notes.items():
        # A link nobody probed keeps the state it had, verdict included: the
        # re-check pass reads that verdict to know which failures are already
        # established, and overwriting it with "skip" would quietly hand every
        # confirmed outage back to the slow path.
        if note["verdict"] == "skip":
            continue
        link_state[key] = {
            "fail_streak": note["fail_streak"],
            "pass_streak": note["pass_streak"],
            "verdict": note["verdict"],
            "confirmed": note.get("confirmed", True),
            "reason": note["reason"],
            "deferred": note.get("deferred"),
            "updated_at": now,
        }

    # Links that vanished from the fleet should not keep state forever.
    for gone in set(link_state) - set(links):
        link_state.pop(gone, None)

    return {
        "disable": sorted(set(disable)), "enable": sorted(set(enable)),
        "links": notes,
        "deferred": [{"link": c["key"], "reason": c["reason"],
                      "deferred": c["deferred"],
                      "host_ids": sorted(c["link"].enabled_host_ids)}
                     for c in deferred],
    }
