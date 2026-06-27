#!/usr/bin/env python3
import json
import subprocess

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
ip = "45.150.239.178"


def remote(cmd):
    return subprocess.run(SSH + [f"root@{ip}", cmd], capture_output=True, text=True, timeout=25)


cfg = json.loads(remote("cat /var/lib/marznode/xray_config.json").stdout)
for ob in cfg.get("outbounds", []):
    if ob.get("tag") in ("fr-out", "fr-2-out"):
        v = (ob.get("settings", {}) or {}).get("vnext", [{}])[0]
        print(f"  {ob['tag']:9} -> {v.get('address')}:{v.get('port')}")
print("--- backups ---")
print(remote("ls -t /var/lib/marznode/xray_config.json.bak-* 2>/dev/null | head -3").stdout.strip() or "(none)")
print("--- marznode container ---")
print(remote('docker ps --format "{{.Names}} {{.Status}}" | grep -i marz').stdout.strip())
