#!/usr/bin/env python3
"""Run ON panel. Look inside the GE node27 marznode container for the RUNNING xray
config (with injected users) to see how bridge user 91040b97 is provisioned there.
Then compare against FR node23."""
import subprocess

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
BRIDGE = "91040b97"

for name, ip in [("GE node27", "93.123.85.191"), ("FR node23", "132.243.204.182")]:
    print("=" * 60, name, ip)
    cmd = (
        "c=$(docker ps --format '{{.Names}}' | grep -i marz | head -1); echo container=$c; "
        "echo '-- marznode env / data dir --'; "
        "docker exec $c sh -c 'ls -la /var/lib/marznode 2>/dev/null; ls -la /usr/local/share/xray 2>/dev/null' 2>/dev/null | head; "
        "echo '-- search running config files for bridge uuid --'; "
        "docker exec $c sh -c 'grep -rl 91040b97 / 2>/dev/null | grep -v proc | head' 2>/dev/null; "
        "echo '-- count 91040b97 occurrences in any json under container --'; "
        "docker exec $c sh -c 'grep -rc 91040b97 /var/lib 2>/dev/null | grep -v :0' 2>/dev/null | head; "
        "echo '-- marznode logs tail (sync) --'; "
        "docker logs --tail 8 $c 2>&1 | sed 's/^/   /'"
    )
    r = subprocess.run(SSH + [f"root@{ip}", cmd], capture_output=True, text=True, timeout=40)
    print(r.stdout)
    if r.stderr.strip():
        print("STDERR:", r.stderr.strip()[:200])
