#!/usr/bin/env bash
# Run ON the panel server (vpn_norway). Pulls /var/lib/marznode/xray_config.json
# from each given node IP into /root/uni_configs/<ip>.json using the panel's
# vpn_node_default key. Then prints a compact per-node summary.
set -u
KEY=~/.ssh/vpn_node_default
OUT=/root/uni_configs
mkdir -p "$OUT"

NODES="$*"
if [ -z "$NODES" ]; then
  echo "usage: $0 <ip> [ip...]" >&2
  exit 1
fi

for ip in $NODES; do
  dest="$OUT/$ip.json"
  if ssh -o ConnectTimeout=8 -o BatchMode=yes -i "$KEY" "root@$ip" \
        'cat /var/lib/marznode/xray_config.json' > "$dest" 2>/dev/null && [ -s "$dest" ]; then
    echo "OK   $ip -> $dest ($(wc -c < "$dest") bytes)"
  else
    echo "FAIL $ip"
  fi
done
