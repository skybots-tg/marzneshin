"""Backup endpoints used by the "Backup" button above the AI chat.

Why a separate job API instead of a single synchronous POST?
    The dump can take minutes on installs with millions of usage rows.
    Reverse proxies (nginx / cloudflare) normally cap HTTP request
    duration at 60 seconds, so any synchronous endpoint would die mid-
    dump and leave the admin with no useful feedback. The job-based
    design returns immediately with a job id; the UI polls for progress
    and downloads the artefact when done.

Endpoints:
    POST   /api/ai/backup/jobs              — start a job, return snapshot
    GET    /api/ai/backup/jobs              — list recent jobs
    GET    /api/ai/backup/jobs/{id}         — poll one job
    DELETE /api/ai/backup/jobs/{id}         — cooperative cancel request
    POST   /api/ai/backup/jobs/{id}/download-ticket
                                           — exchange sudo-admin session
                                             for a short-lived one-shot
                                             download ticket
    GET    /api/ai/backup/jobs/{id}/download
                                           — stream the finished dump
                                             (sudo-admin OR ticket auth)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.ai.backup import BACKUP_MODES, HEAVY_HISTORY_TABLES, list_backups
from app.ai.backup_jobs import download_tickets, registry
from app.dependencies import SudoAdminDep

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai/backup", tags=["AI Assistant"])


class CreateBackupBody(BaseModel):
    mode: str = Field(
        default="light",
        description="'full' | 'light' | 'config'",
    )
    history_days: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Trim heavy history tables to this many days. "
            "Defaults to 30 when mode='light'."
        ),
    )
    skip_tables: list[str] = Field(
        default_factory=list,
        description=(
            "Extra tables to skip data for. Schema is still written."
        ),
    )


@router.get("/info")
def backup_info(admin: SudoAdminDep):
    """Static info the dialog needs to render (modes + known heavy tables)."""
    return {
        "modes": list(BACKUP_MODES),
        "heavy_history_tables": sorted(HEAVY_HISTORY_TABLES.keys()),
        "default_history_days": 30,
    }


@router.post("/jobs", status_code=202)
def start_backup(body: CreateBackupBody, admin: SudoAdminDep):
    if body.mode not in BACKUP_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid mode; expected one of {BACKUP_MODES}",
        )
    job = registry.start(
        mode=body.mode,
        history_days=body.history_days,
        skip_tables=body.skip_tables or None,
    )
    return job.snapshot()


@router.get("/jobs")
def list_jobs(admin: SudoAdminDep):
    return {
        "jobs": registry.list(),
        "artefacts": list_backups(),
    }


@router.get("/jobs/{job_id}")
def get_job(admin: SudoAdminDep, job_id: str = Path(..., min_length=1)):
    job = registry.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job.snapshot()


@router.delete("/jobs/{job_id}")
def cancel_job(admin: SudoAdminDep, job_id: str = Path(..., min_length=1)):
    ok = registry.request_cancel(job_id)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="job is not active (already finished or unknown id)",
        )
    return {"cancel_requested": True}


def _resolve_ready_job(job_id: str):
    job = registry.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.status != "succeeded" or not job.path:
        raise HTTPException(
            status_code=409,
            detail=f"job is not ready for download (status={job.status})",
        )
    if not os.path.exists(job.path):
        raise HTTPException(
            status_code=410,
            detail="backup file is no longer available on disk",
        )
    return job


def _file_response_for(job) -> FileResponse:
    filename = os.path.basename(job.path)
    media_type = (
        "application/x-sqlite3"
        if filename.endswith(".sqlite")
        else "application/sql"
    )
    return FileResponse(
        path=job.path,
        filename=filename,
        media_type=media_type,
    )


@router.post("/jobs/{job_id}/download-ticket")
def issue_download_ticket(
    admin: SudoAdminDep, job_id: str = Path(..., min_length=1)
):
    """Mint a one-shot, short-lived URL the browser can open directly.

    The bearer-protected GET /download endpoint cannot be opened from a
    plain <a href> / new tab / download manager — browsers never attach
    the Authorization header to navigational requests, so they get 401.
    The UI exchanges its sudo session for a ticket here and navigates
    to the returned URL (which is bearerless and authenticated purely
    by the single-use ticket).
    """
    job = _resolve_ready_job(job_id)
    ticket, ttl = download_tickets.issue(job.id)
    return {
        "ticket": ticket,
        "url": f"/api/ai/backup/jobs/{job.id}/download/{ticket}",
        "expires_in": int(ttl),
    }


@router.get("/jobs/{job_id}/download/{ticket}")
def download_job_artefact_by_ticket(
    job_id: str = Path(..., min_length=1),
    ticket: str = Path(..., min_length=8),
):
    """Stream the finished dump using a one-shot download ticket.

    Intentionally not protected by SudoAdminDep — the ticket itself is
    the credential. Tickets are consumed on first use and expire after
    a couple of minutes, so a leaked URL cannot be replayed.
    """
    if not download_tickets.consume(ticket, job_id):
        raise HTTPException(
            status_code=401,
            detail="invalid or expired download ticket",
        )
    job = _resolve_ready_job(job_id)
    return _file_response_for(job)


@router.get("/jobs/{job_id}/download")
def download_job_artefact(
    admin: SudoAdminDep, job_id: str = Path(..., min_length=1)
):
    """Stream the finished dump (sudo-admin Bearer auth).

    Kept for programmatic/API clients. The UI uses the ticket-based
    endpoint above so that browser navigation works.
    """
    job = _resolve_ready_job(job_id)
    return _file_response_for(job)
