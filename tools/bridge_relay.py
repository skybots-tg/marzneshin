#!/usr/bin/env python3
"""Route a node's blocked connections through a Russian relay node.

Some entries lose the path to part of the world while staying reachable from
Russia: Yandex.Cloud-0 since 24.09.2026, DataCheap RU-1 / RU-1-new since
29.09.2026. New TCP connections between them and a set of foreign addresses
hang right after the handshake; the panel can't reach the node, the node can't
reach its bridge exits. Another Russian node still reaches both sides, so the
kernel sends those connections through it:

- on the source (an entry, or the panel), nat OUTPUT DNATs dst:dport to
  relay:rport;
- on the relay, nat PREROUTING DNATs relay:rport back to dst:dport, and
  POSTROUTING masquerades it; docker's FORWARD DROP gets an exception.

Nothing above the kernel changes: xray and marznode keep their configs, Reality
and TLS pass through untouched, the node keeps its address in the panel, and
every tool that SSHes to it just works.

The table is ``bridge_relay.routes`` (one row: src relay rport dst dport tag).
Each machine applies the rows where it is the source or the relay. The rules
live in their own chains, replaced atomically by ``iptables-restore -n``, so a
re-run never leaves stale rules or a gap.

Stdlib only -- it runs on bare nodes. ``bridge_relay_install.py`` pushes it.

    bridge_relay.py plan <self-ip> [--routes FILE]   # print the ruleset
    bridge_relay.py up   <self-ip> [--routes FILE]   # apply it
    bridge_relay.py down                             # remove everything
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass

DEFAULT_ROUTES = "/usr/local/etc/bridge-relay.routes"
COMMENT = "bridge-relay"

OUT, PRE, POST, FWD = ("BRIDGE_RELAY_OUT", "BRIDGE_RELAY_PRE",
                       "BRIDGE_RELAY_POST", "BRIDGE_RELAY_FWD")
NAT_JUMPS = (("OUTPUT", OUT), ("PREROUTING", PRE), ("POSTROUTING", POST))


@dataclass(frozen=True)
class Route:
    src: str
    relay: str
    rport: int
    dst: str
    dport: int
    tag: str


def parse_routes(text: str) -> list[Route]:
    routes = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 6:
            raise ValueError(f"line {n}: need src relay rport dst dport tag: {raw!r}")
        src, relay, rport, dst, dport = parts[:5]
        for ip in (src, relay, dst):
            ipaddress.IPv4Address(ip)
        r = Route(src, relay, int(rport), dst, int(dport), " ".join(parts[5:]))
        if not (0 < r.rport < 65536 and 0 < r.dport < 65536):
            raise ValueError(f"line {n}: port out of range: {raw!r}")
        routes.append(r)
    seen: dict[tuple[str, int], Route] = {}
    for r in routes:
        clash = seen.get((r.relay, r.rport))
        if clash:
            raise ValueError(f"relay port {r.relay}:{r.rport} used twice: "
                             f"{clash.tag!r} and {r.tag!r}")
        seen[(r.relay, r.rport)] = r
    return routes


def machines(routes: list[Route]) -> set[str]:
    """Everything that needs rules: sources and relays, never the far ends."""
    return {r.src for r in routes} | {r.relay for r in routes}


def _c(tag: str) -> str:
    return f'-m comment --comment "{COMMENT} {tag}"'


def ruleset(routes: list[Route], self_ip: str) -> str:
    """The iptables-restore payload for one machine (chains are flushed first)."""
    out, pre, post, fwd = [], [], [], []
    back: list[str] = []
    for r in routes:
        if r.src == self_ip:
            out.append(f"-A {OUT} -d {r.dst}/32 -p tcp -m tcp --dport {r.dport} "
                       f"{_c(r.tag)} -j DNAT --to-destination {r.relay}:{r.rport}")
        if r.relay == self_ip:
            pre.append(f"-A {PRE} -s {r.src}/32 -p tcp -m tcp --dport {r.rport} "
                       f"{_c(r.tag)} -j DNAT --to-destination {r.dst}:{r.dport}")
            post.append(f"-A {POST} -s {r.src}/32 -d {r.dst}/32 -p tcp -m tcp "
                        f"--dport {r.dport} {_c(r.tag)} -j MASQUERADE")
            fwd.append(f"-A {FWD} -s {r.src}/32 -d {r.dst}/32 -p tcp -m tcp "
                       f"--dport {r.dport} {_c(r.tag)} -j ACCEPT")
            if r.src not in back:
                back.append(r.src)
    fwd += [f"-A {FWD} -d {src}/32 -m conntrack --ctstate RELATED,ESTABLISHED "
            f"{_c('back')} -j ACCEPT" for src in back]
    return "\n".join(["*nat", f":{OUT} - [0:0]", f":{PRE} - [0:0]", f":{POST} - [0:0]",
                      *out, *pre, *post, "COMMIT",
                      "*filter", f":{FWD} - [0:0]", *fwd, "COMMIT", ""])


def is_relay(routes: list[Route], self_ip: str) -> bool:
    return any(r.relay == self_ip for r in routes)


# ── applying ─────────────────────────────────────────────────────────

def ipt(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["iptables", *args], capture_output=True, text=True, check=check)


def has_chain(table: str, chain: str) -> bool:
    return ipt("-t", table, "-S", chain, check=False).returncode == 0


def forward_hook() -> str:
    # docker sets FORWARD to DROP and gives DOCKER-USER for exceptions
    return "DOCKER-USER" if has_chain("filter", "DOCKER-USER") else "FORWARD"


def ensure_jump(table: str, parent: str, chain: str) -> None:
    if ipt("-t", table, "-C", parent, "-j", chain, check=False).returncode != 0:
        ipt("-t", table, "-I", parent, "1", "-j", chain)


def drop_legacy() -> int:
    """Remove rules the old bridge-relay.sh put straight into built-in chains."""
    removed = 0
    for table, chains in (("nat", ("OUTPUT", "PREROUTING", "POSTROUTING")),
                          ("filter", ("DOCKER-USER", "FORWARD"))):
        for chain in chains:
            listing = ipt("-t", table, "-S", chain, check=False)
            if listing.returncode != 0:
                continue
            for line in listing.stdout.splitlines():
                if line.startswith(f"-A {chain} ") and f'--comment "{COMMENT} ' in line:
                    ipt("-t", table, "-D", *shlex.split(line)[1:], check=False)
                    removed += 1
    return removed


def up(routes: list[Route], self_ip: str) -> str:
    payload = ruleset(routes, self_ip)
    subprocess.run(["iptables-restore", "-n"], input=payload, text=True,
                   capture_output=True, check=True)
    for parent, chain in NAT_JUMPS:
        ensure_jump("nat", parent, chain)
    ensure_jump("filter", forward_hook(), FWD)
    if is_relay(routes, self_ip):
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write("1\n")
    legacy = drop_legacy()
    counts = {c: sum(1 for ln in payload.splitlines() if ln.startswith(f"-A {c} "))
              for c in (OUT, PRE, POST, FWD)}
    return (f"STATE up self={self_ip} out={counts[OUT]} pre={counts[PRE]} "
            f"post={counts[POST]} fwd={counts[FWD]} legacy_removed={legacy}")


def down() -> str:
    for parent, chain in NAT_JUMPS:
        while ipt("-t", "nat", "-D", parent, "-j", chain, check=False).returncode == 0:
            pass
    for parent in ("DOCKER-USER", "FORWARD"):
        while ipt("-t", "filter", "-D", parent, "-j", FWD, check=False).returncode == 0:
            pass
    for table, chain in (("nat", OUT), ("nat", PRE), ("nat", POST), ("filter", FWD)):
        ipt("-t", table, "-F", chain, check=False)
        ipt("-t", table, "-X", chain, check=False)
    return f"STATE down legacy_removed={drop_legacy()}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("plan", "up", "down"))
    ap.add_argument("self_ip", nargs="?", default="")
    ap.add_argument("--routes", default=DEFAULT_ROUTES)
    args = ap.parse_args(argv)
    if args.action == "down":
        print(down())
        return 0
    if not args.self_ip:
        ap.error("self_ip is required for plan/up")
    with open(args.routes, encoding="utf-8") as f:
        routes = parse_routes(f.read())
    if args.self_ip not in machines(routes):
        print(f"{args.self_ip} has no rows in {args.routes}", file=sys.stderr)
    if args.action == "plan":
        sys.stdout.write(ruleset(routes, args.self_ip))
        return 0
    if os.geteuid() != 0:
        print("up needs root", file=sys.stderr)
        return 2
    print(up(routes, args.self_ip))
    return 0


if __name__ == "__main__":
    sys.exit(main())
