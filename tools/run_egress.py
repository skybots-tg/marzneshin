#!/usr/bin/env python3
"""Run ON panel. Push fr_egress_test.py to U4 node and test the U4->FR hop."""
import subprocess

KEY = "/root/.ssh/vpn_node_default"
BASE = ["-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
NODE = "45.150.239.178"
UUID = "91040b97-0a20-6eac-dfb7-f4b4e56ecf42"

subprocess.run(["scp", *BASE, "/root/fr_egress_test.py", f"root@{NODE}:/tmp/fr_egress_test.py"],
               timeout=30)
r = subprocess.run(["ssh", *BASE, f"root@{NODE}",
                    f"python3 /tmp/fr_egress_test.py 132.243.204.182 44443 {UUID}; rm -f /tmp/fr_egress_test.py"],
                   capture_output=True, text=True, timeout=90)
print(r.stdout)
if r.stderr.strip():
    print("STDERR:", r.stderr.strip())
