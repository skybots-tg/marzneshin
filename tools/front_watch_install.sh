#!/usr/bin/env bash
# Install the systemd timer that checks every node's masking front.
# Run once, as root, on the panel host. Safe to re-run.
#
# What it buys: `dest` is somebody else's server, and when it stops speaking
# TLS 1.3 the node refuses every subscriber while still answering its port and
# reporting healthy. That happened to both French exits and cost three days and
# ~600 GB of traffic before anyone looked. One handshake per node, once a day,
# and the panel turns a failure into a #RealityFront alert within the hour.
set -euo pipefail

cat >/usr/local/bin/marz-front-watch <<'EOF'
#!/usr/bin/env bash
# Probe each node's own dest. Log: /var/lib/marzneshin/front_watch.log
# Status the panel alerts from: /var/lib/marzneshin/reality_fronts.status
set -uo pipefail
cd /opt/marzneshin/tools || exit 1
{
    echo "=== front watch run $(date -Is) ==="
    python3 -u front_watch.py
    echo "=== finished $(date -Is) rc=$? ==="
} >>/var/lib/marzneshin/front_watch.log 2>&1
tail -n 2000 /var/lib/marzneshin/front_watch.log >/var/lib/marzneshin/front_watch.log.tmp \
    && mv /var/lib/marzneshin/front_watch.log.tmp /var/lib/marzneshin/front_watch.log
EOF
chmod 755 /usr/local/bin/marz-front-watch

cat >/etc/systemd/system/marz-front-watch.service <<'EOF'
[Unit]
Description=Check that every Marzneshin node's REALITY front still works
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/marz-front-watch
# One ssh and a handful of openssl handshakes per node; a slow node must not
# take the sweep down with it.
TimeoutStartSec=1800
EOF

cat >/etc/systemd/system/marz-front-watch.timer <<'EOF'
[Unit]
Description=Daily REALITY front check

[Timer]
# An hour before the P2P sweep, so the two never share an ssh storm.
OnCalendar=*-*-* 04:20:00
OnBootSec=15min
Persistent=true
AccuracySec=5min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now marz-front-watch.timer
systemctl list-timers marz-front-watch.timer --no-pager | head -4
echo "installed: /usr/local/bin/marz-front-watch + marz-front-watch.timer"
