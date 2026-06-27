#!/usr/bin/env bash
# Run ON the panel server (vpn_norway).
# For each entry node IP, pull xray_config.json, list outbounds (tag -> dest:port),
# and test TCP reachability of each outbound dest from the entry node itself.
# This reveals whether the 2nd-hop bridge can actually reach its exit.
set -u
KEY=~/.ssh/vpn_node_default
SSH="ssh -o ConnectTimeout=8 -o BatchMode=yes -i $KEY"

# entry IPs: U1 U2 U3 U4 U5 U6 U7
for ip in 89.191.225.218 84.252.101.98 5.35.125.174 45.150.239.178 185.219.41.121 193.233.246.18 193.233.246.41; do
  echo "================ ENTRY $ip ================"
  $SSH "root@$ip" '
    cfg=/var/lib/marznode/xray_config.json
    if [ ! -s "$cfg" ]; then echo "  NO CONFIG"; exit 0; fi
    # inbound count + listening ports
    echo -n "  inbounds(ports): "; jq -r "[.inbounds[].port]|@csv" "$cfg" 2>/dev/null
    # outbounds with their dial dest (vless/vmess/shadowsocks/freedom)
    jq -r ".outbounds[] | [.tag, (.settings.vnext[0].address // .settings.servers[0].address // \"-\"), (.settings.vnext[0].port // .settings.servers[0].port // \"-\")] | @tsv" "$cfg" 2>/dev/null | while IFS=$(printf "\t") read -r tag addr port; do
      if [ "$addr" = "-" ] || [ -z "$addr" ]; then
        printf "  OUT %-22s direct/freedom\n" "$tag"
      else
        if timeout 4 bash -c "echo > /dev/tcp/$addr/$port" 2>/dev/null; then st=UP; else st=DOWN; fi
        printf "  OUT %-22s -> %s:%s  [%s]\n" "$tag" "$addr" "$port" "$st"
      fi
    done
  '
done
