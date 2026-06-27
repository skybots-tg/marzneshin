#!/usr/bin/env python3
import json
import subprocess

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
ip = "45.150.239.178"
cfg = json.loads(subprocess.run(SSH + [f"root@{ip}", "cat /var/lib/marznode/xray_config.json"],
                                capture_output=True, text=True, timeout=25).stdout)
for ob in cfg["outbounds"]:
    if ob.get("tag") in ("fr-out", "fr-2-out"):
        print(json.dumps(ob, ensure_ascii=False))
