"""Database backups for the AI agent.

The agent must create a safety backup before it performs any write
operation, at most once per chat session. Backups live in a dedicated
directory and are retained for `BACKUP_RETENTION_DAYS` days.

Supported dialects:
    - SQLite: uses the sqlite3 online backup API (safe for live DBs).
    - MySQL / MariaDB: shells out to `mysqldump` / `mariadb-dump`.
      If the tool is missing on the host, falls back to `docker exec`
      into the DB container (override the container name via
      `$MARZNESHIN_DB_CONTAINER`, defaults include `marzneshin-db-1`).
    - PostgreSQL: shells out to `pg_dump`, with the same docker fallback.

If the dialect is unsupported or the required CLI tool is missing,
the caller receives a clear error message and the AI agent is
expected to abort the write operation.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.engine.url import make_url

from app.config.env import SQLALCHEMY_DATABASE_URL

logger = logging.getLogger(__name__)

BACKUP_RETENTION_DAYS = 7
_PROD_BACKUP_DIR = "/var/lib/marzneshin/ai_backups"
_DEFAULT_TIMEOUT_SEC = 60 * 30  # 30 min — hard ceiling for dump subprocess


@dataclass
class BackupInfo:
    path: str
    size_bytes: int
    dialect: str
    created_at: float  # unix ts

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "dialect": self.dialect,
            "created_at": datetime.fromtimestamp(
                self.created_at, tz=timezone.utc
            ).isoformat(),
        }


def get_backup_dir() -> str:
    """Return an existing, writable backup directory.

    Prefers `/var/lib/marzneshin/ai_backups` on production hosts;
    falls back to a stable path under the OS temp dir (useful on
    developer machines and in tests).
    """
    candidates = [_PROD_BACKUP_DIR, os.path.join(tempfile.gettempdir(), "marzneshin_ai_backups")]
    for candidate in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
            if os.access(candidate, os.W_OK):
                return candidate
        except OSError:
            continue
    # Last resort: current working directory.
    fallback = os.path.abspath("ai_backups")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def _build_backup_path(extension: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:8]
    return os.path.join(get_backup_dir(), f"marzneshin_ai_{ts}_{short}.{extension}")


def _backup_sqlite(db_url: str) -> BackupInfo:
    url = make_url(db_url)
    db_path = url.database
    if not db_path:
        raise RuntimeError("SQLite database path is empty")
    if not os.path.isabs(db_path):
        db_path = os.path.abspath(db_path)
    if not os.path.exists(db_path):
        raise RuntimeError(f"SQLite DB file not found: {db_path}")

    dest = _build_backup_path("sqlite")
    # Use the online backup API so the dump is consistent even while
    # other connections are writing to the main DB.
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    return BackupInfo(
        path=dest,
        size_bytes=os.path.getsize(dest),
        dialect="sqlite",
        created_at=time.time(),
    )


def _run_subprocess_dump(cmd: list[str], dest: str, env: Optional[dict] = None) -> None:
    with open(dest, "wb") as out:
        try:
            subprocess.run(
                cmd,
                stdout=out,
                stderr=subprocess.PIPE,
                env=env,
                timeout=_DEFAULT_TIMEOUT_SEC,
                check=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Backup timed out after {_DEFAULT_TIMEOUT_SEC}s") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Dump command failed: {stderr or exc}") from exc


def _container_running(name: str) -> bool:
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return (
        res.returncode == 0
        and res.stdout.decode("utf-8", errors="replace").strip() == "true"
    )


def _find_db_container(url_host: Optional[str]) -> Optional[str]:
    """Find a running Docker container that hosts the DB.

    Priority:
        1. $MARZNESHIN_DB_CONTAINER override.
        2. Hostname from SQLALCHEMY_DATABASE_URL (docker-compose services
           are addressable by their service name / container name).
        3. Conventional Marzneshin container names.
    """
    if not shutil.which("docker"):
        return None

    override = os.environ.get("MARZNESHIN_DB_CONTAINER", "").strip()
    if override:
        return override if _container_running(override) else None

    candidates: list[str] = []
    if url_host and url_host not in ("localhost", "127.0.0.1", "::1", ""):
        candidates.append(url_host)
    candidates += [
        "marzneshin-db-1",
        "marzneshin-mariadb-1",
        "marzneshin-mysql-1",
        "marzneshin-postgres-1",
        "marzneshin_db_1",
    ]

    seen = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        if _container_running(name):
            return name
    return None


def _which_in_container(container: str, binary: str) -> bool:
    try:
        res = subprocess.run(
            ["docker", "exec", container, "sh", "-c", f"command -v {binary}"],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return res.returncode == 0 and bool(res.stdout.strip())


def _first_binary_in_container(
    container: str, binaries: tuple[str, ...]
) -> Optional[str]:
    for b in binaries:
        if _which_in_container(container, b):
            return b
    return None


def _backup_mysql(db_url: str) -> BackupInfo:
    url = make_url(db_url)
    dest = _build_backup_path("sql")
    database = url.database or ""
    dump_args = ["--single-transaction", "--quick", "--routines", "--triggers"]

    # Strategy 1: local dump tool
    local_bin = None
    for candidate in ("mariadb-dump", "mysqldump"):
        if shutil.which(candidate):
            local_bin = candidate
            break

    if local_bin:
        cmd = [local_bin, *dump_args]
        if url.host:
            cmd += ["-h", url.host]
        if url.port:
            cmd += ["-P", str(url.port)]
        if url.username:
            cmd += ["-u", url.username]
        cmd.append(database)

        env = os.environ.copy()
        if url.password:
            env["MYSQL_PWD"] = str(url.password)

        _run_subprocess_dump(cmd, dest, env=env)
        return BackupInfo(
            path=dest,
            size_bytes=os.path.getsize(dest),
            dialect="mysql",
            created_at=time.time(),
        )

    # Strategy 2: docker exec into the DB container
    container = _find_db_container(url.host)
    if container:
        binary = _first_binary_in_container(container, ("mariadb-dump", "mysqldump"))
        if binary:
            cmd = ["docker", "exec"]
            if url.password:
                # Pass the password into the container env only, so it
                # doesn't show up in `ps` / host audit logs.
                cmd += ["-e", f"MYSQL_PWD={url.password}"]
            cmd += [container, binary, *dump_args]
            # Inside the container the DB is on localhost, so we don't
            # pass -h/-P — that avoids DNS / port confusion when the
            # URL host is actually the container's own name.
            if url.username:
                cmd += ["-u", url.username]
            cmd.append(database)

            _run_subprocess_dump(cmd, dest)
            return BackupInfo(
                path=dest,
                size_bytes=os.path.getsize(dest),
                dialect="mysql",
                created_at=time.time(),
            )

    raise RuntimeError(
        "Neither mysqldump/mariadb-dump was found on the host, nor could "
        "a running MariaDB/MySQL Docker container be located "
        "(tried $MARZNESHIN_DB_CONTAINER, the URL hostname, and default "
        "marzneshin-db-1 / marzneshin-mariadb-1 names). "
        "Install mysqldump on the host or expose a DB container."
    )


def _backup_postgres(db_url: str) -> BackupInfo:
    url = make_url(db_url)
    dest = _build_backup_path("sql")
    dump_args = ["--format=plain", "--no-owner", "--no-acl"]

    if shutil.which("pg_dump"):
        cmd = ["pg_dump", *dump_args]
        if url.host:
            cmd += ["-h", url.host]
        if url.port:
            cmd += ["-p", str(url.port)]
        if url.username:
            cmd += ["-U", url.username]
        if url.database:
            cmd += ["-d", url.database]

        env = os.environ.copy()
        if url.password:
            env["PGPASSWORD"] = str(url.password)

        _run_subprocess_dump(cmd, dest, env=env)
        return BackupInfo(
            path=dest,
            size_bytes=os.path.getsize(dest),
            dialect="postgresql",
            created_at=time.time(),
        )

    container = _find_db_container(url.host)
    if container and _which_in_container(container, "pg_dump"):
        cmd = ["docker", "exec"]
        if url.password:
            cmd += ["-e", f"PGPASSWORD={url.password}"]
        cmd += [container, "pg_dump", *dump_args]
        if url.username:
            cmd += ["-U", url.username]
        if url.database:
            cmd += ["-d", url.database]

        _run_subprocess_dump(cmd, dest)
        return BackupInfo(
            path=dest,
            size_bytes=os.path.getsize(dest),
            dialect="postgresql",
            created_at=time.time(),
        )

    raise RuntimeError(
        "Neither pg_dump was found on the host, nor could a running "
        "PostgreSQL Docker container be located "
        "(tried $MARZNESHIN_DB_CONTAINER, the URL hostname, and default "
        "marzneshin-postgres-1 name). "
        "Install pg_dump on the host or expose a DB container."
    )


def create_backup() -> BackupInfo:
    """Create a DB backup for the currently configured SQLALCHEMY_DATABASE_URL.

    Raises RuntimeError with a human-readable message on failure so the
    AI tool can report the reason to the user verbatim.
    """
    url = SQLALCHEMY_DATABASE_URL
    lower = url.lower()
    if lower.startswith("sqlite"):
        return _backup_sqlite(url)
    if lower.startswith("mysql") or lower.startswith("mariadb"):
        return _backup_mysql(url)
    if lower.startswith("postgresql") or lower.startswith("postgres"):
        return _backup_postgres(url)
    raise RuntimeError(f"Unsupported database dialect for backup: {url.split(':')[0]}")


def cleanup_old_backups(retention_days: int = BACKUP_RETENTION_DAYS) -> dict:
    """Delete backups older than `retention_days` from the backup dir.

    Returns a summary dict with counts and freed bytes. Safe to call
    from a scheduler — never raises on individual file errors.
    """
    backup_dir = get_backup_dir()
    cutoff = time.time() - retention_days * 86400
    deleted = 0
    freed_bytes = 0
    errors = 0

    try:
        entries = list(Path(backup_dir).iterdir())
    except OSError as exc:
        logger.warning("Cannot list backup dir %s: %s", backup_dir, exc)
        return {"deleted": 0, "freed_bytes": 0, "errors": 1}

    for entry in entries:
        if not entry.is_file():
            continue
        if not entry.name.startswith("marzneshin_ai_"):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            errors += 1
            continue
        if mtime >= cutoff:
            continue
        try:
            size = entry.stat().st_size
            entry.unlink()
            deleted += 1
            freed_bytes += size
        except OSError as exc:
            logger.warning("Failed to remove stale backup %s: %s", entry, exc)
            errors += 1

    logger.info(
        "AI backup cleanup: deleted=%d, freed=%d bytes, errors=%d, dir=%s",
        deleted, freed_bytes, errors, backup_dir,
    )
    return {
        "deleted": deleted,
        "freed_bytes": freed_bytes,
        "errors": errors,
        "retention_days": retention_days,
        "backup_dir": backup_dir,
    }


def list_backups() -> list[dict]:
    """Return metadata for all current AI backups, newest first."""
    backup_dir = get_backup_dir()
    try:
        entries = [p for p in Path(backup_dir).iterdir() if p.is_file()]
    except OSError:
        return []

    items = []
    for entry in entries:
        if not entry.name.startswith("marzneshin_ai_"):
            continue
        try:
            st = entry.stat()
        except OSError:
            continue
        items.append({
            "path": str(entry),
            "size_bytes": st.st_size,
            "created_at": datetime.fromtimestamp(
                st.st_mtime, tz=timezone.utc
            ).isoformat(),
            "expires_at": datetime.fromtimestamp(
                st.st_mtime + BACKUP_RETENTION_DAYS * 86400, tz=timezone.utc
            ).isoformat(),
        })
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items
