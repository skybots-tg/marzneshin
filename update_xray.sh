#!/usr/bin/env bash
set -e

# Update Xray-core to the latest version on a marznode
# This script downloads the latest Xray binary from GitHub releases,
# mounts it into the marznode Docker container via volume, and restarts the container.

XRAY_DIR="/var/lib/marznode/xray-core"
XRAY_BIN="$XRAY_DIR/xray"
GITHUB_API="https://api.github.com/repos/XTLS/Xray-core/releases/latest"

colorized_echo() {
    local color=$1
    local text=$2
    case $color in
        "red")    printf "\e[91m${text}\e[0m\n";;
        "green")  printf "\e[92m${text}\e[0m\n";;
        "yellow") printf "\e[93m${text}\e[0m\n";;
        "blue")   printf "\e[94m${text}\e[0m\n";;
        *)        echo "${text}";;
    esac
}

detect_arch() {
    local arch=$(uname -m)
    case "$arch" in
        x86_64|amd64)  echo "64" ;;
        aarch64|arm64) echo "arm64-v8a" ;;
        armv7l)        echo "arm32-v7a" ;;
        i686|i386)     echo "32" ;;
        s390x)         echo "s390x" ;;
        *)
            colorized_echo red "Unsupported architecture: $arch"
            exit 1
            ;;
    esac
}

get_current_xray_version() {
    if [ -f "$XRAY_BIN" ]; then
        "$XRAY_BIN" version 2>/dev/null | head -1 | awk '{print $2}' || echo "unknown"
    else
        # Try to get version from running container
        local container_name=$(docker ps --format '{{.Names}}' | grep -i marznode | head -1)
        if [ -n "$container_name" ]; then
            docker exec "$container_name" /usr/local/bin/xray version 2>/dev/null | head -1 | awk '{print $2}' || echo "unknown"
        else
            echo "not installed"
        fi
    fi
}

get_latest_xray_version() {
    curl -s "$GITHUB_API" | grep '"tag_name"' | sed -E 's/.*"tag_name": *"v?([^"]+)".*/\1/'
}

download_xray() {
    local version=$1
    local arch=$(detect_arch)
    local download_url="https://github.com/XTLS/Xray-core/releases/download/v${version}/Xray-linux-${arch}.zip"

    echo "[Step 1/4] Detecting system architecture..."
    colorized_echo blue "Architecture: $(uname -m) -> Xray arch: ${arch}"

    echo "[Step 2/4] Downloading Xray v${version}..."
    colorized_echo blue "URL: ${download_url}"

    mkdir -p "$XRAY_DIR"
    local tmp_zip="/tmp/xray-core.zip"

    if ! curl -sL "$download_url" -o "$tmp_zip"; then
        colorized_echo red "✗ Failed to download Xray"
        exit 1
    fi

    if ! file "$tmp_zip" | grep -q "Zip archive"; then
        colorized_echo red "✗ Downloaded file is not a valid zip archive"
        rm -f "$tmp_zip"
        exit 1
    fi
    colorized_echo green "✓ Downloaded successfully"

    echo "[Step 3/4] Extracting Xray binary..."
    # Extract only the xray binary and geoip/geosite files
    unzip -o "$tmp_zip" xray geoip.dat geosite.dat -d "$XRAY_DIR" 2>/dev/null || \
    unzip -o "$tmp_zip" xray -d "$XRAY_DIR"
    chmod +x "$XRAY_BIN"
    rm -f "$tmp_zip"
    colorized_echo green "✓ Extracted to ${XRAY_DIR}"

    # Verify the binary works
    if "$XRAY_BIN" version >/dev/null 2>&1; then
        local installed_version=$("$XRAY_BIN" version | head -1 | awk '{print $2}')
        colorized_echo green "✓ Xray v${installed_version} installed successfully"
    else
        colorized_echo red "✗ Xray binary verification failed"
        exit 1
    fi
}

update_compose_volumes() {
    echo "[Step 4/4] Updating docker-compose and restarting marznode..."

    # Find the compose file
    local compose_file=""
    for f in /opt/marznode/compose.yml /opt/marznode/docker-compose.yml /etc/opt/marzneshin/docker-compose.yml; do
        if [ -f "$f" ]; then
            compose_file="$f"
            break
        fi
    done

    if [ -z "$compose_file" ]; then
        colorized_echo yellow "! Could not find docker-compose file. Please manually add these volume mounts to your marznode service:"
        echo "    volumes:"
        echo "      - ${XRAY_BIN}:/usr/local/bin/xray"
        echo "      - ${XRAY_DIR}/geoip.dat:/usr/local/lib/xray/geoip.dat"
        echo "      - ${XRAY_DIR}/geosite.dat:/usr/local/lib/xray/geosite.dat"
        echo ""
        colorized_echo yellow "Then restart your marznode container."
        return 0
    fi

    colorized_echo blue "Found compose file: ${compose_file}"

    # Check if volume mount already exists
    if grep -q "${XRAY_DIR}/xray:/usr/local/bin/xray" "$compose_file" 2>/dev/null || \
       grep -q "${XRAY_BIN}:/usr/local/bin/xray" "$compose_file" 2>/dev/null; then
        colorized_echo blue "Volume mount already configured in compose file"
    else
        # Add xray binary volume mount to the marznode service
        # We use sed to add after the existing volumes line of marznode
        # This is a best-effort approach - complex compose files may need manual editing
        if grep -q "marznode" "$compose_file"; then
            # Try to add the volume mount after /var/lib/marznode line
            sed -i "/\/var\/lib\/marznode/a\\      - ${XRAY_BIN}:/usr/local/bin/xray" "$compose_file"
            colorized_echo green "✓ Added xray binary volume mount to compose file"

            # Also add geoip/geosite if they exist
            if [ -f "${XRAY_DIR}/geoip.dat" ]; then
                sed -i "/\/usr\/local\/bin\/xray/a\\      - ${XRAY_DIR}/geoip.dat:/usr/local/lib/xray/geoip.dat" "$compose_file"
                colorized_echo green "✓ Added geoip.dat volume mount"
            fi
            if [ -f "${XRAY_DIR}/geosite.dat" ]; then
                sed -i "/geoip.dat:\/usr\/local\/lib\/xray\/geoip.dat/a\\      - ${XRAY_DIR}/geosite.dat:/usr/local/lib/xray/geosite.dat" "$compose_file"
                colorized_echo green "✓ Added geosite.dat volume mount"
            fi
        else
            colorized_echo yellow "! Could not find marznode service in compose file"
            colorized_echo yellow "Please manually add the volume mount"
            return 0
        fi
    fi

    # Restart marznode container
    local compose_dir=$(dirname "$compose_file")
    cd "$compose_dir"

    if docker compose >/dev/null 2>&1; then
        COMPOSE="docker compose"
    elif docker-compose >/dev/null 2>&1; then
        COMPOSE="docker-compose"
    else
        colorized_echo red "docker compose not found"
        exit 1
    fi

    colorized_echo blue "Restarting marznode..."
    $COMPOSE -f "$compose_file" up -d marznode 2>/dev/null || \
    $COMPOSE -f "$compose_file" up -d 2>/dev/null || \
    docker restart $(docker ps --format '{{.Names}}' | grep -i marznode | head -1) 2>/dev/null

    colorized_echo green "✓ Marznode restarted"
}

main() {
    colorized_echo blue "=== Xray-core Update Tool ==="
    echo ""

    # Check for required tools
    for cmd in curl unzip; do
        if ! command -v $cmd >/dev/null 2>&1; then
            colorized_echo yellow "Installing $cmd..."
            apt-get update -qq && apt-get install -y -qq $cmd 2>/dev/null || \
            yum install -y $cmd 2>/dev/null || \
            dnf install -y $cmd 2>/dev/null || \
            pacman -S --noconfirm $cmd 2>/dev/null
        fi
    done

    local current_version=$(get_current_xray_version)
    colorized_echo blue "Current Xray version: ${current_version}"

    local latest_version=$(get_latest_xray_version)
    if [ -z "$latest_version" ]; then
        colorized_echo red "✗ Failed to fetch latest Xray version from GitHub"
        exit 1
    fi
    colorized_echo blue "Latest Xray version: ${latest_version}"

    if [ "$current_version" = "$latest_version" ]; then
        colorized_echo green "Xray is already up to date (v${current_version})"
        echo ""
        colorized_echo green "UPDATE COMPLETED - ALREADY UP TO DATE"
        exit 0
    fi

    echo ""
    download_xray "$latest_version"
    update_compose_volumes

    echo ""
    colorized_echo green "========================================="
    colorized_echo green "  XRAY UPDATE COMPLETED SUCCESSFULLY"
    colorized_echo green "  Version: v${current_version} -> v${latest_version}"
    colorized_echo green "========================================="
}

main "$@"
