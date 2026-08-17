#!/usr/bin/env bash
# Install the systemd timer that keeps the BitTorrent/P2P guard on every node.
# Run once, as root, on the panel host. Safe to re-run.
#
# The timer is what makes the guard survive events nobody watches: a node that
# was dead during the fleet-wide run (24, 33), a node whose config was rebuilt
# by hand, a node bought next month. `apply` is a no-op on a node that already
# carries the rules, so a daily run costs one SSH per node and restarts nothing.
set -euo pipefail

cat >/usr/local/bin/marz-p2p-guard <<'EOF'
#!/usr/bin/env bash
# Re-assert the P2P guard across the fleet. Log: /var/lib/marzneshin/p2p_guard.log
set -uo pipefail
cd /opt/marzneshin/tools || exit 1
{
    echo "=== p2p guard run $(date -Is) ==="
    python3 -u p2p_guard.py apply
    echo "=== finished $(date -Is) rc=$? ==="
} >>/var/lib/marzneshin/p2p_guard.log 2>&1
# Keep the log from growing without bound.
tail -n 2000 /var/lib/marzneshin/p2p_guard.log >/var/lib/marzneshin/p2p_guard.log.tmp \
    && mv /var/lib/marzneshin/p2p_guard.log.tmp /var/lib/marzneshin/p2p_guard.log
EOF
chmod 755 /usr/local/bin/marz-p2p-guard

cat >/etc/systemd/system/marz-p2p-guard.service <<'EOF'
[Unit]
Description=Re-assert BitTorrent/P2P blocking rules on every Marzneshin node
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/marz-p2p-guard
TimeoutStartSec=1800
EOF

cat >/etc/systemd/system/marz-p2p-guard.timer <<'EOF'
[Unit]
Description=Daily BitTorrent/P2P guard sweep

[Timer]
OnCalendar=*-*-* 05:20:00
# A node that came back after being down gets the rules on the next boot too.
OnBootSec=10min
Persistent=true
AccuracySec=5min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now marz-p2p-guard.timer
systemctl list-timers marz-p2p-guard.timer --no-pager | head -4
echo "installed: /usr/local/bin/marz-p2p-guard + marz-p2p-guard.timer"
