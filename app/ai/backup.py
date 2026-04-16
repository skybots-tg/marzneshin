"""Database backups for the AI agent.

The agent must create a safety backup before it performs any write
operation, at most once per chat session. Backups live in a dedicated
directory and are retained for `BACKUP_RETENTION_DAYS` days.

Supported dialects:
    - SQLite: uses the sqlite3 online backup API (safe for live DBs).
    - MySQL / MariaDB: shells out to `mysqldump`.
    - PostgreSQL: shells out to `pg_dump`.

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


def _backup_mysql(db_url: str) -> BackupInfo:
    if not shutil.which("mysqldump"):
        raise RuntimeError("mysqldump is not installed on this host")

    url = make_url(db_url)
    dest = _build_backup_path("sql")
    cmd = ["mysqldump", "--single-transaction", "--quick", "--routines", "--triggers"]
    if url.host:
        cmd += ["-h", url.host]
    if url.port:
        cmd += ["-P", str(url.port)]
    if url.username:
        cmd += ["-u", url.username]

    env = os.environ.copy()
    if url.password:
        # Password via env to keep it out of `ps` / audit logs.
        env["MYSQL_PWD"] = str(url.password)

    cmd.append(url.database or "")

    _run_subprocess_dump(cmd, dest, env=env)
    return BackupInfo(
        path=dest,
        size_bytes=os.path.getsize(dest),
        dialect="mysql",
        created_at=time.time(),
    )


def _backup_postgres(db_url: str) -> BackupInfo:
    if not shutil.which("pg_dump"):
        raise RuntimeError("pg_dump is not installed on this host")

    url = make_url(db_url)
    dest = _build_backup_path("sql")
    cmd = ["pg_dump", "--format=plain", "--no-owner", "--no-acl"]
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
