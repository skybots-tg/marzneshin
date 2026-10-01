#!/usr/bin/env python3
"""Run ON the panel. Can every node still reach its own REALITY ``dest``?

``front_watch.py`` asks whether a front *can* front — TLS 1.3, X25519, h2, a
covering certificate — once a day. This asks the cheaper and more urgent
question every five minutes: does the front answer *this node* at all.

They fail differently. A REALITY listener dials ``dest`` before it reads the
client hello (``xtls/reality`` ``Server()``), and even an authorised client
needs the ServerHello it borrows from there. A front that stops answering the
node's address takes every new connection down with it, for everyone, while
the node keeps its gRPC link, reports healthy and shows nothing but a pile of
connections. On 2026-10-01 www.elisa.ee banned EE-1 (node 48) in waves of 30–60
minutes: heartbeat read it as 9–13k active connections, the node held ~4.8k
xray sockets in SYN-SENT to 194.150.66.65:443, and a daily check at 04:20 had
no chance of seeing any of it.

Per node, one ssh round trip, and on the node a stdlib-only script that:

* reads the ``dest`` of every REALITY inbound from the live xray config;
* opens a plain TCP connection to it — no TLS: one more handshake per node
  every few minutes is exactly the kind of load that got EE-1 banned;
* counts the node's sockets stuck in SYN-SENT to that address, which is the
  same failure seen from xray's side and needs no traffic of our own.

A front is *bad* when the connect fails twice or SYN-SENT piles past
``SYN_SENT_ALARM``. Two bad runs in a row open an episode, two good ones close
it; start and end go to ``front_reach.status`` for the panel to alert from
(``app/tasks/front_reach_monitor.py``) and closed episodes to
``front_reach.episodes.jsonl`` for the record.

The run skips itself while the daily front watch or the P2P sweep is active:
those are the fleet-wide ssh storms, and the nodes' sshd MaxStartups is what
loses when they overlap.

    python3 front_reach.py              # one run, one summary line
    python3 front_reach.py --json       # the status it wrote
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import marz_common as mc

DATA_DIR = "/var/lib/marzneshin"
STATUS_PATH = os.path.join(DATA_DIR, "front_reach.status")
STATE_PATH = os.path.join(DATA_DIR, "front_reach.state.json")
HISTORY_PATH = os.path.join(DATA_DIR, "front_reach.episodes.jsonl")

# Bad runs in a row before an episode opens, good runs before it closes. At a
# five-minute cadence that is detection within ten minutes, and one lucky
# connect in the middle of a ban wave does not split it into two alerts.
CONFIRM_BAD = 2
CONFIRM_GOOD = 2
# A healthy node holds 0–10 sockets in SYN-SENT to its front: a handshake there
# takes milliseconds. EE-1 held ~4.8k during the ban.
SYN_SENT_ALARM = 100
# How long closed episodes stay in the status for the panel to report.
RECENT_CLOSED_SEC = 48 * 3600
# Fleet-wide ssh sweeps this run must not overlap.
NEIGHBOURS = ("marz-front-watch.service", "marz-p2p-guard.service")
WORKERS = 4
SSH_TIMEOUT = 45

# Runs on the node with whatever python3 it has (3.6 on the oldest), stdlib
# only. Prints one line: REACH <json>.
REMOTE = r'''
import json, socket, time

CONNECT_TIMEOUT = 4

def decode(hexaddr):
    raw = bytes.fromhex(hexaddr)
    if len(raw) == 4:
        return socket.inet_ntoa(raw[::-1])
    raw = b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
    if raw[:12] == b"\0" * 10 + b"\xff\xff":
        return socket.inet_ntoa(raw[12:])
    return socket.inet_ntop(socket.AF_INET6, raw)

def syn_sent():
    counts = {}
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as f:
                next(f)
                for line in f:
                    p = line.split()
                    if len(p) < 4 or p[3] != "02":
                        continue
                    addr, port = p[2].split(":")
                    key = (decode(addr), int(port, 16))
                    counts[key] = counts.get(key, 0) + 1
        except (OSError, StopIteration, ValueError):
            continue
    return counts

def fronts(cfg):
    out = {}
    for ib in cfg.get("inbounds") or []:
        rs = (ib.get("streamSettings") or {}).get("realitySettings") or {}
        dest = rs.get("dest") or rs.get("target")
        if not isinstance(dest, str) or ":" not in dest:
            continue  # a bare port is a local fallback, not a front
        host, _, port = dest.rpartition(":")
        host = host.strip("[]")
        if not port.isdigit() or not host or host == "localhost" \
                or host.startswith("127."):
            continue
        out.setdefault((host, int(port)), []).append(ib.get("tag") or "?")
    return out

def reach(host, port):
    try:
        ips = sorted({a[4][0] for a in socket.getaddrinfo(
            host, port, socket.AF_INET, socket.SOCK_STREAM)})
    except OSError as e:
        return [], False, None, "resolve: %s" % e
    err = None
    for attempt in range(2):
        ip = ips[attempt % len(ips)]
        t0 = time.time()
        try:
            socket.create_connection((ip, port), CONNECT_TIMEOUT).close()
            return ips, True, int((time.time() - t0) * 1000), None
        except OSError as e:
            err = "%s: %s" % (ip, e)
    return ips, False, None, err

try:
    with open("/var/lib/marznode/xray_config.json") as f:
        cfg = json.load(f)
except (OSError, ValueError) as e:
    print("REACH " + json.dumps({"error": "xray config: %s" % e}))
    raise SystemExit(0)

rows = []
for (host, port), tags in sorted(fronts(cfg).items()):
    ips, ok, ms, err = reach(host, port)
    rows.append({"front": host, "port": port, "inbounds": tags, "ips": ips,
                 "ok": ok, "ms": ms, "error": err})
pending = syn_sent()
for r in rows:
    r["syn_sent"] = sum(pending.get((ip, r["port"]), 0) for ip in r["ips"])
print("REACH " + json.dumps({"fronts": rows}))
'''


# --------------------------------------------------------------------------
# Measuring


def parse_remote(stdout: str) -> dict | None:
    """The node's answer, or None when it never got as far as answering."""
    for line in stdout.splitlines():
        if line.startswith("REACH "):
            try:
                return json.loads(line[6:])
            except ValueError:
                return None
    return None


def probe(ip: str) -> dict:
    """One node: ``{"fronts": [...]}`` or ``{"error": ...}``."""
    r = None
    for attempt in range(2):
        try:
            r = mc.ssh(ip, "python3 -", inp=REMOTE, timeout=SSH_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"error": "ssh timeout"}
        # 255 is ssh itself: on a busy node sshd's MaxStartups drops some
        # attempts before the key exchange. Once more, then give up quietly.
        if r.returncode != 255:
            break
        time.sleep(3)
    answer = parse_remote(r.stdout)
    if answer is None:
        why = (r.stderr or r.stdout or "").strip().splitlines()
        return {"error": (why[-1][:160] if why else f"rc={r.returncode}")}
    return answer


def verdict(row: dict) -> str | None:
    """Why this front is bad from this node, or None if it is fine."""
    if not row.get("ok"):
        return "connect: " + (row.get("error") or "no answer")
    if int(row.get("syn_sent") or 0) >= SYN_SENT_ALARM:
        return f"SYN-SENT: {row['syn_sent']}"
    return None


def busy_neighbours() -> list[str]:
    active = []
    for unit in NEIGHBOURS:
        r = subprocess.run(["systemctl", "is-active", "--quiet", unit])
        if r.returncode == 0:
            active.append(unit)
    return active


def load_nodes() -> dict[int, dict]:
    nodes = {}
    for row in mc.db_query(
            "SELECT id, address, name, status FROM nodes ORDER BY id;"):
        try:
            nodes[int(row[0])] = {"address": row[1], "name": row[2],
                                  "status": row[3]}
        except (ValueError, IndexError):
            continue
    return nodes


# --------------------------------------------------------------------------
# Episodes


def key_of(node_id: int, front: str, port: int) -> str:
    return f"{node_id}|{front}:{port}"


def advance(state: dict, nodes: dict[int, dict], results: dict[int, dict],
            now: int) -> tuple[dict, list[dict], list[dict]]:
    """Fold one run into the episode state.

    ``results`` holds the nodes probed this run: ``{"fronts": [...]}`` or
    ``{"error": ...}``. A node that could not be asked, or was not asked, says
    nothing either way — its streaks stay where they were. Returns the new
    state and the episodes opened and closed by this run.
    """
    fronts = state.setdefault("fronts", {})
    opened, closed = [], []

    def close(entry: dict, ended_at: int, resolution: str) -> None:
        ep = dict(entry["episode"], ended_at=ended_at, resolution=resolution)
        entry["episode"] = None
        closed.append(ep)

    for node_id, res in results.items():
        if "error" in res:
            continue
        node = nodes.get(node_id) or {}
        seen = set()
        for row in res.get("fronts") or []:
            key = key_of(node_id, row["front"], int(row["port"]))
            seen.add(key)
            entry = fronts.setdefault(key, {
                "node_id": node_id, "front": row["front"],
                "port": int(row["port"]), "bad": 0, "good": 0,
                "first_bad_at": None, "first_good_at": None, "episode": None,
            })
            reason = verdict(row)
            syn = int(row.get("syn_sent") or 0)
            entry["last"] = {"at": now, "reason": reason, "syn_sent": syn,
                             "ms": row.get("ms")}
            if reason:
                entry["good"], entry["first_good_at"] = 0, None
                entry["bad"] += 1
                if entry["bad"] == 1:
                    entry["first_bad_at"] = now
                ep = entry["episode"]
                if ep is None and entry["bad"] >= CONFIRM_BAD:
                    ep = entry["episode"] = {
                        "id": f"{key}|{entry['first_bad_at']}",
                        "node_id": node_id, "address": node.get("address"),
                        "name": node.get("name"), "front": row["front"],
                        "port": int(row["port"]),
                        "ips": row.get("ips") or [],
                        "inbounds": len(row.get("inbounds") or []),
                        "started_at": entry["first_bad_at"],
                        "detected_at": now, "reason": reason,
                        "max_syn_sent": syn,
                    }
                    opened.append(dict(ep))
                elif ep is not None:
                    ep["reason"] = reason
                    ep["max_syn_sent"] = max(ep["max_syn_sent"], syn)
            else:
                entry["bad"], entry["first_bad_at"] = 0, None
                entry["good"] += 1
                if entry["good"] == 1:
                    entry["first_good_at"] = now
                if entry["episode"] and entry["good"] >= CONFIRM_GOOD:
                    close(entry, entry["first_good_at"], "recovered")
        # Fronts the node no longer uses: swapped by reality_front_apply.py.
        for key in [k for k, e in fronts.items()
                    if e["node_id"] == node_id and k not in seen]:
            if fronts[key]["episode"]:
                close(fronts[key], now, "front_replaced")
            del fronts[key]

    # Nodes deleted from the panel take their episodes with them.
    for key in [k for k, e in fronts.items() if e["node_id"] not in nodes]:
        if fronts[key]["episode"]:
            close(fronts[key], now, "node_removed")
        del fronts[key]

    recent = state.setdefault("recent_closed", [])
    recent.extend(closed)
    state["recent_closed"] = [ep for ep in recent
                              if now - int(ep["ended_at"]) <= RECENT_CLOSED_SEC]
    return state, opened, closed


def status_of(state: dict, now: int, probed: int, failed: dict[int, str],
              skipped: list[str] | None = None) -> dict:
    fronts = state.get("fronts") or {}
    return {
        "generated_at": now,
        "skipped": skipped or None,
        "nodes_probed": probed,
        "nodes_failed": [{"node_id": n, "error": e}
                         for n, e in sorted(failed.items())],
        "open": [dict(e["episode"], last=e.get("last"))
                 for _, e in sorted(fronts.items()) if e.get("episode")],
        "closed": state.get("recent_closed") or [],
        "fronts": [{"key": k, "bad": e["bad"], **(e.get("last") or {})}
                   for k, e in sorted(fronts.items())],
    }


# --------------------------------------------------------------------------
# Files


def _read_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return default


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _fmt_ts(ts) -> str:
    return time.strftime("%H:%M", time.gmtime(int(ts)))


def run(args) -> dict:
    now = int(time.time())
    busy = busy_neighbours()
    state = _read_json(args.state, {})
    if busy:
        # Keep the status fresh so the panel can tell a skip from a stall.
        status = _read_json(args.status, {})
        status.update(generated_at=now, skipped=busy)
        _write_json(args.status, status)
        print(f"skipped: {', '.join(busy)} running")
        return status

    nodes = load_nodes()
    targets = {nid: n for nid, n in nodes.items() if n["status"] == "healthy"}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        answers = dict(zip(targets, pool.map(
            lambda n: probe(n["address"]), targets.values())))

    state, opened, closed = advance(state, nodes, answers, now)
    _write_json(args.state, state)
    failed = {nid: a["error"] for nid, a in answers.items() if "error" in a}
    status = status_of(state, now, len(answers), failed)
    _write_json(args.status, status)
    if closed:
        with open(args.history, "a", encoding="utf-8") as f:
            for ep in closed:
                f.write(json.dumps(ep, ensure_ascii=False) + "\n")

    n_fronts = sum(len(a.get("fronts") or []) for a in answers.values())
    print(f"{len(answers)} nodes, {n_fronts} fronts, "
          f"open {len(status['open'])}, ssh failed {len(failed)}")
    for ep in opened:
        print(f"  OPEN  node {ep['node_id']} {ep['front']} since "
              f"{_fmt_ts(ep['started_at'])} — {ep['reason']}")
    for ep in closed:
        print(f"  CLOSE node {ep['node_id']} {ep['front']} "
              f"{_fmt_ts(ep['started_at'])}–{_fmt_ts(ep['ended_at'])} "
              f"({ep['resolution']})")
    for nid, err in sorted(failed.items()):
        print(f"  ssh   node {nid}: {err}")
    return status


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--status", default=STATUS_PATH)
    ap.add_argument("--state", default=STATE_PATH)
    ap.add_argument("--history", default=HISTORY_PATH)
    args = ap.parse_args()
    status = run(args)
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
