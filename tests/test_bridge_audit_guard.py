"""When the bridge audit may act on a run in which many visible hosts failed.

The guard exists for a panel that lost its own egress: then every probe fails
and acting would empty every subscription. It must not also fire on a real
outage -- 21.10.2026 a genuine 55% of the visible hosts went dark, every run
was refused, and the dead hosts stayed in subscriptions for four days.
"""

from __future__ import annotations

import os
import sys
import types

_TOOLS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
# The audit locks its state with fcntl; the guard never touches the lock, and
# the tests also run on machines without the module.
sys.modules.setdefault("fcntl", types.ModuleType("fcntl"))

import bridge_audit as ba  # noqa: E402


def report(passed: int, failed: int, skipped: int = 0, hidden_failed: int = 0):
    hosts = (
        [{"is_disabled": False, "verdict": "pass"}] * passed
        + [{"is_disabled": False, "verdict": "fail"}] * failed
        + [{"is_disabled": False, "verdict": "skip"}] * skipped
        # The graveyard fails by definition and says nothing about the panel.
        + [{"is_disabled": True, "verdict": "fail"}] * hidden_failed
    )
    return {"hosts": hosts, "changes": {"disable": [], "enable": []}}


def args(force=False):
    return types.SimpleNamespace(max_fail_pct=ba.MAX_VISIBLE_FAIL_PCT, force=force)


def test_a_blind_panel_is_refused():
    assert ba.apply_report(report(passed=3, failed=97), [], args()) == 3


def test_a_wide_real_outage_is_acted_on():
    # The 25.10.2026 picture: 58 of 102 visible hosts dead, 44 still answering.
    assert ba.apply_report(report(passed=44, failed=58), [], args()) == 0


def test_hosts_a_quick_run_skipped_do_not_count_as_silence():
    # 10 answered out of 30 probed is a third of the evidence, not a tenth.
    assert ba.apply_report(report(passed=10, failed=20, skipped=70), [], args()) == 0


def test_hidden_failures_do_not_trip_the_guard():
    assert ba.apply_report(report(passed=95, failed=5, hidden_failed=200), [], args()) == 0


def test_force_overrides_a_blind_run():
    assert ba.apply_report(report(passed=0, failed=100), [], args(force=True)) == 0


def test_a_small_recheck_is_not_judged_at_all():
    assert ba.apply_report(report(passed=0, failed=ba.MIN_HOSTS_FOR_GUARD - 1), [], args()) == 0
