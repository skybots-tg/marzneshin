#!/usr/bin/env python3
"""Run ON the panel. Normalise Reality masking domain on entry nodes to the
proven-working domestic SNI (api-maps.yandex.ru), matching the only node that
delivers traffic under RU/Siberian DPI (U4 / 45.150.239.178).

For every reality inbound whose dest != api-maps.yandex.ru it rewrites:
    realitySettings.dest        -> "api-maps.yandex.ru:443"
    realitySettings.serverNames -> ["api-maps.yandex.ru", "ads.x5.ru"]
privateKey / shortIds / pbk are left untouched, so existing client keys stay valid.

Safe deploy: xray -test inside the marznode container -> timestamped backup ->
atomic swap -> restart -> show status. Dry-run unless --apply is given.

usage: fix_reality_sni.py [--apply] <ip> [ip...]
"""
import json
import subprocess
import sys

KEY = "/root/.ssh/vpn_node_default"
GOOD_HOST = "api-maps.yandex.ru"
GOOD_DEST = "api-maps.yandex.ru:443"
GOOD_SNI = ["api-maps.yandex.ru", "ads.x5.ru"]


def ssh(ip, cmd, inp=None, timeout=40):
    return subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", "-i", KEY,
         f"root@{ip}", cmd],
        input=inp, capture_output=True, text=True, timeout=timeout)


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    ips = [a for a in args if not a.startswith("--")]
    if not ips:
        print("usage: fix_reality_sni.py [--apply] <ip> [ip...]")
        sys.exit(1)

    for ip in ips:
        print("=" * 64)
        print(f"NODE {ip}   mode={'APPLY' if apply else 'DRY-RUN'}")
        r = ssh(ip, "cat /var/lib/marznode/xray_config.json")
        if r.returncode != 0 or not r.stdout.strip():
            print("  FETCH FAILED:", r.stderr.strip()[:200]); continue
        cfg = json.loads(r.stdout)

        changed = []
        for ib in cfg.get("inbounds", []):
            ss = ib.get("streamSettings", {}) or {}
            if ss.get("security") != "reality":
                continue
            rs = ss.get("realitySettings", {}) or {}
            dest = rs.get("dest", "")
            if dest.startswith(GOOD_HOST):
                continue
            changed.append(f"{ib.get('port')} {ib.get('tag')}: {dest} -> {GOOD_DEST}")
            rs["dest"] = GOOD_DEST
            rs["serverNames"] = list(GOOD_SNI)

        if not changed:
            print("  already normalised, nothing to do"); continue
        print(f"  {len(changed)} inbounds to change:")
        for c in changed:
            print("   ", c)

        if not apply:
            continue

        # reachability sanity: can the node TLS-connect to the new dest?
        chk = ssh(ip, f"timeout 6 bash -c 'echo > /dev/tcp/{GOOD_HOST}/443' && echo REACH_OK || echo REACH_FAIL")
        print("  dest reachability:", chk.stdout.strip())
        if "REACH_OK" not in chk.stdout:
            print("  ABORT: node cannot reach new dest, skipping"); continue

        new_json = json.dumps(cfg, ensure_ascii=False, indent=2)
        deploy = r'''
set -u
c=$(docker ps --format '{{.Names}}' | grep -i marz | head -1)
[ -n "$c" ] || { echo FATAL_NO_CONTAINER; exit 1; }
cat > /tmp/xray_new.json
docker cp /tmp/xray_new.json "$c:/tmp/xray_new.json" >/dev/null
if docker exec "$c" xray run -test -c /tmp/xray_new.json >/tmp/t.log 2>&1 \
   || docker exec "$c" xray -test -config /tmp/xray_new.json >/tmp/t.log 2>&1; then
  echo TEST_OK
else
  echo TEST_FAILED; tail -5 /tmp/t.log; exit 2
fi
TS=$(date +%Y%m%d-%H%M%S)
cp -a /var/lib/marznode/xray_config.json /var/lib/marznode/xray_config.json.bak-$TS
echo "backup: xray_config.json.bak-$TS"
cp -f /tmp/xray_new.json /var/lib/marznode/xray_config.json
docker restart "$c" >/dev/null && echo RESTARTED
sleep 6
docker ps --filter "name=$c" --format '{{.Names}} {{.Status}}'
docker logs --tail 6 "$c" 2>&1 | sed 's/^/  log: /'
'''
        out = ssh(ip, deploy, inp=new_json, timeout=90)
        print(out.stdout)
        if out.stderr.strip():
            print("  stderr:", out.stderr.strip()[:300])


if __name__ == "__main__":
    main()
