#!/usr/bin/env python3
"""Close REALITY connections that never got past the client hello.

Two halves in one file, so the node runs exactly the code the repo holds:

    python3 reality_reaper.py run [--dry-run]        # ON A NODE, from its timer
    python3 reality_reaper.py install [--node 47,50] # ON THE PANEL: put it on nodes
    python3 reality_reaper.py status  [--node 47]    # ON THE PANEL: last runs per node

Why it exists. Under the 2026 whitelist regime a mobile network lets the first
TCP segment of a big client hello through and drops the rest. xray's REALITY
listener (xtls/reality ``Server()``) dials ``dest`` on accept and then waits for
the rest of the hello with no deadline; the client's side never closes, keepalives
are answered, and the pair of sockets lives for days. On 2026-11-01 IHC RU-1
(node 47) held 28k of them — exactly one MSS received (1348/1388/1448 bytes),
nothing sent — plus 28k idle sockets to api-maps.yandex.ru. Yandex then stopped
taking new connections from the node's address to 87.250.250.0/23, REALITY could
no longer borrow a ServerHello, and every handshake on the node hung while TCP
to the entry and the bridges stayed fine. ``ss -K`` on the dest sockets freed it
in seconds: xray closes the client side once its dest side dies.

What counts as stuck, per socket on a REALITY inbound port: the server has not
sent a single byte (no ``bytes_sent``) and nothing came in for ``IDLE_SEC``.
A REALITY client always gets a ServerHello within its first round trips — from
xray for an authorised one, from ``dest`` for anyone else — so a socket without
one after two minutes is not a slow client, it is a dead one. The orphan pass
then closes sockets to ``dest`` that never carried a byte and sat as long.

The node half is stdlib-only (no marz_common, no _secrets.py): it runs from a
systemd timer on the node itself every five minutes, so a node the panel cannot
reach still cleans up after itself. One journal line per run that closed
anything; ``status`` reads them.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys

CONFIG = "/var/lib/marznode/xray_config.json"
IDLE_SEC = 120
# Sockets per `ss -K` call: one filter expression per socket, and a 20k backlog
# in one call makes an expression ss chokes on.
KILL_CHUNK = 200

INSTALL_DIR = "/usr/local/lib/reality-reaper"
UNIT = "reality-reaper"


# ── node half ────────────────────────────────────────────────────────────


def reality_inbounds(cfg: dict) -> dict[int, tuple[str, int] | None]:
    """{listen port: (dest host, dest port) or None} for every REALITY inbound."""
    out: dict[int, tuple[str, int] | None] = {}
    for inbound in cfg.get("inbounds") or []:
        stream = inbound.get("streamSettings") or {}
        if stream.get("security") != "reality":
            continue
        port = inbound.get("port")
        if isinstance(port, str) and port.isdigit():
            port = int(port)
        if not isinstance(port, int):
            continue  # port ranges / env placeholders: not ours to guess
        reality = stream.get("realitySettings") or {}
        dest = reality.get("dest") or reality.get("target")
        out[port] = _split_dest(dest)
    return out


def _split_dest(dest) -> tuple[str, int] | None:
    if isinstance(dest, int):
        return ("127.0.0.1", dest)
    if not isinstance(dest, str) or not dest:
        return None
    if dest.isdigit():
        return ("127.0.0.1", int(dest))
    host, _, port = dest.rpartition(":")
    if not host or not port.isdigit():
        return None
    return (host.strip("[]"), int(port))


_ADDR = re.compile(r"^\[?(?P<ip>.*?)\]?:(?P<port>\d+)$")


def _addr(token: str) -> tuple[str, int]:
    m = _ADDR.match(token)
    if not m:
        return token, 0
    ip = m.group("ip")
    if ip.startswith("::ffff:") and "." in ip:
        ip = ip[len("::ffff:"):]
    return ip, int(m.group("port"))


def parse_ss(text: str) -> list[dict]:
    """`ss -Htni state established`: a socket line, then an indented info line."""
    socks: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t":
            if socks:
                info = socks[-1]["info"]
                for token in line.split():
                    key, sep, value = token.partition(":")
                    if sep and value.replace(".", "", 1).isdigit():
                        info[key] = float(value) if "." in value else int(value)
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        lip, lport = _addr(parts[2])
        rip, rport = _addr(parts[3])
        socks.append({"local": (lip, lport), "peer": (rip, rport), "info": {}})
    return socks


def _silent(sock: dict, idle_ms: int) -> bool:
    info = sock["info"]
    return not info.get("bytes_sent") and info.get("lastsnd", 0) >= idle_ms


def stuck_inbound(socks: list[dict], ports: set[int], idle_ms: int) -> list[dict]:
    """Client sockets on REALITY ports that got no reply and went quiet."""
    return [
        s for s in socks
        if s["local"][1] in ports and _silent(s, idle_ms) and s["info"].get("lastrcv", 0) >= idle_ms
    ]


def orphan_dest(socks: list[dict], dests: set[tuple[str, int]], idle_ms: int) -> list[dict]:
    """Sockets to a REALITY dest that never carried a byte."""
    return [
        s for s in socks
        if s["peer"] in dests and _silent(s, idle_ms) and not s["info"].get("bytes_received")
    ]


def kill_filter(batch: list[dict]) -> str:
    terms = []
    for s in batch:
        ip = s["peer"][0]
        terms.append(f"( sport = :{s['local'][1]} and dport = :{s['peer'][1]} "
                     f"and dst {f'[{ip}]' if ':' in ip else ip} )")
    return " or ".join(terms)


def _resolve(host: str, port: int) -> set[tuple[str, int]]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return set()
    return {(info[4][0], port) for info in infos}


def _established() -> list[dict]:
    r = subprocess.run(["ss", "-Htni", "state", "established"],
                       capture_output=True, text=True, timeout=120)
    return parse_ss(r.stdout)


def _kill(batch: list[dict]) -> None:
    for i in range(0, len(batch), KILL_CHUNK):
        chunk = batch[i:i + KILL_CHUNK]
        subprocess.run(["ss", "-K", "state", "established", kill_filter(chunk)],
                       capture_output=True, text=True, timeout=120)


def cmd_run(args) -> int:
    try:
        with open(CONFIG) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"reality-reaper: cannot read {CONFIG}: {e}")
        return 1
    inbounds = reality_inbounds(cfg)
    if not inbounds:
        return 0
    ports = set(inbounds)
    dests: set[tuple[str, int]] = set()
    for dest in {d for d in inbounds.values() if d}:
        dests |= _resolve(*dest)
    idle_ms = args.idle * 1000

    socks = _established()
    stuck = stuck_inbound(socks, ports, idle_ms)
    orphans = orphan_dest(socks, dests, idle_ms)
    if not stuck and not orphans:
        return 0
    if args.dry_run:
        print(f"reality-reaper: would close {len(stuck)} stuck inbound, {len(orphans)} orphan dest "
              f"(established {len(socks)})")
        return 0

    _kill(stuck)
    # xray drops the dest side of a killed pair by itself; what is left is a
    # dest socket whose client went away some other way.
    left = {(s["local"], s["peer"]) for s in _established()}
    _kill([s for s in orphans if (s["local"], s["peer"]) in left])
    after = _established()
    alive = {(s["local"], s["peer"]) for s in after}
    not_closed = sum(1 for s in stuck if (s["local"], s["peer"]) in alive)
    by_port: dict[int, int] = {}
    for s in stuck:
        by_port[s["local"][1]] = by_port.get(s["local"][1], 0) + 1
    top = ", ".join(f":{p} {n}" for p, n in sorted(by_port.items(), key=lambda x: -x[1])[:5])
    print(f"reality-reaper: closed {len(stuck) - not_closed} stuck inbound ({top}), "
          f"{len(orphans)} orphan dest seen; established {len(socks)} → {len(after)}"
          + (f"; {not_closed} would not close (ss -K unsupported?)" if not_closed else ""))
    return 0


# ── panel half ───────────────────────────────────────────────────────────

_SERVICE = f"""[Unit]
Description=Close REALITY connections stuck before the server hello
After=docker.service

[Service]
Type=oneshot
Nice=10
ExecStart=/usr/bin/python3 {INSTALL_DIR}/reality_reaper.py run
TimeoutStartSec=240
"""

_TIMER = """[Unit]
Description=Every-five-minutes sweep of stuck REALITY connections

[Timer]
OnCalendar=*:04/5
OnBootSec=3min
AccuracySec=30s

[Install]
WantedBy=timers.target
"""

_INSTALL = r"""
set -eu
command -v python3 >/dev/null || { echo NO_PYTHON3; exit 3; }
ss -h 2>&1 | grep -q -- '--kill\|-K' || { echo NO_SS_KILL; exit 3; }
mkdir -p INSTALL_DIR
cat > INSTALL_DIR/reality_reaper.py
cat > /etc/systemd/system/UNIT.service <<'XEOF'
SERVICE
XEOF
cat > /etc/systemd/system/UNIT.timer <<'XEOF'
TIMER
XEOF
systemctl daemon-reload
systemctl enable --now UNIT.timer >/dev/null 2>&1
python3 INSTALL_DIR/reality_reaper.py run --dry-run || true
systemctl start UNIT.service || true
echo INSTALLED
journalctl -u UNIT.service -n 5 --no-pager -o cat | grep 'reality-reaper:' || true
"""


def install_script() -> str:
    return (_INSTALL.replace("INSTALL_DIR", INSTALL_DIR).replace("SERVICE", _SERVICE.strip())
            .replace("TIMER", _TIMER.strip()).replace("UNIT", UNIT))


def _nodes(only: set[int]) -> list[tuple[int, str, str, str]]:
    import marz_common as mc

    rows = []
    for row in mc.db_query("SELECT id, name, address, status FROM nodes ORDER BY id;"):
        if len(row) == 4 and (not only or int(row[0]) in only):
            rows.append((int(row[0]), row[1], row[2], row[3]))
    return rows


def cmd_install(args) -> int:
    import marz_common as mc

    with open(os.path.abspath(__file__)) as fh:
        code = fh.read()
    failed = []
    for nid, name, ip, status in _nodes(args.node):
        label = f"{nid:>3} {name[:34]:34s}"
        if status == "disabled" and not args.node:
            print(f"{label} skip (disabled)")
            continue
        try:
            r = mc.ssh(ip, install_script(), inp=code, timeout=300)
        except subprocess.TimeoutExpired:
            print(f"{label} FAILED: ssh timeout")
            failed.append(nid)
            continue
        out = (r.stdout + r.stderr).strip()
        if "INSTALLED" in r.stdout:
            tail = [ln for ln in r.stdout.splitlines() if ln.startswith("reality-reaper")]
            print(f"{label} installed" + (f" — {tail[-1][len('reality-reaper: '):]}" if tail else ""))
        else:
            print(f"{label} FAILED: {out[-160:]}")
            failed.append(nid)
    if failed:
        print("\nnodes needing attention: " + ", ".join(map(str, failed)))
        return 1
    return 0


def cmd_status(args) -> int:
    import marz_common as mc

    cmd = (f"systemctl is-active {UNIT}.timer; "
           f"journalctl -u {UNIT}.service --since '-1 hour' --no-pager -o short-iso | grep 'reality-reaper:' | tail -3")
    for nid, name, ip, status in _nodes(args.node):
        if status == "disabled" and not args.node:
            continue
        try:
            r = mc.ssh(ip, cmd, timeout=60)
            lines = r.stdout.strip().splitlines() or ["no answer"]
        except subprocess.TimeoutExpired:
            lines = ["ssh timeout"]
        print(f"{nid:>3} {name[:34]:34s} timer {lines[0]}")
        for line in lines[1:]:
            print(f"      {line}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--idle", type=int, default=IDLE_SEC, help="seconds of silence before a socket counts as stuck")
    for name in ("install", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--node", type=lambda s: {int(x) for x in s.split(",") if x.strip()}, default=set(),
                        help="limit to these node ids")
    args = p.parse_args()
    if args.cmd in ("install", "status"):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        return cmd_install(args) if args.cmd == "install" else cmd_status(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
