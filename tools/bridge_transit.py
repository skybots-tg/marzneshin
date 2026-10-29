#!/usr/bin/env python3
"""Run ON THE PANEL. Keep every Russian node's legs open without a human.

Russia cuts our paths by IP, a few at a time and without warning: on
2026-10-29 four exits closed for seven RU entries in one afternoon, and the
panel had lost two nodes the week before. Each time the cure was the same --
send that leg through another Russian machine that still gets through
(bridge_relay.py) -- and each time it waited for someone to read an alert.
This does it on a timer:

1. survey -- every RU node (and the panel, for its gRPC legs to the nodes)
   opens fresh TLS sessions to each of its legs, the way it does now and the
   way it would without bridge_relay (transit_probe.py);
2. a leg that stays broken for BAD_RUNS runs gets candidates: every relay in
   RELAY_POOL measures the same ``dst:dport`` itself, and the source checks
   it can reach the relay;
3. the best candidate that clears GOOD becomes an automatic row in
   bridge_relay.auto.routes, laid over the hand-kept table; machines are
   updated relay first, source second, old relay last, the leg is measured
   again from the source and rolled back if it did not get better;
4. a leg on an automatic row goes back to its baseline (the hand-kept row, or
   the direct path) once that baseline has been good for HEAL_RUNS runs.

A leg nobody reaches -- a dead node, a dead exit -- is left alone: no relay
fixes it, and the hosts on it are bridge_audit's business. The hand-kept table
is never edited; automatic rows only shadow it. Each move lands in
``bridge_transit.status`` and the panel posts it as #BridgeTransit.

    python3 bridge_transit.py run            # survey and print, change nothing
    python3 bridge_transit.py run --apply    # what the timer does
    python3 bridge_transit.py run --apply --now   # act on one bad run
    python3 bridge_transit.py status         # automatic rows and recent moves
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import bridge_relay as brl
import bridge_relay_install as inst
import marz_common as mc

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, "transit_probe.py")
REMOTE_PROBE = "/tmp/transit_probe.py"
DATA = "/var/lib/marzneshin"
STATE_PATH = os.path.join(DATA, "bridge_transit.state.json")
STATUS_PATH = os.path.join(DATA, "bridge_transit.status")
PANEL_IP = inst.PANEL_IP
RU_FLAG = "\U0001F1F7\U0001F1FA"

# Machines that may carry other nodes' legs, best first. Webhost1 RU-2 (50) and
# RU-1 (40) reach every exit and the panel sees them directly; DataCheap
# RU-2-new (43) idles on a wide channel but loses NL-1 and part of GE-2. 40
# carries the most subscribers itself, so it comes last.
RELAY_POOL = [ip for ip in os.environ.get(
    "TRANSIT_RELAYS", "185.179.189.226,45.81.33.150,185.179.191.236").split(",") if ip]
AUTO_PORTS = (48000, 48999)         # hand-kept rows live in 470xx-479xx
PANEL_PORTS = (53042, 22)           # gRPC decides; SSH follows the same relay

N_SURVEY = 6
N_CHOOSE = 12
TIMEOUT = 5
# Share of fresh handshakes that must get an answer. Below BAD a client sees
# the server as flaky or dead (GE-2 through 43 at 19/24 already showed); a
# replacement has to clear GOOD, the level every healthy leg sits at.
BAD = 0.75
GOOD = 0.9
BAD_RUNS = 2
HEAL_RUNS = 3
MAX_MOVES = 12
# Bridge legs one relay may carry (hand-kept and automatic), and the step in
# which load starts to count against an equally good relay.
RELAY_CAP = int(os.environ.get("TRANSIT_RELAY_CAP", "60"))
LOAD_STEP = 8
EVENTS_KEPT = 200


@dataclass
class Leg:
    src: str
    dst: str
    dport: int
    sni: str
    tag: str
    direct: float | None = None     # share answered without bridge_relay
    eff: float | None = None        # share answered the way traffic goes now

    @property
    def k3(self) -> tuple:
        return (self.src, self.dst, self.dport)

    @property
    def key(self) -> str:
        return f"{self.src}>{self.dst}:{self.dport}"

    @property
    def is_panel(self) -> bool:
        return self.src == PANEL_IP


# ── tables ───────────────────────────────────────────────────────────

def by_leg(routes) -> dict[tuple, brl.Route]:
    return {(r.src, r.dst, r.dport): r for r in routes if not r.via_wg}


def auto_text(rows) -> str:
    lines = ["# Written by bridge_transit.py -- edit bridge_relay.routes instead;",
             "# a row here shadows the hand-kept one for the same src dst dport."]
    for r in sorted(rows, key=lambda r: (r.src, r.dst, r.dport)):
        lines.append(f"{r.src:<18} {r.relay:<16} {r.rport:<6} {r.dst:<16} {r.dport:<6} {r.tag}")
    return "\n".join(lines) + "\n"


def effective(base_text: str, auto: dict) -> tuple[str, dict]:
    """The table every machine would get with these automatic rows."""
    text = brl.overlay(base_text, auto_text(auto.values()))
    return text, by_leg(brl.parse_routes(text))


def free_port(relay: str, taken: set, listening: set) -> int:
    for port in range(AUTO_PORTS[0], AUTO_PORTS[1] + 1):
        if (relay, port) not in taken and port not in listening:
            return port
    raise RuntimeError(f"no free automatic relay port left on {relay}")


def install_order(old: dict, new: dict, keys) -> list[str]:
    """Relays that gain rows, then the sources, then relays that lose them.

    A source switching before its new relay has the rows would send the leg
    into nothing; an old relay dropping its rows first would cut a leg that
    may still be the only one working. Every machine gets the whole table, so
    the order is the only thing that matters.
    """
    def relays(table):
        return {table[k].relay for k in keys if k in table}
    gaining = sorted(relays(new) - relays(old))
    losing = sorted(relays(old) - relays(new))
    out: list[str] = []
    for ip in gaining + sorted({k[0] for k in keys}) + losing:
        if ip not in out:
            out.append(ip)
    return out


# ── decisions (pure) ─────────────────────────────────────────────────

def pick(leg: Leg, relay_q: dict, reach: dict, load: dict,
         now_relay: str | None, baseline_relay: str | None):
    """Best way for one broken leg: (relay or None for direct, share), or None.

    Ranked by measured share first -- 12/12 beats 11/12, and that one handshake
    was the whole difference between 50 and 43 for GE-2 -- then the baseline,
    then how loaded a relay already is (in steps of LOAD_STEP legs, so equal
    relays share the work instead of the first one taking all of it), then
    RELAY_POOL order. A relay at RELAY_CAP legs takes no more. The relay the
    leg is failing on now is not a candidate. Direct is one only when no
    hand-kept row covers the leg: the overlay can shadow a row with another
    relay, not with nothing.
    """
    options = []
    if (baseline_relay is None and now_relay is not None
            and leg.direct is not None and leg.direct >= GOOD):
        options.append((leg.direct, 0, -1, -1, None))
    for i, relay in enumerate(RELAY_POOL):
        if relay in (leg.src, leg.dst) or relay == now_relay:
            continue
        q = relay_q.get((relay, leg.dst, leg.dport))
        if q is None or q < GOOD or reach.get((leg.src, relay), 0) < 2 / 3:
            continue
        if load.get(relay, 0) >= RELAY_CAP and relay != baseline_relay:
            continue
        options.append((q, 0 if relay == baseline_relay else 1,
                        load.get(relay, 0) // LOAD_STEP, i, relay))
    if not options:
        return None
    best = sorted(options, key=lambda o: (-o[0], o[1], o[2], o[3]))[0]
    return best[4], best[0]


def plan(legs: list[Leg], static: dict, auto: dict, merged: dict, streaks: dict,
         relay_q: dict, reach: dict, answered: set, now: bool = False):
    """Decide this run's changes. Returns (changes, stuck); mutates streaks.

    A change is ``(k3, relay or None, why, share)``: None gives the leg back
    to its baseline. ``why`` is ``moved``, ``baseline`` (the best way out of a
    broken leg is where it came from), ``returned`` (the baseline healed) or
    ``gone`` (the leg left the node's config).
    """
    by_k = {leg.k3: leg for leg in legs}
    changes, stuck = [], []

    for k, row in auto.items():
        if k[2] == PANEL_PORTS[1] and (k[0], k[1], PANEL_PORTS[0]) in auto:
            continue    # the SSH twin follows its gRPC row
        leg = by_k.get(k)
        if leg is None:
            if k[0] in answered:
                changes.append((k, None, "gone", None))
            continue
        base = static.get(k)
        base_q = relay_q.get((base.relay, leg.dst, leg.dport)) if base else leg.direct
        s = streaks[leg.key]
        s["heal"] = s.get("heal", 0) + 1 if base_q is not None and base_q >= GOOD else 0
        if s["heal"] >= HEAL_RUNS and s["bad"] == 0:
            changes.append((k, None, "returned", base_q))

    load: dict[str, int] = {}
    for row in merged.values():
        if row.src != PANEL_IP:     # gRPC and SSH carry next to nothing
            load[row.relay] = load.get(row.relay, 0) + 1
    broken = [leg for leg in legs
              if streaks[leg.key].get("share") is not None
              and streaks[leg.key]["share"] < BAD
              and (streaks[leg.key]["bad"] >= BAD_RUNS or now)]
    for leg in sorted(broken, key=lambda l: streaks[l.key]["share"]):
        cur, base = merged.get(leg.k3), static.get(leg.k3)
        choice = pick(leg, relay_q, reach, load, cur.relay if cur else None,
                      base.relay if base else None)
        if choice is None:
            seen = [q for (_, d, p), q in relay_q.items() if (d, p) == (leg.dst, leg.dport)]
            stuck.append({"leg": leg.key, "tag": leg.tag, "share": streaks[leg.key]["share"],
                          "best": max(seen) if seen else 0,
                          "reason": "nobody_reaches" if not seen or max(seen) == 0
                          else "no_good_relay"})
            continue
        relay, q = choice
        if relay is None or (base is not None and relay == base.relay):
            if leg.k3 in auto:
                changes.append((leg.k3, None, "baseline", q))
        else:
            changes.append((leg.k3, relay, "moved", q))
            load[relay] = load.get(relay, 0) + 1
    # broken legs first: they are why this runs
    changes.sort(key=lambda c: c[2] not in ("moved", "baseline"))
    return changes[:MAX_MOVES], stuck


def rewrite(auto: dict, changes, merged: dict, listening: dict, names: dict, legs) -> dict:
    """The automatic table after ``changes``; panel legs carry their SSH twin."""
    by_k = {leg.k3: leg for leg in legs}
    new = dict(auto)
    taken = {(r.relay, r.rport) for r in merged.values()}
    for k, relay, why, q in changes:
        twins = [k] + ([(k[0], k[1], PANEL_PORTS[1])] if k[0] == PANEL_IP else [])
        for kk in twins:
            new.pop(kk, None)
        if relay is None:
            continue
        leg = by_k[k]
        label = "panel" if leg.is_panel else f"n{names.get(leg.src, '?').split(' ', 1)[0]}"
        for kk in twins:
            port = free_port(relay, taken, listening.get(relay, set()))
            taken.add((relay, port))
            tag = f"auto {label} {leg.tag}" + (" ssh" if kk[2] == PANEL_PORTS[1] else "")
            new[kk] = brl.Route(k[0], relay, port, k[1], kk[2], tag.strip())
    return new


# ── remote ───────────────────────────────────────────────────────────

def probe_on(ip: str, job: dict, timeout: int) -> dict | None:
    with open(PROBE, encoding="utf-8") as f:
        script = f.read()
    payload = json.dumps(job)
    try:
        if ip == PANEL_IP:
            r = subprocess.run(["python3", PROBE], input=payload, capture_output=True,
                               text=True, timeout=timeout)
        else:
            b64 = base64.b64encode(script.encode()).decode()
            r = mc.ssh(ip, f"echo {b64} | base64 -d > {REMOTE_PROBE} && python3 {REMOTE_PROBE}",
                       inp=payload, timeout=timeout)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001 - an unreachable machine just has no say
        return None


def ru_nodes() -> list[dict]:
    rows = mc.db_query("SELECT id, name, address, status FROM nodes;")
    return [{"id": int(r[0]), "name": r[1], "address": r[2], "status": r[3]}
            for r in rows if len(r) >= 4 and RU_FLAG in r[1] and r[3] != "disabled"]


def survey(nodes: list[dict], merged: dict):
    """Every leg of every RU node and of the panel, measured from its source."""
    relayed: dict[str, list] = {}
    for (src, dst, dport) in merged:
        relayed.setdefault(src, []).append([dst, dport])
    jobs = {}
    for n in nodes:
        jobs[n["address"]] = {
            "from_config": True, "relayed": relayed.get(n["address"], []),
            "n": N_SURVEY, "timeout": TIMEOUT, "workers": 8,
            "tcp": [[ip, 22] for ip in RELAY_POOL if ip != n["address"]]}
    jobs[PANEL_IP] = {
        "legs": [{"dst": n["address"], "dport": PANEL_PORTS[0], "sni": "",
                  "tag": f"panel {n['id']}"} for n in nodes],
        "relayed": [x for x in relayed.get(PANEL_IP, []) if x[1] == PANEL_PORTS[0]],
        "n": N_SURVEY, "timeout": TIMEOUT, "workers": 12,
        "tcp": [[ip, 22] for ip in RELAY_POOL]}
    with ThreadPoolExecutor(max_workers=8) as pool:
        answers = dict(zip(jobs, pool.map(lambda ip: probe_on(ip, jobs[ip], 420), jobs)))
    legs, reach = [], {}
    for src, ans in answers.items():
        if not ans:
            continue
        for item in ans.get("legs") or []:
            n = item.get("n") or N_SURVEY
            legs.append(Leg(src, item["dst"], int(item["dport"]), item.get("sni") or "",
                            item.get("tag") or "", item["direct"] / n,
                            None if item.get("eff") is None else item["eff"] / n))
        for target, k in (ans.get("tcp") or {}).items():
            reach[(src, target.rsplit(":", 1)[0])] = k / 3
    return legs, reach, {ip for ip, ans in answers.items() if ans}


def measure_relays(wanted: dict[str, list[Leg]]):
    """relay -> legs to try from it; returns (shares, listening ports)."""
    def one(relay):
        ans = probe_on(relay, {
            "legs": [{"dst": l.dst, "dport": l.dport, "sni": l.sni, "tag": l.tag}
                     for l in wanted[relay]],
            "n": N_CHOOSE, "timeout": TIMEOUT, "workers": 8,
            "listen_range": list(AUTO_PORTS)}, 420)
        return relay, ans
    shares, listening = {}, {}
    with ThreadPoolExecutor(max_workers=max(1, len(wanted))) as pool:
        for relay, ans in pool.map(one, wanted):
            if not ans:
                continue
            listening[relay] = set(ans.get("listening") or [])
            for item in ans.get("legs") or []:
                shares[(relay, item["dst"], int(item["dport"]))] = item["direct"] / item["n"]
    return shares, listening


def share_of(item: dict | None) -> float | None:
    if not item:
        return None
    k = item["eff"] if item.get("eff") is not None else item["direct"]
    return k / item["n"]


# ── run ──────────────────────────────────────────────────────────────

def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _write_auto(auto: dict):
    tmp = inst.AUTO_ROUTES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(auto_text(auto.values()))
    os.replace(tmp, inst.AUTO_ROUTES)


def ship(base_text: str, old: dict, auto: dict, keys, script: str) -> tuple[list, dict]:
    """Write ``auto``, push the machines ``keys`` touch in safe order."""
    text, new = effective(base_text, auto)
    _write_auto(auto)
    failed = []
    for ip in install_order(old, new, keys):
        ok, state = inst.push(ip, text, "", script)
        print(f"    push {ip:<16} {'OK  ' if ok else 'FAIL'} {state}")
        if not ok:
            failed.append(ip)
    return failed, new


def run(apply: bool, now: bool) -> int:
    held = inst.lock(blocking=False) if apply else True
    if held is None:
        print("another relay change is in progress; skipping this run")
        return 0
    t0 = time.time()
    with open(inst.ROUTES, encoding="utf-8") as f:
        base_text = f.read()
    static = by_leg(brl.parse_routes(base_text))
    try:
        with open(inst.AUTO_ROUTES, encoding="utf-8") as f:
            auto = by_leg(brl.parse_routes(f.read()))
    except FileNotFoundError:
        auto = {}
    _, merged = effective(base_text, auto)

    nodes = ru_nodes()
    names = {n["address"]: f"{n['id']} {n['name']}" for n in nodes}
    names[PANEL_IP] = "панель"
    all_names = {r[1]: f"{r[0]} {r[2]}" for r in
                 mc.db_query("SELECT id, address, name FROM nodes;") if len(r) >= 3}
    legs, reach, answered = survey(nodes, merged)
    print(f"survey: {len(legs)} legs from {len(answered)} of {len(nodes) + 1} machines "
          f"({time.time() - t0:.0f}s)")

    state = _load(STATE_PATH, {"legs": {}})
    streaks = state.setdefault("legs", {})
    for leg in legs:
        share = leg.eff if leg.k3 in merged else leg.direct
        s = streaks.setdefault(leg.key, {"bad": 0, "heal": 0})
        s["bad"] = 0 if share is None or share >= BAD else s["bad"] + 1
        s["share"] = share
        s["seen"] = int(t0)

    # Relays get measured only for what needs a decision: broken legs, and
    # automatic rows whose hand-kept baseline goes through a relay.
    wanted: dict[str, list[Leg]] = {}
    by_k = {leg.k3: leg for leg in legs}
    for leg in legs:
        s = streaks[leg.key]
        if s["share"] is not None and s["share"] < BAD and (s["bad"] >= BAD_RUNS or now):
            for relay in RELAY_POOL:
                if relay not in (leg.src, leg.dst):
                    wanted.setdefault(relay, []).append(leg)
    for k in auto:
        if k in static and k in by_k:
            wanted.setdefault(static[k].relay, []).append(by_k[k])
    relay_q, listening = measure_relays(wanted) if wanted else ({}, {})

    changes, stuck = plan(legs, static, auto, merged, streaks, relay_q, reach, answered, now)
    for item in stuck:
        item["src"] = names.get(item["leg"].split(">")[0], "")
    for k, relay, why, q in changes:
        cur = merged.get(k)
        to = relay or (static[k].relay if k in static else "direct")
        tag = by_k[k].tag if k in by_k else (auto[k].tag if k in auto else "")
        print(f"  {why:<9} {k[0]}>{k[1]}:{k[2]:<6} {tag:<24} "
              f"{cur.relay if cur else 'direct'} -> {to}" + (f"  ({q:.0%})" if q else ""))
    for item in stuck:
        print(f"  stuck     {item['leg']:<34} {item['tag']:<24} {item['reason']}")

    if not apply:
        print(f"dry run: {len(changes)} change(s) not applied")
        return 0

    status = _load(STATUS_PATH, {"events": []})
    events = []
    told = state.setdefault("told", [])
    for item in stuck:
        # one message per leg until it is fixed, not one per run
        if item["reason"] == "no_good_relay" and item["leg"] not in told:
            told.append(item["leg"])
            leg = item["leg"]
            events.append({"kind": "no_path", "leg": leg, "src": item["src"],
                           "tag": item["tag"], "share": item["share"], "best": item["best"],
                           "dst": all_names.get(leg.split(">")[1].split(":")[0], "")})
    still = {i["leg"] for i in stuck}
    state["told"] = [x for x in told if x in still]

    if changes:
        events += apply_changes(base_text, changes, auto, merged, static, legs, listening,
                                names, all_names)
    for i, e in enumerate(events):
        e.setdefault("ts", int(time.time()))
        e["id"] = f"{e['ts']}-{i}-{e['leg']}"
        status["events"].append(e)
    status["events"] = status["events"][-EVENTS_KEPT:]
    final = _load_auto()
    status.update({
        "updated_at": int(time.time()), "duration": int(time.time() - t0),
        "machines": len(answered), "expected": len(nodes) + 1, "legs": len(legs),
        "auto_rows": len(final),
        "relays": {ip: sum(1 for r in final.values() if r.relay == ip) for ip in RELAY_POOL},
        "stuck": stuck,
    })
    for key in [k for k, s in streaks.items() if s.get("seen", 0) < t0 - 7 * 86400]:
        del streaks[key]
    _save(STATE_PATH, state)
    _save(STATUS_PATH, status)
    print(f"done in {time.time() - t0:.0f}s: {len(changes)} change(s), "
          f"{len(final)} automatic row(s)")
    return 0


def _load_auto() -> dict:
    try:
        with open(inst.AUTO_ROUTES, encoding="utf-8") as f:
            return by_leg(brl.parse_routes(f.read()))
    except FileNotFoundError:
        return {}


def apply_changes(base_text, changes, auto, merged, static, legs, listening,
                  names, all_names) -> list[dict]:
    """Install, verify from the source, roll back what did not help."""
    with open(inst.SCRIPT, encoding="utf-8") as f:
        script = f.read()
    by_k = {leg.k3: leg for leg in legs}
    keys = set()
    for k, *_ in changes:
        keys |= {k, (k[0], k[1], PANEL_PORTS[1])} if k[0] == PANEL_IP else {k}

    new_auto = rewrite(auto, changes, merged, listening, names, legs)
    failed, new = ship(base_text, merged, new_auto, keys, script)
    if failed:
        # a relay that did not take its rows must not get traffic: put back
        # every change that leans on it, and push again
        backed = {k for k in keys if k in new and new[k].relay in failed}
        for k in backed:
            if k in auto:
                new_auto[k] = auto[k]
            else:
                new_auto.pop(k, None)
        if backed:
            _, new = ship(base_text, new, new_auto, backed, script)

    verify: dict[str, list[Leg]] = {}
    for k, relay, why, q in changes:
        if k in by_k:
            verify.setdefault(k[0], []).append(by_k[k])
    events, rollback = [], set()
    for src, vlegs in verify.items():
        ans = probe_on(src, {
            "legs": [{"dst": l.dst, "dport": l.dport, "sni": l.sni, "tag": l.tag} for l in vlegs],
            "relayed": [[l.dst, l.dport] for l in vlegs if l.k3 in new],
            "n": N_SURVEY, "timeout": TIMEOUT, "workers": 8}, 300) or {}
        got = {(i["dst"], int(i["dport"])): i for i in ans.get("legs") or []}
        for l in vlegs:
            after = share_of(got.get((l.dst, l.dport)))
            before = l.eff if l.k3 in merged else l.direct
            why = next(c[2] for c in changes if c[0] == l.k3)
            frm = merged[l.k3].relay if l.k3 in merged else "direct"
            to = new[l.k3].relay if l.k3 in new else "direct"
            ev = {"leg": l.key, "src": names.get(l.src, l.src), "tag": l.tag,
                  "dst": all_names.get(l.dst, l.dst), "from": frm, "to": to,
                  "from_name": all_names.get(frm, frm), "to_name": all_names.get(to, to),
                  "before": before, "after": after, "why": why,
                  "kind": "returned" if why in ("returned", "baseline") else "moved"}
            if after is None or (after < BAD and (before is None or after <= before)):
                ev["kind"] = "rolled_back"
                rollback.add(l.k3)
            events.append(ev)
    if rollback:
        rkeys = set()
        for k in rollback:
            twins = {k, (k[0], k[1], PANEL_PORTS[1])} if k[0] == PANEL_IP else {k}
            rkeys |= twins
            for kk in twins:
                if kk in auto:
                    new_auto[kk] = auto[kk]
                else:
                    new_auto.pop(kk, None)
        print(f"  rolling back {len(rollback)} leg(s) that did not get better")
        ship(base_text, new, new_auto, rkeys, script)
    for k, relay, why, q in changes:
        if why == "gone":
            events.append({"kind": "gone", "leg": f"{k[0]}>{k[1]}:{k[2]}",
                           "src": names.get(k[0], k[0]), "tag": auto[k].tag if k in auto else ""})
    return events


def status() -> int:
    st = _load(STATUS_PATH, {})
    try:
        with open(inst.AUTO_ROUTES, encoding="utf-8") as f:
            print(f.read().rstrip())
    except FileNotFoundError:
        print("(no automatic rows)")
    if st:
        print(f"\nlast run {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(st.get('updated_at', 0)))} "
              f"UTC, {st.get('legs')} legs from {st.get('machines')}/{st.get('expected')} "
              f"machines, {st.get('duration')}s")
        for e in st.get("events", [])[-15:]:
            print(f"  {time.strftime('%m-%d %H:%M', time.gmtime(e['ts']))} {e['kind']:<11} "
                  f"{e['leg']:<36} {e.get('tag', ''):<22} {e.get('from', '')} -> {e.get('to', '')}")
        for s in st.get("stuck", []):
            print(f"  stuck {s['leg']} {s['tag']} {s['reason']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--apply", action="store_true")
    r.add_argument("--now", action="store_true",
                   help=f"act on legs bad in this run, without waiting {BAD_RUNS} runs")
    sub.add_parser("status")
    args = ap.parse_args()
    if args.cmd == "status":
        return status()
    return run(args.apply, args.now)


if __name__ == "__main__":
    sys.exit(main())
