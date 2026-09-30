#!/usr/bin/env python3
"""Run ON the panel. Put bridge_relay.py and its route table on every machine.

Order matters: a source that is cut off from the panel is only reachable once
its relay and the panel itself carry the rows, so relays go first, then the
panel (locally), then the sources. Idempotent -- re-running is how a changed
table reaches the fleet; rows, routes and tunnels dropped from the table
disappear from the machines too.

Tunnels need each end's WireGuard public key. Every machine keeps its own
private key (``/etc/bridge-relay/wg.key``, made on first use); the installer
collects the public halves first and ships them as ``bridge-relay.peers``.

The systemd unit re-applies everything at boot (after docker, whose FORWARD
DROP the relay punches through). It replaces the hand-written
``bridge-relay.sh`` of 24.09 on the Yandex.Cloud-0 path; the old rules are
removed as the new chains come up.

usage:
    bridge_relay_install.py                  # every machine in the table
    bridge_relay_install.py --only 45.91.54.49
    bridge_relay_install.py --dry-run        # print each machine's ruleset
    bridge_relay_install.py --status         # rule hit counters, tunnel handshakes
    bridge_relay_install.py --uninstall --only 45.81.33.150
"""
import argparse
import base64
import os
import re
import subprocess
import sys
import time

import bridge_relay as brl
import marz_common as mc

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "bridge_relay.py")
ROUTES = os.path.join(HERE, "bridge_relay.routes")
PANEL_IP = "195.54.170.162"

UNIT = """[Unit]
Description=Bridge relay: blocked connections through a Russian node (bridge_relay.py)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 /usr/local/sbin/bridge_relay.py up %(self)s
ExecStop=/usr/bin/python3 /usr/local/sbin/bridge_relay.py down

[Install]
WantedBy=multi-user.target
"""

PUSH = r'''
set -eu
command -v python3 >/dev/null 2>&1 || { echo NO_PYTHON; exit 3; }
cat > /usr/local/sbin/bridge_relay.py
chmod 755 /usr/local/sbin/bridge_relay.py
'''

# needrestart would otherwise offer to restart docker in the middle of it
KEYGEN = PUSH + r'''
command -v wg >/dev/null 2>&1 || NEEDRESTART_SUSPEND=1 DEBIAN_FRONTEND=noninteractive \
  apt-get install -y -qq wireguard-tools >/dev/null 2>&1
echo "PUBKEY $(python3 /usr/local/sbin/bridge_relay.py wg-key)"
'''

# The routes and peers travel base64-encoded inside the command; the script on stdin.
INSTALL = PUSH + r'''
mkdir -p /usr/local/etc
echo '%(routes_b64)s' | base64 -d > /usr/local/etc/bridge-relay.routes
echo '%(peers_b64)s' | base64 -d > /usr/local/etc/bridge-relay.peers
python3 /usr/local/sbin/bridge_relay.py plan %(self)s >/dev/null
cat > /etc/systemd/system/bridge-relay.service <<'UNIT_EOF'
%(unit)sUNIT_EOF
systemctl daemon-reload
systemctl enable bridge-relay >/dev/null 2>&1
python3 /usr/local/sbin/bridge_relay.py up %(self)s
systemctl start bridge-relay 2>/dev/null || true
rm -f /usr/local/sbin/bridge-relay.sh
'''

UNINSTALL = r'''
python3 /usr/local/sbin/bridge_relay.py down 2>/dev/null || echo "STATE down (script missing)"
systemctl disable bridge-relay >/dev/null 2>&1 || true
rm -f /etc/systemd/system/bridge-relay.service /usr/local/sbin/bridge_relay.py \
      /usr/local/etc/bridge-relay.routes /usr/local/etc/bridge-relay.peers
systemctl daemon-reload
'''

STATUS = r'''
for c in BRIDGE_RELAY_OUT BRIDGE_RELAY_PRE BRIDGE_RELAY_POST; do
  iptables -t nat -L $c -nvx 2>/dev/null | awk -v c=$c '/bridge-relay/ {
    s=$0; sub(/.*\/\* bridge-relay /, "", s); sub(/ \*\/.*/, "", s);
    printf "  %-4s %-26s pkts=%s\n", tolower(substr(c, 14)), s, $1 }'
done
command -v wg >/dev/null 2>&1 && wg show all latest-handshakes 2>/dev/null | while read i p t; do
  case "$i" in brwg*) echo "  wg   $i handshake $(( $(date +%s) - t ))s ago";; esac; done
for i in $(ip -o link show type wireguard 2>/dev/null | grep -oE 'brwg[0-9]+'); do
  echo "  wg   $i routes: $(ip -4 route show dev $i | grep -v proto | awk '{print $1}' | tr '\n' ' ')"; done
'''


def order(routes, tunnels=()):
    """Relays, then the panel, then the remaining sources."""
    relays = sorted({r.relay for r in routes} | {t.relay for t in tunnels})
    sources = sorted(({r.src for r in routes} | {t.src for t in tunnels})
                     - set(relays) - {PANEL_IP})
    panel = ([PANEL_IP] if PANEL_IP in brl.machines(routes, tunnels) and PANEL_IP not in relays
             else [])
    return relays + panel + sources


def run_on(ip, script, inp=None, timeout=90):
    if ip == PANEL_IP:
        return subprocess.run(["bash", "-c", script], input=inp, capture_output=True,
                              text=True, timeout=timeout)
    # sshd MaxStartups on busy nodes drops some attempts before the key exchange
    for attempt in range(3):
        r = mc.ssh(ip, script, inp=inp, timeout=timeout)
        if r.returncode != 255 or attempt == 2:
            return r
        time.sleep(3)
    return r


def collect_peers(tunnels, script):
    peers = {}
    for ip in sorted({t.src for t in tunnels} | {t.relay for t in tunnels}):
        r = run_on(ip, KEYGEN, inp=script, timeout=180)
        m = re.search(r"^PUBKEY (\S{44})$", r.stdout, re.M)
        if not m:
            raise SystemExit(f"{ip}: no WireGuard key: {(r.stderr or r.stdout).strip()[-200:]}")
        peers[ip] = m.group(1)
    return peers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated machine IPs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()

    routes_text = open(ROUTES, encoding="utf-8").read()
    routes, tunnels = brl.parse_table(routes_text)
    script = open(SCRIPT, encoding="utf-8").read()
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    peers_text = ""
    if tunnels and not (args.dry_run or args.status or args.uninstall):
        peers = collect_peers(tunnels, script)
        peers_text = "".join(f"{ip} {key}\n" for ip, key in sorted(peers.items()))
    failed = 0
    for ip in order(routes, tunnels):
        if only and ip not in only:
            continue
        roles = "+".join(x for x, hit in (
            ("relay", brl.is_relay(routes, ip, tunnels)),
            ("source", any(r.src == ip for r in routes) or any(t.src == ip for t in tunnels)))
            if hit)
        label = f"{ip:<16} {roles:<12}"
        if args.dry_run:
            print(f"── {label}\n{brl.ruleset(routes, ip, tunnels)}")
            for iface, dsts in brl.wg_routes(routes, tunnels, ip).items():
                print(f"# route via {iface}: {' '.join(sorted(dsts))}")
            continue
        try:
            if args.status:
                r = run_on(ip, STATUS, timeout=40)
                print(f"{label}\n{r.stdout.rstrip() or '  (no rules)'}")
                continue
            if args.uninstall:
                r = run_on(ip, UNINSTALL, timeout=60)
            else:
                b64 = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731
                r = run_on(ip, INSTALL % {"routes_b64": b64(routes_text),
                                          "peers_b64": b64(peers_text), "self": ip,
                                          "unit": UNIT % {"self": ip}},
                           inp=script, timeout=120)
        except Exception as exc:  # noqa: BLE001 - one machine must not stop the rest
            print(f"{label} FAILED: {type(exc).__name__}: {str(exc)[:100]}")
            failed += 1
            continue
        state = next((ln for ln in r.stdout.splitlines() if ln.startswith(("STATE", "NO_PYTHON"))),
                     (r.stderr or r.stdout).strip()[-160:] or f"rc={r.returncode}")
        ok = r.returncode == 0 and state.startswith("STATE")
        failed += 0 if ok else 1
        print(f"{label} {'OK  ' if ok else 'FAIL'} {state}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
