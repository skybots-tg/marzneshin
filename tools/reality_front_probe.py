#!/usr/bin/env python3
"""Run ON the panel. Vet candidate REALITY masking domains, per node.

Picking a masking domain by taste is how the fleet ended up with one front on
92 of 96 inbounds: whatever survived last time got normalised everywhere, and a
single blocklist entry then costs the whole catalogue. Rotation has to be
routine, so it needs a measurement rather than an opinion -- this is that
measurement.

Four things decide whether a domain can front a given node, and every one of
them is checked *from that node*, because latency and routing differ per host:

* the handshake must actually work over TLS 1.3 with an X25519 key share and
  negotiate ``h2``. REALITY steals the target's own handshake, so anything the
  target does not support, the disguise cannot fake;
* the certificate must cover the name we intend to send. This is the check the
  current fleet fails: a probe sending ``api-maps.yandex.ru`` to the Polish
  exit gets back ``CN=www.apple.com`` -- ``dest`` and ``serverNames`` disagree,
  and one exchange is enough to see it;
* the target should sit near the node -- same country at least, ideally the same
  AS. The cheapest detector in service today resolves the SNI and compares
  networks: a Russian domain claimed by a packet arriving at a Warsaw address
  is an anomaly no fingerprint work can hide;
* and it must be dull. A domain everybody uses as a front is a blocklist entry
  waiting to happen, which is the same trap as the monoculture, one level up.

Nothing here writes anything. It prints a ranked table (``--json`` for a
machine); applying a choice is fix_reality_sni.py's job, and it has to be
staged -- adding a name is safe, removing one rejects the handshakes of every
client that has not re-read its subscription yet.

usage:
    reality_front_probe.py --node 212.192.11.201
    reality_front_probe.py --all-exits --json
    reality_front_probe.py --node 1.2.3.4 --candidates www.a.fi,www.b.fi
"""
import argparse
import json
import re
import sys
import time

import marz_common as mc

# Candidates by the country the node *geolocates* to, which is not always the
# country it is labelled with: 86.107.179.232 is sold as RO and answers from
# Frankfurt. Deliberately unremarkable infrastructure and commerce -- never
# banks, government, health or anything political, whose traffic patterns draw
# attention of their own. These are starting points to be measured, not
# answers; add your own with --candidates.
CANDIDATES = {
    "FI": ["www.aalto.fi", "www.elisa.fi", "www.verkkokauppa.com"],
    "EE": ["www.ut.ee", "www.telia.ee", "www.rimi.ee"],
    "FR": ["www.sorbonne-universite.fr", "www.cdiscount.com", "www.free.fr"],
    "TR": ["www.boun.edu.tr", "www.turkcell.com.tr", "www.hepsiburada.com"],
    "US": ["www.wisc.edu", "www.newegg.com", "www.digitalocean.com"],
    "PL": ["www.uw.edu.pl", "www.allegro.pl", "www.orange.pl"],
    "NL": ["www.tudelft.nl", "www.bol.com", "www.kpn.com"],
    "DE": ["www.tum.de", "www.otto.de", "www.hetzner.com"],
    "RO": ["www.upb.ro", "www.emag.ro", "www.digi.ro"],
    # Входные ноды стоят в РФ, и российский SNI на российском адресе как раз
    # правдоподобен -- менять его тут надо не ради географии, а чтобы одна
    # запись в блок-листе не стоила всех девяноста двух инбаундов. Никакой
    # госуслуги и никаких банков: их трафик сам по себе под присмотром.
    "RU": ["www.ozon.ru", "dodopizza.ru", "www.mipt.ru"],
}

# What the fleet uses today, always measured alongside the candidates so the
# table shows whether a change is an improvement or a lateral move.
INCUMBENTS = ["api-maps.yandex.ru", "www.apple.com"]

GEO_URL = "http://ip-api.com/json/{}?fields=countryCode,as"
GEO_PAUSE = 1.4  # ip-api allows ~45/min; this stays well under it

# One ssh round trip per node: the loop runs there, one line per candidate.
REMOTE = r"""
for d in %s; do
  ip=$(getent hosts "$d" 2>/dev/null | awk '{print $1; exit}')
  [ -z "$ip" ] && { echo "RESULT|$d|-|-|-|-|-|resolve failed"; continue; }
  t0=$(date +%%s%%3N)
  out=$(echo | openssl s_client -connect "$d:443" -servername "$d" \
        -tls1_3 -alpn h2 2>/dev/null)
  t1=$(date +%%s%%3N)
  cipher=$(printf '%%s' "$out" | sed -n 's/^New, TLSv1.3, Cipher is \(.*\)$/\1/p' | head -1)
  group=$(printf '%%s' "$out" | sed -n 's/^Server Temp Key: \(.*\)$/\1/p' | head -1)
  alpn=$(printf '%%s' "$out" | sed -n 's/^ALPN protocol: \(.*\)$/\1/p' | head -1)
  names=$(printf '%%s' "$out" | openssl x509 -noout -subject -ext subjectAltName 2>/dev/null \
          | tr -d ' ' | tr '\n' ',')
  echo "RESULT|$d|$ip|$((t1-t0))|$cipher|$group|$alpn|$names"
done
"""


def geo(ip, cache):
    """Country and AS of an address, or (None, None) when the lookup fails."""
    if ip in cache:
        return cache[ip]
    try:
        import urllib.request
        with urllib.request.urlopen(GEO_URL.format(ip), timeout=8) as r:
            d = json.loads(r.read().decode())
        out = (d.get("countryCode"), d.get("as") or "")
    except Exception:
        out = (None, "")
    cache[ip] = out
    time.sleep(GEO_PAUSE)
    return out


def asn_of(as_field):
    m = re.match(r"AS(\d+)", as_field or "")
    return m.group(1) if m else None


def covers(domain, names):
    """Whether the presented certificate actually covers ``domain``.

    Wildcards are matched one label deep, which is what a browser does and
    therefore what a prober comparing SNI to certificate will do too.
    """
    low = (names or "").lower()
    if domain.lower() in low:
        return True
    parent = domain.split(".", 1)[1] if "." in domain else domain
    return f"*.{parent}".lower() in low


def probe_node(node_ip, candidates, cache):
    """Measure every candidate from ``node_ip``; returns rows, node geo."""
    node_cc, node_as = geo(node_ip, cache)
    cmd = REMOTE % " ".join(candidates)
    r = mc.ssh(node_ip, cmd, timeout=45 + 12 * len(candidates))
    rows = []
    for line in r.stdout.splitlines():
        if not line.startswith("RESULT|"):
            continue
        _, dom, ip, ms, cipher, group, alpn, names = (line.split("|") + [""] * 8)[:8]
        ok_tls = bool(cipher.strip())
        x25519 = "x25519" in group.lower()
        h2 = alpn.strip() == "h2"
        cc, as_field = geo(ip, cache) if ip not in ("-", "") else (None, "")
        same_cc = bool(cc and node_cc and cc == node_cc)
        same_as = bool(
            asn_of(as_field) and asn_of(node_as)
            and asn_of(as_field) == asn_of(node_as)
        )
        rows.append({
            "domain": dom, "ip": ip, "latency_ms": ms,
            "tls13": ok_tls, "x25519": x25519, "h2": h2,
            "cert_covers": covers(dom, names),
            "country": cc, "same_country": same_cc, "same_as": same_as,
            "usable": ok_tls and x25519 and h2 and covers(dom, names),
            "incumbent": dom in INCUMBENTS,
        })
    return rows, node_cc, node_as


def score(row):
    """Rank usable fronts: network proximity first, then latency."""
    if not row["usable"]:
        return (-1, 0)
    prox = 3 if row["same_as"] else (2 if row["same_country"] else 0)
    try:
        ms = int(row["latency_ms"])
    except ValueError:
        ms = 9999
    return (prox, -ms)


def render(node_ip, node_cc, node_as, rows):
    print(f"\n=== узел {node_ip}  ({node_cc or '?'}, {node_as or '?'})")
    print(f"{'домен':<30} {'TLS1.3':<7} {'X25519':<7} {'h2':<4} "
          f"{'cert':<5} {'гео':<4} {'сеть':<6} {'мс':>6}")
    for row in sorted(rows, key=score, reverse=True):
        mark = "*" if row["incumbent"] else " "
        prox = "AS" if row["same_as"] else ("страна" if row["same_country"] else "—")
        print(f"{mark}{row['domain']:<29} "
              f"{'да' if row['tls13'] else 'НЕТ':<7} "
              f"{'да' if row['x25519'] else 'НЕТ':<7} "
              f"{'да' if row['h2'] else 'НЕТ':<4} "
              f"{'да' if row['cert_covers'] else 'НЕТ':<5} "
              f"{row['country'] or '?':<4} {prox:<6} {row['latency_ms']:>6}")
    best = [r for r in rows if r["usable"] and not r["incumbent"]]
    best.sort(key=score, reverse=True)
    if best:
        b = best[0]
        where = "той же сети" if b["same_as"] else (
            "той же стране" if b["same_country"] else "другой стране")
        print(f"  → лучший кандидат: {b['domain']} ({where}, {b['latency_ms']} мс)")
    else:
        print("  → ни один кандидат не прошёл обязательные проверки")
    print("  (* — то, что стоит сейчас)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", action="append", default=[],
                    help="IP узла; можно повторять")
    ap.add_argument("--all-exits", action="store_true",
                    help="все выходные ноды из БД")
    ap.add_argument("--candidates",
                    help="свой список домен,домен вместо встроенного")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    nodes = list(args.node)
    if args.all_exits:
        nodes += [r[0] for r in mc.db_query(
            "SELECT DISTINCT address FROM nodes WHERE address IS NOT NULL;")
            if r[0] not in nodes]
    if not nodes:
        ap.error("нужен --node или --all-exits")

    cache, out = {}, {}
    for node_ip in nodes:
        node_cc, node_as = geo(node_ip, cache)
        cands = ([c.strip() for c in args.candidates.split(",")]
                 if args.candidates
                 else CANDIDATES.get(node_cc or "", []) + INCUMBENTS)
        if not cands:
            print(f"=== узел {node_ip}: нет кандидатов для страны "
                  f"{node_cc or '?'} — задайте --candidates", file=sys.stderr)
            continue
        rows, node_cc, node_as = probe_node(node_ip, cands, cache)
        out[node_ip] = {"country": node_cc, "as": node_as, "candidates": rows}
        if not args.json:
            render(node_ip, node_cc, node_as, rows)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
