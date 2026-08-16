#!/usr/bin/env python3
"""Audit every RU-entry -> exit bridge and keep the subscription honest.

Run ON THE PANEL, from this directory.

    python3 bridge_audit.py scan                 # probe everything, dry run
    python3 bridge_audit.py scan --apply         # + hide dead / restore fixed
    python3 bridge_audit.py scan --quick --apply # one host per link, the watchdog
    python3 bridge_audit.py apply                # act on the saved report
    python3 bridge_audit.py matrix               # last report as a grid
    python3 bridge_audit.py gaps                 # entry x exit combos to fill
    python3 bridge_audit.py fill U4 RO --apply   # add one missing bridge

Companion tools: `bridge_state.py` (what gets hidden, and when), `bridge_drift.py`
(DB vs node config), `bridge_debug.py` (why one host fails, with the full client
log).

`scan` connects to each host exactly the way a subscribed client would and
checks where the traffic surfaces. What happens next is not this file's call:
results are rolled up per entry->exit link and handed to `bridge_state.py`,
which weighs them against previous runs and against the bytes each node really
carried before anything is switched to `is_disabled=1`. The JSON report is what
the panel's Bridge Health page reads.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict

import bridge_lib as bl
import bridge_probe as bp
import bridge_state as bs
import marz_common as mc

REPORT_PATH = "/var/lib/marzneshin/bridge_audit.json"

VERDICT_MARK = {"pass": "OK", "wrong_geo": "GEO", "fail": "--", "skip": "??"}

# Below this many probed hosts the "too many failures" guard is meaningless.
MIN_HOSTS_FOR_GUARD = 20


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------


def resolve_vantages(args, targets) -> list[dict]:
    """Where to probe from.

    A named vantage is looked up in the nodes table rather than among the
    targets: the two sets only overlap for a full scan. Narrowing a scan to a
    handful of hosts — the usual way to re-check one suspect — would otherwise
    empty the vantage list and leave nothing to probe from.
    """
    if not args.vantage:
        return bp.default_vantages(targets, limit=args.vantages)

    wanted = [v.strip() for v in args.vantage.split(",") if v.strip()]
    known = {str(t.node_id): {"node_id": t.node_id, "name": t.node_name,
                              "address": t.address, "status": t.node_status}
             for t in targets}
    for nid, name, address, status in mc.db_query(
            "SELECT id, name, address, status FROM nodes"):
        known.setdefault(str(nid), {"node_id": int(nid), "name": name,
                                    "address": address, "status": status})
    out = []
    for w in wanted:
        if w == bp.PANEL:
            out.append({"node_id": 0, "name": "panel",
                        "address": bp.PANEL, "status": "healthy"})
        elif w in known:
            out.append(known[w])
        else:
            print(f"  unknown vantage {w!r}, skipping")
    return out


def cmd_scan(args) -> int:
    tiers = ("universal", "elite", "fast") if args.tier == "all" else (args.tier,)
    node_ids = {int(x) for x in args.nodes.split(",")} if args.nodes else None
    targets = bl.load_targets(tiers=tiers, node_ids=node_ids)
    complete = not (args.slot or args.hosts)
    if args.slot:
        want = {s.strip().upper() for s in args.slot.split(",")}
        targets = [t for t in targets if t.slot in want]
    if args.hosts:
        want_ids = {int(x) for x in args.hosts.replace(" ", "").split(",") if x}
        targets = [t for t in targets if t.host_id in want_ids]
    if not args.include_direct:
        # FAST hosts are direct by definition — dropping every direct host would
        # silently drop the whole tier, which is how it went unaudited for so
        # long. The flag is only about RU Direct entries on the bridge nodes.
        targets = [t for t in targets
                   if t.is_bridge or t.slot.startswith("RU")
                   or t.tier == "fast"]
    if not targets:
        print("no targets matched")
        return 1

    probe_targets = targets
    if args.quick:
        probe_targets = one_per_link(targets)
        complete = False
        print(f"quick run: {len(probe_targets)} link representative(s) "
              f"stand in for {len(targets)} host(s)")
        # What makes the full sweep slow is the failing jobs: each pays for
        # three geo endpoints, twice over. A watchdog only needs to know
        # whether anything came back, so it asks once. Being wrong costs a
        # streak, not a hidden host — two runs still have to agree.
        args.geo_tries = args.geo_tries or 1
        args.attempts = 1

    vantages = resolve_vantages(args, targets)
    if not vantages:
        print("no usable vantage node")
        return 2
    origins = bp.vantage_origins(vantages)
    print(f"probing {len(probe_targets)} hosts from {len(vantages)} vantage "
          f"point(s), {args.jobs} workers each:")
    for v in vantages:
        print(f"    node {v['node_id']:<4} {v['name']} ({v['address']}) "
              f"[{origins[bp.vantage_key(v)].lower()}]")
    print()
    started = time.time()

    def done(v, res):
        if "__error__" in res:
            print(f"  vantage {v['name']}: FAILED — {res['__error__']}")
            return
        ok = sum(1 for r in res.values() if r["verdict"] == "pass")
        print(f"  vantage {v['name']}: {ok}/{len(res)} reachable")

    per_vantage = bp.probe_all(probe_targets, vantages, args.user,
                               workers=args.jobs, timeout=args.timeout,
                               on_vantage_done=done,
                               geo_tries=args.geo_tries,
                               attempts=args.attempts)
    bp.merge(probe_targets, per_vantage, origins)
    for t in targets:
        # Hosts a quick run stood down for still belong to their link; they just
        # carry no opinion of their own this time round.
        t.result.setdefault("verdict", "skip")

    state = bs.load()
    decisions = weigh(targets, state, args)
    report = build_report(targets, round(time.time() - started, 1), complete,
                          decisions)
    report["vantages"] = [
        {"node_id": v["node_id"], "name": v["name"], "address": v["address"],
         "origin": origins.get(bp.vantage_key(v)),
         "error": per_vantage.get(bp.vantage_key(v), {}).get("__error__")}
        for v in vantages
    ]
    save_report(report, args.report)
    print()
    print_summary(report)
    print(f"\nreport written to {args.report}")

    if args.apply:
        rc = apply_report(report, targets, args)
        if rc == 0:
            # Streaks only advance on runs that were allowed to act. A dry run
            # that aged them would let `scan` (no --apply) silently arm the next
            # `scan --apply` to hide something on its first look.
            bs.save(state)
        return rc
    changes = report["changes"]
    if changes["disable"] or changes["enable"]:
        print(f"\nDRY RUN. Re-run with --apply to hide "
              f"{len(changes['disable'])} dead host(s) and restore "
              f"{len(changes['enable'])} recovered host(s).")
    return 0


def one_per_link(targets) -> list:
    """One host per link, enough to tell whether that leg still carries traffic.

    A watchdog that runs every quarter of an hour cannot afford to probe all
    ~190 hosts, and it does not need to: hosts on the same leg rise and fall
    together. Enabled hosts are preferred as the stand-in, but a link whose
    hosts are all hidden still gets probed — otherwise nothing would ever be
    restored.
    """
    chosen: dict[str, object] = {}
    for t in sorted(targets, key=lambda t: (t.is_disabled, t.host_id)):
        chosen.setdefault(t.link_key, t)
    return list(chosen.values())


def visible_by_remark(targets) -> dict[str, list[int]]:
    out: dict[str, list[int]] = defaultdict(list)
    for t in targets:
        if not t.is_disabled:
            out[t.remark].append(t.host_id)
    return out


def weigh(targets, state, args) -> dict:
    """Turn this run's probe results into actions, with memory and corroboration.

    The probe alone does not get to decide: ``bridge_state`` folds it together
    with the previous runs and with the bytes ``node_usages`` says each node
    actually carried. See that module for the rules.
    """
    links = bs.roll_up(targets)
    try:
        traffic = mc.node_traffic(bs.TRAFFIC_WINDOW_HOURS)
    except Exception as exc:
        # Losing the corroborating signal must not turn into losing the audit;
        # an empty map simply means no link gets the fast "silent node" path.
        print(f"  node traffic unavailable ({exc}); relying on probes alone")
        traffic = {}
    node_status = {t.node_id: t.node_status for t in targets}
    decisions = bs.decide(
        links, state, traffic, node_status,
        visible_by_remark=visible_by_remark(targets),
        remark_of={t.host_id: t.remark for t in targets},
    )
    decisions["views"] = {k: v.brief() for k, v in links.items()}
    return decisions


def build_report(targets, elapsed, complete: bool = True,
                 decisions: dict | None = None) -> dict:
    rows = [t.brief() for t in targets]
    visible = visible_by_remark(targets)
    decisions = decisions or {"disable": [], "enable": [], "links": {},
                              "views": {}}
    to_disable = decisions["disable"]
    to_enable = decisions["enable"]
    shadowed = [t.host_id for t in targets
                if t.result["verdict"] == "pass" and t.is_disabled
                and visible.get(t.remark)]
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
        "outages": build_outages(targets, complete),
        "duplicates": [{"remark": r, "host_ids": ids}
                       for r, ids in sorted(visible.items()) if len(ids) > 1],
        "shadowed": shadowed,
        "links": [dict(view, **decisions["links"].get(key, {}))
                  for key, view in sorted(decisions["views"].items())],
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


def build_outages(targets, complete: bool = True) -> list[dict]:
    """Entry nodes where nothing at all got through.

    One dead exit is a bridge problem; every exit dead on the same node,
    including its direct RU hosts, is the node itself — xray down, or the
    machine off the network. Hiding those hosts is still right, since nobody
    can use them, but it is worth saying out loud: the fix is on the node, and
    the whole group comes back at once when it is.

    The claim only holds when the node's whole set of hosts was probed. On a
    scan narrowed to one exit, "every host failed" says nothing more than that
    the one exit is down, so a filtered run reports no outages at all.
    """
    if not complete:
        return []
    by_node: dict[int, list] = defaultdict(list)
    for t in targets:
        by_node[t.node_id].append(t)
    out = []
    for node_id, ts in sorted(by_node.items()):
        if len(ts) < 2 or any(t.result["verdict"] != "fail" for t in ts):
            continue
        out.append({
            "node_id": node_id, "node_name": ts[0].node_name,
            "address": ts[0].address, "node_status": ts[0].node_status,
            "entry_keys": sorted({t.entry_key for t in ts}),
            "host_ids": sorted(t.host_id for t in ts),
        })
    return out


def slot_is_alive(cell) -> bool:
    return bool(cell) and (cell["pass"] + cell["wrong_geo"]) > 0


def build_gaps(targets) -> list[dict]:
    """(entry, slot) combos worth attention, split by what can be done.

    Two very different situations look the same in the matrix. If the entry has
    no bridge to that exit at all, cloning a working one from another entry
    fixes it. If it already has one and the probe fails, the wiring is not the
    problem: on both AdminVPS entries the outbounds are byte-identical to a
    working donor's, TCP to the exit completes in both directions, and only the
    TLS handshake goes unanswered — the uplink is filtering those destinations,
    and a cloned bridge would take the same blocked path. Those are reported as
    blocked and left out of the fill suggestions.
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
                "reason": "blocked" if cell else "missing",
                "fillable": cell is None,
                "dead_host_ids": cell["host_ids"] if cell else [],
                "donors": [d for d in donors if d != ek],
                "reachable_slots": sorted(
                    s for s, c in grid[ek].items()
                    if slot_is_alive(c) and not s.startswith("RU")),
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
    for o in report.get("outages") or []:
        print(f"\nENTRY NODE DOWN: node {o['node_id']} {o['node_name']} "
              f"({o['address']}, panel says {o['node_status']}) — all "
              f"{len(o['host_ids'])} host(s) failed, so this is the node, not "
              f"its bridges. Check xray there before reading the rest.")
    by_link = {ln["link"]: ln for ln in report.get("links") or []}
    hiding = set(report["changes"]["disable"])
    dead = [h for h in report["hosts"]
            if h["verdict"] == "fail" and not h["is_disabled"]]
    doomed = [h for h in dead if h["host_id"] in hiding]
    if doomed:
        print(f"\nLINK DOWN -> will be hidden ({len(doomed)}):")
        for h in sorted(doomed, key=lambda x: x["remark"]):
            note = by_link.get(h.get("link"), {})
            tried = ",".join(h.get("vantages_tried") or [])
            print(f"  #{h['host_id']:<4} {h['remark'][:40]:<42} "
                  f"{note.get('reason', ''):<12} "
                  f"fails={note.get('fail_streak', '?')} [{tried}]")
    lone = [h for h in dead if h["host_id"] not in hiding]
    if lone:
        print(f"\nFAILING, BUT NOT YET ACTED ON ({len(lone)}) — either the "
              f"link still works for its other hosts (a config problem, not "
              f"an outage) or the failure streak is too short:")
        for h in sorted(lone, key=lambda x: x["remark"]):
            note = by_link.get(h.get("link"), {})
            print(f"  #{h['host_id']:<4} {h['remark'][:40]:<42} "
                  f"link {h.get('link', ''):<14} "
                  f"{note.get('verdict', '?')}/{note.get('reason', '')}")
    contested = [ln for ln in report.get("links") or [] if ln.get("contested")]
    if contested:
        nodes = sorted({ln["entry_node_name"] for ln in contested})
        print(f"\nHELD BACK ({len(contested)} link(s) on {len(nodes)} node(s)) "
              f"— every link on the node failed while the node is still "
              f"carrying traffic, so this is the probe's footing, not the "
              f"fleet. Nothing was hidden:")
        for ln in contested:
            print(f"  {ln['link']:<16} {ln['entry_node_name'][:26]:<28} "
                  f"node moved {ln.get('entry_bytes', 0):,} bytes")
    partial = [h for h in report["hosts"] if h.get("partial")]
    if partial:
        print(f"\nREACHABLE FROM SOME VANTAGES ONLY ({len(partial)}) "
              f"— kept enabled, but the route is flaky:")
        for h in sorted(partial, key=lambda x: x["remark"]):
            print(f"  #{h['host_id']:<4} {h['remark'][:40]:<42} "
                  f"ok from {h.get('vantages_ok')} of {h.get('vantages_tried')}")
    by_id = {h["host_id"]: h for h in report["hosts"]}
    revive = [by_id[i] for i in report["changes"]["enable"] if i in by_id]
    if revive:
        print(f"\nHIDDEN BUT WORKING -> will be restored ({len(revive)}):")
        for h in sorted(revive, key=lambda x: x["remark"]):
            print(f"  #{h['host_id']:<4} {h['remark'][:46]:<48} "
                  f"{h.get('country', '')}")
    shadowed = [by_id[i] for i in report.get("shadowed", []) if i in by_id]
    if shadowed:
        print(f"\nWORKING BUT KEPT HIDDEN ({len(shadowed)}) — a visible host "
              f"already carries the same name:")
        for h in sorted(shadowed, key=lambda x: x["remark"]):
            print(f"  #{h['host_id']:<4} {h['remark'][:46]:<48} "
                  f"node {h['node_id']} {h.get('node_name', '')[:22]}")
    geo = [h for h in report["hosts"] if h["verdict"] == "wrong_geo"]
    if geo:
        print(f"\nTRAFFIC OK BUT UNEXPECTED COUNTRY ({len(geo)}) "
              f"— left enabled, check labelling:")
        for h in sorted(geo, key=lambda x: x["remark"]):
            print(f"  #{h['host_id']:<4} {h['remark'][:38]:<40} "
                  f"labelled {h.get('expected_country')} -> exits "
                  f"{h.get('country')} ({h.get('egress_ip')})")
    dups = report.get("duplicates") or []
    if dups:
        print(f"\nDUPLICATE NAMES IN THE SUBSCRIPTION ({len(dups)}) "
              f"— users see the same entry twice:")
        for d in dups:
            print(f"  {d['remark'][:46]:<48} hosts {d['host_ids']}")
    if report["gaps"]:
        fillable = sum(1 for g in report["gaps"] if g.get("fillable"))
        print(f"\nGAPS: {fillable} fillable, "
              f"{len(report['gaps']) - fillable} blocked by the network path "
              f"— see `gaps` command")


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
    # The guard is about spotting a fleet-wide outage. On a handful of hosts —
    # a targeted re-check of known suspects, say — a high failure rate is the
    # expected outcome, not a red flag.
    if (tested >= MIN_HOSTS_FOR_GUARD
            and fails * 100 // tested > args.max_fail_pct and not args.force):
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


def cmd_apply(args) -> int:
    """Apply the saved report without re-probing.

    Scanning takes a quarter of an hour; when a dry run has already been read
    and agreed with, re-running it just to flip the flags invites a different
    (and unreviewed) verdict.
    """
    report = load_report(args.report)
    live = {int(r[0]): r[1] == "1" for r in mc.db_query(
        "SELECT id, is_disabled FROM hosts")}
    by_id = {h["host_id"]: h for h in report["hosts"]}
    saved = report.get("changes") or {"disable": [], "enable": []}

    # The report already carries the verdict of the link state machine; this
    # command only reconciles it with rows as they are *now*, since a host may
    # have been deleted or flipped by hand since the scan.
    ch = {
        "disable": [i for i in saved["disable"]
                    if i in live and not live[i]],
        "enable": [i for i in saved["enable"] if i in live and live[i]],
    }
    visible = {h["remark"] for i, h in by_id.items()
               if i in live and not live[i]}
    shadowed = [i for i in ch["enable"]
                if by_id.get(i, {}).get("remark") in visible]
    ch["enable"] = [i for i in ch["enable"] if i not in shadowed]

    gone = [i for i in by_id if i not in live]
    if gone:
        print(f"{len(gone)} host(s) from the report no longer exist: {gone}")
    if shadowed:
        print(f"{len(shadowed)} working host(s) left hidden because a visible "
              f"host already uses the same name: {shadowed}")
    age = int(time.time()) - report.get("generated_at", 0)
    print(f"report is {age // 60} min old, covers {report['total']} host(s)")
    report = dict(report, changes=ch)
    return apply_report(report, [], args)


def cmd_matrix(args) -> int:
    report = load_report(args.report)
    print_summary(report)
    return 0


def cmd_gaps(args) -> int:
    report = load_report(args.report)
    gaps = report["gaps"]
    if not gaps:
        print("no gaps: every entry reaches every live exit slot")
        return 0
    by_entry = defaultdict(list)
    for g in gaps:
        by_entry[g["entry_key"]].append(g)

    fillable = sum(1 for g in gaps if g.get("fillable"))
    print(f"{fillable} fillable gap(s), {len(gaps) - fillable} blocked "
          f"(exit reachable from another entry, but not from this one):\n")
    for ek in sorted(by_entry):
        rows = by_entry[ek]
        m = rows[0]
        print(f"{ek}  node {m['node_id']} {m['node_name']} ({m['address']})")
        for g in rows:
            if g.get("fillable"):
                print(f"    {g['slot']:<8} missing   "
                      f"donors: {', '.join(g['donors'][:4])}")
            else:
                print(f"    {g['slot']:<8} blocked   wired but no traffic "
                      f"(hosts {g['dead_host_ids']}) — this entry's uplink "
                      f"cannot reach that exit, cloning will not help")
        todo = sorted({g["slot"] for g in rows if g.get("fillable")})
        if todo:
            print(f"    -> python3 bridge_audit.py fill {ek} "
                  f"{' '.join(todo)} --apply")
        elif rows[0].get("reachable_slots"):
            print(f"    this entry does reach: "
                  f"{', '.join(rows[0]['reachable_slots'])}")
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
    s.add_argument("--hosts", default="",
                   help="comma-separated host ids; the resulting report covers "
                        "only those, so point --report elsewhere")
    s.add_argument("--jobs", type=int, default=6,
                   help="parallel probes per vantage node")
    s.add_argument("--vantages", type=int, default=3,
                   help="how many RU nodes to probe from")
    s.add_argument("--vantage", default="",
                   help="explicit vantage node ids, or 'panel'")
    s.add_argument("--timeout", type=int, default=12)
    s.add_argument("--geo-attempts", dest="geo_tries", type=int, default=0,
                   help="how many geo endpoints a failing probe may try "
                        "(0 = all of them)")
    s.add_argument("--attempts", type=int, default=2,
                   help="sweeps over the failures; the second one catches "
                        "geo rate limits")
    s.add_argument("--user", default=bl.DEFAULT_USER)
    s.add_argument("--include-direct", action="store_true",
                   help="also probe non-bridge RU Direct hosts")
    s.add_argument("--quick", action="store_true",
                   help="probe one host per link instead of all of them; for "
                        "the frequent watchdog run")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("--max-fail-pct", type=int, default=60)
    s.set_defaults(func=cmd_scan)

    a = sub.add_parser("apply", help="apply the saved report, no re-probe")
    a.add_argument("--force", action="store_true")
    a.add_argument("--max-fail-pct", type=int, default=60)
    a.set_defaults(func=cmd_apply, apply=True)

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
