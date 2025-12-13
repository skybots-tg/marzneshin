#!/usr/bin/env bash
set -euo pipefail

# --- CONFIG ---
WORKDIR="${WORKDIR:-/opt/marznode}"
REMOTE_URL="${REMOTE_URL:-https://github.com/skybots-tg/marznode.git}"
LOCK_FILE="${LOCK_FILE:-/var/lock/marznode-update.lock}"
LOG_FILE="${LOG_FILE:-/var/log/marznode-update.log}"

# 0 = auto (main if exists else master), or set explicitly: BRANCH=main
BRANCH="${BRANCH:-auto}"

# --- helpers ---
ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_FILE" >&2; }
die() { log "ERROR: $*"; exit 1; }

need_root() {
  [[ "$(id -u)" -eq 0 ]] || die "Run as root"
}

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif docker-compose version >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    die "docker compose not found"
  fi
}

with_lock() {
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    die "Another update is running (lock: $LOCK_FILE)"
  fi
}

backup_files() {
  local bkdir="$WORKDIR/_backup/$(date +"%Y%m%d_%H%M%S")"
  mkdir -p "$bkdir"

  # back up likely customized files in WORKDIR
  for f in \
    compose.yml docker-compose.yml docker-compose.yaml \
    docker-compose.override.yml docker-compose.override.yaml \
    .env .env.local .env.production \
    *.override.yml *.override.yaml \
  ; do
    if compgen -G "$WORKDIR/$f" >/dev/null; then
      cp -a "$WORKDIR"/$f "$bkdir/" 2>/dev/null || true
    fi
  done

  log "Backup stored in: $bkdir"
}

ensure_workdir() {
  [[ -d "$WORKDIR" ]] || die "WORKDIR not found: $WORKDIR"
  cd "$WORKDIR"

  # sanity: must look like marznode compose dir
  if ! ls -1 . | grep -qiE 'compose\.yml|docker-compose\.yml'; then
    log "WARNING: compose file not found in $WORKDIR (still continuing)"
  fi
}

git_switch_and_update() {
  cd "$WORKDIR"
  [[ -d .git ]] || die "$WORKDIR is not a git repo (.git missing). If you installed from image-only, repo update won't work."

  log "Git: setting origin to $REMOTE_URL"
  git remote set-url origin "$REMOTE_URL"

  log "Git: fetching origin"
  git fetch --prune origin

  local target="$BRANCH"
  if [[ "$target" == "auto" ]]; then
    if git show-ref --verify --quiet refs/remotes/origin/main; then
      target="main"
    elif git show-ref --verify --quiet refs/remotes/origin/master; then
      target="master"
    else
      die "Cannot find origin/main or origin/master"
    fi
  fi

  log "Git: switching to $target"
  if git show-ref --verify --quiet "refs/heads/$target"; then
    git checkout -q "$target"
  else
    git checkout -q -B "$target" "origin/$target"
  fi

  # hard sync to origin to make mass rollout deterministic
  log "Git: hard reset to origin/$target"
  git reset --hard "origin/$target"

  # do NOT nuke .env/compose backups already done; clean only untracked (safe-ish)
  log "Git: cleaning untracked files (excluding backups folder)"
  git clean -fdx -e "_backup/"
}

compose_plan_check() {
  cd "$WORKDIR"

  # try to detect whether service uses build:
  local has_build="no"
  if grep -R --line-number -E '^\s*build:\s*$|^\s*build:\s*[^#]+' . 2>/dev/null | head -n1 >/dev/null; then
    has_build="yes"
  fi

  local uses_image="no"
  if grep -R --line-number -E '^\s*image:\s*' . 2>/dev/null | head -n1 >/dev/null; then
    uses_image="yes"
  fi

  log "Compose: detected build=$has_build, image=$uses_image"

  if [[ "$has_build" == "no" ]]; then
    log "WARNING: I don't see 'build:' in compose files."
    log "WARNING: If you're running only from registry image (e.g. dawsh/marznode:latest), switching git repo won't change runtime."
    log "WARNING: In that case you must change the 'image:' to your fork image, or add build, then rerun."
  fi
}

compose_update_and_restart() {
  cd "$WORKDIR"

  log "Compose: validating config (best-effort)"
  "${COMPOSE[@]}" config >/dev/null 2>&1 || log "WARNING: compose config validation failed (continuing)"

  # Build/pull without stopping currently running container(s)
  log "Compose: pulling images (best-effort)"
  "${COMPOSE[@]}" pull --ignore-pull-failures 2>&1 | tee -a "$LOG_FILE" || true

  log "Compose: building images (best-effort)"
  "${COMPOSE[@]}" build --pull 2>&1 | tee -a "$LOG_FILE" || true

  # Fast recreate
  log "Compose: applying update (recreate)"
  "${COMPOSE[@]}" up -d --remove-orphans 2>&1 | tee -a "$LOG_FILE"

  log "Compose: status"
  "${COMPOSE[@]}" ps 2>&1 | tee -a "$LOG_FILE"
}

health_check() {
  # quick sanity: show current running container image for marznode project if label exists
  log "Docker: marznode containers (by compose label if present)"
  docker ps --filter 'label=com.docker.compose.project=marznode' --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}' 2>&1 | tee -a "$LOG_FILE" || true
}

main() {
  need_root
  detect_compose
  with_lock

  log "=== marznode update start ==="
  log "WORKDIR=$WORKDIR"
  log "REMOTE_URL=$REMOTE_URL"
  log "BRANCH=$BRANCH"

  ensure_workdir
  backup_files
  compose_plan_check
  git_switch_and_update
  compose_update_and_restart
  health_check

  log "=== marznode update done ==="
}

main "$@"
