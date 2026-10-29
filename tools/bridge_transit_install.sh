#!/usr/bin/env bash
# Install the systemd timer that keeps RU nodes' legs open on its own
# (tools/bridge_transit.py). Run once, as root, on the panel host. Safe to re-run.
#
# Every 30 minutes: every RU node and the panel measure their legs, a leg broken
# two runs running is sent through a relay that gets through, a leg whose own
# path held for three runs is given back. Moves land in bridge_transit.status,
# which the panel posts as #BridgeTransit. One run is 3-6 minutes.
set -euo pipefail

cat >/usr/local/bin/marz-bridge-transit <<'EOF'
#!/usr/bin/env bash
# Log: /var/lib/marzneshin/bridge_transit.log
# Status the panel alerts from: /var/lib/marzneshin/bridge_transit.status
# Automatic relay rows: /var/lib/marzneshin/bridge_relay.auto.routes
set -uo pipefail
cd /opt/marzneshin/tools || exit 1
{
    echo "=== bridge transit started $(date -Is) ==="
    python3 -u bridge_transit.py run --apply 2>&1 | grep -v '^  stuck'
    echo "=== finished $(date -Is) rc=${PIPESTATUS[0]} ==="
} >>/var/lib/marzneshin/bridge_transit.log 2>&1
tail -n 4000 /var/lib/marzneshin/bridge_transit.log >/var/lib/marzneshin/bridge_transit.log.tmp \
    && mv /var/lib/marzneshin/bridge_transit.log.tmp /var/lib/marzneshin/bridge_transit.log
EOF
chmod 755 /usr/local/bin/marz-bridge-transit

cat >/etc/systemd/system/marz-bridge-transit.service <<'EOF'
[Unit]
Description=Relay RU nodes' cut legs through RU machines that still get through
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/marz-bridge-transit
# A run is 3-6 minutes; a wedged one must not eat the next slot. The relay
# lock (bridge_relay.lock) keeps a hand run of the installer out meanwhile.
TimeoutStartSec=1500
EOF

cat >/etc/systemd/system/marz-bridge-transit.timer <<'EOF'
[Unit]
Description=Every-30-minutes RU leg survey and relay switch

[Timer]
OnCalendar=*:11/30
OnBootSec=10min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now marz-bridge-transit.timer
systemctl list-timers marz-bridge-transit.timer --no-pager | head -4
echo "installed: /usr/local/bin/marz-bridge-transit + marz-bridge-transit.timer"
