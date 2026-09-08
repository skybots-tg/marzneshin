#!/usr/bin/env python3
"""Run ON the panel. Check that every node's masking front still works.

A REALITY listener does not serve its own TLS: it relays the handshake of
``dest``, the real site it pretends to be. That makes ``dest`` an outside
dependency inside the critical path, and outside dependencies change without
telling anyone. When ``www.free.fr`` stopped negotiating TLS 1.3 with X25519,
both French exits kept answering their ports, kept their keys, kept reporting
healthy — and refused every subscriber under every ``serverName`` they list,
because there was no handshake left to borrow. 200 GB a day went to zero and
stayed there for three days.

Nothing else in the fleet looks at this. The audit probes bridges and would
eventually hide the hosts; node health checks the panel's own gRPC link; the
traffic alarms notice the symptom hours later. One openssl handshake per node
answers it directly, and it costs one ssh round trip.

Checked per node, from that node, because that is where the handshake is made:
TLS 1.3, an X25519 key share, ALPN ``h2``, and a certificate that actually
covers the name — the same four things reality_front_probe.py measures when
choosing a front, asked here of the front already in use.

Writes ``/var/lib/marzneshin/reality_fronts.status`` for the panel to alert
from, and exits non-zero if any front is broken.

    python3 front_watch.py              # table
    python3 front_watch.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import marz_common as mc
import reality_front_probe as rfp

STATUS_PATH = "/var/lib/marzneshin/reality_fronts.status"


def node_fronts(ip: str) -> tuple[list[str], dict[str, list[str]], str | None]:
    """(fronts in use on this node, front -> inbound tags, failure reason)."""
    try:
        cfg = mc.node_cfg(ip)
    except Exception as exc:
        return [], {}, str(exc)[:120]
    by_front: dict[str, list[str]] = {}
    for ib in cfg.get("inbounds", []):
        rs = (ib.get("streamSettings") or {}).get("realitySettings")
        if not rs:
            continue
        dest = (rs.get("dest") or "").split(":")[0]
        if dest:
            by_front.setdefault(dest, []).append(ib.get("tag", "?"))
    return sorted(by_front), by_front, None


def check() -> dict:
    nodes = {}
    for row in mc.db_query(
            "SELECT id, address, name, status FROM nodes ORDER BY id;"):
        try:
            nodes[int(row[0])] = (row[1], row[2], row[3])
        except (ValueError, IndexError):
            continue

    cache: dict = {}
    results, broken = [], 0
    for node_id, (ip, name, status) in nodes.items():
        if status != "healthy":
            continue  # a node the panel cannot reach has a louder problem
        fronts, tags, failure = node_fronts(ip)
        if failure or not fronts:
            results.append({"node_id": node_id, "address": ip, "name": name,
                            "error": failure or "no reality inbound"})
            continue
        rows, _cc, _as, probe_failure = rfp.probe_node(ip, fronts, cache)
        if probe_failure:
            results.append({"node_id": node_id, "address": ip, "name": name,
                            "error": probe_failure})
            continue
        for r in rows:
            entry = {
                "node_id": node_id, "address": ip, "name": name,
                "front": r["domain"], "usable": r["usable"],
                "tls13": r["tls13"], "x25519": r["x25519"], "h2": r["h2"],
                "cert_covers": r["cert_covers"],
                "inbounds": tags.get(r["domain"], []),
            }
            if not r["usable"]:
                broken += 1
            results.append(entry)
    return {"generated_at": int(time.time()), "broken": broken,
            "fronts": results}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--status", default=STATUS_PATH)
    args = ap.parse_args()

    report = check()

    os.makedirs(os.path.dirname(args.status), exist_ok=True)
    tmp = args.status + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    os.replace(tmp, args.status)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 1 if report["broken"] else 0

    print(f"{'node':<6}{'front':<28}{'TLS1.3':<8}{'X25519':<8}{'h2':<5}"
          f"{'cert':<6}инбаунды")
    for r in report["fronts"]:
        if "error" in r:
            print(f"{r['node_id']:<6}!! {r['error'][:70]}")
            continue
        mark = "" if r["usable"] else "  <-- СЛОМАН"
        print(f"{r['node_id']:<6}{r['front']:<28}"
              f"{'да' if r['tls13'] else 'НЕТ':<8}"
              f"{'да' if r['x25519'] else 'НЕТ':<8}"
              f"{'да' if r['h2'] else 'НЕТ':<5}"
              f"{'да' if r['cert_covers'] else 'НЕТ':<6}"
              f"{len(r['inbounds'])}{mark}")
    print(f"\nсломанных фронтов: {report['broken']}")
    return 1 if report["broken"] else 0


if __name__ == "__main__":
    sys.exit(main())
