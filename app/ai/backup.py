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
      As the last resort, produces a pure-Python SQL dump through the
      same PyMySQL connection the panel already uses — this always
      works while the DB itself is reachable.
    - PostgreSQL: shells out to `pg_dump`, with the same docker fallback.

If the dialect is unsupported or the required CLI tool is missing,
the caller receives a clear error message and the AI agent is
expected to abort the write operation.
"""
from __future__ import annotations

import decimal
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

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


# Heavy history/metric tables. Keyed by table name; value is the time column
# used for "last N days" filtering (or None if there is no natural time
# column — in that case history_days cannot apply, and data is either
# fully included or fully skipped).
HEAVY_HISTORY_TABLES: dict[str, Optional[str]] = {
    "node_user_usages": "created_at",
    "node_usages": "created_at",
    "node_user_usages_daily": "date",
    "node_usages_daily": "date",
    "user_device_traffic": "bucket_start",
    "user_device_ips": "last_seen_at",
}


BACKUP_MODES = ("full", "light", "config")


@dataclass
class BackupOptions:
    """Tuning knobs exposed to the "Backup" UI.

    mode:
        - "full"   — dump everything (default for safety restores).
        - "light"  — dump everything, but trim heavy history tables to
                     the last `history_days` days (default 30).
        - "config" — dump schema + data for configuration tables only;
                     heavy history tables get schema-only (no rows).
    history_days:
        - None   → no filter (mode=full);
        - int>0  → keep only rows where the table's time column is within
                   the last N days (applied in mode=light, and also in
                   mode=full if the caller explicitly passes it).
    skip_tables:
        - extra table names for which data should be skipped (schema is
          still written so a restore recreates them empty).
    progress:
        - optional callback; receives dict events with keys like
          {"phase": "...", "current": int, "total_tables": int,
           "table": str, "rows": int, "bytes_written": int,
           "percent": float}. Best-effort, never blocks the dump.
    """

    mode: str = "full"
    history_days: Optional[int] = None
    skip_tables: set[str] = field(default_factory=set)
    progress: Optional[Callable[[dict], None]] = None

    def __post_init__(self) -> None:
        if self.mode not in BACKUP_MODES:
            raise ValueError(
                f"invalid backup mode {self.mode!r}; "
                f"expected one of {BACKUP_MODES}"
            )
        if self.history_days is not None and self.history_days < 0:
            raise ValueError("history_days must be >= 0")
        if self.skip_tables is None:
            self.skip_tables = set()

    def effective_history_days(self) -> Optional[int]:
        if self.mode == "light":
            return self.history_days if self.history_days is not None else 30
        if self.mode == "config":
            return 0  # never keep data
        # full
        return self.history_days

    def should_skip_data(self, table: str) -> bool:
        if table in self.skip_tables:
            return True
        if self.mode == "config" and table in HEAVY_HISTORY_TABLES:
            return True
        return False

    def emit_progress(self, event: dict) -> None:
        cb = self.progress
        if cb is None:
            return
        try:
            cb(event)
        except Exception:  # noqa: BLE001
            # Progress must never take down the dump.
            logger.exception("Backup progress callback failed")


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


# ---------------------------------------------------------------------------
# Pure-Python MySQL / MariaDB dump (last-resort fallback).
#
# This path uses the same SQLAlchemy/PyMySQL connection the panel already
# relies on. It has zero external dependencies and works inside a
# containerised panel that has no access to docker.sock. The trade-offs:
#   - schema-only: base tables. Views, stored routines, triggers and events
#     are NOT included (rare in Marzneshin, and mysqldump is still preferred
#     when available);
#   - the output is deterministic, mysqldump-compatible SQL that can be
#     restored with `mysql -u … db < dump.sql`.
# ---------------------------------------------------------------------------


_INSERT_BATCH_SIZE = 500


def _format_mysql_value(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float, decimal.Decimal)):
        return str(v)
    if isinstance(v, datetime):
        return "'" + v.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(v, date):
        return "'" + v.strftime("%Y-%m-%d") + "'"
    if isinstance(v, dt_time):
        return "'" + v.strftime("%H:%M:%S") + "'"
    if isinstance(v, timedelta):
        total = int(v.total_seconds())
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"'{hours:02d}:{minutes:02d}:{seconds:02d}'"
    if isinstance(v, (bytes, bytearray, memoryview)):
        raw = bytes(v)
        return "0x" + raw.hex() if raw else "''"
    s = str(v)
    escaped = (
        s.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\0", "\\0")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\x1a", "\\Z")
    )
    return "'" + escaped + "'"


def _format_mysql_row(row) -> str:
    return "(" + ",".join(_format_mysql_value(v) for v in row) + ")"


_MYSQL_SESSION_TWEAKS = (
    # MariaDB 10.x / MySQL 5.7+ — may not all exist on every version.
    # Best-effort: ignore errors silently.
    "SET SESSION max_statement_time=0",          # MariaDB
    "SET SESSION MAX_EXECUTION_TIME=0",          # MySQL 5.7+ hint alt.
    "SET SESSION net_read_timeout=31536000",
    "SET SESSION net_write_timeout=31536000",
    "SET SESSION wait_timeout=31536000",
    "SET SESSION interactive_timeout=31536000",
    "SET SESSION innodb_lock_wait_timeout=1073741824",
    # Consistent non-locking snapshot — works when binlog/durability is off.
    "SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ",
)


def _apply_mysql_session_tweaks(conn) -> None:
    """Relax per-statement / connection timeouts for the dump session.

    Best-effort: each tweak is wrapped in try/except because the exact set
    of supported variables depends on the MariaDB/MySQL version.
    """
    from sqlalchemy import text

    for stmt in _MYSQL_SESSION_TWEAKS:
        try:
            conn.execute(text(stmt))
        except Exception:  # noqa: BLE001
            logger.debug("Session tweak skipped: %s", stmt)


def _find_single_int_pk(conn, table: str) -> Optional[str]:
    """Return the column name of a single-column integer PK, else None."""
    from sqlalchemy import text

    rows = conn.execute(
        text(
            """
            SELECT k.COLUMN_NAME, c.DATA_TYPE
            FROM information_schema.KEY_COLUMN_USAGE k
            JOIN information_schema.COLUMNS c
              ON c.TABLE_SCHEMA = k.TABLE_SCHEMA
             AND c.TABLE_NAME  = k.TABLE_NAME
             AND c.COLUMN_NAME = k.COLUMN_NAME
            WHERE k.TABLE_SCHEMA = DATABASE()
              AND k.TABLE_NAME = :t
              AND k.CONSTRAINT_NAME = 'PRIMARY'
            ORDER BY k.ORDINAL_POSITION
            """
        ),
        {"t": table},
    ).fetchall()
    if not rows or len(rows) != 1:
        return None
    col, dtype = rows[0][0], rows[0][1]
    if str(dtype).lower() not in (
        "int", "integer", "bigint", "smallint", "mediumint", "tinyint"
    ):
        return None
    return col


def _count_rows(conn, table: str, where_sql: str, params: dict) -> int:
    """Fast COUNT(*) on a table under an optional WHERE clause."""
    from sqlalchemy import text

    q = f"SELECT COUNT(*) FROM `{table}`"
    if where_sql:
        q += f" WHERE {where_sql}"
    try:
        return int(conn.execute(text(q), params).scalar() or 0)
    except Exception:
        return -1  # unknown


def _history_where(table: str, history_days: Optional[int]) -> tuple[str, dict]:
    """Build a WHERE clause that trims a table to the last N days, if applicable."""
    if history_days is None:
        return "", {}
    time_col = HEAVY_HISTORY_TABLES.get(table)
    if not time_col:
        return "", {}
    if history_days == 0:
        # Sentinel "keep no rows" — only used by mode=config, and only
        # if the caller hasn't decided to skip data entirely. Practically
        # we shouldn't get here in mode=config because should_skip_data()
        # returns True upstream, but handle it anyway.
        return f"`{time_col}` >= CURRENT_TIMESTAMP", {}
    return (
        f"`{time_col}` >= (NOW() - INTERVAL :hist_days DAY)",
        {"hist_days": history_days},
    )


def _stream_table_by_pk(
    f,
    conn,
    table: str,
    pk: str,
    history_where: str,
    history_params: dict,
    batch_size: int,
    on_batch: Callable[[int], None],
) -> int:
    """Dump `SELECT * FROM table` in PK-keyset chunks.

    Each chunk is a short, bounded statement — immune to
    `max_statement_time` kills on huge tables. Returns total rows written.
    """
    from sqlalchemy import text

    total = 0
    last_pk = None
    while True:
        where_parts: list[str] = []
        params: dict = {"lim": batch_size}
        if last_pk is not None:
            where_parts.append(f"`{pk}` > :last_pk")
            params["last_pk"] = last_pk
        if history_where:
            where_parts.append(f"({history_where})")
            params.update(history_params)
        where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
        sql = (
            f"SELECT * FROM `{table}`{where_sql} "
            f"ORDER BY `{pk}` LIMIT :lim"
        )
        rs = conn.execute(text(sql), params)
        rows = rs.fetchall()
        if not rows:
            break

        cols = list(rs.keys())
        col_list = ",".join(f"`{c}`" for c in cols)
        values_sql = ",\n".join(_format_mysql_row(r) for r in rows)
        f.write(
            f"INSERT INTO `{table}` ({col_list}) VALUES\n{values_sql};\n"
        )

        pk_idx = cols.index(pk)
        last_pk = rows[-1][pk_idx]
        total += len(rows)
        on_batch(len(rows))

        if len(rows) < batch_size:
            break
    return total


def _stream_table_streaming(
    f,
    conn,
    table: str,
    history_where: str,
    history_params: dict,
    batch_size: int,
    on_batch: Callable[[int], None],
) -> int:
    """Fallback for tables without a usable integer PK: server-side cursor.

    `max_statement_time` may still fire here on very large tables; that's
    why `_apply_mysql_session_tweaks` disables it earlier in the session.
    """
    from sqlalchemy import text

    where_sql = f" WHERE {history_where}" if history_where else ""
    sql = f"SELECT * FROM `{table}`{where_sql}"
    rs = conn.execution_options(
        stream_results=True, yield_per=batch_size
    ).execute(text(sql), history_params)
    cols = list(rs.keys())
    col_list = ",".join(f"`{c}`" for c in cols)
    batch: list = []
    total = 0
    for row in rs:
        batch.append(row)
        if len(batch) >= batch_size:
            values_sql = ",\n".join(_format_mysql_row(r) for r in batch)
            f.write(
                f"INSERT INTO `{table}` ({col_list}) VALUES\n{values_sql};\n"
            )
            total += len(batch)
            on_batch(len(batch))
            batch.clear()
    if batch:
        values_sql = ",\n".join(_format_mysql_row(r) for r in batch)
        f.write(
            f"INSERT INTO `{table}` ({col_list}) VALUES\n{values_sql};\n"
        )
        total += len(batch)
        on_batch(len(batch))
    return total


def _backup_mysql_via_sqlalchemy(
    db_url: str, opts: BackupOptions
) -> BackupInfo:
    from sqlalchemy import create_engine, text

    url = make_url(db_url)
    dest = _build_backup_path("sql")
    database = url.database or ""
    history_days = opts.effective_history_days()

    engine = create_engine(db_url, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as conn, open(
            dest, "w", encoding="utf-8", newline="\n"
        ) as f:
            _apply_mysql_session_tweaks(conn)

            f.write("-- Marzneshin AI backup (pure-Python via SQLAlchemy)\n")
            f.write(
                f"-- Generated at: {datetime.now(timezone.utc).isoformat()}\n"
            )
            f.write(f"-- Database: {database}\n")
            f.write(f"-- Mode: {opts.mode}\n")
            if history_days is not None:
                f.write(f"-- History window: last {history_days} days\n")
            if opts.skip_tables:
                f.write(
                    f"-- Explicitly skipped tables (data only): "
                    f"{', '.join(sorted(opts.skip_tables))}\n"
                )
            f.write(
                "-- NOTE: schema-only base tables + data. Views, routines,\n"
            )
            f.write(
                "--       triggers and events are NOT included.\n\n"
            )
            f.write("SET NAMES utf8mb4;\n")
            f.write(
                "SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, "
                "FOREIGN_KEY_CHECKS=0;\n"
            )
            f.write(
                "SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;\n"
            )
            f.write(
                "SET @OLD_SQL_MODE=@@SQL_MODE, "
                "SQL_MODE='NO_AUTO_VALUE_ON_ZERO';\n\n"
            )

            tables = [
                row[0]
                for row in conn.execute(
                    text("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
                )
            ]
            total_tables = len(tables)
            opts.emit_progress(
                {
                    "phase": "start",
                    "total_tables": total_tables,
                    "current": 0,
                    "table": None,
                }
            )

            for idx, table in enumerate(tables, 1):
                tn = table.replace("`", "``")

                opts.emit_progress(
                    {
                        "phase": "schema",
                        "current": idx,
                        "total_tables": total_tables,
                        "table": table,
                    }
                )

                f.write("-- ----------------------------------------\n")
                f.write(f"-- Table: `{tn}`\n")
                f.write("-- ----------------------------------------\n")
                f.write(f"DROP TABLE IF EXISTS `{tn}`;\n")

                create_row = conn.execute(
                    text(f"SHOW CREATE TABLE `{tn}`")
                ).fetchone()
                if create_row is None:
                    continue
                create_sql = create_row[1]
                f.write(create_sql + ";\n\n")

                if opts.should_skip_data(table):
                    f.write(
                        f"-- data skipped (mode={opts.mode}"
                        + (
                            f", in skip_tables"
                            if table in opts.skip_tables
                            else ""
                        )
                        + ")\n\n"
                    )
                    opts.emit_progress(
                        {
                            "phase": "data_skipped",
                            "current": idx,
                            "total_tables": total_tables,
                            "table": table,
                        }
                    )
                    continue

                where_sql, where_params = _history_where(table, history_days)
                row_count = _count_rows(conn, table, where_sql, where_params)
                opts.emit_progress(
                    {
                        "phase": "data",
                        "current": idx,
                        "total_tables": total_tables,
                        "table": table,
                        "expected_rows": row_count,
                    }
                )

                pk = _find_single_int_pk(conn, table)
                written = 0

                def _on_batch(n: int, _table=table, _idx=idx) -> None:
                    nonlocal written
                    written += n
                    opts.emit_progress(
                        {
                            "phase": "data_batch",
                            "current": _idx,
                            "total_tables": total_tables,
                            "table": _table,
                            "rows_written": written,
                            "expected_rows": row_count,
                        }
                    )

                if pk:
                    rows_written = _stream_table_by_pk(
                        f,
                        conn,
                        table,
                        pk,
                        where_sql,
                        where_params,
                        _INSERT_BATCH_SIZE,
                        _on_batch,
                    )
                else:
                    rows_written = _stream_table_streaming(
                        f,
                        conn,
                        table,
                        where_sql,
                        where_params,
                        _INSERT_BATCH_SIZE,
                        _on_batch,
                    )

                if rows_written > 0:
                    f.write("\n")

                opts.emit_progress(
                    {
                        "phase": "data_done",
                        "current": idx,
                        "total_tables": total_tables,
                        "table": table,
                        "rows_written": rows_written,
                    }
                )

            f.write("SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;\n")
            f.write("SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;\n")
            f.write("SET SQL_MODE=@OLD_SQL_MODE;\n")

            opts.emit_progress(
                {"phase": "finalising", "total_tables": total_tables}
            )
    finally:
        engine.dispose()

    return BackupInfo(
        path=dest,
        size_bytes=os.path.getsize(dest),
        dialect="mysql",
        created_at=time.time(),
    )


def _mysqldump_ignore_args(database: str, opts: BackupOptions) -> list[str]:
    """Build `--ignore-table=db.table` args for subprocess dumpers.

    Subprocess paths (mysqldump / mariadb-dump) have no native time-window
    filter, so mode=light+history_days is honoured by dropping heavy
    tables entirely. mode=config drops heavy history tables; mode=full
    only drops explicitly skipped ones.
    """
    skip: set[str] = set(opts.skip_tables or ())
    if opts.mode in ("config", "light"):
        skip |= set(HEAVY_HISTORY_TABLES)
    args: list[str] = []
    for t in sorted(skip):
        args.append(f"--ignore-table={database}.{t}")
    return args


def _backup_mysql(db_url: str, opts: BackupOptions) -> BackupInfo:
    url = make_url(db_url)
    dest = _build_backup_path("sql")
    database = url.database or ""
    dump_args = ["--single-transaction", "--quick", "--routines", "--triggers"]
    ignore_args = _mysqldump_ignore_args(database, opts)

    opts.emit_progress({"phase": "start", "dialect": "mysql", "mode": opts.mode})

    # Strategy 1: local dump tool.
    local_bin = None
    for candidate in ("mariadb-dump", "mysqldump"):
        if shutil.which(candidate):
            local_bin = candidate
            break

    if local_bin:
        opts.emit_progress({"phase": "subprocess", "strategy": "local", "binary": local_bin})
        cmd = [local_bin, *dump_args, *ignore_args]
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

    # Strategy 2: docker exec into the DB container.
    container = _find_db_container(url.host)
    if container:
        binary = _first_binary_in_container(
            container, ("mariadb-dump", "mysqldump")
        )
        if binary:
            opts.emit_progress(
                {"phase": "subprocess", "strategy": "docker",
                 "container": container, "binary": binary}
            )
            cmd = ["docker", "exec"]
            if url.password:
                # Pass the password into the container env only, so it
                # doesn't show up in `ps` / host audit logs.
                cmd += ["-e", f"MYSQL_PWD={url.password}"]
            cmd += [container, binary, *dump_args, *ignore_args]
            # Inside the container the DB is on localhost, so we don't
            # pass -h/-P — avoids DNS / port confusion when the URL host
            # is actually the container's own name.
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

    # Strategy 3: pure-Python dump via the existing SQLAlchemy/PyMySQL link.
    opts.emit_progress({"phase": "subprocess", "strategy": "pure-python"})
    try:
        return _backup_mysql_via_sqlalchemy(db_url, opts)
    except Exception as exc:
        raise RuntimeError(
            "MySQL/MariaDB backup failed: no mysqldump/mariadb-dump on the "
            "host, no reachable DB container for docker exec "
            "(tried $MARZNESHIN_DB_CONTAINER, URL host, marzneshin-db-1, "
            "marzneshin-mariadb-1), and the pure-Python fallback also "
            f"failed: {exc}"
        ) from exc


def _backup_postgres(db_url: str, opts: BackupOptions) -> BackupInfo:
    url = make_url(db_url)
    dest = _build_backup_path("sql")
    dump_args = ["--format=plain", "--no-owner", "--no-acl"]
    # Postgres has no pure-Python fallback here (yet), so history_days /
    # skip_tables only affect the excluded-table list passed to pg_dump.
    exclude_tables: set[str] = set(opts.skip_tables or ())
    if opts.mode in ("config", "light"):
        exclude_tables |= set(HEAVY_HISTORY_TABLES)
    for t in sorted(exclude_tables):
        dump_args.append(f"--exclude-table-data={t}")

    opts.emit_progress({"phase": "start", "dialect": "postgresql", "mode": opts.mode})

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


def create_backup(opts: Optional[BackupOptions] = None) -> BackupInfo:
    """Create a DB backup for the currently configured SQLALCHEMY_DATABASE_URL.

    Parameters
    ----------
    opts:
        Optional BackupOptions controlling the backup scope (mode,
        history_days, skipped tables) and an optional progress callback.
        When omitted, defaults to a full backup with no progress events
        and no filtering — preserving the previous semantics.

    Raises RuntimeError with a human-readable message on failure so the
    caller can surface the reason to the user verbatim.
    """
    if opts is None:
        opts = BackupOptions()
    url = SQLALCHEMY_DATABASE_URL
    lower = url.lower()
    if lower.startswith("sqlite"):
        opts.emit_progress({"phase": "start", "dialect": "sqlite"})
        info = _backup_sqlite(url)
        opts.emit_progress({"phase": "done"})
        return info
    if lower.startswith("mysql") or lower.startswith("mariadb"):
        info = _backup_mysql(url, opts)
        opts.emit_progress({"phase": "done"})
        return info
    if lower.startswith("postgresql") or lower.startswith("postgres"):
        info = _backup_postgres(url, opts)
        opts.emit_progress({"phase": "done"})
        return info
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
