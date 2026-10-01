"""What the #FrontReach alarm says, and how often.

Once when an episode opens, once when it closes, and never again for the same
one — not on the next tick and not after a panel restart in the middle of it.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from app.tasks import front_reach_monitor as m


def episode(started_at=1000, node_id=48, front="www.elisa.ee", **extra):
    ep = {"id": f"{node_id}|{front}:443|{started_at}", "node_id": node_id,
          "name": "EE-1", "address": "217.146.76.253", "front": front,
          "port": 443, "ips": ["194.150.66.65"], "inbounds": 1,
          "started_at": started_at, "detected_at": started_at + 300,
          "reason": "connect: timed out", "max_syn_sent": 4800}
    ep.update(extra)
    return ep


@pytest.fixture
def alarm(tmp_path, monkeypatch):
    sent = {"open": [], "closed": [], "stale": []}

    async def fake_open(eps):
        sent["open"].append([ep["id"] for ep in eps])
        return True

    async def fake_closed(eps, announced):
        sent["closed"].append([(ep["id"], ep["id"] in announced) for ep in eps])
        return True

    async def fake_stale(minutes):
        sent["stale"].append(minutes)

    monkeypatch.setattr(m, "notify_unreachable", fake_open)
    monkeypatch.setattr(m, "notify_recovered", fake_closed)
    monkeypatch.setattr(m, "notify_check_stale", fake_stale)
    monkeypatch.setattr(m, "_last_stale_alert_ts", 0.0)
    status = tmp_path / "front_reach.status"
    monkeypatch.setattr(m, "STATUS_PATH", str(status))
    monkeypatch.setattr(m, "NOTIFIED_PATH", str(tmp_path / "notified.json"))

    def write(open_=(), closed=(), age=0):
        status.write_text(json.dumps({
            "generated_at": int(time.time()) - age,
            "open": list(open_), "closed": list(closed)}))

    def tick():
        asyncio.run(m.check_front_reach())

    return sent, write, tick


def test_no_status_no_words(alarm):
    sent, _, tick = alarm
    tick()
    assert sent == {"open": [], "closed": [], "stale": []}


def test_an_episode_is_announced_once(alarm):
    sent, write, tick = alarm
    write(open_=[episode()])
    tick()
    tick()
    assert sent["open"] == [["48|www.elisa.ee:443|1000"]]


def test_a_restart_mid_episode_does_not_repeat_it(alarm, monkeypatch):
    sent, write, tick = alarm
    write(open_=[episode()])
    tick()
    # Nothing in memory survives a restart; only the file does.
    monkeypatch.setattr(m, "_last_stale_alert_ts", 0.0)
    tick()
    assert len(sent["open"]) == 1


def test_the_end_is_reported_once_and_tied_to_the_start(alarm):
    sent, write, tick = alarm
    write(open_=[episode()])
    tick()
    ended = episode(ended_at=3000, resolution="recovered")
    write(closed=[ended])
    tick()
    tick()
    assert sent["closed"] == [[("48|www.elisa.ee:443|1000", True)]]


def test_history_from_before_the_alarm_is_not_news(alarm):
    sent, write, tick = alarm
    write(closed=[episode(ended_at=3000, resolution="recovered")])
    tick()
    assert sent["closed"] == []


def test_an_episode_that_opened_and_closed_unseen_is_still_reported(alarm):
    """The panel was down for the whole of it: the end says so."""
    sent, write, tick = alarm
    write()
    tick()  # the alarm has run before
    write(closed=[episode(ended_at=3000, resolution="recovered")])
    tick()
    assert sent["closed"] == [[("48|www.elisa.ee:443|1000", False)]]


def test_a_new_wave_is_a_new_episode(alarm):
    sent, write, tick = alarm
    first = episode(started_at=1000)
    write(open_=[first])
    tick()
    write(closed=[dict(first, ended_at=3000, resolution="recovered")])
    tick()
    write(open_=[episode(started_at=7000)],
          closed=[dict(first, ended_at=3000, resolution="recovered")])
    tick()
    assert sent["open"] == [["48|www.elisa.ee:443|1000"],
                            ["48|www.elisa.ee:443|7000"]]


def test_a_stopped_timer_is_called_out_once(alarm):
    sent, write, tick = alarm
    write(age=m.STALE_SEC + 600)
    tick()
    tick()
    assert sent["stale"] == [(m.STALE_SEC + 600) // 60]


def test_a_fresh_status_is_not_stale(alarm):
    sent, write, tick = alarm
    write(age=m.STALE_SEC - 60)
    tick()
    assert sent["stale"] == []


def test_messages_render(monkeypatch):
    texts = []

    async def fake_send(text):
        texts.append(text)
        return True

    monkeypatch.setattr(m, "_send", fake_send)
    monkeypatch.setattr(m, "_admin_tags", lambda: "")
    ep = episode(name="🇪🇪 Zone.eu <EE-1>")
    assert asyncio.run(m.notify_unreachable([ep]))
    assert "#FrontReach" in texts[0] and "&lt;EE-1&gt;" in texts[0]
    assert "217.146.76.253" in texts[0] and "SYN-SENT: 4800" in texts[0]
    done = dict(ep, ended_at=1000 + 3 * 3600 + 5 * 60, resolution="recovered")
    assert asyncio.run(m.notify_recovered([done], set()))
    assert "3 ч 05 мин" in texts[1] and "начало не сообщалось" in texts[1]
