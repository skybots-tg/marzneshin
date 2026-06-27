#!/usr/bin/env python3
"""Run ON panel. Compare bridge-user ids across all *-out outbounds on U4, and
check whether a WORKING exit node (GE node27) carries that user as a STATIC client
in its listener inbound. Reveals the canonical multihop auth pattern."""
import json
import subprocess

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]


def pull(ip):
    return json.loads(subprocess.run(SSH + [f"root@{ip}", "cat /var/lib/marznode/xray_config.json"],
                                     capture_output=True, text=True, timeout=25).stdout)


print("=== U4 (45.150.239.178) outbound bridge users ===")
u4 = pull("45.150.239.178")
for ob in u4["outbounds"]:
    vnext = (ob.get("settings", {}) or {}).get("vnext", [])
    if vnext:
        users = vnext[0].get("users", [])
        ids = [u.get("id") for u in users]
        print(f"  out[{ob.get('tag')}] -> {vnext[0].get('address')}:{vnext[0].get('port')} users={ids}")

print("\n=== GE exit node27 (93.123.85.191) listener inbounds + STATIC clients ===")
ge = pull("93.123.85.191")
for ib in ge["inbounds"]:
    clients = (ib.get("settings", {}) or {}).get("clients", [])
    ids = [c.get("id") for c in clients]
    print(f"  in[{ib.get('tag')}] :{ib.get('port')} static_clients={ids}")

print("\n=== FR exit node23 (132.243.204.182) listener inbounds + STATIC clients ===")
fr = pull("132.243.204.182")
for ib in fr["inbounds"]:
    clients = (ib.get("settings", {}) or {}).get("clients", [])
    ids = [c.get("id") for c in clients]
    print(f"  in[{ib.get('tag')}] :{ib.get('port')} static_clients={ids}")
