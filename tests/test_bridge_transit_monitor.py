"""What #BridgeTransit says, and how often.

One message per batch of new moves, never the same event twice -- not on the
next tick and not after a panel restart; what was in the status before the
alarm first ran is history. Only rollbacks and legs with no path call people.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from app.tasks import bridge_transit_monitor as m


def event(n, kind="moved", **extra):
    e = {"id": f"{1000 + n}-0-leg{n}", "ts": 1000 + n, "kind": kind,
         "leg": f"178.57.222.142>132.243.204.182:{44443 + n}",
         "src": "47 🇷🇺 IHC RU-1", "tag": "fr-out", "dst": "17 🇫🇷 FR",
         "from": "direct", "to": "185.179.189.226",
         "from_name": "direct", "to_name": "50 🇷🇺 Webhost1.ru RU-2",
         "before": 0.0, "after": 1.0}
    e.update(extra)
    return e


@pytest.fixture
def alarm(tmp_path, monkeypatch):
    sent = {"events": [], "stale": []}

    async def fake_events(events):
        sent["events"].append([e["id"] for e in events])
        return True

    async def fake_stale(minutes):
        sent["stale"].append(minutes)

    status = tmp_path / "bridge_transit.status"
    monkeypatch.setattr(m, "STATUS_PATH", str(status))
    monkeypatch.setattr(m, "NOTIFIED_PATH", str(tmp_path / "notified.json"))
    monkeypatch.setattr(m, "notify_events", fake_events)
    monkeypatch.setattr(m, "notify_stale", fake_stale)
    monkeypatch.setattr(m, "_last_stale_alert_ts", 0.0)

    def tick(events, updated_at=None):
        status.write_text(json.dumps({"updated_at": updated_at or int(time.time()),
                                      "events": events}))
        asyncio.run(m.check_bridge_transit())
        return sent

    return tick


def test_what_was_there_before_the_alarm_is_history(alarm):
    sent = alarm([event(1), event(2)])
    assert sent["events"] == []
    sent = alarm([event(1), event(2), event(3)])
    assert sent["events"] == [[event(3)["id"]]]


def test_an_event_is_told_once(alarm):
    alarm([])
    alarm([event(1)])
    sent = alarm([event(1)])
    assert sent["events"] == [[event(1)["id"]]]


def test_a_silent_timer_is_reported_once_per_cooldown(alarm):
    old = int(time.time()) - m.STALE_SEC - 600
    alarm([], updated_at=old)
    sent = alarm([], updated_at=old)
    assert len(sent["stale"]) == 1


def test_the_message_names_the_leg_the_relay_and_the_shares(monkeypatch):
    texts = []

    async def fake_send(text):
        texts.append(text)
        return True

    monkeypatch.setattr(m, "_send", fake_send)
    monkeypatch.setattr(m, "_admin_tags", lambda: "\nADMINS")
    asyncio.run(m.notify_events([event(1)]))
    assert "47 IHC RU-1 → <code>fr-out</code> (17 FR)" in texts[0]
    assert "напрямую → 50 Webhost1.ru RU-2, было 0%, стало 100%" in texts[0]
    assert "ADMINS" not in texts[0]
    asyncio.run(m.notify_events([event(2, kind="no_path", share=0.0, best=0.5)]))
    assert "Нет рабочего пути" in texts[1] and "лучший релей 50%" in texts[1]
    assert texts[1].endswith("ADMINS")
