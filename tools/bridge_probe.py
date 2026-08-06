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


def vantage_deadline(n_jobs: int, workers: int, timeout: int) -> int:
    """Seconds one vantage may spend before it must hand back what it has."""
    waves = -(-n_jobs // max(1, workers))
    per_job = JOB_OVERHEAD + GEO_ENDPOINTS * (timeout + 5)
    return max(120, min(2400, waves * per_job))


def _build_jobs(targets, user_uuid: str) -> list[dict]:
    jobs = []
    for t in targets:
        if not t.port or not t.pbk:
            continue
        jobs.append({"id": str(t.host_id),
                     "client": bl.build_client(t, 12100, user_uuid)})
    return jobs


def probe_from_vantage(vantage: dict, targets, user_uuid: str,
                       workers: int = 6, timeout: int = 12) -> dict:
    """Ship the runner to one node, execute all jobs there, return results."""
    jobs = _build_jobs(targets, user_uuid)
    if not jobs:
        return {}
    deadline = vantage_deadline(len(jobs), workers, timeout)
    payload = json.dumps({"jobs": jobs, "workers": workers,
                          "timeout": timeout, "deadline": deadline})

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
              timeout: int = 12, on_vantage_done=None) -> dict:
    """Probe every target from every vantage, in parallel across vantages."""
    per_vantage: dict[str, dict] = {}

    def one(v):
        key = v["name"] if v["address"] == PANEL else str(v["node_id"])
        res = probe_from_vantage(v, targets, user_uuid, workers, timeout)
        per_vantage[key] = res
        if on_vantage_done:
            on_vantage_done(v, res)

    with ThreadPoolExecutor(max_workers=max(1, len(vantages))) as pool:
        list(pool.map(one, vantages))
    return per_vantage


def merge(targets, per_vantage: dict) -> None:
    """Collapse per-vantage results onto each target's ``result``.

    A target passes if any vantage got traffic out of it. Failures are only
    trusted when *every* vantage agrees, which is what keeps provider-level
    filtering from masquerading as a dead bridge.
    """
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

        good = {k: v for k, v in views.items() if v["verdict"] == "pass"}
        best = (min(good.values(), key=lambda v: v.get("elapsed", 99))
                if good else next(iter(views.values())))
        t.result = dict(best)
        t.result["vantages_ok"] = sorted(good)
        t.result["vantages_tried"] = sorted(views)
        t.result["by_vantage"] = {
            k: {"verdict": v["verdict"],
                "country": v.get("country") or v.get("error")}
            for k, v in views.items()
        }
        if not good:
            t.result["verdict"] = "fail"
            continue

        countries = {v.get("country") for v in good.values()}
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
