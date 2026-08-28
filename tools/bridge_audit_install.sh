#!/usr/bin/env bash
# Install the systemd timer that drives the bridge audit. Run once, as root,
# on the panel host. Safe to re-run.
set -euo pipefail

install -m 755 /opt/marzneshin/tools/bridge_audit_runner.sh \
    /usr/local/bin/marz-bridge-audit

cat >/etc/systemd/system/marz-bridge-audit.service <<'EOF'
[Unit]
Description=Marzneshin bridge audit (scheduled + panel-requested)
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/marz-bridge-audit
# A full 4-vantage sweep measured 1695s over 229 hosts, and it grows with the
# number of broken legs: a failing probe pays for every geo endpoint in turn.
# The old 1800s ceiling was close enough that the sweep started being killed
# mid-run, which wedged the scheduler for three days. Leave real headroom.
TimeoutStartSec=3600
EOF

cat >/etc/systemd/system/marz-bridge-audit.timer <<'EOF'
[Unit]
Description=Poll for bridge audit requests and run the nightly sweep

[Timer]
OnBootSec=3min
OnUnitActiveSec=1min
AccuracySec=15s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now marz-bridge-audit.timer
systemctl status marz-bridge-audit.timer --no-pager | head -8
echo "installed: /usr/local/bin/marz-bridge-audit + marz-bridge-audit.timer"
