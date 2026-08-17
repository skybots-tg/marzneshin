"""Keep BitTorrent/P2P blocking rules present in every node's Xray config.

Why this exists as its own module: a single `protocol: ["bittorrent"]` rule is
not enough, and we learned it from an abuse report. On node 37 (DataForest GE-2)
that rule was in place and live, yet the access log for 17.08.2026 showed, on
well-known BitTorrent ports, 12381 connections blocked and **12349 passed**
plus 3689 UDP — the sniffer only recognises the plaintext BitTorrent handshake,
so a client that retries with MSE encryption (and does DHT over UDP) walks
straight through. Hence three layers instead of one:

  1. protocol sniffing        — catches the plaintext handshake;
  2. well-known P2P ports     — catches clients on their default ports, no
                                matter how the payload is obfuscated;
  3. tracker / DHT bootstrap  — takes away peer discovery, so a client on a
     domains                    random port has nobody to talk to.

Random-port peers with encryption still get through layer 1 only ~50% of the
time; a port whitelist (`strict=True`) is the airtight version, and it is off by
default because it also kills games and anything else on a non-standard port.

Rules carry a `ruleTag` so re-applying is idempotent: we drop ours and re-insert
them at the front, leaving every hand-made rule alone. Stdlib only — the module
is imported both by the panel (app.utils.xray_config_patcher) and by the
host-side tool (tools/p2p_guard.py).
"""

import copy

RULE_TAG_PREFIX = "p2p-guard"

# Default listen ports of the common clients and public trackers. Deliberately
# narrow: these ranges carry nothing but P2P, so blocking them costs us nothing.
#   6881-6999  BitTorrent default range (6969 tracker announce included)
#   2710-2711  OpenBitTorrent / public tracker announce
#   1337       public tracker announce
#   6771       BitTorrent Local Service Discovery
#   51413-51415, 50413, 16881  Transmission / µTorrent defaults seen in our logs
#   4661-4672, 6346-6347       eDonkey/eMule, Gnutella
P2P_PORTS = (
    "1337,2710-2711,4661-4672,6346-6347,6771,6881-6999,"
    "16881,50413,51413-51415"
)

# Peer discovery. Without trackers and DHT bootstrap a client that dodged the
# port rule has no way to find peers. Distro/archive trackers are left out on
# purpose — they serve legal downloads and were never part of any abuse report.
P2P_DOMAINS = [
    # DHT bootstrap
    "domain:router.bittorrent.com",
    "domain:router.utorrent.com",
    "domain:dht.transmissionbt.com",
    "domain:dht.libtorrent.org",
    "domain:dht.aelitis.com",
    # public trackers
    "domain:opentrackr.org",
    "domain:openbittorrent.com",
    "domain:open.stealth.si",
    "domain:desync.com",
    "domain:torrent.eu.org",
    "domain:demonii.com",
    "domain:dler.org",
    "domain:explodie.org",
    "domain:internetwarriors.net",
    "domain:leechers-paradise.org",
    "domain:coppersurfer.tk",
]

# strict mode only: everything a normal client needs, nothing a peer can listen
# on. QUIC and DNS live here too, so the whitelist must not be narrowed further
# without checking DNS (5353 is the local AdGuard Home listener).
#
# Enforced as a block rule over the *complement* of these ranges, never as an
# allow rule: an allow rule would name an outbound, and on an entry node that
# would hijack bridge traffic (whose `inboundTag` rules sit further down) into
# the local `direct` outbound.
ALLOWED_TCP_PORTS = [
    (20, 25), (53, 53), (80, 80), (110, 110), (143, 143), (443, 443),
    (465, 465), (563, 563), (587, 587), (853, 853), (873, 873), (993, 993),
    (995, 995), (1935, 1935), (3128, 3128), (3389, 3389), (5222, 5228),
    (5353, 5353), (8080, 8080), (8443, 8443), (8880, 8880), (9418, 9418),
]
ALLOWED_UDP_PORTS = [
    (53, 53), (123, 123), (443, 443), (853, 853), (3478, 3497),
    (5353, 5353), (19302, 19309),
]

_SNIFFING = {
    "enabled": True,
    "destOverride": ["http", "tls", "quic"],
    "routeOnly": True,
}


def _tag(suffix):
    return "%s-%s" % (RULE_TAG_PREFIX, suffix)


def _complement(allowed):
    """Port ranges outside `allowed`, as an Xray `port` string."""
    out, cursor = [], 1
    for lo, hi in sorted(allowed):
        if lo > cursor:
            out.append((cursor, lo - 1))
        cursor = max(cursor, hi + 1)
    if cursor <= 65535:
        out.append((cursor, 65535))
    return ",".join(
        str(lo) if lo == hi else "%d-%d" % (lo, hi) for lo, hi in out
    )


def rules(strict=False):
    """The rule list we want at the head of routing.rules, in order."""
    out = [
        {
            "ruleTag": _tag("protocol"),
            "type": "field",
            "protocol": ["bittorrent"],
            "outboundTag": "block",
        },
        {
            "ruleTag": _tag("ports"),
            "type": "field",
            "network": "tcp,udp",
            "port": P2P_PORTS,
            "outboundTag": "block",
        },
        {
            "ruleTag": _tag("domains"),
            "type": "field",
            "domain": list(P2P_DOMAINS),
            "outboundTag": "block",
        },
    ]
    if strict:
        out += [
            {
                "ruleTag": _tag("strict-tcp"),
                "type": "field",
                "network": "tcp",
                "port": _complement(ALLOWED_TCP_PORTS),
                "outboundTag": "block",
            },
            {
                "ruleTag": _tag("strict-udp"),
                "type": "field",
                "network": "udp",
                "port": _complement(ALLOWED_UDP_PORTS),
                "outboundTag": "block",
            },
        ]
    return out


def _is_ours(rule):
    tag = rule.get("ruleTag", "")
    if tag.startswith(RULE_TAG_PREFIX):
        return True
    # The hand-written predecessor of the protocol rule: untagged, no other
    # fields. Dropped so we don't end up with it twice.
    return (
        rule.get("protocol") == ["bittorrent"]
        and rule.get("outboundTag") == "block"
        and not rule.get("inboundTag")
        and not rule.get("domain")
        and not rule.get("ip")
    )


def _ensure_block_outbound(outbounds):
    for ob in outbounds:
        if ob.get("tag") == "block":
            return outbounds
    return outbounds + [{"tag": "block", "protocol": "blackhole"}]


def _ensure_sniffing(inbounds):
    """Layer 1 needs sniffing on; leave inbounds that already have it alone."""
    changed = False
    for inbound in inbounds:
        if not inbound.get("sniffing", {}).get("enabled"):
            inbound["sniffing"] = copy.deepcopy(_SNIFFING)
            changed = True
    return changed


def audit(config, strict=False):
    """What is missing from `config`. Empty list means the guard is in place."""
    present = {
        r.get("ruleTag")
        for r in config.get("routing", {}).get("rules", [])
        if r.get("ruleTag", "").startswith(RULE_TAG_PREFIX)
    }
    missing = [
        r["ruleTag"] for r in rules(strict) if r["ruleTag"] not in present
    ]
    unsniffed = [
        ib.get("tag", "?")
        for ib in config.get("inbounds", [])
        if not ib.get("sniffing", {}).get("enabled")
    ]
    if unsniffed:
        missing.append("sniffing:" + ",".join(unsniffed))
    return missing


def ensure(config, strict=False):
    """Put the guard at the head of routing.rules. Returns True if changed."""
    before = copy.deepcopy(config)

    routing = config.setdefault("routing", {})
    kept = [r for r in routing.get("rules", []) if not _is_ours(r)]
    routing["rules"] = copy.deepcopy(rules(strict)) + kept

    config["outbounds"] = _ensure_block_outbound(config.get("outbounds", []))
    _ensure_sniffing(config.setdefault("inbounds", []))

    return config != before
