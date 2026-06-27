#!/usr/bin/env bash
# Run ON the panel. Safely deploys a new xray_config.json to a node:
#   backup -> xray -test inside container -> atomic swap -> restart -> health.
# usage: deploy_node.sh <ip>
# Expects /root/uni_configs/<ip>.final.json to already exist on the panel.
set -u
KEY=~/.ssh/vpn_node_default
ip="$1"
SRC="/root/uni_configs/$ip.final.json"
[ -s "$SRC" ] || { echo "FATAL: $SRC missing/empty"; exit 1; }

echo "=== Deploying to $ip ==="
# push new config to node /tmp
scp -o ConnectTimeout=10 -o BatchMode=yes -i "$KEY" "$SRC" "root@$ip:/tmp/xray_new.json" >/dev/null || {
  echo "FATAL: scp to node failed"; exit 1; }

ssh -o ConnectTimeout=10 -o BatchMode=yes -i "$KEY" "root@$ip" '
set -u
LIVE=/var/lib/marznode/xray_config.json
NEW=/tmp/xray_new.json
TS=$(date +%Y%m%d-%H%M%S)
c=$(docker ps --format "{{.Names}}" | grep -i marz | head -1)
[ -n "$c" ] || { echo "FATAL: no marznode container"; exit 1; }

# basic JSON sanity inside container (xray validates structure)
docker cp "$NEW" "$c:/tmp/xray_new.json" >/dev/null
echo "-- xray -test --"
if docker exec "$c" xray run -test -c /tmp/xray_new.json >/tmp/xraytest.log 2>&1 \
   || docker exec "$c" xray -test -config /tmp/xray_new.json >/tmp/xraytest.log 2>&1; then
  tail -2 /tmp/xraytest.log
  echo "TEST_OK"
else
  echo "TEST_FAILED:"; cat /tmp/xraytest.log; exit 2
fi

cp -a "$LIVE" "/var/lib/marznode/xray_config.json.bak-$TS"
echo "backup: /var/lib/marznode/xray_config.json.bak-$TS"
cp -f "$NEW" "$LIVE"

echo "-- restart $c --"
cd "$(dirname "$(find /opt /etc/opt -maxdepth 4 -name docker-compose.yml -path "*marz*" 2>/dev/null | head -1)")" 2>/dev/null || true
docker restart "$c" >/dev/null
sleep 6
echo "-- container status --"
docker ps --filter "name=$c" --format "{{.Names}} {{.Status}}"
echo "-- last logs --"
docker logs --tail 12 "$c" 2>&1 | sed "s/^/  /"
'
