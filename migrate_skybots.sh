#!/usr/bin/env bash
set -euo pipefail

# --- CONFIG ---
MARZNODE_DIR="${MARZNODE_DIR:-/opt/marznode}"
FORK_REPO="${FORK_REPO:-https://github.com/skybots-tg/marznode}"
LOG_FILE="${LOG_FILE:-/var/log/marznode-migrate.log}"

# --- helpers ---
ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_FILE"; }
die() { log "ERROR: $*"; exit 1; }

# Timestamp for backups
TS="$(date +%F_%H%M%S)"

# Detect docker compose
detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
  elif docker-compose version >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  else
    die "docker compose not found"
  fi
}

main() {
  log "[Step 1/8] Stopping and removing old marznode containers with volumes..."
  
  cd "$MARZNODE_DIR" || die "Cannot cd to $MARZNODE_DIR"
  detect_compose
  
  # Stop and remove containers with volumes
  if [ -f "compose.yml" ] || [ -f "docker-compose.yml" ]; then
    $COMPOSE -f compose.yml down -v --remove-orphans 2>/dev/null || \
    $COMPOSE -f docker-compose.yml down -v --remove-orphans 2>/dev/null || true
    log "✓ Old containers stopped and removed"
  else
    log "! No compose file found, skipping container removal"
  fi
  
  log "[Step 2/8] Removing old marznode docker image..."
  
  # Remove old image
  if docker image rm -f dawsh/marznode:latest 2>/dev/null; then
    log "✓ Old image removed: dawsh/marznode:latest"
  else
    log "! Old image not found or already removed"
  fi
  
  log "[Step 3/8] Creating backup of old installation..."
  
  # Backup old code
  cd /opt || die "Cannot cd to /opt"
  if [ -d "$MARZNODE_DIR" ]; then
    mv "$MARZNODE_DIR" "/opt/marznode_old_$TS"
    log "✓ Backup created: /opt/marznode_old_$TS"
  else
    die "Marznode directory not found: $MARZNODE_DIR"
  fi
  
  log "[Step 4/8] Cloning skybots-tg/marznode fork..."
  
  # Clone new repository
  if git clone "$FORK_REPO" "$MARZNODE_DIR" 2>&1 | tee -a "$LOG_FILE"; then
    log "✓ Repository cloned successfully"
  else
    log "✗ Failed to clone repository"
    log "Restoring backup..."
    mv "/opt/marznode_old_$TS" "$MARZNODE_DIR"
    die "Clone failed, backup restored"
  fi
  
  log "[Step 5/8] Building docker image from source..."
  
  # Build local image
  cd "$MARZNODE_DIR" || die "Cannot cd to $MARZNODE_DIR"
  if docker build -t skybots-tg/marznode:fork . 2>&1 | tee -a "$LOG_FILE"; then
    log "✓ Docker image built successfully"
  else
    die "Failed to build docker image"
  fi
  
  log "[Step 6/8] Updating compose.yml with new image..."
  
  # Update compose file
  if [ -f "compose.yml" ]; then
    cp -a compose.yml "compose.yml.bak_$TS"
    sed -i 's#dawsh/marznode:latest#skybots-tg/marznode:fork#g' compose.yml
    log "✓ compose.yml updated (backup: compose.yml.bak_$TS)"
  else
    die "compose.yml not found!"
  fi
  
  log "[Step 7/8] Starting marznode with new configuration..."
  
  # Start services
  if $COMPOSE -f compose.yml up -d --force-recreate 2>&1 | tee -a "$LOG_FILE"; then
    log "✓ Services started successfully"
  else
    die "Failed to start services"
  fi
  
  log "[Step 8/8] Verifying deployment..."
  
  # Verification
  log "Running containers:"
  docker ps --filter name=marznode --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" 2>&1 | tee -a "$LOG_FILE"
  
  log ""
  log "Recent logs (last 20 lines):"
  $COMPOSE -f compose.yml logs --tail=20 --no-color 2>&1 | tee -a "$LOG_FILE"
  
  log ""
  log "=========================================="
  log "  MIGRATION COMPLETED SUCCESSFULLY!"
  log "=========================================="
  log "Old installation backup: /opt/marznode_old_$TS"
}

main "$@"
