#!/bin/bash
# Marzneshin AI — TLS+Landing+gRPC provisioner.
#
# Installs Caddy as a single binary, writes a Caddyfile that
# (a) terminates TLS on 80/443 with Let's Encrypt HTTP-01,
# (b) serves the supplied landing site for plain HTTPS hits, and
# (c) reverse-proxies gRPC requests under a configurable path to a
#     unix domain socket where Xray (managed separately by marznode) is
#     expected to listen.
#
# Run as root. Idempotent: re-running with the same args re-applies
# the configuration and reloads Caddy without losing the existing cert.
#
# Output is parsed by the AI tool, so we use ### MARKER lines to
# delimit structured sections.
#
# Args (positional):
#   $1  domain         — public hostname (must already resolve to this IP)
#   $2  email          — contact email for Let's Encrypt
#   $3  uds_path       — absolute path of the unix socket Xray will listen on
#                        (the directory is created with mode 0755)
#   $4  grpc_service   — service name segment matched as `/<grpc_service>/*`
#   $5  landing_dir    — local directory where index.html was uploaded
set +e

DOMAIN="${1:?domain required}"
EMAIL="${2:?email required}"
UDS_PATH="${3:?uds_path required}"
GRPC_SVC="${4:?grpc_service required}"
LANDING_SRC="${5:?landing_dir required}"

CADDY_BIN=/usr/local/bin/caddy
CADDY_USER=caddy
CADDY_DATA=/var/lib/caddy
CADDY_CONF=/etc/caddy
CADDY_FILE="${CADDY_CONF}/Caddyfile"
SITE_ROOT=/var/www/landing
UNIT=/etc/systemd/system/caddy.service

emit() { printf '### %s\n' "$1"; }

emit start
echo "domain=${DOMAIN}"
echo "email=${EMAIL}"
echo "uds=${UDS_PATH}"
echo "grpc=${GRPC_SVC}"

if [ "$EUID" -ne 0 ]; then
  emit fatal
  echo "must run as root"
  emit end
  exit 2
fi

# -------- 1. detect arch / install caddy binary --------------------
emit step_install_caddy
ARCH_RAW=$(uname -m)
case "$ARCH_RAW" in
  x86_64|amd64) CADDY_ARCH=amd64 ;;
  aarch64|arm64) CADDY_ARCH=arm64 ;;
  armv7l) CADDY_ARCH=armv7 ;;
  *)
    emit fatal
    echo "unsupported architecture: ${ARCH_RAW}"
    emit end
    exit 3
  ;;
esac
echo "arch=${CADDY_ARCH}"

CADDY_VERSION="2.8.4"
if [ ! -x "$CADDY_BIN" ] || ! "$CADDY_BIN" version 2>/dev/null | grep -q "v${CADDY_VERSION}"; then
  TMP=$(mktemp -d)
  URL="https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${CADDY_ARCH}.tar.gz"
  echo "downloading ${URL}"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$URL" -o "${TMP}/caddy.tgz" || DL_RC=$?
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "${TMP}/caddy.tgz" "$URL" || DL_RC=$?
  else
    DL_RC=127
  fi
  if [ -n "$DL_RC" ] && [ "$DL_RC" -ne 0 ]; then
    emit fatal
    echo "download_failed rc=${DL_RC}"
    emit end
    exit 4
  fi
  tar -C "$TMP" -xzf "${TMP}/caddy.tgz" caddy
  install -m 0755 "${TMP}/caddy" "$CADDY_BIN"
  rm -rf "$TMP"
  echo "installed=${CADDY_BIN}"
else
  echo "already_present=$($CADDY_BIN version)"
fi

# -------- 2. user / dirs --------------------------------------------
emit step_dirs
id -u "$CADDY_USER" >/dev/null 2>&1 || useradd --system --home "$CADDY_DATA" --shell /usr/sbin/nologin "$CADDY_USER"
mkdir -p "$CADDY_CONF" "$CADDY_DATA" "$SITE_ROOT" "$(dirname "$UDS_PATH")"
# Caddy needs write access to its data dir for cert storage.
chown -R "${CADDY_USER}:${CADDY_USER}" "$CADDY_DATA"
chown -R "${CADDY_USER}:${CADDY_USER}" "$SITE_ROOT"
# UDS path will be created by Xray; we just make sure the directory
# is reachable by the caddy user.
chmod 0755 "$(dirname "$UDS_PATH")"
echo "ok"

# -------- 3. landing copy -------------------------------------------
emit step_landing
if [ ! -f "${LANDING_SRC}/index.html" ]; then
  emit fatal
  echo "landing_index_missing=${LANDING_SRC}/index.html"
  emit end
  exit 5
fi
install -m 0644 "${LANDING_SRC}/index.html" "${SITE_ROOT}/index.html"
chown "${CADDY_USER}:${CADDY_USER}" "${SITE_ROOT}/index.html"
echo "installed=${SITE_ROOT}/index.html"

# -------- 4. caddyfile ----------------------------------------------
emit step_caddyfile
cat > "$CADDY_FILE" <<CFEOF
{
    email ${EMAIL}
    admin off
}

${DOMAIN} {
    encode zstd gzip

    @grpc {
        path /${GRPC_SVC}/*
        protocol grpc
    }
    handle @grpc {
        reverse_proxy unix/${UDS_PATH} {
            transport http {
                versions h2c 2
            }
        }
    }

    handle {
        root * ${SITE_ROOT}
        try_files {path} /index.html
        file_server
    }

    log {
        output file /var/log/caddy/access.log {
            roll_size 10mb
            roll_keep 3
        }
        format console
        level WARN
    }
}
CFEOF
mkdir -p /var/log/caddy
chown -R "${CADDY_USER}:${CADDY_USER}" /var/log/caddy
"$CADDY_BIN" fmt --overwrite "$CADDY_FILE" >/dev/null 2>&1
if ! "$CADDY_BIN" validate --config "$CADDY_FILE" --adapter caddyfile 2>/tmp/caddy_validate.log; then
  emit fatal
  echo "caddyfile_invalid"
  cat /tmp/caddy_validate.log
  emit end
  exit 6
fi
echo "ok"

# -------- 5. systemd unit -------------------------------------------
emit step_systemd
cat > "$UNIT" <<UNITEOF
[Unit]
Description=Caddy
Documentation=https://caddyserver.com/docs/
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=${CADDY_USER}
Group=${CADDY_USER}
ExecStart=${CADDY_BIN} run --environ --config ${CADDY_FILE} --adapter caddyfile
ExecReload=${CADDY_BIN} reload --config ${CADDY_FILE} --adapter caddyfile --force
TimeoutStopSec=5s
LimitNOFILE=1048576
PrivateTmp=true
ProtectSystem=full
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
UNITEOF
systemctl daemon-reload
echo "ok"

# -------- 6. start / reload caddy -----------------------------------
emit step_start
ACTION=
if systemctl is-active --quiet caddy; then
  systemctl reload caddy
  ACTION=reloaded
else
  systemctl enable --now caddy
  ACTION=started
fi
echo "action=${ACTION}"
sleep 2
systemctl is-active --quiet caddy && STATE=active || STATE=inactive
echo "state=${STATE}"
if [ "$STATE" != "active" ]; then
  emit fatal
  echo "caddy_not_active"
  journalctl -u caddy --no-pager -n 30 2>/dev/null
  emit end
  exit 7
fi

# -------- 7. wait for cert -----------------------------------------
emit step_cert
# Caddy stores certs at /var/lib/caddy/.local/share/caddy/certificates/
CERT_DIR=$(find "$CADDY_DATA" -type d -name "${DOMAIN}" 2>/dev/null | head -n1)
DEADLINE=$(( $(date +%s) + 60 ))
while [ -z "$CERT_DIR" ] || [ ! -f "${CERT_DIR}/${DOMAIN}.crt" ]; do
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then break; fi
  sleep 3
  CERT_DIR=$(find "$CADDY_DATA" -type d -name "${DOMAIN}" 2>/dev/null | head -n1)
done

if [ -n "$CERT_DIR" ] && [ -f "${CERT_DIR}/${DOMAIN}.crt" ]; then
  echo "cert_path=${CERT_DIR}/${DOMAIN}.crt"
  if command -v openssl >/dev/null 2>&1; then
    NOT_BEFORE=$(openssl x509 -in "${CERT_DIR}/${DOMAIN}.crt" -noout -startdate 2>/dev/null | cut -d= -f2)
    NOT_AFTER=$(openssl x509 -in "${CERT_DIR}/${DOMAIN}.crt" -noout -enddate 2>/dev/null | cut -d= -f2)
    SUBJECT=$(openssl x509 -in "${CERT_DIR}/${DOMAIN}.crt" -noout -subject 2>/dev/null | sed 's/^subject= //')
    ISSUER=$(openssl x509 -in "${CERT_DIR}/${DOMAIN}.crt" -noout -issuer 2>/dev/null | sed 's/^issuer= //')
    echo "not_before=${NOT_BEFORE}"
    echo "not_after=${NOT_AFTER}"
    echo "subject=${SUBJECT}"
    echo "issuer=${ISSUER}"
  fi
  echo "status=ok"
else
  echo "status=pending"
  echo "hint=cert_not_yet_issued_check_logs_in_60s"
  journalctl -u caddy --no-pager -n 20 2>/dev/null | tail -n 20
fi

emit end
exit 0
