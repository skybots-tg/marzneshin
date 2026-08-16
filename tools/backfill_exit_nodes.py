#!/usr/bin/env python3
"""Teach the database where each bridge inbound actually comes out.

Run ON THE PANEL, from this directory.

    python3 backfill_exit_nodes.py            # report what it would write
    python3 backfill_exit_nodes.py --apply    # write it
    python3 backfill_exit_nodes.py --nodes 25,31

``inbounds.exit_node_id`` has existed since the 20260503 migration and has
never been filled in, so every reader that needs to know which two servers a
bridge spans has been parsing the inbound tag (``RU->FR Bridge``) or the host
remark instead. Those strings are a naming convention, not a fact: rename a
host and the topology silently changes shape.

The fact is on the node. Its xray config says which outbound a bridge inbound
routes to, and that outbound dials a specific address -- which is a node's
address, or is not, in which case the exit is a server the panel does not
manage and the column stays NULL.

    inbound.tag -> routing.rules[].inboundTag -> outboundTag
                -> outbounds[].settings.vnext[0].address -> nodes.address

Nothing else changes as a result of running this. The one behaviour keyed off
``exit_node_id`` -- the adblock suffix on host remarks -- is gated behind
``host_remark_adblock_suffix_follows_exit``, off by default, precisely so that
filling this column cannot quietly rename entries in live subscriptions.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

import marz_common as mc


def node_rows(node_ids=None):
    rows = mc.db_query(
        "SELECT id, name, address, status FROM nodes ORDER BY id;")
    out = []
    for row in rows:
        if len(row) < 4:
            continue
        node_id = int(row[0])
        if node_ids and node_id not in node_ids:
            continue
        out.append({"id": node_id, "name": row[1], "address": row[2],
                    "status": row[3]})
    return out


def inbound_rows(node_ids=None):
    rows = mc.db_query(
        "SELECT id, node_id, tag, exit_node_id FROM inbounds ORDER BY id;")
    out = []
    for row in rows:
        if len(row) < 4:
            continue
        node_id = int(row[1])
        if node_ids and node_id not in node_ids:
            continue
        current = row[3]
        out.append({
            "id": int(row[0]), "node_id": node_id, "tag": row[2],
            "exit_node_id": None if current in ("NULL", "", None)
            else int(current),
        })
    return out


def outbound_targets(cfg) -> dict[str, str]:
    """outbound tag -> the address it dials, for the outbounds that dial one."""
    targets = {}
    for out in cfg.get("outbounds") or []:
        settings = out.get("settings") or {}
        vnext = settings.get("vnext") or []
        servers = settings.get("servers") or []
        peer = (vnext or servers or [{}])[0]
        address = peer.get("address")
        if address:
            targets[out.get("tag")] = address
    return targets


def exits_for_node(address: str) -> dict[str, str]:
    """inbound tag -> exit address, as the node itself is configured."""
    cfg = mc.node_cfg(address)
    routing = mc.routing_map(cfg)
    targets = outbound_targets(cfg)
    return {tag: targets[out_tag]
            for tag, out_tag in routing.items()
            if out_tag in targets}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", default="", help="comma-separated node ids")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    node_ids = ({int(x) for x in args.nodes.split(",") if x.strip()}
                if args.nodes else None)
    nodes = node_rows(node_ids)
    by_address = {n["address"]: n for n in nodes if n["address"]}
    inbounds = inbound_rows(node_ids)

    print(f"reading xray config from {len(nodes)} node(s)")
    configs: dict[int, object] = {}

    def read(node):
        try:
            configs[node["id"]] = exits_for_node(node["address"])
        except Exception as exc:
            configs[node["id"]] = exc

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(read, nodes))

    unreadable = {nid: exc for nid, exc in configs.items()
                  if isinstance(exc, Exception)}
    for node in nodes:
        if node["id"] in unreadable:
            print(f"  SKIP node {node['id']:<4} {node['name'][:30]:<32} "
                  f"{str(unreadable[node['id']])[:70]}")

    updates: list[tuple[int, int]] = []
    unmanaged: dict[str, list[str]] = {}
    unchanged = 0
    for inbound in inbounds:
        exits = configs.get(inbound["node_id"])
        if not isinstance(exits, dict):
            continue
        address = exits.get(inbound["tag"])
        if not address:
            continue  # direct inbound: no exit leg to record
        exit_node = by_address.get(address)
        if exit_node is None:
            unmanaged.setdefault(address, []).append(inbound["tag"])
            continue
        if inbound["exit_node_id"] == exit_node["id"]:
            unchanged += 1
            continue
        updates.append((inbound["id"], exit_node["id"]))

    print(f"\n{len(updates)} inbound(s) to write, {unchanged} already correct")
    if updates:
        detail = {i["id"]: i for i in inbounds}
        for inbound_id, exit_id in updates[:200]:
            i = detail[inbound_id]
            was = i["exit_node_id"]
            print(f"  inbound {inbound_id:<5} node {i['node_id']:<4} "
                  f"{i['tag'][:28]:<30} exit_node_id "
                  f"{'NULL' if was is None else was} -> {exit_id}")

    if unmanaged:
        print(f"\n{len(unmanaged)} exit(s) are not registered as nodes; the "
              f"inbounds pointing at them keep exit_node_id = NULL:")
        for address, tags in sorted(unmanaged.items()):
            print(f"  {address:<20} {len(tags)} inbound(s), e.g. {tags[0]}")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply to write these.")
        return 0
    if not updates:
        print("\nnothing to write")
        return 0

    # One statement per exit node keeps the SQL short without CASE gymnastics.
    by_exit: dict[int, list[int]] = {}
    for inbound_id, exit_id in updates:
        by_exit.setdefault(exit_id, []).append(inbound_id)
    sql = "\n".join(
        f"UPDATE inbounds SET exit_node_id={exit_id} WHERE id IN "
        f"({','.join(str(i) for i in ids)});"
        for exit_id, ids in sorted(by_exit.items())
    )
    result = mc.db(sql + "\n")
    if result.returncode != 0:
        print("DB UPDATE FAILED:", result.stderr[:400])
        return 1
    print(f"\nAPPLIED: {len(updates)} inbound(s) now know their exit node.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
