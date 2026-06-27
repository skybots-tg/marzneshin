#!/usr/bin/env bash
for ip in 109.61.110.125 109.61.110.150; do
  echo "=== $ip ==="
  ping -c2 -W2 "$ip" >/dev/null 2>&1 && echo "  ping: OK" || echo "  ping: FAIL"
  for p in 22 443 44443 47443; do
    if timeout 4 bash -c "echo > /dev/tcp/$ip/$p" 2>/dev/null; then echo "  tcp/$p: UP"; else echo "  tcp/$p: DOWN"; fi
  done
done
