#!/bin/bash
set -e

ADGUARD_PORT="${1:-5353}"
ADGUARD_DIR="/opt/adguard-home"
ADGUARD_WEB_PORT="3033"

echo "[Step 1/5] Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "✗ Docker is not installed. Installing..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker installed successfully"
else
    echo "Docker found: $(docker --version)"
fi

echo "[Step 2/5] Creating AdGuard Home configuration directory..."
mkdir -p "${ADGUARD_DIR}/work" "${ADGUARD_DIR}/conf"

if [ ! -f "${ADGUARD_DIR}/conf/AdGuardHome.yaml" ]; then
    cat > "${ADGUARD_DIR}/conf/AdGuardHome.yaml" << YAMLEOF
http:
  pprof:
    port: 6060
    enabled: false
  address: 127.0.0.1:${ADGUARD_WEB_PORT}
  session_ttl: 720h
users: []
auth_attempts: 5
block_auth_min: 15
http_proxy: ""
language: ""
theme: auto
dns:
  bind_hosts:
    - 127.0.0.1
  port: ${ADGUARD_PORT}
  anonymize_client_ip: false
  ratelimit: 0
  ratelimit_subnet_len_ipv4: 24
  ratelimit_subnet_len_ipv6: 56
  ratelimit_whitelist: []
  refuse_any: true
  upstream_dns:
    - https://dns.cloudflare.com/dns-query
    - https://dns.google/dns-query
  upstream_dns_file: ""
  bootstrap_dns:
    - 1.1.1.1
    - 8.8.8.8
  fallback_dns: []
  upstream_mode: parallel
  fastest_timeout: 1s
  allowed_clients: []
  disallowed_clients: []
  blocked_hosts:
    - version.bind
    - id.server
    - hostname.bind
  trusted_proxies:
    - 127.0.0.0/8
    - ::1/128
  cache_size: 4194304
  cache_ttl_min: 0
  cache_ttl_max: 0
  cache_optimistic: true
  bogus_nxdomain: []
  aaaa_disabled: false
  enable_dnssec: true
  edns_client_subnet:
    custom_ip: ""
    enabled: false
    use_custom: false
  max_goroutines: 300
  handle_ddr: true
  ipset: []
  ipset_file: ""
  bootstrap_prefer_ipv6: false
  upstream_timeout: 10s
  private_networks: []
  use_private_ptr_resolvers: false
  local_ptr_upstreams: []
  use_dns64: false
  dns64_prefixes: []
  serve_http3: false
  use_http3_upstreams: false
  serve_plain_dns: true
  hostsfile_enabled: true
filtering:
  blocking_ipv4: ""
  blocking_ipv6: ""
  blocked_services:
    schedule:
      time_zone: UTC
    ids: []
  protection_disabled_until: null
  safe_search:
    enabled: false
    bing: true
    duckduckgo: true
    ecosia: true
    google: true
    pixabay: true
    yandex: true
    youtube: true
  blocking_mode: default
  parental_enabled: false
  safebrowsing_enabled: false
  rewrites: []
  safebrowsing_cache_size: 1048576
  safesearch_cache_size: 1048576
  parental_cache_size: 1048576
  cache_time: 30
  filters_update_interval: 24
  blocked_response_ttl: 10
  filtering_enabled: true
  filters:
    - enabled: true
      url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_1.txt
      name: AdGuard DNS filter
      id: 1
    - enabled: true
      url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_2.txt
      name: AdAway Default Blocklist
      id: 2
    - enabled: true
      url: https://big.oisd.nl
      name: OISD Big
      id: 3
    - enabled: true
      url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_27.txt
      name: OONI Probe list
      id: 4
  whitelist_filters: []
  user_rules: []
querylog:
  ignored: []
  interval: 24h
  size_memory: 1000
  enabled: true
  file_enabled: true
statistics:
  ignored: []
  interval: 24h
  enabled: true
log:
  file: ""
  max_backups: 0
  max_size: 100
  max_age: 3
  compress: false
  local_time: false
  verbose: false
os:
  group: ""
  user: ""
  rlimit_nofile: 0
schema_version: 29
YAMLEOF
    echo "Configuration created"
else
    echo "Configuration already exists, preserving"
fi

echo "[Step 3/5] Stopping existing AdGuard Home container (if any)..."
docker rm -f adguardhome 2>/dev/null || true
echo "Container cleanup done"

echo "[Step 4/5] Starting AdGuard Home container..."
docker run -d \
    --name adguardhome \
    --restart always \
    --network host \
    -v "${ADGUARD_DIR}/work:/opt/adguardhome/work" \
    -v "${ADGUARD_DIR}/conf:/opt/adguardhome/conf" \
    adguard/adguardhome:latest

echo "AdGuard Home container started"

echo "[Step 5/5] Verifying AdGuard Home is running..."
sleep 3
if docker ps --format '{{.Names}}' | grep -q adguardhome; then
    echo "AdGuard Home installed successfully"
    echo "DNS listening on 127.0.0.1:${ADGUARD_PORT}"
    echo "Web UI available at http://127.0.0.1:${ADGUARD_WEB_PORT}"
else
    echo "✗ AdGuard Home container failed to start"
    docker logs adguardhome 2>&1 | tail -20
    exit 1
fi
