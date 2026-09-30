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

AdminVPS (UNIVERSAL 1 and 5) is cut differently: its network lets five
Reality connections through and then drops every new one for about ninety
seconds -- to any address, Russian relays included, while plain TCP passes.
A DNAT hop still shows the Reality handshake, so those rows go through a
WireGuard tunnel instead (rport ``wg``): the source routes dst/32 into the
tunnel, the relay masquerades it out. The wire between them carries only
WireGuard.

Nothing above the kernel changes: xray and marznode keep their configs, Reality
and TLS pass through untouched, the node keeps its address in the panel, and
every tool that SSHes to it just works.

The table is ``bridge_relay.routes``: rows ``src relay rport dst dport tag``
and tunnels ``tunnel src relay 10.77.N.0/30 udp-port``. Each machine applies
what concerns it. Rules live in their own chains, replaced atomically by
``iptables-restore -n``; tunnels are ``brwgN`` interfaces set with
``wg syncconf``; a re-run leaves no stale rules, routes or interfaces.

Stdlib only -- it runs on bare nodes. ``bridge_relay_install.py`` pushes it.

    bridge_relay.py plan <self-ip> [--routes FILE]   # print the ruleset
    bridge_relay.py up   <self-ip> [--routes FILE]   # apply it
    bridge_relay.py down                             # remove everything
    bridge_relay.py wg-key                           # make/print this machine's key
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass

DEFAULT_ROUTES = "/usr/local/etc/bridge-relay.routes"
DEFAULT_PEERS = "/usr/local/etc/bridge-relay.peers"
WG_KEY = "/etc/bridge-relay/wg.key"
WG_MTU = 1420
COMMENT = "bridge-relay"

OUT, PRE, POST, FWD = ("BRIDGE_RELAY_OUT", "BRIDGE_RELAY_PRE",
                       "BRIDGE_RELAY_POST", "BRIDGE_RELAY_FWD")
NAT_JUMPS = (("OUTPUT", OUT), ("PREROUTING", PRE), ("POSTROUTING", POST))


@dataclass(frozen=True)
class Route:
    src: str
    relay: str
    rport: int          # 0 when the row goes through the WireGuard tunnel
    dst: str
    dport: int
    tag: str

    @property
    def via_wg(self) -> bool:
        return self.rport == 0


@dataclass(frozen=True)
class Tunnel:
    src: str
    relay: str
    net: str            # 10.77.N.0/30: relay .1, source .2
    port: int           # UDP port the relay listens on

    @property
    def iface(self) -> str:
        return f"brwg{ipaddress.ip_network(self.net).network_address.packed[2]}"

    @property
    def relay_ip(self) -> str:
        return str(ipaddress.ip_network(self.net).network_address + 1)

    @property
    def src_ip(self) -> str:
        return str(ipaddress.ip_network(self.net).network_address + 2)


def parse_table(text: str) -> tuple[list[Route], list[Tunnel]]:
    routes: list[Route] = []
    tunnels: list[Tunnel] = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if parts[0] == "tunnel":
            if len(parts) != 5:
                raise ValueError(f"line {n}: need tunnel src relay net port: {raw!r}")
            _, src, relay, net, port = parts
            for ip in (src, relay):
                ipaddress.IPv4Address(ip)
            if ipaddress.ip_network(net).prefixlen != 30:
                raise ValueError(f"line {n}: tunnel net must be a /30: {raw!r}")
            tunnels.append(Tunnel(src, relay, net, int(port)))
            continue
        if len(parts) < 6:
            raise ValueError(f"line {n}: need src relay rport dst dport tag: {raw!r}")
        src, relay, rport, dst, dport = parts[:5]
        for ip in (src, relay, dst):
            ipaddress.IPv4Address(ip)
        r = Route(src, relay, 0 if rport == "wg" else int(rport), dst, int(dport),
                  " ".join(parts[5:]))
        if not ((r.via_wg or 0 < r.rport < 65536) and 0 < r.dport < 65536):
            raise ValueError(f"line {n}: port out of range: {raw!r}")
        routes.append(r)

    seen: dict[tuple[str, int], Route] = {}
    for r in routes:
        if r.via_wg:
            continue
        clash = seen.get((r.relay, r.rport))
        if clash:
            raise ValueError(f"relay port {r.relay}:{r.rport} used twice: "
                             f"{clash.tag!r} and {r.tag!r}")
        seen[(r.relay, r.rport)] = r
    pairs = {(t.src, t.relay) for t in tunnels}
    for r in routes:
        if r.via_wg and (r.src, r.relay) not in pairs:
            raise ValueError(f"row {r.tag!r} goes via wg but there is no tunnel "
                             f"{r.src} -> {r.relay}")
    for attr in ("iface", "net"):
        values = [getattr(t, attr) for t in tunnels]
        if len(values) != len(set(values)):
            raise ValueError(f"two tunnels share a {attr}")
    listen = [(t.relay, t.port) for t in tunnels]
    if len(listen) != len(set(listen)):
        raise ValueError("two tunnels listen on the same relay port")
    return routes, tunnels


def parse_routes(text: str) -> list[Route]:
    return parse_table(text)[0]


def machines(routes: list[Route], tunnels: list[Tunnel] = ()) -> set[str]:
    """Everything that needs rules: sources and relays, never the far ends."""
    return ({r.src for r in routes} | {r.relay for r in routes}
            | {t.src for t in tunnels} | {t.relay for t in tunnels})


def tunnel_of(tunnels: list[Tunnel], r: Route) -> Tunnel:
    return next(t for t in tunnels if (t.src, t.relay) == (r.src, r.relay))


def _c(tag: str) -> str:
    return f'-m comment --comment "{COMMENT} {tag}"'


def ruleset(routes: list[Route], self_ip: str, tunnels: list[Tunnel] = ()) -> str:
    """The iptables-restore payload for one machine (chains are flushed first)."""
    out, pre, post, fwd = [], [], [], []
    back: list[str] = []
    for r in routes:
        if r.via_wg:
            # the source only routes (see wg_routes); the relay lets it out
            if r.relay == self_ip:
                t = tunnel_of(tunnels, r)
                post.append(f"-A {POST} -s {t.src_ip}/32 -d {r.dst}/32 -p tcp -m tcp "
                            f"--dport {r.dport} {_c(r.tag)} -j MASQUERADE")
                fwd.append(f"-A {FWD} -s {t.src_ip}/32 -d {r.dst}/32 -i {t.iface} -p tcp "
                           f"-m tcp --dport {r.dport} {_c(r.tag)} -j ACCEPT")
                if t.src_ip not in back:
                    back.append(t.src_ip)
            continue
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


def is_relay(routes: list[Route], self_ip: str, tunnels: list[Tunnel] = ()) -> bool:
    return (any(r.relay == self_ip for r in routes)
            or any(t.relay == self_ip for t in tunnels))


# ── WireGuard ────────────────────────────────────────────────────────

def parse_peers(text: str) -> dict[str, str]:
    """``ip pubkey`` per line -- written by the installer from each machine's key."""
    out = {}
    for line in text.splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


def wg_config(t: Tunnel, self_ip: str, peers: dict[str, str], private_key: str) -> str:
    """``wg syncconf`` text for this machine's end of the tunnel."""
    other = t.src if self_ip == t.relay else t.relay
    if other not in peers:
        raise ValueError(f"no public key for {other} in the peers file -- run the installer")
    if self_ip == t.relay:
        return (f"[Interface]\nPrivateKey = {private_key}\nListenPort = {t.port}\n\n"
                f"[Peer]\nPublicKey = {peers[t.src]}\nAllowedIPs = {t.src_ip}/32\n")
    return (f"[Interface]\nPrivateKey = {private_key}\n\n"
            f"[Peer]\nPublicKey = {peers[t.relay]}\nAllowedIPs = 0.0.0.0/0\n"
            f"Endpoint = {t.relay}:{t.port}\nPersistentKeepalive = 25\n")


def wg_routes(routes: list[Route], tunnels: list[Tunnel], self_ip: str) -> dict[str, set[str]]:
    """iface -> destinations this source sends into it."""
    out: dict[str, set[str]] = {t.iface: set() for t in tunnels if t.src == self_ip}
    for r in routes:
        if r.via_wg and r.src == self_ip:
            out[tunnel_of(tunnels, r).iface].add(r.dst)
    return out


def run(*cmd: str, check: bool = True, inp: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=check, input=inp)


def wg_key() -> str:
    if not os.path.exists(WG_KEY):
        os.makedirs(os.path.dirname(WG_KEY), mode=0o700, exist_ok=True)
        key = run("wg", "genkey").stdout.strip()
        fd = os.open(WG_KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key + "\n")
    with open(WG_KEY) as f:
        return f.read().strip()


def existing_tunnels() -> list[str]:
    links = run("ip", "-o", "link", "show", "type", "wireguard", check=False).stdout
    return [m.group(1) for m in re.finditer(r"^\d+: (brwg\d+)[:@]", links, re.M)]


def wg_apply(routes: list[Route], tunnels: list[Tunnel], self_ip: str,
             peers: dict[str, str]) -> str:
    mine = [t for t in tunnels if self_ip in (t.src, t.relay)]
    wanted = {t.iface for t in mine}
    for iface in existing_tunnels():
        if iface not in wanted:
            run("ip", "link", "del", iface, check=False)
    if not mine:
        return "tunnels=0"
    key = wg_key()
    dests = wg_routes(routes, tunnels, self_ip)
    for t in mine:
        if run("ip", "link", "show", t.iface, check=False).returncode != 0:
            run("ip", "link", "add", t.iface, "type", "wireguard")
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write(wg_config(t, self_ip, peers, key))
        try:
            os.chmod(f.name, 0o600)
            run("wg", "syncconf", t.iface, f.name)
        finally:
            os.unlink(f.name)
        mine_ip = t.relay_ip if self_ip == t.relay else t.src_ip
        run("ip", "addr", "replace", f"{mine_ip}/30", "dev", t.iface)
        run("ip", "link", "set", t.iface, "mtu", str(WG_MTU), "up")
        if t.src == self_ip:
            want = dests.get(t.iface, set())
            have = set()
            for line in run("ip", "-4", "route", "show", "dev", t.iface).stdout.splitlines():
                first = line.split()[0]
                if "/" not in first or first.endswith("/32"):
                    have.add(first.split("/")[0])
            for dst in sorted(want):
                run("ip", "route", "replace", f"{dst}/32", "dev", t.iface)
            for dst in sorted(have - want):
                run("ip", "route", "del", f"{dst}/32", "dev", t.iface, check=False)
    routed = sum(len(v) for v in dests.values())
    return f"tunnels={len(mine)} wg_routes={routed}"


# ── iptables ─────────────────────────────────────────────────────────

def ipt(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run("iptables", *args, check=check)


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


def up(routes: list[Route], self_ip: str, tunnels: list[Tunnel] = (),
       peers: dict[str, str] | None = None) -> str:
    # interfaces first: FWD rules name them, and routes need them
    wg_state = wg_apply(routes, tunnels, self_ip, peers or {})
    payload = ruleset(routes, self_ip, tunnels)
    run("iptables-restore", "-n", inp=payload)
    for parent, chain in NAT_JUMPS:
        ensure_jump("nat", parent, chain)
    ensure_jump("filter", forward_hook(), FWD)
    if is_relay(routes, self_ip, tunnels):
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write("1\n")
    legacy = drop_legacy()
    counts = {c: sum(1 for ln in payload.splitlines() if ln.startswith(f"-A {c} "))
              for c in (OUT, PRE, POST, FWD)}
    return (f"STATE up self={self_ip} out={counts[OUT]} pre={counts[PRE]} "
            f"post={counts[POST]} fwd={counts[FWD]} {wg_state} legacy_removed={legacy}")


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
    for iface in existing_tunnels():
        run("ip", "link", "del", iface, check=False)
    return f"STATE down legacy_removed={drop_legacy()}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=("plan", "up", "down", "wg-key"))
    ap.add_argument("self_ip", nargs="?", default="")
    ap.add_argument("--routes", default=DEFAULT_ROUTES)
    ap.add_argument("--peers", default=DEFAULT_PEERS)
    args = ap.parse_args(argv)
    if args.action == "down":
        print(down())
        return 0
    if args.action == "wg-key":
        print(run("wg", "pubkey", inp=wg_key() + "\n").stdout.strip())
        return 0
    if not args.self_ip:
        ap.error("self_ip is required for plan/up")
    with open(args.routes, encoding="utf-8") as f:
        routes, tunnels = parse_table(f.read())
    if args.self_ip not in machines(routes, tunnels):
        print(f"{args.self_ip} has no rows in {args.routes}", file=sys.stderr)
    if args.action == "plan":
        sys.stdout.write(ruleset(routes, args.self_ip, tunnels))
        for iface, dsts in wg_routes(routes, tunnels, args.self_ip).items():
            print(f"# route via {iface}: {' '.join(sorted(dsts))}")
        return 0
    if os.geteuid() != 0:
        print("up needs root", file=sys.stderr)
        return 2
    peers = {}
    if tunnels and os.path.exists(args.peers):
        with open(args.peers, encoding="utf-8") as f:
            peers = parse_peers(f.read())
    print(up(routes, args.self_ip, tunnels, peers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
