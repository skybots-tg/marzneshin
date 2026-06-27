#!/usr/bin/env python3
# Run ON the panel. Fetches xray_config.json from each entry node via the node key,
# then prints a COMPACT structural comparison so we can see why U4 delivers and others don't.
import json, subprocess, sys

KEY = "/root/.ssh/vpn_node_default"
NODES = {
    "U1": "89.191.225.218",
    "U2": "84.252.101.98",
    "U3": "5.35.125.174",
    "U4": "45.150.239.178",   # WORKING
    "U5": "185.219.41.121",
    "U6": "193.233.246.18",
    "U7": "193.233.246.41",
}

def fetch(ip):
    r = subprocess.run(
        ["ssh","-o","ConnectTimeout=8","-o","BatchMode=yes","-i",KEY,
         f"root@{ip}","cat /var/lib/marznode/xray_config.json"],
        capture_output=True, text=True, timeout=20)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except Exception as e:
        return {"_parse_error": str(e), "_raw_len": len(r.stdout)}

for name, ip in NODES.items():
    c = fetch(ip)
    print("="*70)
    print(f"{name}  {ip}")
    if c is None:
        print("  FETCH FAILED / EMPTY")
        continue
    if "_parse_error" in c:
        print("  PARSE ERROR:", c)
        continue
    inb = c.get("inbounds", [])
    outb = c.get("outbounds", [])
    routing = c.get("routing", {})
    rules = routing.get("rules", [])
    dns = c.get("dns", {})
    print(f"  inbounds={len(inb)} outbounds={len(outb)} routing_rules={len(rules)} dns_servers={len(dns.get('servers',[])) if dns else 0}")
    # outbound tags
    print("  outbound tags:", ",".join(o.get("tag","?") for o in outb))
    # routing: map inboundTag/port -> outboundTag
    print("  routing rules (inbound->outbound):")
    for r in rules:
        itag = r.get("inboundTag")
        port = r.get("port")
        otag = r.get("outboundTag")
        dom = r.get("domain")
        ip_r = r.get("ip")
        key = itag if itag else (f"port:{port}" if port else (f"domain:{dom}" if dom else (f"ip:{ip_r}" if ip_r else "*")))
        print(f"    {str(key)[:40]:<40} -> {otag}")
