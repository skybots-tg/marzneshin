#!/usr/bin/env python3
"""Find drift between what a node really listens on and what the DB advertises.

A bridge can be perfectly configured on both ends and still be dead for users:
if the reality keypair, shortId or port stored in the DB no longer matches the
node's live xray config, every subscription link built from that row points at
a listener that will reject the handshake. That failure looks exactly like a
network outage from a probe, so it is worth checking before touching anything.

    python3 bridge_drift.py                 # report drift on every entry node
    python3 bridge_drift.py --nodes 25,31   # only these
    python3 bridge_drift.py --apply         # rewrite the DB rows from the node
"""
from __future__ import annotations

import argparse
import json
import sys

import marz_common as mc

FIELDS = ("port", "pbk", "sid", "sni", "network", "flow", "path")


def node_view(cfg: dict) -> dict[str, dict]:
    """tag -> the client-facing parameters the node actually enforces."""
    out = {}
    for ib in cfg.get("inbounds", []):
        tag = ib.get("tag")
        if not tag:
            continue
        ss = ib.get("streamSettings") or {}
        rs = ss.get("realitySettings") or {}
        net = ss.get("network") or "tcp"
        clients = (ib.get("settings") or {}).get("clients") or []
        path = None
        if net in ("splithttp", "xhttp"):
            path = (ss.get("splithttpSettings") or ss.get("xhttpSettings")
                    or {}).get("path")
        out[tag] = {
            "port": ib.get("port"),
            "pbk": None,  # filled by the caller: derived from the private key
            "priv": rs.get("privateKey"),
            "sid": (rs.get("shortIds") or [None])[0],
            "sni": (rs.get("serverNames") or [None])[0],
            "network": "splithttp" if net == "xhttp" else net,
            "flow": (clients[0].get("flow") if clients else None) or None,
            "path": path,
        }
    return out


def db_view(node_id: int) -> dict[str, dict]:
    rows = mc.db_query(
        "SELECT tag, config FROM inbounds WHERE node_id=%d" % node_id)
    out = {}
    for tag, cfg_json in rows:
        try:
            cfg = json.loads(cfg_json)
        except (TypeError, ValueError):
            cfg = {}
        sni = cfg.get("sni")
        out[tag] = {
            "port": cfg.get("port"),
            "pbk": cfg.get("pbk"),
            "sid": cfg.get("sid"),
            "sni": sni[0] if isinstance(sni, list) and sni else sni,
            "network": cfg.get("network"),
            "flow": cfg.get("flow") or None,
            "path": cfg.get("path") or None,
            "_raw": cfg,
        }
    return out


def compare(node_id: int, address: str) -> list[dict]:
    cfg = mc.node_cfg(address)
    live, stored = node_view(cfg), db_view(node_id)
    privs = [v["priv"] for v in live.values() if v["priv"]]
    pubs = mc.pubkeys(address, privs) if privs else {}
    for v in live.values():
        v["pbk"] = pubs.get(v["priv"])

    drift = []
    for tag, want in sorted(live.items()):
        have = stored.get(tag)
        if have is None:
            drift.append({"tag": tag, "kind": "db_missing", "diff": {}})
            continue
        bad = {f: (have[f], want[f]) for f in FIELDS
               if want[f] is not None and have[f] != want[f]}
        # a node may legitimately not expose a path for tcp inbounds
        bad.pop("path", None) if want["path"] is None else None
        if bad:
            drift.append({"tag": tag, "kind": "mismatch", "diff": bad,
                          "want": want, "raw": have["_raw"]})
    for tag in sorted(set(stored) - set(live)):
        drift.append({"tag": tag, "kind": "node_missing", "diff": {}})
    return drift


def repair_sql(node_id: int, entry: dict) -> str:
    cfg = dict(entry["raw"])
    want = entry["want"]
    cfg.update({"port": want["port"], "pbk": want["pbk"], "sid": want["sid"],
                "network": want["network"]})
    if want["sni"]:
        cfg["sni"] = [want["sni"]]
    if want["path"] is not None:
        cfg["path"] = want["path"]
    return (f"UPDATE inbounds SET config={mc.sqlstr(json.dumps(cfg))} "
            f"WHERE node_id={node_id} AND tag={mc.sqlstr(entry['tag'])};")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nodes", default="", help="comma-separated node ids")
    p.add_argument("--apply", action="store_true",
                   help="rewrite drifted DB rows from the node config")
    args = p.parse_args()

    wanted = {int(x) for x in args.nodes.split(",")} if args.nodes else None
    nodes = [r for r in mc.db_query(
        "SELECT id, name, address, status FROM nodes ORDER BY id")
        if wanted is None or int(r[0]) in wanted]

    sql, total = [], 0
    for nid, name, address, status in nodes:
        nid = int(nid)
        try:
            drift = compare(nid, address)
        except Exception as exc:  # unreachable node, bad json, ...
            print(f"node {nid:<4} {name}: SKIP ({type(exc).__name__}: {exc})")
            continue
        if not drift:
            print(f"node {nid:<4} {name}: in sync")
            continue
        print(f"node {nid:<4} {name} ({address}, {status}): "
              f"{len(drift)} drifted")
        for d in drift:
            if d["kind"] != "mismatch":
                print(f"    {d['tag']:<34} {d['kind']}")
                continue
            fields = ", ".join(
                f"{f}: db={old!r} node={new!r}" for f, (old, new) in
                d["diff"].items())
            print(f"    {d['tag']:<34} {fields}")
            sql.append(repair_sql(nid, d))
            total += 1

    if not sql:
        print("\nnothing to repair")
        return 0
    if not args.apply:
        print(f"\nDRY RUN: {total} DB row(s) would be rewritten from the node "
              f"config. Re-run with --apply.")
        return 0
    r = mc.db("\n".join(sql) + "\n")
    if r.returncode != 0:
        print("DB UPDATE FAILED:", r.stderr[:400])
        return 4
    print(f"\nrewrote {total} inbound row(s) from the live node config")
    return 0


if __name__ == "__main__":
    sys.exit(main())
