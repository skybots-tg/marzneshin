#!/usr/bin/env python3
"""Explain why one host fails, with the client log the audit throws away.

The audit only records a 300-char tail per probe, which is enough to spot a
pattern across 115 hosts but never enough to fix one. This runs a single probe
from a chosen RU vantage at debug loglevel and prints everything: the client
log, the entry TCP check, and the entry->exit TCP check, so the failure can be
placed on one of the three legs.

    python3 bridge_debug.py 363              # probe host 363 from a RU node
    python3 bridge_debug.py 363 --from 30    # ... from a specific vantage
"""
from __future__ import annotations

import argparse
import json
import random
import sys

import bridge_lib as bl
import bridge_probe as bp
import marz_common as mc

REMOTE = "/tmp/bridge_debug_client.json"

SCRIPT = r'''
set -u
c=$(docker ps --format '{{.Names}}' | grep -i marz | grep -vi db | head -1)
X=/tmp/xray_bridge_probe
[ -x "$X" ] || docker cp "$c":/usr/local/bin/xray "$X" >/dev/null 2>&1
chmod +x "$X" 2>/dev/null
echo "--- entry reachability ---"
timeout 6 bash -c "</dev/tcp/%(entry_ip)s/%(entry_port)s" 2>/dev/null \
  && echo "tcp %(entry_ip)s:%(entry_port)s OPEN" \
  || echo "tcp %(entry_ip)s:%(entry_port)s SHUT"
echo "--- client run ---"
"$X" run -c %(cfg)s > /tmp/bridge_debug.log 2>&1 &
XP=$!
sleep 2
curl -s -o /tmp/bridge_debug.out -w "curl_exit=%%{http_code} time=%%{time_total}\n" \
  --socks5-hostname 127.0.0.1:%(socks)s --max-time 20 https://ipinfo.io/json
echo "response: $(head -c 300 /tmp/bridge_debug.out)"
kill $XP 2>/dev/null; sleep 1
echo "--- xray client log ---"
cat /tmp/bridge_debug.log
'''


def test_outbound(entry_ip: str, outbound: dict, socks: int = 0) -> str:
    """Run the entry node's own bridge outbound and see if the exit answers.

    This isolates the second leg. If the client reaches the entry fine but this
    comes back empty, the exit node stopped honouring the outbound (rekeyed,
    firewalled the entry's IP, or died) and no amount of entry-side fixing
    helps.
    """
    socks = socks or random.randint(12800, 13600)
    cfg = {
        "log": {"loglevel": "warning"},
        "inbounds": [{"tag": "s", "listen": "127.0.0.1", "port": socks,
                      "protocol": "socks", "settings": {"udp": False}}],
        "outbounds": [dict(outbound, tag="p")],
    }
    # One geo service is not enough: they rate-limit, and a throttled lookup
    # reads exactly like a dead tunnel. Ask three before believing the silence.
    lookups = " ".join(
        f'r=$(curl -s --socks5-hostname 127.0.0.1:{socks} --max-time 12 {u}); '
        f'case "$r" in *country*|*"ip"*) echo "$r"; ok=1;; esac; '
        f'[ -z "${{ok:-}}" ] && sleep 2;'
        for u in ("https://ipinfo.io/json", "https://api.country.is/",
                  "http://ip-api.com/json/?fields=status,countryCode,query"))
    script = (
        'c=$(docker ps --format "{{.Names}}" | grep -i marz | grep -vi db '
        f'| head -1); X=/tmp/xray_bridge_probe; L=/tmp/leg2-{socks}; '
        '[ -x "$X" ] || docker cp "$c":/usr/local/bin/xray "$X" >/dev/null 2>&1; '
        'chmod +x "$X"; cat > "$L.json"; '
        '"$X" run -c "$L.json" > "$L.log" 2>&1 & XP=$!; sleep 2; '
        + lookups +
        ' kill $XP 2>/dev/null; '
        'grep -iE "rejected|failed|refused|timeout|EOF" "$L.log" | tail -2; '
        'rm -f "$L.json" "$L.log"')
    r = mc.ssh(entry_ip, script, inp=json.dumps(cfg), timeout=120)
    return r.stdout


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("host_id", type=int)
    p.add_argument("--from", dest="vantage", default="",
                   help="node id to probe from (default: busiest RU entry)")
    p.add_argument("--user", default=bl.DEFAULT_USER)
    p.add_argument("--leg2", action="store_true",
                   help="also drive the entry node's outbound directly")
    p.add_argument("--no-client", action="store_true",
                   help="skip the end-to-end probe, only inspect the legs")
    args = p.parse_args()

    targets = bl.load_targets(tiers=("universal", "elite", "fast"))
    t = next((x for x in targets if x.host_id == args.host_id), None)
    if not t:
        raise SystemExit(f"host {args.host_id} not found")

    print(f"host #{t.host_id}  {t.remark}")
    print(f"  entry   node {t.node_id} {t.node_name} {t.address}:{t.port} "
          f"({t.variant}, sni={t.sni}, flow={t.flow})")
    print(f"  inbound {t.tag}  pbk={t.pbk[:16]}...  sid={t.sid}")

    entry_cfg = mc.node_cfg(t.address)
    out_tag = mc.routing_map(entry_cfg).get(t.tag)
    ob = mc.find(entry_cfg["outbounds"], out_tag) if out_tag else None
    if ob:
        v = ((ob.get("settings") or {}).get("vnext") or [{}])[0]
        print(f"  exit    {out_tag} -> {v.get('address')}:{v.get('port')}")
        er = mc.ssh(t.address,
                    f'timeout 6 bash -c "</dev/tcp/{v.get("address")}/'
                    f'{v.get("port")}" && echo OPEN || echo SHUT')
        print(f"  entry->exit tcp: {er.stdout.strip() or 'no answer'}")
        if args.leg2:
            print("  entry->exit tunnel:",
                  test_outbound(t.address, ob).strip() or "no answer")
    elif t.is_bridge:
        print("  exit    NO ROUTING RULE for this inbound (traffic stays local)")

    if args.no_client:
        return 0
    if args.vantage:
        vlist = [v for v in ({"node_id": x.node_id, "name": x.node_name,
                              "address": x.address, "status": x.node_status}
                             for x in targets)
                 if str(v["node_id"]) == args.vantage]
        vantage = vlist[0] if vlist else None
    else:
        vantage = bp.default_vantages(targets, limit=1)[0]
    if not vantage:
        raise SystemExit(f"unknown vantage {args.vantage}")
    print(f"\nprobing from node {vantage['node_id']} {vantage['name']} "
          f"({vantage['address']})\n")

    socks = 12777
    cfg = bl.build_client(t, socks, args.user)
    cfg["log"] = {"loglevel": "debug"}
    up = mc.ssh(vantage["address"], f"cat > {REMOTE}",
                inp=json.dumps(cfg), timeout=30)
    if up.returncode != 0:
        raise SystemExit(f"cannot upload client config: {up.stderr[:200]}")

    script = SCRIPT % {"entry_ip": t.address, "entry_port": t.port,
                       "cfg": REMOTE, "socks": socks}
    r = mc.ssh(vantage["address"], script, timeout=120)
    print(r.stdout)
    if r.stderr.strip():
        print("stderr:", r.stderr[-500:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
