#!/usr/bin/env python3
"""Audit every RU-entry -> exit bridge and keep the subscription honest.

Run ON THE PANEL, from this directory.

    python3 bridge_audit.py scan                 # probe everything, dry run
    python3 bridge_audit.py scan --apply         # + hide dead / restore fixed
    python3 bridge_audit.py matrix               # last report as a grid
    python3 bridge_audit.py gaps                 # entry x exit combos to fill
    python3 bridge_audit.py fill U4 RO --apply   # add one missing bridge

`scan` connects to each host exactly the way a subscribed client would and
checks where the traffic surfaces. Hosts with no egress are switched to
`is_disabled=1` so they drop out of every subscription; hosts that recover are
switched back on. The JSON report is what the panel's Bridge Health page reads.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import bridge_lib as bl
import marz_common as mc

REPORT_PATH = "/var/lib/marzneshin/bridge_audit.json"
SOCKS_BASE = 11500

VERDICT_MARK = {"pass": "OK", "wrong_geo": "GEO", "fail": "--", "skip": "??"}


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------


def cmd_scan(args) -> int:
    if not bl.ensure_xray():
        print("FATAL: cannot extract the xray binary from a local marznode "
              "container; is marznode running on the panel host?")
        return 2

    tiers = ("universal", "elite", "fast") if args.tier == "all" else (args.tier,)
    node_ids = {int(x) for x in args.nodes.split(",")} if args.nodes else None
    targets = bl.load_targets(tiers=tiers, node_ids=node_ids)
    if args.slot:
        want = {s.strip().upper() for s in args.slot.split(",")}
        targets = [t for t in targets if t.slot in want]
    if not args.include_direct:
        targets = [t for t in targets if t.is_bridge or t.slot.startswith("RU")]
    if not targets:
        print("no targets matched")
        return 1

    print(f"probing {len(targets)} hosts with {args.jobs} workers "
          f"({args.attempts} attempts each)...\n")
    started = time.time()
    done = [0]

    def run(idx_target):
        idx, t = idx_target
        t.result = bl.probe(t, SOCKS_BASE + (idx % args.jobs),
                            user_uuid=args.user, timeout=args.timeout,
                            attempts=args.attempts)
        done[0] += 1
        v = t.result["verdict"]
        extra = t.result.get("country") or t.result.get("error") or ""
        print(f"  [{done[0]:>3}/{len(targets)}] {VERDICT_MARK[v]:<3} "
              f"{t.label:<28} {t.remark[:42]:<44} {extra}")
        return t

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(run, enumerate(targets)))

    report = build_report(targets, round(time.time() - started, 1))
    save_report(report, args.report)
    print()
    print_summary(report)
    print(f"\nreport written to {args.report}")

    if args.apply:
        return apply_report(report, targets, args)
    changes = report["changes"]
    if changes["disable"] or changes["enable"]:
        print(f"\nDRY RUN. Re-run with --apply to hide "
              f"{len(changes['disable'])} dead host(s) and restore "
              f"{len(changes['enable'])} recovered host(s).")
    return 0


def build_report(targets, elapsed) -> dict:
    rows = [t.brief() for t in targets]
    to_disable = [t.host_id for t in targets
                  if t.result["verdict"] == "fail" and not t.is_disabled]
    to_enable = [t.host_id for t in targets
                 if t.result["verdict"] == "pass" and t.is_disabled]
    counts = defaultdict(int)
    for t in targets:
        counts[t.result["verdict"]] += 1
    return {
        "generated_at": int(time.time()),
        "elapsed_sec": elapsed,
        "total": len(targets),
        "counts": dict(counts),
        "hosts": rows,
        "matrix": build_matrix(targets),
        "gaps": build_gaps(targets),
        "changes": {"disable": to_disable, "enable": to_enable},
    }


def save_report(report, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_report(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# matrix + gaps
# --------------------------------------------------------------------------


def build_matrix(targets) -> dict:
    """entry_key -> slot -> aggregated state across tcp/xhttp variants."""
    grid: dict[str, dict[str, dict]] = defaultdict(dict)
    for t in targets:
        cell = grid[t.entry_key].setdefault(
            t.slot, {"pass": 0, "wrong_geo": 0, "fail": 0, "skip": 0,
                     "host_ids": [], "enabled": 0})
        cell[t.result["verdict"]] += 1
        cell["host_ids"].append(t.host_id)
        cell["enabled"] += 0 if t.is_disabled else 1
    return {k: v for k, v in grid.items()}


def slot_is_alive(cell) -> bool:
    return bool(cell) and (cell["pass"] + cell["wrong_geo"]) > 0


def build_gaps(targets) -> list[dict]:
    """(entry, slot) combos that are missing or dead while proven elsewhere.

    A slot only counts as fillable when some other entry node reaches it
    right now — there is no point wiring a bridge to an exit that is down.
    """
    grid = build_matrix(targets)
    entries = {}
    for t in targets:
        entries.setdefault(t.entry_key, {
            "entry_key": t.entry_key, "tier": t.tier, "index": t.tier_index,
            "node_id": t.node_id, "node_name": t.node_name,
            "address": t.address, "node_status": t.node_status,
        })

    live_slots: dict[str, list[str]] = defaultdict(list)
    for ek, slots in grid.items():
        for slot, cell in slots.items():
            if slot_is_alive(cell):
                live_slots[slot].append(ek)

    # An entry whose every slot is dead is a node-level outage, not a set of
    # per-slot gaps; filling bridges there would just add more dead hosts.
    healthy_entries = {ek for ek, slots in grid.items()
                       if any(slot_is_alive(c) for c in slots.values())}

    gaps = []
    for ek, meta in sorted(entries.items()):
        if ek not in healthy_entries:
            continue
        if meta["tier"] != "universal":
            continue
        for slot, donors in sorted(live_slots.items()):
            if slot.startswith("RU"):
                continue
            cell = grid[ek].get(slot)
            if cell and slot_is_alive(cell):
                continue
            gaps.append({
                **meta,
                "slot": slot,
                "reason": "dead" if cell else "missing",
                "dead_host_ids": cell["host_ids"] if cell else [],
                "donors": [d for d in donors if d != ek],
            })
    return gaps


def print_summary(report):
    c = report["counts"]
    print("=" * 78)
    print(f"SCAN  total={report['total']}  pass={c.get('pass', 0)}  "
          f"wrong_geo={c.get('wrong_geo', 0)}  fail={c.get('fail', 0)}  "
          f"skip={c.get('skip', 0)}  ({report['elapsed_sec']}s)")
    print("=" * 78)
    print_matrix(report)
    dead = [h for h in report["hosts"]
            if h["verdict"] == "fail" and not h["is_disabled"]]
    if dead:
        print(f"\nLIVE BUT BROKEN -> will be hidden ({len(dead)}):")
        for h in sorted(dead, key=lambda x: x["remark"]):
            print(f"  #{h['host_id']:<4} {h['remark'][:46]:<48} "
                  f"{h.get('error', '')}")
    revive = [h for h in report["hosts"]
              if h["verdict"] == "pass" and h["is_disabled"]]
    if revive:
        print(f"\nHIDDEN BUT WORKING -> will be restored ({len(revive)}):")
        for h in sorted(revive, key=lambda x: x["remark"]):
            print(f"  #{h['host_id']:<4} {h['remark'][:46]:<48} "
                  f"{h.get('country', '')}")
    geo = [h for h in report["hosts"] if h["verdict"] == "wrong_geo"]
    if geo:
        print(f"\nTRAFFIC OK BUT UNEXPECTED COUNTRY ({len(geo)}) "
              f"— left enabled, check labelling:")
        for h in sorted(geo, key=lambda x: x["remark"]):
            print(f"  #{h['host_id']:<4} {h['remark'][:38]:<40} "
                  f"labelled {h.get('expected_country')} -> exits "
                  f"{h.get('country')} ({h.get('egress_ip')})")
    if report["gaps"]:
        print(f"\nFILLABLE GAPS ({len(report['gaps'])}) — see `gaps` command")


def print_matrix(report):
    grid = report["matrix"]
    slots = sorted({s for v in grid.values() for s in v})
    if not slots:
        return
    w = max(max((len(s) for s in slots), default=4), 4) + 1
    print("\nentry".ljust(14) + "".join(s.ljust(w) for s in slots))
    for ek in sorted(grid, key=lambda k: (k.split("-")[0], int(k.split("-")[1]))):
        line = ek.ljust(14)
        for s in slots:
            cell = grid[ek].get(s)
            if not cell:
                line += ".".ljust(w)
            elif cell["pass"]:
                line += ("OK" if cell["enabled"] else "ok*").ljust(w)
            elif cell["wrong_geo"]:
                line += "GEO".ljust(w)
            elif cell["skip"]:
                line += "??".ljust(w)
            else:
                line += ("DEAD" if cell["enabled"] else "-").ljust(w)
        print(line)
    print("  OK=works & visible   ok*=works but hidden   DEAD=visible but no "
          "egress\n  -=hidden & dead      GEO=works, wrong country   .=absent")


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------


def apply_report(report, targets, args) -> int:
    ch = report["changes"]
    tested = report["total"]
    fails = report["counts"].get("fail", 0)
    if tested and fails * 100 // tested > args.max_fail_pct and not args.force:
        print(f"\nREFUSING TO APPLY: {fails}/{tested} probes failed "
              f"(> {args.max_fail_pct}%). That usually means the panel itself "
              f"lost egress, not that every bridge died. Re-run, or pass "
              f"--force if the outage is real.")
        return 3
    if not ch["disable"] and not ch["enable"]:
        print("\nnothing to change")
        return 0

    sql = []
    if ch["disable"]:
        ids = ",".join(str(i) for i in ch["disable"])
        sql.append(f"UPDATE hosts SET is_disabled=1 WHERE id IN ({ids});")
    if ch["enable"]:
        ids = ",".join(str(i) for i in ch["enable"])
        sql.append(f"UPDATE hosts SET is_disabled=0 WHERE id IN ({ids});")
    r = mc.db("\n".join(sql) + "\n")
    if r.returncode != 0:
        print("DB UPDATE FAILED:", r.stderr[:400])
        return 4
    print(f"\nAPPLIED: hid {len(ch['disable'])} host(s), "
          f"restored {len(ch['enable'])} host(s).")
    return 0


# --------------------------------------------------------------------------
# read-only commands over the saved report
# --------------------------------------------------------------------------


def cmd_matrix(args) -> int:
    report = load_report(args.report)
    print_summary(report)
    return 0


def cmd_gaps(args) -> int:
    report = load_report(args.report)
    gaps = report["gaps"]
    if not gaps:
        print("no fillable gaps: every entry reaches every live exit slot")
        return 0
    print(f"{len(gaps)} fillable gap(s) "
          f"(exit proven reachable from another entry):\n")
    by_entry = defaultdict(list)
    for g in gaps:
        by_entry[g["entry_key"]].append(g)
    for ek in sorted(by_entry):
        rows = by_entry[ek]
        m = rows[0]
        print(f"{ek}  node {m['node_id']} {m['node_name']} ({m['address']})")
        for g in rows:
            dead = (f" [dead hosts {g['dead_host_ids']}]"
                    if g["reason"] == "dead" else "")
            print(f"    {g['slot']:<8} {g['reason']:<8} "
                  f"donors: {', '.join(g['donors'][:4])}{dead}")
        print(f"    -> python3 bridge_audit.py fill {ek} "
              f"{' '.join(sorted({g['slot'] for g in rows}))} --apply")
        print()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--report", default=REPORT_PATH)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="probe hosts and optionally apply fixes")
    s.add_argument("--tier", default="universal",
                   choices=["universal", "elite", "fast", "all"])
    s.add_argument("--nodes", default="", help="comma-separated node ids")
    s.add_argument("--slot", default="", help="comma-separated exit slots")
    s.add_argument("--jobs", type=int, default=6)
    s.add_argument("--timeout", type=int, default=12)
    s.add_argument("--attempts", type=int, default=2)
    s.add_argument("--user", default=bl.DEFAULT_USER)
    s.add_argument("--include-direct", action="store_true",
                   help="also probe non-bridge RU Direct hosts")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("--max-fail-pct", type=int, default=60)
    s.set_defaults(func=cmd_scan)

    sub.add_parser("matrix", help="print the last report").set_defaults(
        func=cmd_matrix)
    sub.add_parser("gaps", help="entry x exit combos worth filling").set_defaults(
        func=cmd_gaps)

    f = sub.add_parser("fill", help="add missing bridges to an entry node")
    f.add_argument("entry", help="entry key, e.g. universal-4 or U4")
    f.add_argument("slots", nargs="+", help="exit slots, e.g. RO FI-2")
    f.add_argument("--donor", default="", help="donor entry key (auto if empty)")
    f.add_argument("--apply", action="store_true")
    f.add_argument("--user", default=bl.DEFAULT_USER)
    f.set_defaults(func=lambda a: __import__("bridge_fill").run(a))

    args = p.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
