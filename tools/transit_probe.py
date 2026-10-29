#!/usr/bin/env python3
"""Leg probe that runs ON A NODE (or the panel) for bridge_transit.py.

Copied to the machine and fed a job on stdin; prints one JSON object on
stdout. Stdlib only, like bridge_runner.py: nodes have nothing but python3.

What it answers: can this machine open fresh TLS sessions to a set of
``dst:dport`` -- the way it does now, and the way it would without
bridge_relay. A leg Russia cuts by IP lets TCP through and then loses the
ServerHello, so a bare connect is not enough and a TLS handshake is: Reality
answers an unauthenticated hello with its front's certificate, marznode's gRPC
with its own, and either way bytes have to come back.

"Without bridge_relay" works because every BRIDGE_RELAY_OUT chain starts with
a RETURN for source ports 61900-61999 (below the ephemeral range, so nothing
else ever uses them); binding there skips the DNAT and measures the direct
path even while the leg is relayed.

stdin:  {"legs": [{"dst", "dport", "sni"}], "from_config": bool,
         "relayed": [[dst, dport]], "n": 8, "timeout": 5, "workers": 8,
         "tcp": [[ip, port]], "listen_range": [lo, hi]}
stdout: {"legs": [{"dst", "dport", "sni", "tag", "direct": k,
                   "eff": k or null, "n": n}],
         "tcp": {"ip:port": k}, "listening": [port, ...]}

``from_config`` adds every proxy outbound of this node's xray config to the
legs; ``relayed`` names the legs DNAT currently sends elsewhere, which are the
only ones where the effective path differs from the direct one.
"""
import errno
import ipaddress
import json
import random
import socket
import ssl
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

XRAY_CONFIG = "/var/lib/marznode/xray_config.json"
BYPASS_PORTS = (61900, 61999)
PROXY_PROTOCOLS = {"vless", "vmess", "trojan", "shadowsocks"}

_bypass_lock = threading.Lock()
_bypass_next = [random.randint(*BYPASS_PORTS)]


def _bypass_port() -> int:
    # Round-robin through the range: a port in TIME_WAIT towards the same
    # dst:dport cannot be reused for a while, and consecutive tries hit it.
    with _bypass_lock:
        port = _bypass_next[0]
        _bypass_next[0] = (BYPASS_PORTS[0] if port >= BYPASS_PORTS[1]
                           else port + 1)
        return port


def _connect(dst: str, dport: int, timeout: float, bypass: bool) -> socket.socket:
    last = None
    for _ in range(8 if bypass else 1):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            if bypass:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", _bypass_port()))
            s.connect((dst, dport))
            return s
        except OSError as exc:
            s.close()
            # a bypass port still in TIME_WAIT towards this very dst says
            # nothing about the path: take the next one
            if bypass and exc.errno in (errno.EADDRINUSE, errno.EADDRNOTAVAIL):
                last = exc
                continue
            raise
    raise last or OSError("no bypass port free")


def tls_once(dst: str, dport: int, sni: str, timeout: float, bypass: bool) -> bool:
    """One fresh TLS handshake. True when the server answered at all."""
    try:
        raw = _connect(dst, dport, timeout, bypass)
    except OSError:
        return False
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with ctx.wrap_socket(raw, server_hostname=sni or None,
                             do_handshake_on_connect=False) as s:
            s.do_handshake()
        return True
    except (ssl.SSLEOFError, ssl.SSLZeroReturnError):
        return False
    except ssl.SSLError:
        # An alert (no client certificate, protocol version) is the server
        # talking back: the path carries data both ways.
        return True
    except OSError:
        # timeout, reset -- the shape of a leg cut after the TCP handshake
        return False
    finally:
        try:
            raw.close()
        except OSError:
            pass


def tcp_once(ip: str, port: int, timeout: float) -> bool:
    # Bypassed too: a relay the source reaches only through another relay
    # cannot be one -- DNAT happens once, on the original destination.
    try:
        _connect(ip, port, timeout, True).close()
        return True
    except OSError:
        return False


def config_legs() -> list:
    try:
        with open(XRAY_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return []
    legs = []
    for o in cfg.get("outbounds") or []:
        if o.get("protocol") not in PROXY_PROTOCOLS:
            continue
        settings = o.get("settings") or {}
        server = (settings.get("vnext") or settings.get("servers") or [{}])[0]
        dst, dport = server.get("address"), server.get("port")
        try:
            if not ipaddress.IPv4Address(dst).is_global:
                continue
            dport = int(dport)
        except (ValueError, TypeError):
            continue    # a domain name: DNAT cannot follow it anyway
        stream = o.get("streamSettings") or {}
        sni = ((stream.get("realitySettings") or {}).get("serverName")
               or (stream.get("tlsSettings") or {}).get("serverName") or "")
        legs.append({"dst": dst, "dport": dport, "sni": sni,
                     "tag": o.get("tag") or ""})
    return legs


def listening(lo: int, hi: int) -> list:
    try:
        out = subprocess.run(["ss", "-Htln"], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ports = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and ":" in parts[3]:
            try:
                port = int(parts[3].rsplit(":", 1)[1])
            except ValueError:
                continue
            if lo <= port <= hi:
                ports.add(port)
    return sorted(ports)


def main() -> int:
    job = json.loads(sys.stdin.read() or "{}")
    n = int(job.get("n") or 8)
    timeout = float(job.get("timeout") or 5)
    workers = int(job.get("workers") or 8)
    relayed = {(d, int(p)) for d, p in job.get("relayed") or []}

    legs, seen = [], set()
    for leg in (job.get("legs") or []) + (config_legs() if job.get("from_config") else []):
        key = (leg["dst"], int(leg["dport"]))
        if key in seen:
            continue
        seen.add(key)
        legs.append(dict(leg, dport=int(leg["dport"])))

    def measure(leg):
        direct = sum(tls_once(leg["dst"], leg["dport"], leg.get("sni", ""),
                              timeout, True) for _ in range(n))
        eff = None
        if (leg["dst"], leg["dport"]) in relayed:
            eff = sum(tls_once(leg["dst"], leg["dport"], leg.get("sni", ""),
                               timeout, False) for _ in range(n))
        return dict(leg, direct=direct, eff=eff, n=n)

    def measure_tcp(target):
        ip, port = target
        return f"{ip}:{port}", sum(tcp_once(ip, int(port), timeout) for _ in range(3))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(measure, legs))
        tcp = dict(pool.map(measure_tcp, job.get("tcp") or []))
    lo_hi = job.get("listen_range")
    print(json.dumps({"legs": results, "tcp": tcp,
                      "listening": listening(*lo_hi) if lo_hi else []}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
