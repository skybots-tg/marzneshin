"""Rules the bridge auto-hide obeys, spelled out as tests.

``tools/bridge_state.py`` is what decides whether a location disappears from
every user's subscription, so each rule that protects a working server gets its
own case here. The module is deliberately dependency-free, which is why it can
be imported straight off disk rather than through the ``app`` package.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time

import pytest

_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools", "bridge_state.py",
)
_spec = importlib.util.spec_from_file_location("bridge_state", _STATE_PATH)
bs = importlib.util.module_from_spec(_spec)
# Registered before execution because @dataclass resolves annotations through
# sys.modules; without this the module's own classes cannot be built.
sys.modules["bridge_state"] = bs
_spec.loader.exec_module(bs)

BUSY = bs.SILENT_NODE_BYTES * 100
LINK = "25>FR/tcp"


class FakeTarget:
    """The handful of Target attributes roll_up actually reads."""

    def __init__(self, host_id, verdict, *, link=LINK, node_id=25,
                 is_disabled=False, remark=None, exit_node_id=14,
                 witnesses=3, slot="FR", entry_key="universal-2"):
        self.host_id = host_id
        self.link_key = link
        self.node_id = node_id
        self.node_name = "AdminVPS RU-2"
        self.node_status = "healthy"
        self.exit_node_id = exit_node_id
        self.slot = slot
        self.variant = "tcp"
        self.entry_key = entry_key
        self.is_bridge = True
        self.is_disabled = is_disabled
        self.remark = remark or f"host-{host_id}"
        self.result = {"verdict": verdict, "witnesses": witnesses}


def run(targets, state=None, traffic=None, statuses=None, **kwargs):
    state = state if state is not None else bs.load("/nonexistent/state.json")
    links = bs.roll_up(targets)
    return links, state, bs.decide(
        links, state,
        traffic if traffic is not None else {25: BUSY, 14: BUSY},
        statuses or {25: "healthy", 14: "healthy"},
        remark_of={t.host_id: t.remark for t in targets},
        **kwargs,
    )


def test_one_bad_run_hides_nothing():
    _, state, decisions = run([FakeTarget(1, "fail")])
    assert decisions["disable"] == []
    assert state["links"][LINK]["fail_streak"] == 1


def test_second_consecutive_failure_hides_the_link():
    targets = [FakeTarget(1, "fail"), FakeTarget(2, "fail")]
    _, state, _ = run(targets)
    _, _, decisions = run(targets, state)
    assert decisions["disable"] == [1, 2]


def test_a_recovery_between_failures_resets_the_streak():
    _, state, _ = run([FakeTarget(1, "fail")])
    _, state, _ = run([FakeTarget(1, "pass")], state)
    _, _, decisions = run([FakeTarget(1, "fail")], state)
    assert decisions["disable"] == []


def test_a_live_sibling_keeps_the_link_up():
    """One broken host next to a working one is a config bug, not an outage."""
    targets = [FakeTarget(1, "fail"), FakeTarget(2, "pass")]
    links, _, decisions = run(targets)
    assert links[LINK].verdict == "up"
    assert decisions["disable"] == []


def test_wrong_geo_still_counts_as_traffic_flowing():
    links, _, decisions = run([FakeTarget(1, "wrong_geo")])
    assert links[LINK].verdict == "up"
    assert decisions["disable"] == []


def test_a_reachable_node_moving_nothing_is_hidden_at_once():
    """The panel can see the node, and it has carried nothing: that is real."""
    _, _, decisions = run(
        [FakeTarget(1, "fail")], traffic={25: 0, 14: 0},
        statuses={25: "healthy", 14: "healthy"},
    )
    assert decisions["disable"] == [1]
    assert decisions["links"][LINK]["reason"] == "node_silent"


def test_an_unreachable_node_reports_silence_it_has_not_earned():
    """Usage is collected over the same gRPC link the health flag rides.

    A node the panel cannot route to always reads zero bytes, whether or not
    its users are happily connected, so the shortcut must not fire.
    """
    _, _, decisions = run(
        [FakeTarget(1, "fail")], traffic={25: 0, 14: BUSY},
        statuses={25: "unhealthy", 14: "healthy"},
    )
    assert decisions["disable"] == []
    assert decisions["links"][LINK]["reason"] == "link_down_pending"


def test_one_witness_cannot_take_the_shortcut():
    lone = [FakeTarget(1, "fail", witnesses=1)]
    _, _, decisions = run(lone, traffic={25: 0, 14: 0},
                          statuses={25: "healthy", 14: "healthy"})
    assert decisions["disable"] == []
    assert decisions["links"][LINK]["reason"] == "link_down_pending_alone"


def test_one_witness_still_acts_once_it_has_persisted():
    lone = [FakeTarget(1, "fail", witnesses=1)]
    state = bs.load("/nonexistent/state.json")
    for _ in range(bs.FAIL_STREAK_SINGLE_WITNESS - 1):
        _, state, decisions = run(lone, state)
        assert decisions["disable"] == []
    _, state, decisions = run(lone, state)
    assert decisions["disable"] == [1]


def test_one_failing_link_beside_working_ones_is_not_contested():
    """A busy node proves nothing about one leg among many."""
    targets = [FakeTarget(1, "fail"),
               FakeTarget(2, "pass", link="25>DE/tcp")]
    _, _, decisions = run(targets)
    assert decisions["links"][LINK]["contested"] is False


def test_a_node_failing_everywhere_while_busy_is_not_believed():
    """Fifteen legs do not die in the same second; the probe lost its footing."""
    targets = [FakeTarget(1, "fail"),
               FakeTarget(2, "fail", link="25>DE/tcp"),
               FakeTarget(3, "fail", link="25>NL/tcp")]
    _, state, _ = run(targets)
    _, _, decisions = run(targets, state)
    assert decisions["disable"] == []
    assert decisions["links"][LINK]["contested"] is True
    assert decisions["links"][LINK]["reason"] == "node_unreachable_but_busy"


def test_a_node_failing_everywhere_and_silent_is_believed():
    targets = [FakeTarget(1, "fail"), FakeTarget(2, "fail", link="25>DE/tcp")]
    _, _, decisions = run(targets, traffic={25: 0, 14: 0},
                          statuses={25: "unhealthy", 14: "healthy"})
    assert decisions["disable"] == [1, 2]


def test_skipped_links_do_not_age_the_streak():
    _, state, _ = run([FakeTarget(1, "fail")])
    _, state, decisions = run([FakeTarget(1, "skip")], state)
    assert decisions["disable"] == []
    assert state["links"][LINK]["fail_streak"] == 1


def test_only_hosts_this_module_hid_come_back():
    """A host hidden by hand stays hidden however well it probes."""
    hidden_by_hand = [FakeTarget(9, "pass", is_disabled=True)]
    _, state, _ = run(hidden_by_hand)
    _, _, decisions = run(hidden_by_hand, state)
    assert decisions["enable"] == []


def test_a_link_that_recovers_restores_what_it_hid():
    failing = [FakeTarget(1, "fail")]
    _, state, _ = run(failing)
    _, state, decisions = run(failing, state)
    assert decisions["disable"] == [1]

    recovered = [FakeTarget(1, "pass", is_disabled=True)]
    _, state, _ = run(recovered, state)
    _, state, decisions = run(recovered, state)
    assert decisions["enable"] == [1]
    assert "1" not in state["auto_disabled"]


def test_restore_waits_for_the_node_to_carry_traffic_again():
    failing = [FakeTarget(1, "fail")]
    _, state, _ = run(failing)
    _, state, _ = run(failing, state)

    recovered = [FakeTarget(1, "pass", is_disabled=True)]
    quiet = {"traffic": {25: 0, 14: 0},
             "statuses": {25: "unhealthy", 14: "healthy"}}
    _, state, _ = run(recovered, state, **quiet)
    _, state, decisions = run(recovered, state, **quiet)
    assert decisions["enable"] == []
    assert decisions["links"][LINK]["reason"] == "held_no_traffic"
    # A passing link held back from restore is not a contested failure; a brand
    # new node trips this on every link and must not read as an outage.
    assert decisions["links"][LINK]["restore_held"] is True
    assert decisions["links"][LINK]["contested"] is False


def test_a_visible_twin_blocks_the_restore():
    """Two identical names in one subscription is worse than one hidden host."""
    failing = [FakeTarget(1, "fail", remark="FR")]
    _, state, _ = run(failing)
    _, state, _ = run(failing, state)

    recovered = [FakeTarget(1, "pass", is_disabled=True, remark="FR")]
    links = bs.roll_up(recovered)
    bs.decide(links, state, {25: BUSY, 14: BUSY}, {25: "healthy"},
              visible_by_remark={"FR": [77]}, remark_of={1: "FR"})
    decisions = bs.decide(
        links, state, {25: BUSY, 14: BUSY}, {25: "healthy"},
        visible_by_remark={"FR": [77]}, remark_of={1: "FR"})
    assert decisions["enable"] == []


def test_an_unconfirmed_failure_never_finishes_a_streak():
    """A quick run may start the clock; only a thorough one may act on it."""
    targets = [FakeTarget(1, "fail")]
    state = bs.load("/nonexistent/state.json")
    for _ in range(4):
        links = bs.roll_up(targets)
        decisions = bs.decide(links, state, {25: BUSY, 14: BUSY},
                              {25: "healthy", 14: "healthy"},
                              confirmed_links=set())
    assert decisions["disable"] == []
    assert decisions["links"][LINK]["reason"] == "unconfirmed"
    assert state["links"][LINK]["fail_streak"] == 4


def test_a_confirmed_failure_acts_on_the_streak_it_inherited():
    targets = [FakeTarget(1, "fail")]
    state = bs.load("/nonexistent/state.json")
    links = bs.roll_up(targets)
    bs.decide(links, state, {25: BUSY, 14: BUSY}, {25: "healthy"},
              confirmed_links=set())
    decisions = bs.decide(links, state, {25: BUSY, 14: BUSY}, {25: "healthy"},
                          confirmed_links={LINK})
    assert decisions["disable"] == [1]


def test_the_node_wide_rule_is_off_for_a_filtered_scan():
    """Probing three links of a node says nothing about the other twelve."""
    targets = [FakeTarget(1, "fail"), FakeTarget(2, "fail", link="25>DE/tcp")]
    _, state, _ = run(targets)
    links = bs.roll_up(targets)
    decisions = bs.decide(links, state, {25: BUSY, 14: BUSY}, {25: "healthy"},
                          node_wide_rule=False)
    assert decisions["links"][LINK]["contested"] is False
    assert decisions["disable"] == [1, 2]


def test_links_that_leave_the_fleet_are_forgotten():
    _, state, _ = run([FakeTarget(1, "fail")])
    assert LINK in state["links"]
    run([FakeTarget(2, "pass", link="30>DE/tcp", node_id=30)], state)
    assert LINK not in state["links"]


@pytest.mark.parametrize("verdicts,expected", [
    (["fail", "fail"], "down"),
    (["fail", "pass"], "up"),
    (["skip", "skip"], "skip"),
    (["skip", "fail"], "down"),
])
def test_link_verdict_rollup(verdicts, expected):
    targets = [FakeTarget(i, v) for i, v in enumerate(verdicts, start=1)]
    assert bs.roll_up(targets)[LINK].verdict == expected


# --------------------------------------------------------------------------
# the far end of a bridge: one dead exit used to leave eight entries at once
# --------------------------------------------------------------------------


def legs_to_one_exit(verdict, count=3, exit_node_id=14):
    """The same exit slot reached from several different entry nodes."""
    return [
        FakeTarget(i, verdict, link=f"{20 + i}>FR/tcp", node_id=20 + i,
                   entry_key=f"universal-{i}", exit_node_id=exit_node_id)
        for i in range(1, count + 1)
    ]


def busy_everywhere(targets, exit_node_id=14):
    traffic = {t.node_id: BUSY for t in targets}
    traffic[exit_node_id] = BUSY
    statuses = {t.node_id: "healthy" for t in targets}
    statuses[exit_node_id] = "healthy"
    return {"traffic": traffic, "statuses": statuses}


def test_an_exit_carrying_its_usual_load_is_believed_over_the_probe():
    """Every entry's leg to one exit failing is a claim about the exit."""
    targets = legs_to_one_exit("fail")
    world = busy_everywhere(targets)
    _, state, _ = run(targets, traffic_ratio={14: 0.9}, **world)
    _, _, decisions = run(targets, state, traffic_ratio={14: 0.9}, **world)
    assert decisions["disable"] == []
    reasons = {n["reason"] for n in decisions["links"].values()}
    assert reasons == {"exit_unreachable_but_busy"}


def test_an_exit_whose_traffic_collapsed_is_taken_at_the_probes_word():
    """20 MB where 5 GB is normal: the probe has corroboration, so act."""
    targets = legs_to_one_exit("fail")
    world = busy_everywhere(targets)
    _, state, _ = run(targets, traffic_ratio={14: 0.004}, **world)
    _, _, decisions = run(targets, state, traffic_ratio={14: 0.004}, **world)
    assert decisions["disable"] == [1, 2, 3]
    assert {n["reason"] for n in decisions["links"].values()} == {"exit_down"}


def test_an_exit_with_no_history_earns_neither_belief():
    """A brand new exit gets the ordinary streak rules, nothing more."""
    targets = legs_to_one_exit("fail")
    world = busy_everywhere(targets)
    _, state, _ = run(targets, **world)
    _, _, decisions = run(targets, state, **world)
    assert decisions["disable"] == [1, 2, 3]
    assert {n["reason"] for n in decisions["links"].values()} == {"link_down"}


def test_one_leg_says_nothing_about_the_exit():
    targets = legs_to_one_exit("fail", count=1)
    world = busy_everywhere(targets)
    _, state, _ = run(targets, traffic_ratio={14: 0.9}, **world)
    _, _, decisions = run(targets, state, traffic_ratio={14: 0.9}, **world)
    assert decisions["disable"] == [1]


def test_a_working_leg_keeps_the_exit_out_of_it():
    """If one entry still gets through, the far end is not the story."""
    targets = legs_to_one_exit("fail") + [
        FakeTarget(9, "pass", link="99>FR/tcp", node_id=99,
                   entry_key="universal-9")]
    world = busy_everywhere(targets)
    _, state, _ = run(targets, traffic_ratio={14: 0.9}, **world)
    _, _, decisions = run(targets, state, traffic_ratio={14: 0.9}, **world)
    assert decisions["disable"] == [1, 2, 3]


def test_the_exit_rule_is_off_for_a_filtered_scan():
    targets = legs_to_one_exit("fail")
    world = busy_everywhere(targets)
    _, state, _ = run(targets, traffic_ratio={14: 0.9},
                      exit_wide_rule=False, **world)
    _, _, decisions = run(targets, state, traffic_ratio={14: 0.9},
                          exit_wide_rule=False, **world)
    assert decisions["disable"] == [1, 2, 3]


# --------------------------------------------------------------------------
# how much of the catalogue one run may take
# --------------------------------------------------------------------------


def many_failing_links(count):
    """Failing legs on different entries, each to its own busy exit slot.

    Distinct slots keep the exit-wide rule out of these cases: they are about
    the rate limits, and a shared exit would hand every one of them the same
    verdict for a different reason.
    """
    return [
        FakeTarget(i, "fail", link=f"{20 + i}>S{i}/tcp", node_id=20 + i,
                   entry_key=f"universal-{i}", slot=f"S{i}",
                   exit_node_id=14)
        for i in range(1, count + 1)
    ]


def counts_for(targets, per_entry=4, per_slot=4):
    return {
        "entry": {t.entry_key: per_entry for t in targets},
        "slot": {t.slot: per_slot for t in targets},
        "total": per_entry * len(targets),
    }


def confirm_twice(targets, **kwargs):
    _, state, _ = run(targets, **kwargs)
    return run(targets, state, **kwargs)


def test_a_run_may_not_empty_the_catalogue_in_one_go():
    targets = many_failing_links(10)
    world = busy_everywhere(targets)
    _, _, decisions = confirm_twice(
        targets, visible_counts=counts_for(targets),
        limits={"per_run": 4}, **world)
    assert len(decisions["disable"]) == 4
    assert len(decisions["deferred"]) == 6
    assert {d["deferred"] for d in decisions["deferred"]} == {"rate_limit_run"}


def test_a_deferred_link_keeps_its_streak_and_comes_back():
    targets = many_failing_links(6)
    world = busy_everywhere(targets)
    kwargs = dict(visible_counts=counts_for(targets), limits={"per_run": 2})
    _, state, _ = run(targets, **kwargs, **world)
    _, state, first = run(targets, state, **kwargs, **world)
    assert len(first["disable"]) == 2
    # Nothing was forgotten: the next run picks up where the budget stopped.
    _, state, second = run(targets, state, **kwargs, **world)
    assert len(second["disable"]) == 2
    assert state["links"]["21>S1/tcp"]["fail_streak"] >= 2


def test_the_last_visible_host_of_an_entry_is_not_taken_quietly():
    targets = many_failing_links(2)
    world = busy_everywhere(targets)
    counts = counts_for(targets, per_entry=1, per_slot=4)
    _, _, decisions = confirm_twice(
        targets, visible_counts=counts, limits={"keep_per_entry": 1}, **world)
    assert decisions["disable"] == []
    assert {d["deferred"] for d in decisions["deferred"]} == {
        "last_visible_entry"}


def test_the_last_visible_host_of_a_country_is_not_taken_quietly():
    targets = many_failing_links(2)
    world = busy_everywhere(targets)
    counts = counts_for(targets, per_entry=4, per_slot=1)
    _, _, decisions = confirm_twice(
        targets, visible_counts=counts, limits={"keep_per_slot": 1}, **world)
    assert decisions["disable"] == []
    assert {d["deferred"] for d in decisions["deferred"]} == {
        "last_visible_slot"}


def test_the_days_allowance_is_spent_across_runs():
    targets = many_failing_links(8)
    world = busy_everywhere(targets)
    counts = dict(counts_for(targets), total=20)
    kwargs = dict(visible_counts=counts,
                  limits={"per_run": 10, "per_day_pct": 15})
    _, state, _ = run(targets, **kwargs, **world)
    _, state, first = run(targets, state, **kwargs, **world)
    assert len(first["disable"]) == 3          # 15% of 20
    _, state, second = run(targets, state, **kwargs, **world)
    assert second["disable"] == []
    assert {d["deferred"] for d in second["deferred"]} == {"rate_limit_day"}


def test_a_hide_the_traffic_counters_confirm_ignores_the_allowance():
    """Corroborated verdicts are not the failure mode the brakes are for."""
    targets = many_failing_links(6)
    traffic = {t.node_id: 0 for t in targets}
    statuses = {t.node_id: "healthy" for t in targets}
    _, _, decisions = confirm_twice(
        targets, traffic=traffic, statuses=statuses,
        visible_counts=counts_for(targets, per_entry=1, per_slot=1),
        limits={"per_run": 1, "keep_per_entry": 1, "keep_per_slot": 1})
    assert len(decisions["disable"]) == 6
    assert decisions["deferred"] == []


# --------------------------------------------------------------------------
# the dead man's switch
# --------------------------------------------------------------------------


def test_a_healthy_audit_releases_nothing():
    state = {"auto_disabled": {"1": {"at": int(time.time()) - 600}},
             "scanned_at": int(time.time()) - 60, "links": {}}
    assert bs.hides_to_release(state) == {}


def test_a_silent_audit_hands_back_its_recent_hides():
    now = time.time()
    state = {
        "links": {},
        "scanned_at": int(now) - 5 * 3600,
        "auto_disabled": {
            "1": {"at": int(now) - 3600},        # hidden just before it died
            "2": {"at": int(now) - 40 * 3600},   # long-standing, stands
        },
    }
    assert sorted(bs.hides_to_release(state, now=now)) == [1]


def test_releasing_keeps_the_trail():
    state = bs.load("/nonexistent/state.json")
    state["auto_disabled"]["7"] = {"link": LINK, "at": 1}
    bs.release(state, [7], by="watchdog_stalled")
    assert "7" not in state["auto_disabled"]
    assert state["released"]["7"]["released_by"] == "watchdog_stalled"


def test_a_state_nobody_ever_scanned_reads_as_ancient():
    assert bs.scan_age({}) > 10 ** 8
