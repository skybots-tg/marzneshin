"""Which nodes the panel is allowed to call unusable from Russia.

The panel talks to every node from Norway, so its own health flag cannot answer
this; the audit's RU vantages can. The rule these tests pin down is the careful
half of that: a bridge failure is one entry and one exit failing together, and
charging it to both ends would condemn healthy Russian entries for serving a
broken exit. Only a side with nothing working at all is called dead.
"""

from __future__ import annotations

import json
import time

import pytest

from app.services import bridge_health_service as svc


@pytest.fixture
def probe(tmp_path, monkeypatch):
    """Point the reader at throwaway files and hand back a writer for them."""
    report = tmp_path / "bridge_audit.json"
    state = tmp_path / "bridge_state.json"
    monkeypatch.setattr(svc, "REPORT_PATH", str(report))
    monkeypatch.setattr(svc, "STATE_PATH", str(state))
    monkeypatch.setattr(svc, "_ru_probe_cache", None)

    def write(hosts, links):
        report.write_text(json.dumps({"hosts": hosts}), encoding="utf-8")
        state.write_text(json.dumps({
            "links": {k: ({"pass_streak": 3, "fail_streak": 0} if up else
                          {"pass_streak": 0, "fail_streak": 5})
                      for k, up in links.items()},
            "updated_at": int(time.time()),
        }), encoding="utf-8")
        svc._ru_probe_cache = None
        return svc.node_ru_probe()

    return write


def leg(link, entry, exit_id, audience="RU"):
    return {"link": link, "node_id": entry, "exit_node_id": exit_id,
            "audience": audience}


def test_exit_with_every_leg_down_is_unreachable(probe):
    result = probe(
        [leg("15>NL-2/tcp", 15, 39), leg("30>NL-2/tcp", 30, 39),
         leg("40>NL-2/tcp", 40, 39)],
        {"15>NL-2/tcp": False, "30>NL-2/tcp": False, "40>NL-2/tcp": False},
    )
    assert result[39]["unreachable"] is True
    assert result[39]["reason"] == "exit"
    assert (result[39]["exit_ok"], result[39]["exit_total"]) == (0, 3)


def test_one_working_leg_clears_both_ends(probe):
    """A route that works proves each of its ends is reachable."""
    result = probe(
        [leg("15>NL-2/tcp", 15, 39), leg("30>NL-2/tcp", 30, 39)],
        {"15>NL-2/tcp": True, "30>NL-2/tcp": False},
    )
    assert result[39]["unreachable"] is False
    # ...and the entry whose only probed leg failed is not condemned for it
    # either: the far end is the other suspect, and it is the one that is down.
    assert result[30]["unreachable"] is False


def test_a_single_failing_leg_says_nothing_about_the_exit(probe):
    """One entry's opinion is not a verdict on the far end."""
    result = probe([leg("15>NL-2/tcp", 15, 39)], {"15>NL-2/tcp": False})
    assert result[39]["unreachable"] is False
    # The entry is a different matter: every route it offers is down.
    assert result[15]["unreachable"] is True
    assert result[15]["reason"] == "entry"


def test_entry_that_answers_nowhere_is_unreachable(probe):
    result = probe(
        [leg("13>DE/tcp", 13, 27), leg("13>NL/tcp", 13, 20),
         leg("13>TR/tcp", 13, 26)],
        {"13>DE/tcp": False, "13>NL/tcp": False, "13>TR/tcp": False},
    )
    assert result[13]["reason"] == "entry"
    assert (result[13]["entry_ok"], result[13]["entry_total"]) == (0, 3)


def test_fast_tier_is_not_evidence_about_russia(probe):
    """FAST is judged from abroad, so its rows carry no RU verdict to read."""
    result = probe(
        [leg("39>i243/tcp", 39, None, audience="FOREIGN")],
        {"39>i243/tcp": False},
    )
    assert 39 not in result


def test_no_audit_yet_accuses_nobody(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "REPORT_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(svc, "STATE_PATH", str(tmp_path / "gone.json"))
    monkeypatch.setattr(svc, "_ru_probe_cache", None)
    assert svc.node_ru_probe() == {}
