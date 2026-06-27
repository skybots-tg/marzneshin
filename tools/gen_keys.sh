#!/usr/bin/env bash
# Run ON the panel. Generates N reality private keys on a node via the
# marznode container's xray and prints them (one per line).
# usage: gen_keys.sh <ip> <count>
KEY=~/.ssh/vpn_node_default
ip="$1"; count="$2"
ssh -o ConnectTimeout=10 -o BatchMode=yes -i "$KEY" "root@$ip" "
  c=\$(docker ps --format '{{.Names}}' | grep -i marz | head -1)
  for i in \$(seq 1 $count); do
    docker exec \"\$c\" xray x25519 | awk -F': ' '/PrivateKey/{print \$2}'
  done
"
