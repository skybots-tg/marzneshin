#!/usr/bin/env python3
"""Turn an existing (bare) RU node into a full UNIVERSAL entry node.

Runs ON THE PANEL. It clones a reference universal node's xray config
(all RU Direct + RU->XX Bridge inbounds and every xx-out outbound), gives the
target node a FRESH reality keypair for each inbound, deploys it, then mirrors
everything into the DB (inbounds + service links + user-visible hosts) with the
correct UNIVERSAL <n> branding and weight band.

The outbounds (exit targets + their public keys) are shared across all entry
nodes, so they are copied verbatim from the reference node.

Idempotent: existing inbounds/hosts (matched by tag/remark) are left untouched.

usage:
  setup_universal_node.py --node-id 43 --uni 2 --ip 45.81.33.150 [--ref-ip ...] [--apply]
"""
import argparse
import copy
import sys

import bridge_lib as bl
import marz_common as mc

REF_IP_DEFAULT = "89.191.225.218"   # node 25 = UNIVERSAL 1 (full reference)

# tag -> {"iso", "label", "sub"}, read off the fleet rather than kept by hand.
# The literal maps this replaced had already fallen behind: neither carried
# "RU->RO Bridge", so every node onboarded after Romania was added silently came
# up without it, and the FI-2 exit still claimed Finland after it was found to
# surface in NL.
_CATALOG = {}


def catalog():
    if not _CATALOG:
        _CATALOG.update(bl.exit_catalog("universal"))
        if not _CATALOG:
            sys.exit("cannot derive the exit catalog: no UNIVERSAL entry has "
                     "hosts to learn from")
    return _CATALOG


def branding(tag, uni):
    """(remark, weight) for one inbound on UNIVERSAL <uni>."""
    entry = catalog().get(tag)
    if entry is None:
        return None, None
    weight = 100 + (uni - 1) * 10 + entry["sub"]
    return mc.universal_remark(uni, entry["iso"], entry["label"]), weight


def hosts_only(node_id, uni, ip, apply):
    """Create the user-visible hosts for the UNIVERSAL inbounds already present
    on the node (idempotent, per-inbound)."""
    rows = mc.db_query(
        "SELECT tag, config FROM inbounds WHERE node_id=%d;" % node_id)
    sql, plan = [], []
    import json
    for tag, cfgjson in rows:
        remark, w = branding(tag, uni)
        if remark is None:
            continue
        sql.append(mc.insert_host_sql(node_id, tag, remark, ip, w))
        plan.append(f"  {tag:30s} w={w}  {remark}")
    print(f"== UNIVERSAL {uni} hosts-only on node {node_id} ({ip}) ==")
    print("\n".join(plan))
    if not apply:
        print("\n(dry-run) re-run with --apply")
        return
    r = mc.db("SET NAMES utf8mb4;\n" + "\n".join(sql) + "\n")
    print("DB:", "OK" if r.returncode == 0 else "FAILED")
    if r.returncode != 0:
        print(r.stderr[:800])
        sys.exit(3)
    n = mc.db_query("SELECT COUNT(*) FROM hosts WHERE address='%s' AND "
                    "is_disabled=0;" % ip)
    print(f"enabled hosts now on {ip}: {n[0][0]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node-id", type=int, required=True)
    ap.add_argument("--uni", type=int, required=True, help="UNIVERSAL number")
    ap.add_argument("--ip", required=True, help="target node IP")
    ap.add_argument("--ref-ip", default=REF_IP_DEFAULT)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--hosts-only", action="store_true",
                    help="(re)create user-visible hosts for inbounds already on "
                         "the node; no node deploy")
    args = ap.parse_args()

    node_id, uni, ip = args.node_id, args.uni, args.ip

    if args.hosts_only:
        return hosts_only(node_id, uni, ip, args.apply)
    ref = mc.node_cfg(args.ref_ip)
    cur = mc.node_cfg(ip)
    have_tags = {ib["tag"] for ib in cur.get("inbounds", [])}

    # inbounds to create = reference inbounds not already present on target
    todo = [ib for ib in ref["inbounds"] if ib["tag"] not in have_tags]
    print(f"== UNIVERSAL {uni} on node {node_id} ({ip}) ==")
    print(f"reference {args.ref_ip}: {len(ref['inbounds'])} inbounds, "
          f"target already has {len(have_tags)}; to add: {len(todo)}")
    if not todo:
        print("nothing to add (already configured)")
        return

    pairs = (mc.gen_keys(ip, len(todo)) if args.apply
             else [("__PRIV__", "__PUB__")] * len(todo))

    # Build new node config: start from target, append cloned inbounds with
    # fresh keys, then add any missing outbounds + routing rules from reference.
    new = copy.deepcopy(cur)
    rmap = mc.routing_map(ref)
    have_out = {ob["tag"] for ob in new.get("outbounds", [])}
    new.setdefault("routing", {}).setdefault("rules", [])
    have_rules = {(tuple(r.get("inboundTag", [])), r.get("outboundTag"))
                  for r in new["routing"]["rules"]}

    db_rows = []  # (tag, network, pbk, sid, flow)
    for i, ref_ib in enumerate(todo):
        tag = ref_ib["tag"]
        priv, pub = pairs[i]
        sid = mc.rand_sid()
        ib = copy.deepcopy(ref_ib)
        rs = ib["streamSettings"]["realitySettings"]
        rs["privateKey"] = priv
        rs["shortIds"] = [sid]
        ib["settings"] = {"clients": [], "decryption": "none"}
        new["inbounds"].append(ib)

        net = ib["streamSettings"]["network"]
        ob_tag = rmap.get(tag)
        if ob_tag and ob_tag not in have_out:
            ob = mc.find(ref["outbounds"], ob_tag)
            if ob:
                new["outbounds"].append(copy.deepcopy(ob))
                have_out.add(ob_tag)
        if ob_tag and ((tag,), ob_tag) not in have_rules:
            new["routing"]["rules"].append(
                {"type": "field", "inboundTag": [tag], "outboundTag": ob_tag})
            have_rules.add(((tag,), ob_tag))
        db_rows.append((tag, net, pub, sid))

    # ensure freedom/block exist (RU Direct routes to "direct")
    for base in ("direct", "block"):
        if base not in have_out:
            new["outbounds"].append(mc.find(ref["outbounds"], base)
                                    or {"protocol": "freedom" if base == "direct"
                                        else "blackhole", "tag": base})
            have_out.add(base)

    print(f"plan: +{len(db_rows)} inbounds, "
          f"outbounds now {len(new['outbounds'])}, "
          f"rules now {len(new['routing']['rules'])}")
    for tag, net, pub, sid in db_rows:
        remark, w = branding(tag, uni)
        if remark is None:
            print(f"  {tag:30s} {net:5s} no branding in the catalog — "
                  f"inbound will be created, host will not")
            continue
        print(f"  {tag:30s} {net:5s} w={w}  {remark}")

    if not args.apply:
        print("\n(dry-run) re-run with --apply")
        return

    ok, out = mc.deploy(ip, new)
    print(out)
    if not ok:
        print("DEPLOY FAILED - DB untouched")
        sys.exit(2)

    sql = []
    for tag, net, pub, sid in db_rows:
        sql.append(mc.insert_inbound_sql(
            node_id, tag, mc.db_inbound_config(
                tag, mc.find(new["inbounds"], tag)["port"], net, pub, sid)))
    for tag, *_ in db_rows:
        sql.append(mc.link_service_sql(node_id, tag))
    for tag, net, pub, sid in db_rows:
        remark, w = branding(tag, uni)
        if remark is None:
            continue
        sql.append(mc.insert_host_sql(node_id, tag, remark, ip, w))
    r = mc.db("SET NAMES utf8mb4;\n" + "\n".join(sql) + "\n")
    print("DB:", "OK" if r.returncode == 0 else "FAILED")
    if r.returncode != 0:
        print(r.stderr[:800])
        sys.exit(3)
    print(f"done: UNIVERSAL {uni} node {node_id} configured.")


if __name__ == "__main__":
    main()
