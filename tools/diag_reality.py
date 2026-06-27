#!/usr/bin/env python3
# Run ON the panel. Prints reality dest/serverNames/fp per inbound for selected nodes.
import json, subprocess
KEY = "/root/.ssh/vpn_node_default"
NODES = {"U5":"185.219.41.121","U4":"45.150.239.178"}
for name, ip in NODES.items():
    r = subprocess.run(["ssh","-o","ConnectTimeout=8","-o","BatchMode=yes","-i",KEY,
        f"root@{ip}","cat /var/lib/marznode/xray_config.json"],
        capture_output=True, text=True, timeout=20)
    print("="*70); print(name, ip)
    try:
        c = json.loads(r.stdout)
    except Exception as e:
        print("  ERR", e); continue
    for ib in c.get("inbounds", []):
        ss = ib.get("streamSettings", {}) or {}
        rs = ss.get("realitySettings", {}) or ss.get("realityObject", {}) or {}
        dest = rs.get("dest") or rs.get("target")
        sn = rs.get("serverNames")
        net = ss.get("network")
        sec = ss.get("security")
        print(f"  {str(ib.get('port')):<6} {ib.get('tag','')[:26]:<26} net={net} sec={sec} dest={dest} sni={sn}")
