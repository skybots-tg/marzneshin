#!/usr/bin/env bash
# Run ON the panel. Shows which target bridge ports are listening on a node
# and the latest marznode logs. usage: verify_node_ports.sh <ip>
KEY=~/.ssh/vpn_node_default
ip="$1"
ssh -o ConnectTimeout=10 -o BatchMode=yes -i "$KEY" "root@$ip" '
  echo "=== listening target ports ==="
  ss -lntH 2>/dev/null | awk "{print \$4}" | grep -oE "[0-9]+\$" | sort -un \
    | grep -E "^(11443|12443|13443|14443|14444|15443|16443|16444|17443|18443|19443|55443)\$" \
    | tr "\n" " "; echo
  echo "=== marznode status ==="
  c=$(docker ps --format "{{.Names}}" | grep -i marz | head -1)
  docker ps --filter "name=$c" --format "{{.Names}} {{.Status}}"
  echo "=== recent xray errors (if any) ==="
  docker logs --since 3m "$c" 2>&1 | grep -iE "error|fail|panic|invalid" | tail -8 || echo "(none)"
'
