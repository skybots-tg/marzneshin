#!/usr/bin/env bash
for ip in 89.191.225.218 84.252.101.98 5.35.125.174 185.219.41.121 193.233.246.18 193.233.246.41 158.160.212.139 84.201.177.241 51.250.82.209 51.250.92.21; do
  echo "########## $ip ##########"
  bash /root/deploy_node.sh "$ip" 2>&1 | grep -E "Deploying|TEST_OK|TEST_FAILED|backup|-- restart|marznode.* Up|FATAL|Exited"
done
echo "ALL_DONE"
