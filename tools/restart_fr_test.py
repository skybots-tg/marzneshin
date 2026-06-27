#!/usr/bin/env python3
"""Run ON panel. Restart marznode on FR node23, wait for resync, then test direct
egress to France-1 with a REAL service-1 user and the BRIDGE user."""
import subprocess
import time

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
U4 = "45.150.239.178"
REAL_SVC1 = "68f85dea-ceeb-b5d3-d090-629fd5d52d65"   # user26 test_ru_direct
BRIDGE = "91040b97-0a20-6eac-dfb7-f4b4e56ecf42"       # user31
FR_NODES = [("node14 France-2", "132.243.204.199", 47443),
            ("node23 France-1", "132.243.204.182", 44443)]

for name, ip, port in FR_NODES:
    print(f"-- restart marznode @ {name} ({ip}) --")
    print(subprocess.run(SSH + [f"root@{ip}",
          'c=$(docker ps --format "{{.Names}}"|grep -i marz|head -1); docker restart "$c" && echo restarted $c'],
          capture_output=True, text=True, timeout=40).stdout)
print("waiting 20s for user resync...")
time.sleep(20)

subprocess.run(["scp", *SSH[1:], "/root/fr_egress_test.py", f"root@{U4}:/tmp/fe.py"], timeout=30)
for name, ip, port in FR_NODES:
    print(f"=== {name} via bridge from U4 ===")
    for label, uuid in [("REAL svc1 user26", REAL_SVC1), ("BRIDGE user31", BRIDGE)]:
        r = subprocess.run(SSH + [f"root@{U4}", f"python3 /tmp/fe.py {ip} {port} {uuid}"],
                           capture_output=True, text=True, timeout=70)
        eg = next((l for l in r.stdout.splitlines() if l.startswith("egress:")), "(no output)")
        print(f"  {label:18} -> {eg}")
