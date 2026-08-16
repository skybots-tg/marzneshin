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
QUICK_STAMP="$DATA/bridge_audit.quick"
LOCK="$DATA/bridge_audit.lock"

# Two cadences. The quick run probes one host per link and is what actually
# notices a leg going down; the full sweep probes everything and is what keeps
# the matrix, the gaps and the per-host detail honest.
QUICK_INTERVAL=${QUICK_INTERVAL:-900}
FULL_INTERVAL=${FULL_INTERVAL:-86400}
# Auto-apply on both: a link that fails twice running, from the vantage its own
# subscribers sit behind, is already broken for them. Leaving it in the
# subscription helps nobody. bridge_state.py is what keeps a single bad probe
# from acting.
AUTO_APPLY=${AUTO_APPLY:-1}
# RU vantages for the RU-entry tiers, the panel for FAST. Judging FAST from
# Moscow is how servers that were dead for everyone abroad stayed visible.
VANTAGES=${VANTAGES:-panel,25,30,40}

exec 9>"$LOCK"
flock -n 9 || exit 0   # a scan is already running

run_scan() {
    local report="$1" extra="$2" reason="$3"
    local apply=""
    [ "$AUTO_APPLY" = "1" ] && apply="--apply"
    cd "$TOOLS" || exit 1
    {
        echo "=== bridge audit ($reason) started $(date -Is) ==="
        # shellcheck disable=SC2086
        python3 -u bridge_audit.py --report "$report" scan \
            --tier all --vantage "$VANTAGES" --jobs 6 $extra $apply
        rc=$?
        echo "=== finished $(date -Is) rc=$rc ==="
    } >"$LOG" 2>&1
}

age_of() {
    [ -f "$1" ] || { echo 999999999; return; }
    echo $(( $(date +%s) - $(stat -c %Y "$1" 2>/dev/null || echo 0) ))
}

if [ -f "$REQUEST" ]; then
    # A panel-requested scan is someone looking at the page right now: give
    # them the full picture, and honour the apply box they ticked.
    grep -q '"apply": *true' "$REQUEST" || AUTO_APPLY=0
    rm -f "$REQUEST"
    run_scan "$REPORT" "" "requested from panel"
    exit 0
fi

if [ "$(age_of "$REPORT")" -ge "$FULL_INTERVAL" ]; then
    run_scan "$REPORT" "" "scheduled full sweep"
    touch "$QUICK_STAMP"
    exit 0
fi

if [ "$(age_of "$QUICK_STAMP")" -ge "$QUICK_INTERVAL" ]; then
    # A separate file: the page's report is meant to be the last *complete*
    # picture of the fleet, and a quick run only has an opinion about one host
    # per link. The panel reads this one alongside it.
    run_scan "$DATA/bridge_audit.quick.json" "--quick" "scheduled quick check"
    touch "$QUICK_STAMP"
fi
