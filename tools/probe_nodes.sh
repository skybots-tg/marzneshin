#!/usr/bin/env bash
# Run ON the panel. Probes target nodes for jq, xray, marznode container.
KEY=~/.ssh/vpn_node_default
for ip in "$@"; do
  echo "===== $ip ====="
  ssh -o ConnectTimeout=8 -o BatchMode=yes -i "$KEY" "root@$ip" '
    echo -n "jq: "; (command -v jq || echo MISSING)
    echo -n "host-xray: "; (ls -1 /var/lib/marznode/xray-core/xray 2>/dev/null || echo NONE)
    cname=$(docker ps --format "{{.Names}}" | grep -i marz | head -1)
    echo "marznode-container: ${cname:-NONE}"
    if [ -n "$cname" ]; then
      echo -n "container-xray: "; docker exec "$cname" sh -c "command -v xray || ls /usr/local/bin/xray 2>/dev/null || echo NONE" 2>/dev/null
    fi
    echo -n "config-bytes: "; wc -c < /var/lib/marznode/xray_config.json 2>/dev/null
  '
done
