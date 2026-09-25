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


# --------------------------------------------------------------------------
# dead hosts the audit is holding back for a human
# --------------------------------------------------------------------------

HELD = "19>ELITE US@n45/tcp"


@pytest.fixture
def held(tmp_path, monkeypatch):
    """A fresh audit whose state file the test fills with links."""
    sent: list[tuple[dict, dict]] = []

    async def fake_notify(links, hosts_by_link):
        sent.append((links, hosts_by_link))

    monkeypatch.setattr(wd, "notify_held_hides", fake_notify)
    monkeypatch.setattr(wd, "_held_alert_ts", {})

    state = tmp_path / "bridge_state.json"
    quick = tmp_path / "bridge_audit.quick.json"
    report = tmp_path / "bridge_audit.json"
    now = int(time.time())
    # Fresh verdicts and a fresh sweep: the other two alarms stay quiet.
    report.write_text(json.dumps({"generated_at": now - 3600, "hosts": []}))
    quick.write_text(json.dumps({"generated_at": now, "hosts": [
        {"host_id": 506, "remark": "ELITE US <always>", "link": HELD,
         "is_disabled": False},
        {"host_id": 133, "remark": "ELITE US", "link": "19>ELITE US@n17/tcp",
         "is_disabled": True},
        {"host_id": 496, "remark": "FAST 3", "link": "45>i417/tcp",
         "is_disabled": False},
        {"host_id": 330, "remark": "FAST 9", "link": "9>i330/tcp",
         "is_disabled": True},
    ]}))
    monkeypatch.setattr(wd, "STATE_PATH", str(state))
    monkeypatch.setattr(wd, "QUICK_REPORT_PATH", str(quick))
    monkeypatch.setattr(wd, "REPORT_PATH", str(report))

    def write_links(**links):
        state.write_text(json.dumps({"scanned_at": now, "links": links}))

    return sent, write_links


def link(fail_streak, deferred="last_visible_slot", verdict="down"):
    return {"verdict": verdict, "fail_streak": fail_streak,
            "deferred": deferred, "reason": "link_down"}


def test_a_long_held_hide_is_called_out_with_its_hosts(held):
    sent, write_links = held
    write_links(**{HELD: link(24)})
    asyncio.run(wd.check_bridge_watchdog())
    assert len(sent) == 1
    links, hosts = sent[0]
    assert list(links) == [HELD]
    assert hosts[HELD] == [(506, "ELITE US <always>")]
    assert "19>ELITE US@n17/tcp" not in hosts   # hidden hosts are not news


def test_a_fresh_failure_is_the_audits_business(held):
    sent, write_links = held
    write_links(**{HELD: link(wd.HELD_HIDE_STREAK - 1)})
    asyncio.run(wd.check_bridge_watchdog())
    assert sent == []


def test_a_hide_that_went_through_is_not_held(held):
    sent, write_links = held
    write_links(**{HELD: link(24, deferred=None)})
    asyncio.run(wd.check_bridge_watchdog())
    assert sent == []


def test_a_link_hidden_by_hand_is_not_news(held):
    """Its held note outlives the hide until the hidden half is probed."""
    sent, write_links = held
    write_links(**{"9>i330/tcp": link(24, deferred="last_visible_entry")})
    asyncio.run(wd.check_bridge_watchdog())
    assert sent == []


def test_without_a_report_the_held_link_is_still_told(held, tmp_path):
    sent, write_links = held
    (tmp_path / "bridge_audit.quick.json").unlink()
    (tmp_path / "bridge_audit.json").unlink()
    write_links(**{HELD: link(24)})
    asyncio.run(wd.check_bridge_watchdog())
    assert [list(links) for links, _ in sent] == [[HELD]]


def test_a_held_hide_is_not_repeated_every_quarter_hour(held):
    sent, write_links = held
    write_links(**{HELD: link(24)})
    asyncio.run(wd.check_bridge_watchdog())
    asyncio.run(wd.check_bridge_watchdog())
    assert len(sent) == 1


def test_a_relapse_after_recovery_is_news_again(held):
    sent, write_links = held
    write_links(**{HELD: link(24)})
    asyncio.run(wd.check_bridge_watchdog())
    write_links(**{HELD: link(0, deferred=None, verdict="up")})
    asyncio.run(wd.check_bridge_watchdog())
    write_links(**{HELD: link(9)})
    asyncio.run(wd.check_bridge_watchdog())
    assert len(sent) == 2


def test_a_second_held_link_does_not_wait_for_the_first_ones_cooldown(held):
    sent, write_links = held
    write_links(**{HELD: link(24)})
    asyncio.run(wd.check_bridge_watchdog())
    write_links(**{HELD: link(25), "45>i417/tcp": link(
        9, deferred="last_visible_entry")})
    asyncio.run(wd.check_bridge_watchdog())
    assert [list(links) for links, _ in sent] == [[HELD], ["45>i417/tcp"]]


def test_the_message_names_the_link_and_escapes_the_remark(monkeypatch):
    import sys
    import types

    captured = []

    async def fake_send(text):
        captured.append(text)

    monkeypatch.setitem(sys.modules, "app.notification.telegram",
                        types.SimpleNamespace(send_message=fake_send))
    monkeypatch.setitem(sys.modules, "app.config.env",
                        types.SimpleNamespace(TELEGRAM_ADMIN_ID=[]))
    asyncio.run(wd.notify_held_hides(
        {HELD: link(24)}, {HELD: [(506, "ELITE US <always>")]}))
    text = captured[0]
    assert "19&gt;ELITE US@n45/tcp" in text
    assert "24 провалов подряд" in text
    assert "последний видимый хост страны" in text
    assert "#506 ELITE US &lt;always&gt;" in text
