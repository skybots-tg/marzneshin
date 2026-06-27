#!/usr/bin/env python3
"""Run ON the panel server. Diagnoses the FR multihop bridge:
- entry node (U4 = 45.150.239.178): RU->FR Bridge inbound + the outbound it routes to
- FR exit nodes (14 = 132.243.204.199, 23 = 132.243.204.182): their listener inbounds
Verifies that the entry outbound's reality publicKey/dest/port/shortId match an FR
exit inbound's privateKey-derived publicKey and listening params.
"""
import json
import subprocess

KEY = "/root/.ssh/vpn_node_default"

ENTRY = {"U4": "45.150.239.178"}
FR_EXITS = {"FR-1 (node14)": "132.243.204.199", "FR-2 (node23)": "132.243.204.182"}


def pull(ip):
    r = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
         "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
         "-i", KEY,
         f"root@{ip}", "cat /var/lib/marznode/xray_config.json"],
        capture_output=True, text=True, timeout=25)
    try:
        return json.loads(r.stdout)
    except Exception as e:
        print(f"  !! cannot parse config from {ip}: {e}\n  stderr={r.stderr[:200]}")
        return None


def routing_map(cfg):
    m = {}
    for rule in cfg.get("routing", {}).get("rules", []):
        out = rule.get("outboundTag")
        for it in rule.get("inboundTag", []) or []:
            m[it] = out
    return m


def show_inbound(ib, indent="    "):
    ss = ib.get("streamSettings", {}) or {}
    rs = ss.get("realitySettings", {}) or {}
    print(f"{indent}tag={ib.get('tag')!r} port={ib.get('port')} proto={ib.get('protocol')} "
          f"net={ss.get('network')} sec={ss.get('security')}")
    if rs:
        print(f"{indent}  reality: dest={rs.get('dest')} serverNames={rs.get('serverNames')} "
              f"shortIds={rs.get('shortIds')} privKey={rs.get('privateKey','')[:12]}...")


def show_outbound(ob, indent="    "):
    ss = ob.get("streamSettings", {}) or {}
    rs = ss.get("realitySettings", {}) or {}
    vnext = (ob.get("settings", {}) or {}).get("vnext", [])
    addr = vnext[0].get("address") if vnext else None
    port = vnext[0].get("port") if vnext else None
    print(f"{indent}tag={ob.get('tag')!r} proto={ob.get('protocol')} -> {addr}:{port} "
          f"net={ss.get('network')} sec={ss.get('security')}")
    if rs:
        print(f"{indent}  reality: serverName={rs.get('serverName')} publicKey={rs.get('publicKey','')[:20]}... "
              f"shortId={rs.get('shortId')} fp={rs.get('fingerprint')} spx={rs.get('spiderX')}")


print("#" * 80)
print("ENTRY NODES — FR bridge inbounds + the outbounds they route to")
print("#" * 80)
for name, ip in ENTRY.items():
    cfg = pull(ip)
    print(f"\n=== {name} {ip} ===")
    if not cfg:
        continue
    rm = routing_map(cfg)
    out_by_tag = {ob.get("tag"): ob for ob in cfg.get("outbounds", [])}
    for ib in cfg.get("inbounds", []):
        if "FR" in (ib.get("tag") or ""):
            print("  [INBOUND]")
            show_inbound(ib)
            ot = rm.get(ib["tag"])
            print(f"    routes inboundTag {ib['tag']!r} -> outboundTag {ot!r}")
            ob = out_by_tag.get(ot)
            if ob:
                print("  [OUTBOUND]")
                show_outbound(ob)
            else:
                print(f"    !! no outbound with tag {ot!r} (NO ROUTE / blackholed)")

print("\n" + "#" * 80)
print("FR EXIT NODES — listener inbounds")
print("#" * 80)
for name, ip in FR_EXITS.items():
    cfg = pull(ip)
    print(f"\n=== {name} {ip} ===")
    if not cfg:
        continue
    for ib in cfg.get("inbounds", []):
        show_inbound(ib, indent="  ")
