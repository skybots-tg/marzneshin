#!/usr/bin/env python3
"""Run ON panel. Repoint dead FR exit IPs in fr-out / fr-2-out outbounds on every
entry node to the live FR exit nodes (keys/ports/sni already match).
  109.61.110.125 -> 132.243.204.182  (node23 France-1 :44443)
  109.61.110.150 -> 132.243.204.199  (node14 France-2 :47443)
Pulls each live config, rewrites only outbound vnext addresses, writes
/root/uni_configs/<ip>.final.json. Does NOT deploy (deploy_node.sh does that)."""
import json
import os
import subprocess

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
OUT = "/root/uni_configs"
os.makedirs(OUT, exist_ok=True)

REMAP = {"109.61.110.125": "132.243.204.182", "109.61.110.150": "132.243.204.199"}

NODES = ["89.191.225.218", "84.252.101.98", "5.35.125.174", "45.150.239.178",
         "185.219.41.121", "193.233.246.18", "193.233.246.41",
         "158.160.212.139", "84.201.177.241", "51.250.82.209", "51.250.92.21"]


def pull(ip):
    r = subprocess.run(SSH + [f"root@{ip}", "cat /var/lib/marznode/xray_config.json"],
                       capture_output=True, text=True, timeout=25)
    return json.loads(r.stdout)


for ip in NODES:
    cfg = pull(ip)
    n = 0
    for ob in cfg.get("outbounds", []):
        for v in (ob.get("settings", {}) or {}).get("vnext", []) or []:
            old = v.get("address")
            if old in REMAP:
                v["address"] = REMAP[old]
                n += 1
    final = os.path.join(OUT, f"{ip}.final.json")
    with open(final, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"{ip:18} remapped={n} -> {final}")
