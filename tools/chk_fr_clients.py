#!/usr/bin/env python3
import json
import subprocess

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
BRIDGE_UUID = "91040b97-0a20-6eac-dfb7-f4b4e56ecf42"
NODES = {"node23 France-1": "132.243.204.182", "node14 France-2": "132.243.204.199"}

for name, ip in NODES.items():
    cfg = json.loads(subprocess.run(SSH + [f"root@{ip}", "cat /var/lib/marznode/xray_config.json"],
                                    capture_output=True, text=True, timeout=25).stdout)
    print("=" * 60, name, ip)
    for ib in cfg["inbounds"]:
        clients = (ib.get("settings", {}) or {}).get("clients", [])
        ids = [c.get("id") or c.get("password") for c in clients]
        has = BRIDGE_UUID in ids
        print(f"  tag={ib.get('tag')} port={ib.get('port')} clients={len(clients)} "
              f"bridge_user_present={has}")
        if clients[:3]:
            print("    sample ids:", [str(i)[:12] for i in ids[:3]])
