#!/usr/bin/env bash
KEY=~/.ssh/vpn_node_default
for ip in "$@"; do
  echo "== $ip =="
  ssh -o ConnectTimeout=8 -o BatchMode=yes -i "$KEY" "root@$ip" \
    'docker logs --since 5m marznode-marznode-1 2>&1 | grep -iE "repopulat|sync|users|error|inbound" | tail -5'
done
