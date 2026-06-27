#!/usr/bin/env python3
"""Run ON panel. Print full reality privateKey + derived publicKey for FR exit nodes,
and the current fr-out outbound publicKey on U4 for comparison."""
import json
import subprocess

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]

FR = {"node14 132.243.204.199": "132.243.204.199",
      "node23 132.243.204.182": "132.243.204.182"}


def remote(ip, cmd):
    return subprocess.run(SSH + [f"root@{ip}", cmd], capture_output=True, text=True, timeout=25)


def find_xray(ip):
    for cand in ("which xray",
                 "ls /usr/local/bin/xray",
                 "docker exec marznode-marznode-1 which xray 2>/dev/null",
                 "find / -maxdepth 6 -name xray -type f 2>/dev/null | head -1"):
        r = remote(ip, cand)
        out = r.stdout.strip()
        if out and "/" in out:
            return out.splitlines()[0]
    return None


for name, ip in FR.items():
    print("=" * 70)
    print(name)
    r = remote(ip, "cat /var/lib/marznode/xray_config.json")
    try:
        cfg = json.loads(r.stdout)
    except Exception as e:
        print("  cfg err", e, r.stderr[:150]); continue
    xray = find_xray(ip)
    print("  xray:", xray)
    for ib in cfg.get("inbounds", []):
        rs = (ib.get("streamSettings", {}) or {}).get("realitySettings", {}) or {}
        priv = rs.get("privateKey")
        if not priv:
            continue
        print(f"  inbound tag={ib.get('tag')} port={ib.get('port')}")
        print(f"    privateKey={priv}")
        if xray:
            d = remote(ip, f"{xray} x25519 -i {priv}")
            print("    derive:", (d.stdout + d.stderr).strip().replace("\n", " | "))
