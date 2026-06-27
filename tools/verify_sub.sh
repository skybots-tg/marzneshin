#!/usr/bin/env bash
# Run ON the panel. Fetches a user's subscription and prints the UNIVERSAL
# host remarks in order. usage: verify_sub.sh <username> <key>
u="$1"; k="$2"
curl -s -H 'User-Agent: v2rayN/6.0' "http://127.0.0.1:40215/sub/$u/$k" \
  | base64 -d 2>/dev/null \
  | tr '#' '\n' \
  | python3 -c '
import sys, urllib.parse
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    name=urllib.parse.unquote(line)
    if "UNIVERSAL" in name:
        print(name)
'
