"""Keeping RU legs open without a human: what bridge_transit.py decides.

The decisions are pure functions over measured shares, so they are tested
without a single machine: a broken leg moves only after BAD_RUNS bad runs and
only to a relay that measured GOOD and that the source reaches; the better
share wins, load spreads equal relays; a leg nobody reaches stays put; an
automatic row gives the leg back once its baseline has held for HEAL_RUNS
runs; the new relay is pushed before the source, the old one drains.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
# the tools import marz_common, which refuses to load without _secrets.py
sys.modules.setdefault("marz_common", types.ModuleType("marz_common"))
import bridge_relay as brl  # noqa: E402
import bridge_transit as bt  # noqa: E402

_spec = importlib.util.spec_from_file_location("transit_probe", os.path.join(_TOOLS, "transit_probe.py"))
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

SRC, EXIT = "10.0.0.1", "10.0.0.9"
R50, R43, R40 = bt.RELAY_POOL[:3]
PANEL = bt.PANEL_IP


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(bt, "RELAY_CAP", 60)
    monkeypatch.setattr(bt, "LOAD_STEP", 8)


def leg(direct=0.0, eff=None, src=SRC, dst=EXIT, dport=49443, tag="nl-1-out"):
    return bt.Leg(src, dst, dport, "www.bol.com", tag, direct, eff)


def reach_all(src=SRC):
    return {(src, r): 1.0 for r in bt.RELAY_POOL}


def route(src, relay, rport, dst=EXIT, dport=49443, tag="x"):
    return brl.Route(src, relay, rport, dst, dport, tag)


# ── pick ─────────────────────────────────────────────────────────────

def test_the_better_share_wins_even_against_the_preferred_relay():
    q = {(R50, EXIT, 49443): 11 / 12, (R43, EXIT, 49443): 1.0}
    assert bt.pick(leg(), q, reach_all(), {}, None, None) == (R43, 1.0)


def test_equal_relays_share_the_work():
    q = {(R50, EXIT, 49443): 1.0, (R43, EXIT, 49443): 1.0}
    assert bt.pick(leg(), q, reach_all(), {}, None, None)[0] == R50
    assert bt.pick(leg(), q, reach_all(), {R50: 8}, None, None)[0] == R43


def test_a_relay_below_good_or_out_of_reach_is_no_candidate():
    q = {(R50, EXIT, 49443): 10 / 12, (R43, EXIT, 49443): 1.0}
    reach = {(SRC, R50): 1.0, (SRC, R43): 1 / 3}
    assert bt.pick(leg(), q, reach, {}, None, None) is None


def test_the_relay_the_leg_fails_on_now_is_not_offered_again():
    q = {(R50, EXIT, 49443): 1.0, (R43, EXIT, 49443): 1.0}
    assert bt.pick(leg(), q, reach_all(), {}, R50, None)[0] == R43


def test_a_full_relay_takes_no_more():
    q = {(R50, EXIT, 49443): 1.0}
    assert bt.pick(leg(), q, reach_all(), {R50: 60}, None, None) is None


def test_direct_is_offered_only_where_no_hand_kept_row_covers_the_leg():
    healed = leg(direct=1.0)
    assert bt.pick(healed, {}, reach_all(), {}, R50, None) == (None, 1.0)
    assert bt.pick(healed, {}, reach_all(), {}, R50, R40) is None


# ── plan ─────────────────────────────────────────────────────────────

def streaks_for(legs, bad, share):
    return {l.key: {"bad": bad, "heal": 0, "share": share} for l in legs}


def test_a_broken_leg_moves_only_after_bad_runs():
    l = leg(direct=0.0)
    q = {(R50, EXIT, 49443): 1.0}
    st = streaks_for([l], bt.BAD_RUNS - 1, 0.0)
    assert bt.plan([l], {}, {}, {}, st, q, reach_all(), {SRC})[0] == []
    st = streaks_for([l], bt.BAD_RUNS, 0.0)
    changes, stuck = bt.plan([l], {}, {}, {}, st, q, reach_all(), {SRC})
    assert changes == [((SRC, EXIT, 49443), R50, "moved", 1.0)] and stuck == []
    st = streaks_for([l], 1, 0.0)
    assert bt.plan([l], {}, {}, {}, st, q, reach_all(), {SRC}, now=True)[0]


def test_a_leg_nobody_reaches_is_left_alone_and_said_so():
    l = leg(direct=0.0)
    q = {(R50, EXIT, 49443): 0.0, (R43, EXIT, 49443): 0.0}
    changes, stuck = bt.plan([l], {}, {}, {}, streaks_for([l], 5, 0.0), q, reach_all(), {SRC})
    assert changes == [] and stuck[0]["reason"] == "nobody_reaches"
    q = {(R50, EXIT, 49443): 0.5}
    stuck = bt.plan([l], {}, {}, {}, streaks_for([l], 5, 0.0), q, reach_all(), {SRC})[1]
    assert stuck[0]["reason"] == "no_good_relay"


def test_an_automatic_row_returns_once_its_baseline_held_for_heal_runs():
    k = (SRC, EXIT, 49443)
    auto = {k: route(SRC, R50, 48000)}
    static = {k: route(SRC, R40, 47201)}
    l = leg(direct=0.0, eff=1.0)
    q = {(R40, EXIT, 49443): 1.0}
    st = {l.key: {"bad": 0, "heal": bt.HEAL_RUNS - 2, "share": 1.0}}
    assert bt.plan([l], static, auto, auto, st, q, reach_all(), {SRC})[0] == []
    changes = bt.plan([l], static, auto, auto, st, q, reach_all(), {SRC})[0]
    assert changes == [(k, None, "returned", 1.0)]


def test_a_leg_that_left_the_config_loses_its_row_only_if_its_node_answered():
    k = (SRC, EXIT, 49443)
    auto = {k: route(SRC, R50, 48000)}
    assert bt.plan([], {}, auto, auto, {}, {}, {}, {SRC})[0] == [(k, None, "gone", None)]
    assert bt.plan([], {}, auto, auto, {}, {}, {}, set())[0] == []


# ── rewrite / order ──────────────────────────────────────────────────

def test_a_panel_leg_brings_its_ssh_twin_on_free_automatic_ports():
    l = leg(src=PANEL, dst=SRC, dport=53042, tag="panel 25")
    merged = {(PANEL, SRC, 53042): route(PANEL, R40, 47490, SRC, 53042),
              (PANEL, SRC, 22): route(PANEL, R40, 47491, SRC, 22),
              (SRC, EXIT, 49443): route(SRC, R50, 48000)}
    new = bt.rewrite({}, [((PANEL, SRC, 53042), R50, "moved", 1.0)], merged,
                     {R50: {48001}}, {}, [l])
    grpc, ssh = new[(PANEL, SRC, 53042)], new[(PANEL, SRC, 22)]
    assert (grpc.relay, grpc.rport) == (R50, 48002)       # 48000 taken, 48001 listening
    assert (ssh.relay, ssh.rport) == (R50, 48003)
    assert ssh.tag.endswith(" ssh")
    back = bt.rewrite(new, [((PANEL, SRC, 53042), None, "returned", 1.0)], merged, {}, {}, [l])
    assert back == {}


def test_the_new_relay_goes_first_and_the_old_one_is_left_to_drain():
    k = (SRC, EXIT, 49443)
    old = {k: route(SRC, R40, 47201)}
    new = {k: route(SRC, R50, 48000)}
    assert bt.install_order(old, new, {k}) == [R50, SRC]
    assert bt.install_order(new, {}, {k}) == [SRC]       # back to direct


def test_the_automatic_table_round_trips_through_the_overlay():
    k = (SRC, EXIT, 49443)
    base = f"{SRC}  {R40}  47201  {EXIT}  49443  dc15 nl-1-out\n"
    text, eff = bt.effective(base, {k: route(SRC, R50, 48000, tag="auto n15 nl-1-out")})
    assert eff[k].relay == R50
    assert brl.parse_routes(bt.auto_text([route(SRC, R50, 48000, tag="auto n15 nl-1-out")]))


# ── the node-side probe ──────────────────────────────────────────────

def test_the_probe_reads_proxy_outbounds_and_skips_the_rest(tmp_path, monkeypatch):
    cfg = {"outbounds": [
        {"tag": "nl-1-out", "protocol": "vless",
         "settings": {"vnext": [{"address": "212.16.78.31", "port": 49443}]},
         "streamSettings": {"realitySettings": {"serverName": "www.bol.com"}}},
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "by-name", "protocol": "vless",
         "settings": {"vnext": [{"address": "example.com", "port": 443}]}},
        {"tag": "lan", "protocol": "vless",
         "settings": {"vnext": [{"address": "10.1.2.3", "port": 443}]}},
    ]}
    path = tmp_path / "xray_config.json"
    path.write_text(json.dumps(cfg))
    monkeypatch.setattr(probe, "XRAY_CONFIG", str(path))
    assert probe.config_legs() == [{"dst": "212.16.78.31", "dport": 49443,
                                    "sni": "www.bol.com", "tag": "nl-1-out"}]


def test_probe_bypass_ports_match_the_rule_and_cycle_through_the_range():
    lo, hi = (int(x) for x in brl.PROBE_BYPASS.split(":"))
    assert (lo, hi) == probe.BYPASS_PORTS
    seen = {probe._bypass_port() for _ in range(300)}
    assert min(seen) >= lo and max(seen) <= hi and len(seen) == hi - lo + 1
