#!/usr/bin/env python3
"""Drop IPv4 TCP packets that carry IP options, before the kernel parses them.

    python3 ipopt_guard.py install --mode count [--node 47,50] [--local]
    python3 ipopt_guard.py install --mode drop  [--node 47,50] [--local]
    python3 ipopt_guard.py status  [--node 47] [--local]
    python3 ipopt_guard.py remove  [--node 47] [--local]

Why it exists. CVE-2026-98432 (CVSS 9.8, published 2026-10-15): a peer puts an
IPv4 Record Route or Timestamp option into a TCP SYN, the kernel keeps it in
``ireq_opt``, and a retransmitted SYN racing the child socket's teardown reads it
after ``kfree()`` in ``ip_options_build()`` — heap leak into the SYNACK, out of
bounds writes, panic. Any listening IPv4 TCP port is enough (xray, sshd). Fixed
upstream in 5.15.223 / 6.1.190 / 6.6.159 / 6.12.113 / 7.2.10; Ubuntu's builds
(noble 6.8.0-149, jammy 5.15.0-203) were still pending on 2026-11-02, so the
fleet's 6.8.0-147 / 5.15.0-202 are vulnerable.

The rule sits in raw PREROUTING, which runs before ``ip_rcv_finish()`` hands the
packet to ``ip_rcv_options()``: an option-bearing packet never reaches the
code. It matches IHL > 5 (``0>>22&0x3C`` is the header length in bytes) on TCP
only. Real client traffic carries no IP options — most of the internet drops
them already — so the drop costs nothing; ``--mode count`` is the same rule
without a target, to see that on a node before dropping. IPv6 is not covered:
the first bug is IPv4-only, the second needs CALIPSO, which nothing here sets.

A systemd oneshot puts the rule back on boot. Remove it once the node runs a
fixed kernel (``remove``).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

UNIT = "ipopt-guard"
SCRIPT = f"/usr/local/sbin/{UNIT}"
DEFAULTS = f"/etc/default/{UNIT}"
COMMENT = UNIT
MATCH = '-p tcp -m u32 --u32 "0>>22&0x3C=24:60"'
MODES = ("count", "drop")

_NODE_SCRIPT = r"""#!/bin/sh
# Installed by marzneshin tools/ipopt_guard.py — CVE-2026-98432 guard.
set -eu
MODE=count
[ -f DEFAULTS ] && . DEFAULTS
ipt() { iptables -w 10 -t raw "$@"; }
clear_rules() {
  ipt -L PREROUTING -n --line-numbers | awk '/\/\* COMMENT \*\//{print $1}' | sort -rn |
    while read -r n; do ipt -D PREROUTING "$n"; done
}
case "${1:-apply}" in
  apply)
    clear_rules
    if [ "$MODE" = drop ]; then
      ipt -I PREROUTING 1 MATCH -m comment --comment COMMENT -j DROP
    else
      ipt -I PREROUTING 1 MATCH -m comment --comment COMMENT
    fi ;;
  clear) clear_rules ;;
  status)
    echo "mode=$MODE"
    ipt -L PREROUTING -n -v -x | awk '/\/\* COMMENT \*\//{print "rule pkts=" $1 " bytes=" $2 " target=" ($3 ~ /^[0-9]/ || $3 == "tcp" ? "none" : $3)}' ;;
esac
"""

_SERVICE = f"""[Unit]
Description=Drop IPv4 TCP packets with IP options (CVE-2026-98432)
DefaultDependencies=no
After=local-fs.target
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={SCRIPT} apply
ExecStop={SCRIPT} clear

[Install]
WantedBy=multi-user.target
"""

_INSTALL = r"""
set -eu
command -v iptables >/dev/null || { echo NO_IPTABLES; exit 3; }
modprobe xt_u32 2>/dev/null || { echo NO_XT_U32; exit 3; }
cat > SCRIPT
chmod 755 SCRIPT
echo "MODE=MODEVAL" > DEFAULTS
cat > /etc/systemd/system/UNIT.service <<'XEOF'
SERVICE
XEOF
systemctl daemon-reload
systemctl enable UNIT.service >/dev/null 2>&1
systemctl restart UNIT.service
echo INSTALLED
SCRIPT status
"""

_REMOVE = f"""
systemctl disable --now {UNIT}.service >/dev/null 2>&1 || true
[ -x {SCRIPT} ] && {SCRIPT} clear || true
rm -f /etc/systemd/system/{UNIT}.service {SCRIPT} {DEFAULTS}
systemctl daemon-reload
echo REMOVED
"""

_STATUS = f"systemctl is-active {UNIT}.service; [ -x {SCRIPT} ] && {SCRIPT} status || echo not-installed"


def node_script() -> str:
    return (_NODE_SCRIPT.replace("DEFAULTS", DEFAULTS).replace("COMMENT", COMMENT)
            .replace("MATCH", MATCH))


def install_script(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(mode)
    return (_INSTALL.replace("SCRIPT", SCRIPT).replace("DEFAULTS", DEFAULTS)
            .replace("MODEVAL", mode).replace("SERVICE", _SERVICE.strip()).replace("UNIT", UNIT))


def _nodes(only: set[int]) -> list[tuple[int, str, str, str]]:
    import marz_common as mc

    rows = []
    for row in mc.db_query("SELECT id, name, address, status FROM nodes ORDER BY id;"):
        if len(row) == 4 and (not only or int(row[0]) in only):
            rows.append((int(row[0]), row[1], row[2], row[3]))
    return rows


def _targets(args) -> list[tuple[str, str | None]]:
    """[(label, ip or None for this machine)]; one address once (two nodes share 217.146.76.253)."""
    if args.local:
        return [("panel (local)", None)]
    out, seen = [], set()
    for nid, name, ip, status in _nodes(args.node):
        label = f"{nid:>3} {name[:34]:34s}"
        if status == "disabled" and not args.node:
            print(f"{label} skip (disabled)")
            continue
        if ip in seen:
            print(f"{label} same host as above")
            continue
        seen.add(ip)
        out.append((label, ip))
    return out


def _run(ip: str | None, cmd: str, inp: str | None = None, timeout: int = 120):
    if ip is None:
        return subprocess.run(["sh", "-c", cmd], input=inp, capture_output=True, text=True, timeout=timeout)
    import marz_common as mc

    return mc.ssh(ip, cmd, inp=inp, timeout=timeout)


def _each(args, cmd: str, inp: str | None, ok_marker: str | None) -> int:
    failed = []
    for label, ip in _targets(args):
        try:
            r = _run(ip, cmd, inp=inp)
        except subprocess.TimeoutExpired:
            print(f"{label} FAILED: ssh timeout")
            failed.append(label.split()[0])
            continue
        out = " | ".join(ln for ln in r.stdout.strip().splitlines() if ln != ok_marker)
        if ok_marker and ok_marker not in r.stdout:
            print(f"{label} FAILED: {(r.stdout + r.stderr).strip()[-160:]}")
            failed.append(label.split()[0])
        else:
            print(f"{label} {out or 'no answer'}")
    if failed:
        print("\nneeding attention: " + ", ".join(failed))
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("install", "status", "remove"):
        sp = sub.add_parser(name)
        sp.add_argument("--node", type=lambda s: {int(x) for x in s.split(",") if x.strip()}, default=set(),
                        help="limit to these node ids")
        sp.add_argument("--local", action="store_true", help="this machine (the panel) instead of nodes")
        if name == "install":
            sp.add_argument("--mode", choices=MODES, required=True)
    args = p.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if args.cmd == "install":
        return _each(args, install_script(args.mode), node_script(), "INSTALLED")
    if args.cmd == "remove":
        return _each(args, _REMOVE, None, "REMOVED")
    return _each(args, _STATUS, None, None)


if __name__ == "__main__":
    sys.exit(main())
