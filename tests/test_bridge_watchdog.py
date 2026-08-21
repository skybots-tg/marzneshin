"""What the bridge watchdog is willing to stay quiet about.

Two cadences share one runner: a quick check every few minutes and a full sweep
once a day. Only the quick one stamps ``scanned_at``, which is what makes the
second alarm here necessary -- and what made the first one, on its own, unable
to notice a sweep that had stopped.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from app.tasks import bridge_watchdog_monitor as wd


@pytest.fixture
def sweep(tmp_path, monkeypatch):
    """A watchdog pointed at throwaway files, with its cooldowns cleared."""
    sent: list[int] = []

    async def fake_notify(stale_hours):
        sent.append(stale_hours)

    monkeypatch.setattr(wd, "notify_full_sweep_stale", fake_notify)
    monkeypatch.setattr(wd, "_last_sweep_alert_ts", 0.0)
    monkeypatch.setattr(wd, "_last_alert_ts", 0.0)

    state = tmp_path / "bridge_state.json"
    report = tmp_path / "bridge_audit.json"
    # A perfectly fresh verdict clock: the other alarm has nothing to say, so
    # anything these tests see comes from the sweep check alone.
    state.write_text(json.dumps({"scanned_at": int(time.time())}))
    monkeypatch.setattr(wd, "STATE_PATH", str(state))
    monkeypatch.setattr(wd, "REPORT_PATH", str(report))

    def write_report(age_sec):
        report.write_text(json.dumps(
            {"generated_at": int(time.time()) - age_sec}))

    return sent, write_report


def test_a_sweep_that_ran_today_says_nothing(sweep):
    sent, write_report = sweep
    write_report(6 * 3600)
    asyncio.run(wd.check_bridge_watchdog())
    assert sent == []


def test_a_sweep_that_missed_its_slot_is_called_out(sweep):
    """The verdict clock is fresh here, so only this check can catch it."""
    sent, write_report = sweep
    write_report(wd.FULL_SWEEP_SILENT_SEC + 3600)
    asyncio.run(wd.check_bridge_watchdog())
    assert sent == [(wd.FULL_SWEEP_SILENT_SEC + 3600) // 3600]


def test_it_does_not_repeat_itself_every_quarter_hour(sweep):
    """The task runs every 900s; the alert is not a heartbeat."""
    sent, write_report = sweep
    write_report(wd.FULL_SWEEP_SILENT_SEC + 3600)
    asyncio.run(wd.check_bridge_watchdog())
    asyncio.run(wd.check_bridge_watchdog())
    assert len(sent) == 1


def test_a_report_nobody_has_written_is_not_an_alarm(sweep):
    """No sweep has ever run here, which is a different problem."""
    sent, _ = sweep
    asyncio.run(wd.check_bridge_watchdog())
    assert sent == []


def test_a_report_with_no_stamp_is_not_guessed_at(sweep, tmp_path):
    sent, _ = sweep
    (tmp_path / "bridge_audit.json").write_text(json.dumps({"hosts": []}))
    assert wd._full_sweep_age() is None
    asyncio.run(wd.check_bridge_watchdog())
    assert sent == []
