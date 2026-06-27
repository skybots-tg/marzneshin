#!/usr/bin/env bash
KEY=~/.ssh/vpn_node_default
ip=45.150.239.178
ssh -o ConnectTimeout=8 -o BatchMode=yes -i "$KEY" "root@$ip" '
  c=$(docker ps --format "{{.Names}}" | grep -i marz | head -1)
  echo "container: $c"
  echo "--- x25519 ---"
  docker exec "$c" xray x25519 2>&1 | head -4
  echo "--- exit reach ---"
  for hp in 45.61.135.86:444 23.152.200.52:46443; do
    ip2=${hp%:*}; p=${hp#*:}
    if timeout 5 bash -c "echo > /dev/tcp/$ip2/$p" 2>/dev/null; then echo "$hp UP"; else echo "$hp DOWN"; fi
  done
'
