#!/usr/bin/env python3
"""Run ON the panel. Put the port census on every node of the fleet.

The census (``port_census.py``) is what tells us, per host of the catalogue,
which operators and regions actually hold a connection to it -- the only source
that covers every client, not just the ones running our app. It lived for two
days as an experiment on two Yandex entries and stopped with them. This makes it
a service: systemd keeps it running across reboots and crashes, logrotate keeps
one day per file and three generations, and the day before stays uncompressed
so vpn_project's collector can finish reading it after midnight.

Idempotent: re-running rewrites the script and unit and restarts the service,
which is also how an updated script reaches the fleet.

usage:
    port_census_install.py                 # every node that is not disabled
    port_census_install.py --nodes 19,32   # just these
    port_census_install.py --dry-run
    port_census_install.py --uninstall --nodes 19
"""
import argparse
import os
import sys

import marz_common as mc

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "port_census.py")

UNIT = """[Unit]
Description=Port census: who reaches which xray port (see port_census.py)
After=network-online.target docker.service

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/port_census.py
Restart=always
RestartSec=30
Nice=10

[Install]
WantedBy=multi-user.target
"""

# `su`: /var/log on Ubuntu is root:syslog 0775, and without it logrotate
# refuses the file as "insecure parent directory" and the log grows unbounded.
LOGROTATE = """/var/log/port_census.jsonl {
    su root syslog
    daily
    rotate 3
    missingok
    notifempty
    compress
    delaycompress
    create 0644 root root
}
"""

INSTALL = r'''
set -u
command -v python3 >/dev/null 2>&1 || { echo NO_PYTHON; exit 3; }
cat > /usr/local/bin/port_census.py
chmod 755 /usr/local/bin/port_census.py
python3 -m py_compile /usr/local/bin/port_census.py || { echo COMPILE_FAILED; exit 4; }
cat > /etc/systemd/system/port-census.service <<'UNIT_EOF'
%(unit)sUNIT_EOF
cat > /etc/logrotate.d/port-census <<'LR_EOF'
%(logrotate)sLR_EOF
systemctl daemon-reload
systemctl enable port-census >/dev/null 2>&1
systemctl restart port-census
sleep 3
getent group syslog >/dev/null 2>&1 || sed -i 's/su root syslog/su root root/' /etc/logrotate.d/port-census
lr=$(logrotate -d /etc/logrotate.d/port-census 2>&1 | grep -c "error:")
echo "STATE $(systemctl is-active port-census) $(python3 -V 2>&1) logrotate_errors=$lr"
'''

UNINSTALL = r'''
systemctl disable --now port-census >/dev/null 2>&1
rm -f /etc/systemd/system/port-census.service /etc/logrotate.d/port-census
systemctl daemon-reload
echo "STATE removed"
'''


def targets(only):
    rows = mc.db_query("SELECT id, name, address, status FROM nodes "
                       "WHERE status <> 'disabled' ORDER BY id;")
    out = [(int(r[0]), r[1], r[2], r[3]) for r in rows if len(r) >= 4]
    if only:
        out = [t for t in out if t[0] in only]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", default="", help="comma-separated node ids")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()
    only = {int(x) for x in args.nodes.split(",") if x.strip()}
    script = open(SCRIPT, encoding="utf-8").read()
    failed = 0
    for node_id, name, address, status in targets(only):
        label = f"node {node_id:<3} {address:<16} {name[:28]:<28}"
        if args.dry_run:
            print(f"{label} [{status}] would {'remove' if args.uninstall else 'install'}")
            continue
        try:
            if args.uninstall:
                r = mc.ssh(address, UNINSTALL, timeout=60)
            else:
                r = mc.ssh(address,
                           INSTALL % {"unit": UNIT, "logrotate": LOGROTATE},
                           inp=script, timeout=90)
        except Exception as exc:  # noqa: BLE001 - one node must not stop the fleet
            print(f"{label} FAILED: {type(exc).__name__}: {str(exc)[:80]}")
            failed += 1
            continue
        state = next((ln for ln in r.stdout.splitlines() if ln.startswith(("STATE", "NO_PYTHON", "COMPILE"))),
                     (r.stderr or r.stdout).strip()[-120:] or f"rc={r.returncode}")
        ok = r.returncode == 0 and ("STATE active" in state or "STATE removed" in state)
        failed += 0 if ok else 1
        print(f"{label} {'OK  ' if ok else 'FAIL'} {state}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
