#!/usr/bin/env python3
import json
import subprocess

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
NODES = {"U1": "89.191.225.218", "U6": "193.233.246.18", "ELITE4": "51.250.92.21"}
for name, ip in NODES.items():
    r = subprocess.run(SSH + [f"root@{ip}", "cat /var/lib/marznode/xray_config.json"],
                       capture_output=True, text=True, timeout=25)
    cfg = json.loads(r.stdout)
    print("=", name, ip)
    for ob in cfg.get("outbounds", []):
        if ob.get("tag") in ("fr-out", "fr-2-out"):
            rs = (ob.get("streamSettings", {}) or {}).get("realitySettings", {}) or {}
            vnext = (ob.get("settings", {}) or {}).get("vnext", [{}])[0]
            print(f"  {ob['tag']:9} -> {vnext.get('address')}:{vnext.get('port')} "
                  f"pub={rs.get('publicKey')} sid={rs.get('shortId')} sni={rs.get('serverName')} fp={rs.get('fingerprint')}")
