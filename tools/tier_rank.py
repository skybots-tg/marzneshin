#!/usr/bin/env python3
"""Run ON the panel. Order each tier by what actually works.

Weights decide the order a client shows the servers in, and until now they
encoded geography: a slot got a fixed offset inside its brand's block, so
``FI`` sat second in every UNIVERSAL group whether or not Finland had carried
a byte that week. The first entry in the list is the one most people connect
to, which means a dead slot at the top costs far more than the same slot dead
at the bottom.

This renumbers the offsets by evidence instead. Two sources, deliberately
different in kind:

* the audit report (``bridge_audit.json``) — does a probe from the tier's own
  audience reach the exit right now, from how many vantages, and how fast;
* ``node_usages`` — did the exit carry real traffic in the last day and week.

Neither alone is enough. A probe is one request from a hosting network and can
pass on a server no subscriber can use; traffic alone cannot tell a slot that
broke this morning from one nobody was ever offered, and a slot the automation
has hidden carries nothing *by construction*. Together they separate the three
cases that matter: works and is used, works but nobody is on it, does not work.

Slots land in four tiers, in this order:

    A  every vantage passes, and the exit moved traffic in the last 24h
    B  every vantage passes, but the exit is quiet
    C  some vantages pass, some do not
    D  no vantage passes

and inside a tier the faster probe goes first. The home slot (RU) keeps offset
0: it is not a foreign exit competing with the others, and share.py already
moves it out of the head of the list on its own.

Nothing is applied without --apply, and the rollback SQL is written next to the
report before anything changes.

    python3 tier_rank.py                     # what would change
    python3 tier_rank.py --tier universal --apply
    python3 tier_rank.py --apply             # all three tiers
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict

import bridge_lib as bl
import marz_common as mc

REPORT = "/var/lib/marzneshin/bridge_audit.json"
ROLLBACK_DIR = "/var/lib/marzneshin"

# Where each tier's block starts and how wide the usable offset range is.
# UNIVERSAL keeps offset 0 for the home slot; ELITE keeps it for the two
# "РАБОТАЕТ ВСЕГДА" pins that are deliberately weightless.
LAYOUT = {
    "universal": {"base": lambda i: 100 + (i - 1) * 10, "lo": 1, "hi": 9},
    "elite": {"base": lambda i: i * 10, "lo": 1, "hi": 9},
    "fast": {"base": lambda i: 200, "lo": 0, "hi": 9},
}
HOME_SLOT = "RU"
TRAFFIC_FLOOR_GB = 1.0   # below this a 24h figure is noise, not use


def node_traffic_gb(hours: int) -> dict[int, float]:
    rows = mc.db_query(
        "SELECT node_id, ROUND(SUM(uplink+downlink)/1073741824,3) "
        "FROM node_usages WHERE created_at > NOW() - INTERVAL %d HOUR "
        "GROUP BY node_id;" % hours)
    out = {}
    for nid, gb in rows:
        try:
            out[int(nid)] = float(gb)
        except (TypeError, ValueError):
            continue
    return out


def exit_of(host: dict) -> int | None:
    """Which node's traffic speaks for this host — the far end, not the entry.

    A bridge host is a pair, and the entry is shared with a dozen other slots:
    its traffic says nothing about whether this particular exit is alive, and
    reading it anyway is how every slot behind a busy entry looked like it
    carried 266 GB. A bridge whose far end is not a registered node has no
    figure at all, and saying so beats inventing one. A direct host has no far
    end and answers for itself.
    """
    if host.get("is_bridge"):
        return host.get("exit_node_id")
    return host.get("node_id")


def _ratio(hosts: list[dict]) -> tuple[float, int]:
    tried = sum(len(h.get("vantages_tried") or []) for h in hosts)
    good = sum(len(h.get("vantages_ok") or []) for h in hosts)
    return ((good / tried) if tried else 0.0), tried


def score_slot(hosts: list[dict], gb24: dict, gb7d: dict) -> tuple:
    """(tier letter, median probe seconds, ...) for one slot.

    Judged on the hosts a subscriber can actually see. A slot is not worse for
    carrying a hidden host that fails — that is the automation doing its job —
    and counting those dragged real slots down: FAST US read 50% because the
    MLKEM beta sits next to the live entry and has never worked. When every
    host of a slot is hidden there is nothing else to go on, so the hidden ones
    answer, and the slot is marked so the table does not read as measured fact.
    """
    shown = [h for h in hosts if not h.get("is_disabled")]
    ratio, tried = _ratio(shown or hosts)
    judged_on_hidden = not shown

    lat = [h["elapsed"] for h in (shown or hosts)
           if h.get("verdict") == "pass" and isinstance(h.get("elapsed"), (int, float))]
    median = statistics.median(lat) if lat else 99.0

    known = {nid for nid in (exit_of(h) for h in hosts) if nid is not None}
    carried = max((gb24.get(n, 0.0) for n in known), default=None)
    week = max((gb7d.get(n, 0.0) for n in known), default=None)

    if ratio >= 0.999:
        # No figure is not the same as a figure of zero. Some exits are not
        # registered as nodes (FL, RO-1), so the panel never counts their
        # bytes; demoting them for that would rank them below slots we know
        # are dead. Absent evidence leaves the probe's verdict standing.
        letter = "A" if carried is None or carried >= TRAFFIC_FLOOR_GB else "B"
    elif ratio > 0:
        letter = "C"
    else:
        letter = "D"
    return letter, median, ratio, carried, week, judged_on_hidden, tried


def rank_slots(scores: dict[str, tuple]) -> dict[str, int]:
    """slot -> rank (0 = best), by tier letter then probe latency."""
    order = sorted(scores, key=lambda s: (scores[s][0], scores[s][1], s))
    return {slot: i for i, slot in enumerate(order)}


def spread(rank: int, n: int, lo: int, hi: int) -> int:
    """Map a rank onto the offsets a block has room for.

    There are more slots than offsets — thirteen exits into nine places — so
    some have to share. Sharing at the same offset leaves their relative order
    to the database, which is fine between two slots of equal standing and
    would not be fine between a live one and a dead one; spreading by rank
    keeps every share inside one tier letter's worth of distance.
    """
    if n <= 1:
        return lo
    span = hi - lo
    return lo + round(rank * span / (n - 1))


def collect(report: dict, tier: str) -> dict[int, list[dict]]:
    by_brand = defaultdict(list)
    for h in report["hosts"]:
        if h.get("tier") != tier:
            continue
        if h.get("tier_index") is None:
            continue
        by_brand[h["tier_index"]].append(h)
    return by_brand


def plan_tier(report, tier, gb24, gb7d, verbose=True):
    layout = LAYOUT[tier]
    by_brand = collect(report, tier)
    if not by_brand:
        print(f"no {tier} hosts in the report")
        return []

    # Slot standing is judged across the whole tier, not per brand: one entry
    # having a bad day should not push a slot down for everybody, and a slot
    # that is genuinely dead is dead behind every entry.
    per_slot = defaultdict(list)
    for hosts in by_brand.values():
        for h in hosts:
            per_slot[h["slot"]].append(h)

    scores = {s: score_slot(hs, gb24, gb7d) for s, hs in per_slot.items()}
    foreign = {s: v for s, v in scores.items() if s != HOME_SLOT}
    ranks = rank_slots(foreign)
    n = len(ranks)

    if verbose:
        print(f"\n=== {tier}: slot standing ===")
        print(f"{'slot':<8}{'tier':<6}{'probe':<8}{'ok':<9}{'24h GB':<9}"
              f"{'7d GB':<9}{'offset'}")
        for slot in sorted(scores, key=lambda s: (s != HOME_SLOT,
                                                  ranks.get(s, -1))):
            letter, median, ratio, gb, wk, hidden_only, tried = scores[slot]
            off = 0 if slot == HOME_SLOT else spread(ranks[slot], n,
                                                     layout["lo"], layout["hi"])
            probe = "-" if median >= 99 else f"{median:.2f}s"
            mark = "*" if hidden_only else " "
            traffic = "    n/a" if gb is None else f"{gb:>7.1f}"
            weekly = "    n/a" if wk is None else f"{wk:>7.1f}"
            print(f"{slot:<8}{letter:<6}{probe:<8}{ratio*100:>5.0f}%{mark}  "
                  f"{traffic}  {weekly}  {off:>5}")
        if any(v[5] for v in scores.values()):
            print("  * — весь слот скрыт, судим по скрытым хостам")

    changes = []
    for index, hosts in sorted(by_brand.items()):
        base = layout["base"](index)
        for h in hosts:
            slot = h["slot"]
            off = 0 if slot == HOME_SLOT else spread(ranks[slot], n,
                                                     layout["lo"], layout["hi"])
            want = base + off
            if h["weight"] != want:
                changes.append((h, want))
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", action="append", default=[],
                    choices=sorted(LAYOUT), help="repeatable; default all")
    ap.add_argument("--report", default=REPORT)
    ap.add_argument("--max-age", type=int, default=6 * 3600,
                    help="refuse a report older than this many seconds")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.report):
        print(f"no audit report at {args.report} — run a full sweep first")
        return 1
    with open(args.report, encoding="utf-8") as f:
        report = json.load(f)

    age = int(time.time()) - int(report.get("generated_at", 0))
    if age > args.max_age:
        print(f"report is {age // 3600}h old — ranking on it would freeze "
              f"yesterday's outage into the weights. Run a full sweep first.")
        return 1
    print(f"report: {report['total']} hosts, {age // 60} min old, "
          f"counts={report.get('counts')}")

    gb24 = node_traffic_gb(24)
    gb7d = node_traffic_gb(24 * 7)

    tiers = args.tier or sorted(LAYOUT)
    changes = []
    for tier in tiers:
        changes.extend(plan_tier(report, tier, gb24, gb7d))

    if not changes:
        print("\nevery weight already matches the ranking")
        return 0

    print(f"\n{len(changes)} host(s) move:")
    for h, want in sorted(changes, key=lambda c: (c[0]["tier"],
                                                  c[0]["tier_index"], c[1])):
        vis = "" if not h["is_disabled"] else "  (hidden)"
        print(f"  #{h['host_id']:<5} {h['remark'][:44]:<46} "
              f"{h['weight']} -> {want}{vis}")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply.")
        return 0

    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(ROLLBACK_DIR, f"rollback_tier_rank_{stamp}.sql")
    with open(path, "w", encoding="utf-8") as f:
        for h, _ in changes:
            f.write(f"UPDATE hosts SET weight={h['weight']} "
                    f"WHERE id={h['host_id']};\n")
    print(f"\nrollback: {path}")

    sql = "\n".join(f"UPDATE hosts SET weight={w} WHERE id={h['host_id']};"
                    for h, w in changes)
    r = mc.db(sql + "\n")
    if r.returncode != 0:
        print("DB UPDATE FAILED:", r.stderr[:400])
        return 4
    print(f"renumbered {len(changes)} host(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
