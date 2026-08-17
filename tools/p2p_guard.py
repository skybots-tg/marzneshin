#!/usr/bin/env python3
"""Fleet-wide BitTorrent/P2P guard: audit and repair every node's Xray routing.

Runs ON THE PANEL host (it needs the node SSH key, docker and the local API).

    python3 tools/p2p_guard.py scan                 # what is missing where
    python3 tools/p2p_guard.py apply                # fix every node
    python3 tools/p2p_guard.py apply --node 37      # one node
    python3 tools/p2p_guard.py apply --strict 27,37 # port whitelist on those two

Why not just SSH the file in: pushing through the panel API restarts *xray*
only, and marznode persists the config it receives, so users are re-synced by
the panel afterwards. The config is still validated with `xray -test` on the
node first, because marznode writes the file before it validates it.

The rules themselves live in app/utils/p2p_guard.py — the same module the panel
uses when it rewrites a node config, so there is one definition of "blocked".
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import marz_common as mc  # noqa: E402

# Imported by path, not as app.utils.p2p_guard: importing the package would drag
# in the whole FastAPI app, which is not installed on the host.
_GUARD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "utils", "p2p_guard.py",
)
_spec = importlib.util.spec_from_file_location("p2p_guard_rules", _GUARD_PATH)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

PANEL = os.environ.get("PANEL_API", "http://127.0.0.1:40215/api")
PANEL_CONTAINER = "marzneshin-marzneshin-1"
SUDO_ADMIN = os.environ.get("PANEL_ADMIN", "resist")

_TEST = r'''
set -u
c=$(docker ps --format '{{.Names}}' | grep -i marz | head -1)
[ -n "$c" ] || { echo FATAL_NO_CONTAINER; exit 1; }
cat > /tmp/xray_p2p_test.json
docker cp /tmp/xray_p2p_test.json "$c:/tmp/xray_p2p_test.json" >/dev/null
ASSET=$(docker exec "$c" sh -lc 'd=$(dirname $(find / -name geoip.dat 2>/dev/null | head -1)); echo ${d:-/usr/local/lib/xray}')
if docker exec -e XRAY_LOCATION_ASSET="$ASSET" "$c" xray run -test -c /tmp/xray_p2p_test.json >/tmp/p2p_test.log 2>&1 \
   || docker exec -e XRAY_LOCATION_ASSET="$ASSET" "$c" xray -test -config /tmp/xray_p2p_test.json >/tmp/p2p_test.log 2>&1; then
  echo TEST_OK
else
  echo TEST_FAILED; tail -8 /tmp/p2p_test.log
fi
'''


def nodes():
    """(id, name, ip, status) for every node the panel knows about."""
    rows = []
    for row in mc.db_query(
        "SELECT id, name, address, status FROM nodes ORDER BY id;"
    ):
        if len(row) == 4:
            rows.append((int(row[0]), row[1], row[2], row[3]))
    return rows


def token():
    r = subprocess.run(
        ["docker", "exec", PANEL_CONTAINER, "python", "-c",
         "from app.utils.auth import create_admin_token; "
         f"print(create_admin_token({SUDO_ADMIN!r}, True))"],
        capture_output=True, text=True, timeout=60,
    )
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    if not lines:
        raise SystemExit(f"cannot mint an admin token: {r.stderr[-300:]}")
    return lines[-1]


def api(method, path, tok, body=None):
    req = urllib.request.Request(
        PANEL + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + tok,
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read().decode()
    return json.loads(raw) if raw else None


def validate(ip, cfg):
    out = mc.ssh(ip, _TEST, inp=json.dumps(cfg, ensure_ascii=False, indent=2),
                 timeout=120)
    return "TEST_OK" in out.stdout, (out.stdout + out.stderr)[-400:]


def cmd_scan(args):
    strict_ids = parse_ids(args.strict)
    bad = 0
    for nid, name, ip, status in nodes():
        if args.node and nid not in args.node:
            continue
        try:
            cfg = mc.node_cfg(ip)
        except Exception as e:
            print(f"{nid:>3} {name[:34]:34s} unreachable: {str(e)[:60]}")
            continue
        missing = guard.audit(cfg, strict=nid in strict_ids)
        if missing:
            bad += 1
            print(f"{nid:>3} {name[:34]:34s} MISSING {', '.join(missing)}")
        else:
            print(f"{nid:>3} {name[:34]:34s} ok ({status})")
    print(f"\n{bad} node(s) need the guard applied")
    return 1 if bad else 0


def cmd_apply(args):
    strict_ids = parse_ids(args.strict)
    tok = None if args.dry_run else token()
    failed = []
    for nid, name, ip, status in nodes():
        if args.node and nid not in args.node:
            continue
        label = f"{nid:>3} {name[:34]:34s}"
        try:
            cfg = mc.node_cfg(ip)
        except Exception as e:
            print(f"{label} SKIP unreachable: {str(e)[:60]}")
            failed.append(nid)
            continue

        strict = nid in strict_ids
        if not guard.ensure(cfg, strict=strict):
            print(f"{label} already in place")
            continue
        if args.dry_run:
            print(f"{label} would apply{' (strict)' if strict else ''}")
            continue

        ok, log = validate(ip, cfg)
        if not ok:
            print(f"{label} FAILED xray -test: {log}")
            failed.append(nid)
            continue
        try:
            api("PUT", f"/nodes/{nid}/xray/config", tok,
                {"config": json.dumps(cfg, ensure_ascii=False, indent=2),
                 "format": 1})
        except urllib.error.HTTPError as e:
            print(f"{label} FAILED push: HTTP {e.code} {e.read()[:200]}")
            failed.append(nid)
            continue
        except Exception as e:
            print(f"{label} FAILED push: {str(e)[:120]}")
            failed.append(nid)
            continue

        left = guard.audit(mc.node_cfg(ip), strict=strict)
        if left:
            print(f"{label} pushed but still missing {', '.join(left)}")
            failed.append(nid)
        else:
            print(f"{label} applied{' (strict)' if strict else ''}")

    if failed:
        print("\nnodes needing attention: " + ", ".join(map(str, failed)))
        return 1
    print("\nall selected nodes carry the guard")
    return 0


def parse_ids(raw):
    return {int(x) for x in raw.split(",") if x.strip()} if raw else set()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--node", type=lambda s: [int(x) for x in s.split(",")],
                   help="limit to these node ids")
    p.add_argument("--strict", default=os.environ.get("P2P_STRICT_NODES", ""),
                   help="node ids that also get the port whitelist "
                        "(kills games and anything on a non-standard port)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    ap = sub.add_parser("apply")
    ap.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    return cmd_scan(args) if args.cmd == "scan" else cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
