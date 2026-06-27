#!/usr/bin/env python3
"""Run ON panel. Test bridge egress from U4 to GE(working) and both FR nodes,
reusing the proven fr_egress_test.py (all exits share reality params)."""
import subprocess

KEY = "/root/.ssh/vpn_node_default"
BASE = ["-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
U4 = "45.150.239.178"
UUID = "91040b97-0a20-6eac-dfb7-f4b4e56ecf42"
TARGETS = [("GE node27", "93.123.85.191", 50443),
           ("FR node23", "132.243.204.182", 44443),
           ("FR node14", "132.243.204.199", 47443)]

subprocess.run(["scp", *BASE, "/root/fr_egress_test.py", f"root@{U4}:/tmp/fe.py"], timeout=30)
for name, ip, port in TARGETS:
    print("=" * 50, name)
    r = subprocess.run(["ssh", *BASE, f"root@{U4}",
                        f"python3 /tmp/fe.py {ip} {port} {UUID}"],
                       capture_output=True, text=True, timeout=70)
    for l in r.stdout.splitlines():
        if l.startswith("egress:") or l.startswith("xray:"):
            print("  ", l)
    if r.stderr.strip():
        print("   STDERR:", r.stderr.strip()[:150])
