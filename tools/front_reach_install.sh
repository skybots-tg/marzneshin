#!/usr/bin/env bash
# Install the systemd timer that checks, every five minutes, that each node can
# still reach its own REALITY front. Run once, as root, on the panel host.
# Safe to re-run.
#
# What it buys: xray dials `dest` before it reads the client hello, so a front
# that bans the node's address takes every new connection down with it while
# the node stays "healthy". www.elisa.ee did that to EE-1 on 2026-10-01 in
# waves of 30-60 minutes; the daily front watch cannot see a wave. One ssh and
# one plain TCP connect per node per run, no TLS; the panel turns two bad runs
# in a row into a #FrontReach alert and reports when it ends.
set -euo pipefail

cat >/usr/local/bin/marz-front-reach <<'EOF'
#!/usr/bin/env bash
# Can every node reach its own dest? Log: /var/lib/marzneshin/front_reach.log
# Status the panel alerts from: /var/lib/marzneshin/front_reach.status
# Closed episodes: /var/lib/marzneshin/front_reach.episodes.jsonl
set -uo pipefail
cd /opt/marzneshin/tools || exit 1
exec 9>/var/lib/marzneshin/front_reach.lock
flock -n 9 || exit 0   # the previous run is still going
{
    printf '%s ' "$(date -Is)"
    python3 -u front_reach.py
} >>/var/lib/marzneshin/front_reach.log 2>&1
tail -n 4000 /var/lib/marzneshin/front_reach.log >/var/lib/marzneshin/front_reach.log.tmp \
    && mv /var/lib/marzneshin/front_reach.log.tmp /var/lib/marzneshin/front_reach.log
EOF
chmod 755 /usr/local/bin/marz-front-reach

cat >/etc/systemd/system/marz-front-reach.service <<'EOF'
[Unit]
Description=Check that every Marzneshin node can reach its REALITY front
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/marz-front-reach
# Four nodes at a time, 45 s ssh ceiling each: a run is normally under a
# minute, and a wedged one must not eat the next slot.
TimeoutStartSec=240
EOF

cat >/etc/systemd/system/marz-front-reach.timer <<'EOF'
[Unit]
Description=Every-five-minutes REALITY front reachability check

[Timer]
# Off the :00/:20 marks the daily front watch and P2P sweep start on; while
# either of them runs, a run skips itself (front_reach.py checks).
OnCalendar=*:02/5
OnBootSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now marz-front-reach.timer
systemctl list-timers marz-front-reach.timer --no-pager | head -4
echo "installed: /usr/local/bin/marz-front-reach + marz-front-reach.timer"
