"""Background backup jobs with in-memory progress tracking.

The UI calls `POST /api/ai/backup/jobs` to kick off a backup. Because a
full dump on a 10k-user install easily blows past any reverse-proxy
read timeout (nginx defaults to 60s), we run the dump on a worker
thread and return a `job_id` synchronously. The UI then polls
`GET /api/ai/backup/jobs/{id}` for progress and downloads the finished
dump via `GET /api/ai/backup/jobs/{id}/download`.

Design notes:
    * No DB persistence: jobs live in a process-local dict guarded by a
      lock. That's sufficient — the UI is meant to be used interactively
      and we retain a small history (MAX_JOB_HISTORY) so a page reload
      can still find the last job. File artefacts on disk are the
      durable source of truth (see `app.ai.backup.list_backups`).
    * Progress updates come from `BackupOptions.progress`; we throttle
      them so a million-row table doesn't flood the deque.
    * Cancellation is cooperative and best-effort — the worker can't
      actually kill an in-flight mysqldump subprocess safely, so we
      just mark the job as cancelled and ignore its eventual result.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from app.ai.backup import BackupInfo, BackupOptions, create_backup

logger = logging.getLogger(__name__)

MAX_JOB_HISTORY = 20
_PROGRESS_MIN_INTERVAL_SEC = 0.25

# Short-lived, one-shot tickets that let the browser download a finished
# backup via plain <a href> navigation (which cannot carry the admin's
# Bearer token). The UI exchanges its sudo session for a ticket via an
# authenticated POST, then opens /jobs/{id}/download/{ticket}.
DOWNLOAD_TICKET_TTL_SEC = 120.0


@dataclass
class BackupJob:
    id: str
    mode: str
    history_days: Optional[int]
    skip_tables: list[str]
    status: str  # "pending" | "running" | "succeeded" | "failed" | "cancelled"
    phase: str = "queued"
    table: Optional[str] = None
    current_table_index: int = 0
    total_tables: int = 0
    rows_written_table: int = 0
    expected_rows_table: int = 0
    percent: float = 0.0
    bytes_written: int = 0
    dialect: Optional[str] = None
    strategy: Optional[str] = None  # "local" | "docker" | "pure-python" | "sqlite"
    error: Optional[str] = None
    path: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    cancel_requested: bool = False
    _last_progress_emit: float = 0.0

    def snapshot(self) -> dict:
        """Serialisable view for the API response."""
        return {
            "id": self.id,
            "mode": self.mode,
            "history_days": self.history_days,
            "skip_tables": list(self.skip_tables),
            "status": self.status,
            "phase": self.phase,
            "table": self.table,
            "current_table_index": self.current_table_index,
            "total_tables": self.total_tables,
            "rows_written_table": self.rows_written_table,
            "expected_rows_table": self.expected_rows_table,
            "percent": round(self.percent, 2),
            "bytes_written": self.bytes_written,
            "dialect": self.dialect,
            "strategy": self.strategy,
            "error": self.error,
            "path": self.path,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "cancel_requested": self.cancel_requested,
        }


class _BackupJobRegistry:
    """Thread-safe process-local store for backup jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, BackupJob] = {}
        self._futures: dict[str, Future] = {}
        # One worker at a time — large dumps are disk/db bound, and
        # two concurrent runs just thrash the DB.
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ai-backup"
        )

    def _trim(self) -> None:
        # Retain the newest MAX_JOB_HISTORY terminal jobs + any active ones.
        if len(self._jobs) <= MAX_JOB_HISTORY:
            return
        terminal_ids = [
            j.id
            for j in self._jobs.values()
            if j.status in ("succeeded", "failed", "cancelled")
        ]
        terminal_ids.sort(
            key=lambda jid: self._jobs[jid].finished_at or 0.0
        )
        drop = len(self._jobs) - MAX_JOB_HISTORY
        for jid in terminal_ids[:drop]:
            self._jobs.pop(jid, None)
            self._futures.pop(jid, None)

    def start(
        self,
        *,
        mode: str,
        history_days: Optional[int],
        skip_tables: Optional[list[str]] = None,
    ) -> BackupJob:
        job = BackupJob(
            id=uuid.uuid4().hex,
            mode=mode,
            history_days=history_days,
            skip_tables=list(skip_tables or []),
            status="pending",
        )
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
            future = self._executor.submit(self._run, job.id)
            self._futures[job.id] = future
        return job

    def get(self, job_id: str) -> Optional[BackupJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            return [j.snapshot() for j in sorted(
                self._jobs.values(),
                key=lambda j: j.started_at,
                reverse=True,
            )]

    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status in ("succeeded", "failed", "cancelled"):
                return False
            job.cancel_requested = True
            job.updated_at = time.time()
        return True

    # ----------------------------------------------------------------
    # worker
    # ----------------------------------------------------------------

    def _progress(self, job_id: str, event: dict) -> None:
        now = time.time()
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in ("pending", "running"):
                return

            phase = event.get("phase") or job.phase
            job.phase = phase
            if "table" in event and event["table"] is not None:
                job.table = event["table"]
            if "current" in event:
                job.current_table_index = int(event["current"])
            if "total_tables" in event:
                job.total_tables = int(event["total_tables"])
            if "rows_written" in event:
                job.rows_written_table = int(event["rows_written"])
            if "expected_rows" in event and event["expected_rows"] >= 0:
                job.expected_rows_table = int(event["expected_rows"])
            if "strategy" in event:
                job.strategy = event["strategy"]
            if "dialect" in event:
                job.dialect = event["dialect"]

            if job.total_tables > 0:
                base = (job.current_table_index - 1) / job.total_tables
                per = 0.0
                if phase in ("data", "data_batch") and job.expected_rows_table > 0:
                    per = min(
                        1.0, job.rows_written_table / job.expected_rows_table
                    ) / job.total_tables
                elif phase in ("data_done", "data_skipped", "schema"):
                    per = 1.0 / job.total_tables
                job.percent = max(0.0, min(100.0, (base + per) * 100.0))
            if phase == "finalising":
                job.percent = 99.0
            job.updated_at = now

            # Heavy events (data_batch) are rate-limited; terminal events
            # always go through.
            if phase == "data_batch" and (now - job._last_progress_emit) < _PROGRESS_MIN_INTERVAL_SEC:
                return
            job._last_progress_emit = now

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = "running"
            job.phase = "starting"
            job.updated_at = time.time()

        opts = BackupOptions(
            mode=job.mode,
            history_days=job.history_days,
            skip_tables=set(job.skip_tables),
            progress=lambda ev, _jid=job_id: self._progress(_jid, ev),
        )

        try:
            info: BackupInfo = create_backup(opts)
        except Exception as exc:
            logger.exception("Backup job %s failed", job_id)
            with self._lock:
                j = self._jobs.get(job_id)
                if j:
                    j.status = "failed"
                    j.phase = "failed"
                    j.error = str(exc) or exc.__class__.__name__
                    # Full traceback in debug logs only — don't leak to UI.
                    logger.debug("backup traceback:\n%s", traceback.format_exc())
                    j.finished_at = time.time()
                    j.updated_at = j.finished_at
            return

        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            if j.cancel_requested:
                # Dump finished anyway; keep the file on disk (it's still
                # a valid backup), but mark the job as cancelled.
                j.status = "cancelled"
                j.phase = "cancelled"
            else:
                j.status = "succeeded"
                j.phase = "done"
                j.percent = 100.0
            j.path = info.path
            j.bytes_written = info.size_bytes
            j.dialect = info.dialect
            j.finished_at = time.time()
            j.updated_at = j.finished_at


registry = _BackupJobRegistry()


class _DownloadTicketRegistry:
    """One-shot, time-limited tickets for anonymous download URLs.

    Tickets are consumed on use (pop) so a leaked URL cannot be reused.
    We keep them in-process; there is only ever one admin actively
    downloading a backup, and if the process restarts the UI can
    transparently request a fresh ticket.
    """

    def __init__(self, ttl_sec: float = DOWNLOAD_TICKET_TTL_SEC) -> None:
        self._ttl = ttl_sec
        self._lock = threading.Lock()
        # ticket -> (job_id, expires_at_monotonic)
        self._tickets: dict[str, tuple[str, float]] = {}

    def _prune_locked(self, now: float) -> None:
        expired = [t for t, (_, exp) in self._tickets.items() if exp <= now]
        for t in expired:
            self._tickets.pop(t, None)

    def issue(self, job_id: str) -> tuple[str, float]:
        ticket = secrets.token_urlsafe(32)
        now = time.monotonic()
        expires_at = now + self._ttl
        with self._lock:
            self._prune_locked(now)
            self._tickets[ticket] = (job_id, expires_at)
        return ticket, self._ttl

    def consume(self, ticket: str, job_id: str) -> bool:
        now = time.monotonic()
        with self._lock:
            entry = self._tickets.pop(ticket, None)
            self._prune_locked(now)
        if not entry:
            return False
        tjob_id, expires_at = entry
        if expires_at <= now:
            return False
        return tjob_id == job_id


download_tickets = _DownloadTicketRegistry()
