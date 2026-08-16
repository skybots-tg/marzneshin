#!/usr/bin/env python3
"""Dispatch probes to RU vantage nodes and merge the verdicts.

A single vantage point is not enough. RU providers filter traffic
inconsistently: during development node 43 refused TLS from the panel *and*
from nodes 25 and 40, while node 30 and real subscribers connected fine. Judging
that host from one viewpoint would have hidden a perfectly working server from
everyone.

So a target is probed from several RU nodes and counts as alive if **any**
vantage reaches it — the same bar a user clears. The per-vantage detail is kept,
because "reachable from 1 of 4" is itself a useful signal about a flaky route.
"""
from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

import bridge_lib as bl
import marz_common as mc

RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "bridge_runner.py")
REMOTE_RUNNER = "/tmp/bridge_runner.py"
PANEL = "panel"


def default_vantages(targets, limit: int = 4) -> list[dict]:
    """Pick RU entry nodes to probe from, busiest first.

    Entry nodes make good vantages: they are in RU, we already hold their SSH
    key, and their marznode container ships the xray binary the runner needs.
    """
    seen: dict[int, dict] = {}
    for t in targets:
        seen.setdefault(t.node_id, {
            "node_id": t.node_id, "name": t.node_name,
            "address": t.address, "status": t.node_status,
        })
    usage = {}
    try:
        for nid, cnt in mc.db_query(
            "SELECT node_id, COUNT(DISTINCT user_id) FROM node_user_usages "
            "WHERE created_at > NOW() - INTERVAL 6 HOUR GROUP BY node_id;"
        ):
            usage[int(nid)] = int(cnt)
    except Exception:
        pass
    ranked = sorted(seen.values(),
                    key=lambda n: (n["status"] != "healthy",
                                   -usage.get(n["node_id"], 0)))
    return ranked[:limit]


# Worst case for one probe: xray warm-up, then every geo endpoint in turn
# (the runner rotates through three), then teardown.
GEO_ENDPOINTS = 3
JOB_OVERHEAD = 8


def vantage_deadline(n_jobs: int, workers: int, timeout: int,
                     geo_tries: int | None = None, attempts: int = 2) -> int:
    """Seconds one vantage may spend before it must hand back what it has."""
    waves = -(-n_jobs // max(1, workers))
    lookups = min(geo_tries or GEO_ENDPOINTS, GEO_ENDPOINTS)
    per_job = JOB_OVERHEAD + lookups * (timeout + 5)
    return max(120, min(2400, waves * per_job * max(1, attempts)))


def _build_jobs(targets, user_uuid: str) -> list[dict]:
    jobs = []
    for t in targets:
        if not t.port or not t.pbk:
            continue
        jobs.append({"id": str(t.host_id),
                     "client": bl.build_client(t, 12100, user_uuid)})
    return jobs


def probe_from_vantage(vantage: dict, targets, user_uuid: str,
                       workers: int = 6, timeout: int = 12,
                       geo_tries: int | None = None,
                       attempts: int = 2) -> dict:
    """Ship the runner to one node, execute all jobs there, return results."""
    jobs = _build_jobs(targets, user_uuid)
    if not jobs:
        return {}
    deadline = vantage_deadline(len(jobs), workers, timeout, geo_tries, attempts)
    payload = json.dumps({"jobs": jobs, "workers": workers,
                          "timeout": timeout, "deadline": deadline,
                          "geo_tries": geo_tries or 0, "attempts": attempts})

    if vantage["address"] == PANEL:
        r = subprocess.run(["python3", RUNNER], input=payload,
                           capture_output=True, text=True,
                           timeout=deadline + 90)
    else:
        cp = subprocess.run(
            ["scp", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             "-o", "BatchMode=yes", "-i", mc.KEY, RUNNER,
             f"root@{vantage['address']}:{REMOTE_RUNNER}"],
            capture_output=True, text=True, timeout=60)
        if cp.returncode != 0:
            return {"__error__": f"scp failed: {cp.stderr[:200]}"}
        r = mc.ssh(vantage["address"], f"python3 {REMOTE_RUNNER}",
                   inp=payload, timeout=deadline + 120)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]).get("results", {})
    except Exception:
        return {"__error__": (r.stdout[-200:] or r.stderr[-200:] or
                              "no output from runner")}


def probe_all(targets, vantages, user_uuid: str, workers: int = 6,
              timeout: int = 12, on_vantage_done=None,
              geo_tries: int | None = None, attempts: int = 2) -> dict:
    """Probe every target from every vantage, in parallel across vantages."""
    per_vantage: dict[str, dict] = {}

    def one(v):
        key = vantage_key(v)
        res = probe_from_vantage(v, targets, user_uuid, workers, timeout,
                                 geo_tries, attempts)
        per_vantage[key] = res
        if on_vantage_done:
            on_vantage_done(v, res)

    with ThreadPoolExecutor(max_workers=max(1, len(vantages))) as pool:
        list(pool.map(one, vantages))
    return per_vantage


def vantage_key(vantage: dict) -> str:
    return vantage["name"] if vantage["address"] == PANEL else str(
        vantage["node_id"])


def vantage_origins(vantages) -> dict[str, str]:
    """vantage key -> "RU" or "FOREIGN", read off the node's flag emoji.

    The panel sits in Norway, so it always counts as foreign.
    """
    out = {}
    for v in vantages:
        if v["address"] == PANEL:
            out[vantage_key(v)] = "FOREIGN"
        else:
            iso = bl.flag_to_iso(v.get("name") or "")
            out[vantage_key(v)] = "RU" if iso == "RU" else "FOREIGN"
    return out


# Which vantage speaks for a tier's actual users. UNIVERSAL and ELITE enter
# through a RU node and are sold to people inside Russia, so a RU vantage is the
# honest witness for them. FAST connects straight to a foreign server and is
# what subscribers abroad use. Judging FAST from Moscow hides a whole class of
# outage — a server can be perfectly reachable from RU and dead for everyone
# else — which is exactly how broken FR and DE exits stayed visible for weeks.
TIER_AUDIENCE = {"universal": "RU", "elite": "RU", "fast": "FOREIGN"}


def merge(targets, per_vantage: dict, origins: dict[str, str] | None = None) -> None:
    """Collapse per-vantage results onto each target's ``result``.

    Within the audience that matters for a target's tier, it passes if any
    vantage got traffic out of it: RU providers filter inconsistently, and a
    host reachable from one subscriber's network is not dead just because
    another's drops it. Failures are only trusted when every vantage in that
    audience agrees.

    When no vantage represents the right audience — a hand-run scan from a
    single RU node, say — the target is judged on whatever ran and marked
    ``audience: "fallback"``, because a verdict from the wrong side of the
    border is still better than none.
    """
    origins = origins or {}
    for t in targets:
        views = {}
        for vkey, res in per_vantage.items():
            if "__error__" in res:
                continue
            r = res.get(str(t.host_id))
            # A vantage that ran out of time never tested this host; counting
            # that as evidence of failure would hide a working bridge.
            if r and r.get("verdict") != "skip":
                views[vkey] = r
        if not views:
            t.result = {"verdict": "skip", "error": "not probed anywhere"}
            continue

        by_vantage = dict(views)
        wanted = TIER_AUDIENCE.get(t.tier)
        audience = wanted or "any"
        if wanted:
            speaking = {k: v for k, v in views.items()
                        if origins.get(k, wanted) == wanted}
            if speaking:
                views = speaking
            else:
                audience = "fallback"

        good = {k: v for k, v in views.items() if v["verdict"] == "pass"}
        best = (min(good.values(), key=lambda v: v.get("elapsed", 99))
                if good else next(iter(views.values())))
        t.result = dict(best)
        t.result["audience"] = audience
        # How many vantages actually spoke to this verdict. One is not a
        # consensus: a single vantage with a routing problem of its own would
        # otherwise be enough to condemn a server that everybody else reaches.
        t.result["witnesses"] = len(views)
        t.result["vantages_ok"] = sorted(good)
        t.result["vantages_tried"] = sorted(views)
        t.result["by_vantage"] = {
            k: {"verdict": v["verdict"],
                "country": v.get("country") or v.get("error")}
            for k, v in by_vantage.items()
        }
        if not good:
            t.result["verdict"] = "fail"
            continue

        countries = {bl.egress_country(v.get("country"), v.get("egress_ip"))
                     for v in good.values()}
        t.result["verdict"] = "pass"
        t.result["countries"] = sorted(c for c in countries if c)
        if t.iso and t.iso not in countries:
            t.result["verdict"] = "wrong_geo"
            t.result["expected_country"] = t.iso
        elif t.iso:
            # Report the labelled country rather than whichever vantage
            # happened to answer first, so the UI does not look self-
            # contradictory when providers disagree.
            t.result["country"] = t.iso
        if t.is_bridge and countries == {"RU"}:
            t.result["verdict"] = "fail"
            t.result["error"] = "ru_leak"
            t.result["detail"] = "bridge egress stayed in RU (routing missing)"
        elif len(good) < len(views):
            t.result["partial"] = True
