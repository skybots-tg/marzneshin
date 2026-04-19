#!/bin/bash
# Marzneshin AI — TLS+landing teardown.
#
# Stops + disables the caddy systemd unit, removes its binary and
# configuration, and wipes the landing site root and certificate
# storage. Left in place: the caddy system user (cheap, harmless), the
# /var/log/caddy directory (so admins can still grep what happened)
# and the unix socket directory used by Xray (managed elsewhere).
#
# Idempotent — running on a node that has nothing installed reports
# `nothing_to_do` and exits 0.
set +e

CADDY_BIN=/usr/local/bin/caddy
CADDY_DATA=/var/lib/caddy
CADDY_CONF=/etc/caddy
SITE_ROOT=/var/www/landing
UNIT=/etc/systemd/system/caddy.service

emit() { printf '### %s\n' "$1"; }

emit start
TOUCHED=0

emit step_stop
if systemctl list-unit-files 2>/dev/null | grep -q '^caddy.service'; then
  systemctl disable --now caddy 2>/tmp/caddy_stop.log
  echo "stopped"
  TOUCHED=1
else
  echo "not_present"
fi

emit step_files
if [ -f "$UNIT" ]; then rm -f "$UNIT"; TOUCHED=1; echo "removed_unit"; fi
if [ -d "$CADDY_CONF" ]; then rm -rf "$CADDY_CONF"; TOUCHED=1; echo "removed_conf"; fi
if [ -d "$CADDY_DATA" ]; then rm -rf "$CADDY_DATA"; TOUCHED=1; echo "removed_data"; fi
if [ -d "$SITE_ROOT" ]; then rm -rf "$SITE_ROOT"; TOUCHED=1; echo "removed_site"; fi
if [ -x "$CADDY_BIN" ]; then rm -f "$CADDY_BIN"; TOUCHED=1; echo "removed_bin"; fi

systemctl daemon-reload 2>/dev/null

emit summary
if [ "$TOUCHED" -eq 0 ]; then
  echo "nothing_to_do"
else
  echo "done"
fi

emit end
exit 0
