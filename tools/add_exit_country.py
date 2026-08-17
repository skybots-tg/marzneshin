#!/usr/bin/env python3
"""Add a NEW exit country across the whole fleet, semi-automatically.

Runs ON THE PANEL. For a country (e.g. RO) it does, end to end:

  1. EXIT node: give the country's server one reality listener inbound
     (serves both FAST users directly and the multihop bridges), mirror it into
     the DB and create the FAST host.
  2. ENTRY nodes: for every UNIVERSAL + ELITE entry node, add a
     "RU->XX Bridge" reality inbound (fresh per-node key) routed to a shared
     "xx-out" outbound that targets the exit listener, mirror into the DB
     (inbound + service link) and create the user-visible host with the right
     UNIVERSAL <n> / ELITE <n> branding + weight.

Everything is idempotent (matched by inbound tag / host remark), validated with
`xray -test` before swap, and the DB is only touched after a node deploy
succeeds. Dry-run by default; pass --apply to make changes.

usage:
  add_exit_country.py RO [--only-exit] [--only-entries] [--apply]
"""
import argparse
import copy
import sys

import bridge_lib as bl
import marz_common as mc

def entry_fleet():
    """(node_id, ip, KIND, number) for every entry that should get the country.

    Derived from the database, not from a list kept by hand. The list this
    replaced had drifted: node 40 was down as UNIVERSAL 6 while its hosts said
    UNIVERSAL 3, and node 12 had been gone for a while. Adding a country from
    it would have stamped one entry's branding onto another's hosts, and the
    real UNIVERSAL 6 would have been skipped.

    Unhealthy nodes are left out — deploying to a node the panel cannot reach
    fails anyway — but they are named, so a skip is never silent.
    """
    fleet, skipped = [], []
    for e in bl.entry_nodes():
        if e.node_status != "healthy":
            skipped.append("%s %d (node %d, %s)" % (e.kind, e.index, e.node_id,
                                                    e.node_status))
            continue
        fleet.append((e.node_id, e.address, e.kind, e.index))
    if skipped:
        print("skipping unhealthy entry node(s): " + ", ".join(skipped))
    return fleet

# country registry
COUNTRIES = {
    "RO": {
        "flag": "RO", "label": "RO",
        "bridge_tag": "RU->RO Bridge", "out_tag": "ro-out",
        "bridge_port": 20443,
        "exit_node_id": 44, "exit_ip": "85.204.107.56",
        "exit_tag": "Romania-1", "exit_port": 44443,
        "fast_n": 1, "fast_weight": 206,
    },
}

BRIDGE_TEMPLATE_PREF = ["RU->FR Bridge", "RU->EE Bridge", "RU->TR-1 Bridge"]


def pick_template_inbound(cfg):
    for t in BRIDGE_TEMPLATE_PREF:
        ib = mc.find(cfg["inbounds"], t)
        if ib and ib["streamSettings"]["network"] == "tcp":
            return ib
    return None


def free_port(cfg, preferred):
    used = {ib.get("port") for ib in cfg["inbounds"]}
    if preferred not in used:
        return preferred
    for p in range(preferred, preferred + 600):
        if p not in used:
            return p
    raise RuntimeError("no free port")


def get_host_weight(node_ip, like):
    rows = mc.db_query(
        "SELECT weight FROM hosts WHERE address='%s' AND remark LIKE '%s' "
        "ORDER BY weight LIMIT 1;" % (node_ip, like))
    return int(rows[0][0]) if rows else None


def setup_exit(C, apply):
    """Ensure the exit listener exists on the country node + DB inbound + FAST
    host. Returns (exit_pub, exit_sid)."""
    ip = C["exit_ip"]
    cfg = mc.node_cfg(ip)
    existing = mc.find(cfg["inbounds"], C["exit_tag"])
    if existing:
        sid = existing["streamSettings"]["realitySettings"]["shortIds"][0]
        rows = mc.db_query(
            "SELECT config FROM inbounds WHERE node_id=%d AND tag='%s';"
            % (C["exit_node_id"], C["exit_tag"]))
        pub = None
        if rows:
            import json
            pub = json.loads(rows[0][0]).get("pbk")
        print(f"[exit] {C['exit_tag']} already present on {ip} "
              f"(sid={sid}, pbk={pub})")
        if not pub:
            print("[exit] WARN: DB inbound missing pbk; cannot build outbounds")
        return pub, sid

    print(f"[exit] creating listener {C['exit_tag']} :{C['exit_port']} on {ip}")
    if not apply:
        return "__EXIT_PUB__", "__EXIT_SID__"

    (priv, pub), = mc.gen_keys(ip, 1)
    sid = mc.rand_sid()
    new = copy.deepcopy(cfg)
    new["inbounds"].append(
        mc.exit_listener_inbound(C["exit_tag"], C["exit_port"], priv, sid))
    out_tags = {o["tag"] for o in new.get("outbounds", [])}
    if "direct" not in out_tags:
        new.setdefault("outbounds", []).append(
            {"protocol": "freedom", "tag": "direct"})
    if "block" not in out_tags:
        new["outbounds"].append({"protocol": "blackhole", "tag": "block"})
    new.setdefault("routing", {}).setdefault("rules", [])
    new["routing"]["rules"].append(
        {"type": "field", "inboundTag": [C["exit_tag"]], "outboundTag": "direct"})

    ok, out = mc.deploy(ip, new)
    print(out)
    if not ok:
        print("[exit] DEPLOY FAILED"); sys.exit(2)

    cfgj = mc.db_inbound_config(C["exit_tag"], C["exit_port"], "tcp", pub, sid,
                                sni=mc.EXIT_SERVERNAMES)
    sql = [mc.insert_inbound_sql(C["exit_node_id"], C["exit_tag"], cfgj),
           mc.link_service_sql(C["exit_node_id"], C["exit_tag"])]
    remark = mc.fast_remark(C["fast_n"], C["flag"], C["label"])
    sql.append(mc.insert_host_sql(
        C["exit_node_id"], C["exit_tag"], remark, ip, C["fast_weight"],
        sni=mc.FAST_SNI, fingerprint="none"))
    r = mc.db("SET NAMES utf8mb4;\n" + "\n".join(sql) + "\n")
    print("[exit] DB:", "OK" if r.returncode == 0 else "FAILED")
    if r.returncode != 0:
        print(r.stderr[:800]); sys.exit(3)
    print(f"[exit] FAST host: {remark}")
    return pub, sid


def setup_entry(node_id, ip, kind, num, C, exit_pub, exit_sid, apply):
    tag, out_tag = C["bridge_tag"], C["out_tag"]
    cfg = mc.node_cfg(ip)
    if mc.find(cfg["inbounds"], tag):
        print(f"[{kind} {num}] {tag} already present on {ip} - skip")
        return
    tmpl = pick_template_inbound(cfg)
    if not tmpl:
        print(f"[{kind} {num}] no bridge template on {ip} - SKIP")
        return
    port = free_port(cfg, C["bridge_port"])

    if not apply:
        print(f"[{kind} {num}] would add {tag} :{port} -> {out_tag} on {ip}")
        return

    (priv, pub), = mc.gen_keys(ip, 1)
    sid = mc.rand_sid()
    ib = copy.deepcopy(tmpl)
    ib["tag"] = tag
    ib["port"] = port
    rs = ib["streamSettings"]["realitySettings"]
    rs["privateKey"] = priv
    rs["shortIds"] = [sid]
    ib["settings"] = {"clients": [], "decryption": "none"}

    new = copy.deepcopy(cfg)
    new["inbounds"].append(ib)
    if out_tag not in {o["tag"] for o in new["outbounds"]}:
        new["outbounds"].append(mc.bridge_outbound(
            out_tag, C["exit_ip"], C["exit_port"], exit_pub, exit_sid))
    new.setdefault("routing", {}).setdefault("rules", []).append(
        {"type": "field", "inboundTag": [tag], "outboundTag": out_tag})

    ok, out = mc.deploy(ip, new)
    print(f"[{kind} {num}] deploy {ip}: {'OK' if ok else 'FAILED'}")
    if not ok:
        print(out); print(f"[{kind} {num}] DB untouched"); return

    if kind == "UNIVERSAL":
        remark = mc.universal_remark(num, C["flag"], C["label"])
        weight = 100 + (num - 1) * 10 + 6
    else:
        remark = mc.elite_remark(num, C["flag"], C["label"])
        weight = get_host_weight(ip, "%ELITE%- FR [ 4G ]%") or (num * 10 + 5)

    cfgj = mc.db_inbound_config(tag, port, "tcp", pub, sid)
    sql = [mc.insert_inbound_sql(node_id, tag, cfgj),
           mc.link_service_sql(node_id, tag),
           mc.insert_host_sql(node_id, tag, remark, ip, weight)]
    r = mc.db("SET NAMES utf8mb4;\n" + "\n".join(sql) + "\n")
    print(f"[{kind} {num}] DB: {'OK' if r.returncode == 0 else 'FAILED'}  "
          f"{remark} (w={weight})")
    if r.returncode != 0:
        print(r.stderr[:800])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("country", choices=sorted(COUNTRIES))
    ap.add_argument("--only-exit", action="store_true")
    ap.add_argument("--only-entries", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    C = COUNTRIES[args.country]
    print(f"=== add exit country {args.country} "
          f"({'APPLY' if args.apply else 'dry-run'}) ===")

    exit_pub, exit_sid = None, None
    if not args.only_entries:
        exit_pub, exit_sid = setup_exit(C, args.apply)
    if args.only_exit:
        return
    if exit_pub is None:
        # entries-only run: fetch exit pub/sid from DB
        import json
        rows = mc.db_query(
            "SELECT config FROM inbounds WHERE node_id=%d AND tag='%s';"
            % (C["exit_node_id"], C["exit_tag"]))
        if not rows:
            print("exit listener not set up yet; run without --only-entries first")
            sys.exit(1)
        c = json.loads(rows[0][0])
        exit_pub, exit_sid = c["pbk"], c["sid"]

    for node_id, ip, kind, num in entry_fleet():
        try:
            setup_entry(node_id, ip, kind, num, C, exit_pub, exit_sid, args.apply)
        except Exception as e:
            print(f"[{kind} {num}] ERROR on {ip}: {e}")


if __name__ == "__main__":
    main()
