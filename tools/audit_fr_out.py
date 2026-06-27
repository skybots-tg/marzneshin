#!/usr/bin/env python3
"""Run ON panel. For every entry node that has an FR bridge, print where its
fr-out / fr2-out (and any FR-routed) outbounds point, plus the reality target."""
import json
import subprocess

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]

# entry nodes that carry FR bridges (from DB inbounds audit)
NODES = {
    "U1 (25)": "89.191.225.218",
    "U2 (15)": "84.252.101.98",
    "U3 (12)": "5.35.125.174",
    "U4 (30)": "45.150.239.178",
    "U5 (31)": "185.219.41.121",
    "U6 (34)": "193.233.246.18",
    "U7 (36)": "193.233.246.41",
    "ELITE1 (32)": "158.160.212.139",
    "ELITE2 (10)": "84.201.177.241",
    "ELITE3 (28)": "51.250.82.209",
    "ELITE4 (19)": "51.250.92.21",
}


def pull(ip):
    r = subprocess.run(SSH + [f"root@{ip}", "cat /var/lib/marznode/xray_config.json"],
                       capture_output=True, text=True, timeout=25)
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def routing_map(cfg):
    m = {}
    for rule in cfg.get("routing", {}).get("rules", []):
        out = rule.get("outboundTag")
        for it in rule.get("inboundTag", []) or []:
            m[it] = out
    return m


for name, ip in NODES.items():
    cfg = pull(ip)
    if not cfg:
        print(f"{name:14} {ip:18} !! UNREACHABLE / bad config")
        continue
    rm = routing_map(cfg)
    out_by_tag = {ob.get("tag"): ob for ob in cfg.get("outbounds", [])}
    fr_inbounds = [ib for ib in cfg.get("inbounds", []) if "FR" in (ib.get("tag") or "")]
    seen = set()
    for ib in fr_inbounds:
        ot = rm.get(ib["tag"])
        ob = out_by_tag.get(ot)
        if ob:
            vnext = (ob.get("settings", {}) or {}).get("vnext", [])
            addr = vnext[0].get("address") if vnext else "?"
            port = vnext[0].get("port") if vnext else "?"
            rs = (ob.get("streamSettings", {}) or {}).get("realitySettings", {}) or {}
            tgt = f"{addr}:{port}"
        else:
            tgt = "NO-OUTBOUND"
        line = f"  {ib['tag']:24} -> out={ot!r:14} target={tgt}"
        if line not in seen:
            seen.add(line)
            if "first" not in dir():
                pass
    print(f"{name:14} {ip}")
    for ib in fr_inbounds:
        ot = rm.get(ib["tag"])
        ob = out_by_tag.get(ot)
        if ob:
            vnext = (ob.get("settings", {}) or {}).get("vnext", [])
            addr = vnext[0].get("address") if vnext else "?"
            port = vnext[0].get("port") if vnext else "?"
            tgt = f"{addr}:{port}"
        else:
            tgt = "NO-OUTBOUND(blackhole)"
        print(f"    in[{ib['tag']}] (:{ib.get('port')}) -> out[{ot}] => {tgt}")
