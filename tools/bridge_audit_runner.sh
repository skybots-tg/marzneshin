#!/usr/bin/env bash
# Host-side driver for the bridge audit.
#
# The panel API runs in a container without SSH keys or docker access, so it
# cannot probe anything itself. Instead it drops a request file into the shared
# /var/lib/marzneshin mount and this script — run every minute by a systemd
# timer — picks it up. The same timer performs the scheduled nightly audit, so
# dead bridges get hidden even if nobody opens the dashboard.
#
# install: tools/bridge_audit_install.sh
set -uo pipefail

TOOLS=/opt/marzneshin/tools
DATA=/var/lib/marzneshin
REQUEST="$DATA/bridge_audit.request"
LOG="$DATA/bridge_audit.log"
REPORT="$DATA/bridge_audit.json"
LOCK="$DATA/bridge_audit.lock"
# Auto-apply on the nightly run: a bridge that no RU vantage can reach is
# already broken for users, so leaving it in subscriptions helps nobody.
NIGHTLY_INTERVAL=${NIGHTLY_INTERVAL:-86400}
NIGHTLY_APPLY=${NIGHTLY_APPLY:-1}

exec 9>"$LOCK"
flock -n 9 || exit 0   # a scan is already running

run_scan() {
    local apply_flag="$1" reason="$2"
    cd "$TOOLS" || exit 1
    {
        echo "=== bridge audit ($reason) started $(date -Is) ==="
        # shellcheck disable=SC2086
        python3 -u bridge_audit.py scan --vantages 4 --jobs 6 $apply_flag
        echo "=== finished $(date -Is) rc=$? ==="
    } >"$LOG" 2>&1
}

if [ -f "$REQUEST" ]; then
    apply=""
    grep -q '"apply": *true' "$REQUEST" && apply="--apply"
    rm -f "$REQUEST"
    run_scan "$apply" "requested from panel"
    exit 0
fi

now=$(date +%s)
last=0
[ -f "$REPORT" ] && last=$(stat -c %Y "$REPORT" 2>/dev/null || echo 0)
if [ $((now - last)) -ge "$NIGHTLY_INTERVAL" ]; then
    apply=""
    [ "$NIGHTLY_APPLY" = "1" ] && apply="--apply"
    run_scan "$apply" "scheduled"
fi
