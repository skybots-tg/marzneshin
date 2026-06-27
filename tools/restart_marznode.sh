#!/usr/bin/env bash
# Run ON the panel. Restarts marznode on each given node to force a fresh
# user re-sync (so users get provisioned onto newly-linked inbounds).
KEY=~/.ssh/vpn_node_default
for ip in "$@"; do
  echo "=== restart marznode @ $ip ==="
  ssh -o ConnectTimeout=10 -o BatchMode=yes -i "$KEY" "root@$ip" '
    c=$(docker ps --format "{{.Names}}" | grep -i marz | head -1)
    docker restart "$c" >/dev/null && echo "restarted $c"
  '
done
