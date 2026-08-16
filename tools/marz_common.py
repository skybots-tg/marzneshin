#!/usr/bin/env python3
"""Shared helpers for Marzneshin node/bridge automation.

Runs ON THE PANEL (195.54.170.162): it SSHes to nodes with the panel's node key
and talks to the dockerised MariaDB. Both setup_universal_node.py and
add_exit_country.py build on this module.

Architecture recap (multihop):
  * Every "entry" node (UNIVERSAL RU servers + ELITE Yandex servers) carries a
    set of reality inbounds: "RU Direct" and "RU->XX Bridge" listeners. Each
    bridge inbound is routed to an outbound "xx-out" which is a vless+reality
    CLIENT connecting to the exit node's own reality listener.
  * Every "exit" node carries ONE reality listener inbound that serves both
    FAST users (direct connection) and the bridge outbounds (multihop).
  * The outbounds are identical across all entry nodes (same exit target + key).
  * The DB `inbounds` table mirrors the node inbounds (used by the panel to
    provision users and build subscription links); the DB `hosts` table holds
    one user-visible entry per (inbound, branding).
"""
import json
import os
import re
import secrets
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from _secrets import DB_ROOT_PW
except ImportError as _e:  # pragma: no cover - operator must provide _secrets.py
    raise SystemExit(
        "Missing _secrets.py at repo root. Create it with DB_ROOT_PW=... "
        "(it is gitignored on purpose)."
    ) from _e

KEY = "/root/.ssh/vpn_node_default"
DB = ["docker", "exec", "-i", "marzneshin-db-1", "mariadb",
      "-u", "root", f"-p{DB_ROOT_PW}", "marzneshin"]

# Masking used by exit listeners (mirror of the France exit nodes).
EXIT_SERVERNAMES = [
    "apple.com", "www.apple.com", "microsoft.com", "www.microsoft.com",
    "dl.google.com", "api-maps.yandex.ru", "www.googletagmanager.com",
]
EXIT_DEST = "www.apple.com:443"
EXIT_OUT_SNI = "apple.com"          # serverName the bridge outbound presents
FAST_SNI = "www.googletagmanager.com"  # SNI used by the FAST host
SVC1 = 1                             # default service all hosts belong to

SHARED_USER_ID = "91040b97-0a20-6eac-dfb7-f4b4e56ecf42"  # vnext user across outs

# Flag emojis + decorative glyphs (match existing remarks exactly).
FLAGS = {
    "RU": "\U0001F1F7\U0001F1FA", "FI": "\U0001F1EB\U0001F1EE",
    "EE": "\U0001F1EA\U0001F1EA", "FR": "\U0001F1EB\U0001F1F7",
    "TR": "\U0001F1F9\U0001F1F7", "US": "\U0001F1FA\U0001F1F8",
    "PL": "\U0001F1F5\U0001F1F1", "NL": "\U0001F1F3\U0001F1F1",
    "DE": "\U0001F1E9\U0001F1EA", "RO": "\U0001F1F7\U0001F1F4",
    "GB": "\U0001F1EC\U0001F1E7",
}
SAT = "\U0001F6DC"      # 🛜  universal glyph
INF = "\u267E\uFE0F"    # ♾️
BARS = "\U0001F4F6"     # 📶  elite glyph
BOLT = "\u26A1\uFE0F"   # ⚡️ fast glyph


def ssh(ip, cmd, inp=None, timeout=90):
    return subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
         "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
         "-i", KEY, f"root@{ip}", cmd],
        input=inp, capture_output=True, text=True, timeout=timeout)


def db(sql, timeout=60):
    return subprocess.run(DB, input=sql, capture_output=True, text=True,
                          timeout=timeout)


def db_query(sql, timeout=60):
    """Run a query in batch (tab-separated, no box) and return list of rows."""
    cmd = DB + ["-N", "-B", "-e", sql]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"db_query failed: {r.stderr[:400]}")
    rows = [ln.split("\t") for ln in r.stdout.splitlines() if ln.strip()]
    return rows


def node_traffic(hours=6) -> dict[int, int]:
    """node_id -> bytes the node moved over the last `hours`.

    Independent evidence, and the only kind that comes from users rather than
    from a probe. ``node_usages`` holds hourly deltas written by the panel's own
    collector, so a node that is genuinely carrying traffic cannot look dead
    here no matter what a vantage thinks of it -- and a node sitting at a flat
    zero for hours is dead no matter how healthy its port looks.

    Note ``uplink`` is always 0 in this deployment; ``downlink`` carries the
    volume. Summing both keeps the helper honest if that ever changes.
    """
    rows = db_query(
        "SELECT node_id, COALESCE(SUM(uplink + downlink), 0) FROM node_usages "
        f"WHERE created_at > NOW() - INTERVAL {int(hours)} HOUR "
        "GROUP BY node_id;"
    )
    out = {}
    for row in rows:
        if len(row) < 2 or row[0] in ("NULL", ""):
            continue
        try:
            out[int(row[0])] = int(row[1])
        except ValueError:
            continue
    return out


def node_cfg(ip):
    r = ssh(ip, "cat /var/lib/marznode/xray_config.json")
    try:
        return json.loads(r.stdout)
    except Exception as e:
        raise RuntimeError(f"cannot read xray config from {ip}: {e}; "
                           f"stderr={r.stderr[:200]}")


def routing_map(cfg):
    m = {}
    for r in cfg.get("routing", {}).get("rules", []):
        for it in r.get("inboundTag", []):
            m[it] = r.get("outboundTag")
    return m


def find(seq, tag):
    return next((x for x in seq if x.get("tag") == tag), None)


def rand_sid():
    return secrets.token_hex(8)  # 16 hex chars


def gen_keys(ip, n):
    """Generate n x25519 keypairs inside the marznode container on `ip`."""
    cmd = ('c=$(docker ps --format "{{.Names}}" | grep -i marz | head -1); '
           f'for i in $(seq 1 {n}); do docker exec "$c" xray x25519; '
           'echo "==="; done')
    r = ssh(ip, cmd)
    pairs, priv, pub = [], None, None
    # xray x25519 output varies by version:
    #   PrivateKey: ..  / Password (PublicKey): ..        (old)
    #   PrivateKey: ..  / Password: ..  / Hash32: ..       (newer)
    #   Private key: .. / Public key: ..                   (variant)
    priv_re = re.compile(r'^Private\s*[Kk]ey:\s*(\S+)')
    pub_re = re.compile(
        r'^(?:Password \(PublicKey\)|Password|Public\s*[Kk]ey|PublicKey):\s*(\S+)')
    for line in r.stdout.splitlines():
        line = line.strip()
        m1 = priv_re.match(line)
        m2 = pub_re.match(line)
        if m1:
            priv = m1.group(1)
        elif m2 and pub is None:
            pub = m2.group(1)
        elif line == "===":
            if priv and pub:
                pairs.append((priv, pub))
            priv = pub = None
    if len(pairs) != n:
        raise RuntimeError(f"keygen on {ip}: wanted {n}, got {len(pairs)}\n"
                           f"{r.stdout[:300]}\n{r.stderr[:300]}")
    return pairs


def pubkeys(ip, privs):
    """Map each x25519 private key to its public key, using the node's xray."""
    uniq = [p for p in dict.fromkeys(privs) if p]
    if not uniq:
        return {}
    lines = "\n".join(f'echo "KEY {p}"; docker exec "$c" xray x25519 -i {p}'
                      for p in uniq)
    cmd = ('c=$(docker ps --format "{{.Names}}" | grep -i marz | head -1)\n'
           + lines)
    r = ssh(ip, cmd)
    pub_re = re.compile(
        r'^(?:Password \(PublicKey\)|Password|Public\s*[Kk]ey|PublicKey):\s*(\S+)')
    out, cur = {}, None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("KEY "):
            cur = line[4:]
        elif cur:
            m = pub_re.match(line)
            if m:
                out[cur] = m.group(1)
                cur = None
    return out


_DEPLOY = r'''
set -u
c=$(docker ps --format '{{.Names}}' | grep -i marz | head -1)
[ -n "$c" ] || { echo FATAL_NO_CONTAINER; exit 1; }
cat > /tmp/xray_new.json
docker cp /tmp/xray_new.json "$c:/tmp/xray_new.json" >/dev/null
# locate xray asset dir (geoip.dat/geosite.dat) so -test can resolve geoip:* rules
ASSET=$(docker exec "$c" sh -lc 'd=$(dirname $(find / -name geoip.dat 2>/dev/null | head -1)); echo ${d:-/usr/local/lib/xray}')
if docker exec -e XRAY_LOCATION_ASSET="$ASSET" "$c" xray run -test -c /tmp/xray_new.json >/tmp/t.log 2>&1 \
   || docker exec -e XRAY_LOCATION_ASSET="$ASSET" "$c" xray -test -config /tmp/xray_new.json >/tmp/t.log 2>&1; then
  echo TEST_OK
else
  echo TEST_FAILED; tail -8 /tmp/t.log; exit 2
fi
TS=$(date +%Y%m%d-%H%M%S)
cp -a /var/lib/marznode/xray_config.json /var/lib/marznode/xray_config.json.bak-$TS
echo "backup: xray_config.json.bak-$TS"
cp -f /tmp/xray_new.json /var/lib/marznode/xray_config.json
docker restart "$c" >/dev/null && echo RESTARTED
sleep 6
docker ps --filter "name=$c" --format '{{.Names}} {{.Status}}'
'''


def deploy(ip, new_cfg):
    """Validate (xray -test), backup, atomically swap and restart marznode.
    Returns (ok: bool, output: str)."""
    out = ssh(ip, _DEPLOY, inp=json.dumps(new_cfg, ensure_ascii=False, indent=2),
              timeout=120)
    ok = "TEST_OK" in out.stdout and "RESTARTED" in out.stdout
    return ok, out.stdout + ("\n" + out.stderr if out.stderr else "")


def sqlstr(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


def bridge_outbound(out_tag, exit_ip, exit_port, exit_pub, exit_sid,
                    sni=EXIT_OUT_SNI):
    """Build the vless+reality client outbound that reaches an exit listener."""
    return {
        "tag": out_tag,
        "protocol": "vless",
        "settings": {"vnext": [{
            "address": exit_ip, "port": exit_port,
            "users": [{"id": SHARED_USER_ID, "flow": "xtls-rprx-vision",
                       "encryption": "none"}]}]},
        "streamSettings": {"network": "tcp", "security": "reality",
                           "realitySettings": {
                               "serverName": sni, "publicKey": exit_pub,
                               "shortId": exit_sid, "fingerprint": "chrome",
                               "show": False}},
    }


def exit_listener_inbound(tag, port, priv, sid):
    """Build an exit-side reality listener (serves FAST + bridge traffic)."""
    return {
        "tag": tag, "port": port, "protocol": "vless",
        "settings": {"clients": [], "decryption": "none",
                     "fallbacks": [{"dest": EXIT_DEST, "xver": 1}]},
        "streamSettings": {"network": "tcp", "security": "reality",
                           "realitySettings": {
                               "show": False, "dest": EXIT_DEST, "xver": 0,
                               "serverNames": list(EXIT_SERVERNAMES),
                               "privateKey": priv, "shortIds": [sid]}},
        "sniffing": {"enabled": True, "destOverride": ["http", "tls"],
                     "routeOnly": True},
    }


def db_inbound_config(tag, port, network, pbk, sid, flow="xtls-rprx-vision",
                      sni=("api-maps.yandex.ru",)):
    """JSON stored in inbounds.config (used by panel for link generation)."""
    return {
        "tag": tag, "protocol": "vless", "port": port, "network": network,
        "tls": "reality", "sni": list(sni), "host": [], "path": None,
        "header_type": None, "flow": (flow if network == "tcp" else None),
        "is_fallback": False, "fp": "chrome", "pbk": pbk, "sid": sid,
    }


def insert_inbound_sql(node_id, tag, cfg_json):
    c = sqlstr(json.dumps(cfg_json, ensure_ascii=False))
    return (f"INSERT INTO inbounds (protocol, tag, config, node_id) "
            f"SELECT 'VLESS', {sqlstr(tag)}, {c}, {node_id} "
            f"WHERE NOT EXISTS (SELECT 1 FROM (SELECT * FROM inbounds) x "
            f"WHERE x.node_id={node_id} AND x.tag={sqlstr(tag)});")


def link_service_sql(node_id, tag, service_id=SVC1):
    return (f"INSERT IGNORE INTO inbounds_services (inbound_id, service_id) "
            f"SELECT id, {service_id} FROM inbounds "
            f"WHERE node_id={node_id} AND tag={sqlstr(tag)};")


def insert_host_sql(node_id, tag, remark, address, weight, sni="api-maps.yandex.ru",
                    fingerprint="chrome", port="NULL"):
    """Create a host bound to (node_id, tag) inbound, idempotent per-inbound.

    Idempotency is by inbound (one host per inbound on this node) rather than by
    remark, because the same remark can legitimately exist on another node
    (e.g. a decommissioned/disabled predecessor)."""
    return (
        "INSERT INTO hosts (remark, address, port, sni, security, fingerprint, "
        "inbound_id, is_disabled, weight, universal, mlkem_enabled) "
        f"SELECT {sqlstr(remark)}, {sqlstr(address)}, {port}, {sqlstr(sni)}, "
        f"'inbound_default', {sqlstr(fingerprint)}, i.id, 0, {weight}, 0, 0 "
        f"FROM inbounds i WHERE i.node_id={node_id} AND i.tag={sqlstr(tag)} "
        f"AND NOT EXISTS (SELECT 1 FROM (SELECT * FROM hosts) h "
        f"WHERE h.inbound_id = i.id);")


def universal_remark(n, flag_code, label):
    return f"{FLAGS.get(flag_code, '')} {SAT} UNIVERSAL {n} {INF} {label}"


def elite_remark(n, flag_code, label):
    return f"{FLAGS.get(flag_code, '')}{BARS} ELITE {n} [GB] - {label} [ 4G ]"


def fast_remark(n, flag_code, label):
    return f"{FLAGS.get(flag_code, '')}{BOLT}FAST {n} {INF} - {label}"
