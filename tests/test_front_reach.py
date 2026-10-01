"""When a node's front stops answering, and when that becomes an episode.

front_reach.py imports marz_common, which refuses to load without _secrets.py;
the episode logic and the node-side script do not need it. What must hold: one
bad run is not an outage, two are; one good run in the middle of a ban wave
does not close it; a node we could not ask says nothing either way; and the
node-side script reads REALITY fronts and SYN-SENT sockets the way the kernel
writes them.
"""
from __future__ import annotations

import os
import sys
import types

sys.modules.setdefault("marz_common", types.ModuleType("marz_common"))
_TOOLS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import front_reach as fr  # noqa: E402

NODES = {48: {"address": "217.146.76.253", "name": "EE-1", "status": "healthy"},
         10: {"address": "84.201.177.241", "name": "Y-0", "status": "healthy"}}


def row(front="www.elisa.ee", ok=True, syn=0, ips=("194.150.66.65",)):
    return {"front": front, "port": 443, "inbounds": ["Estonia-1"],
            "ips": list(ips), "ok": ok, "ms": 3 if ok else None,
            "error": None if ok else "194.150.66.65: timed out",
            "syn_sent": syn}


def run(state, now, **per_node):
    results = {48: {"fronts": [per_node.get("ee", row())]}}
    if "y0" in per_node:
        results[10] = per_node["y0"]
    return fr.advance(state, NODES, results, now)


def test_one_bad_run_is_not_an_outage():
    state, opened, closed = run({}, 1000, ee=row(ok=False))
    assert opened == [] and closed == []
    state, opened, _ = run(state, 1300, ee=row())
    assert opened == []
    assert state["fronts"]["48|www.elisa.ee:443"]["episode"] is None


def test_two_bad_runs_open_an_episode_dated_from_the_first():
    state, _, _ = run({}, 1000, ee=row(ok=False))
    state, opened, _ = run(state, 1300, ee=row(ok=False, syn=4800))
    assert len(opened) == 1
    ep = opened[0]
    assert ep["started_at"] == 1000 and ep["detected_at"] == 1300
    assert ep["node_id"] == 48 and ep["front"] == "www.elisa.ee"
    assert ep["address"] == "217.146.76.253"
    assert ep["id"] == "48|www.elisa.ee:443|1000"
    assert ep["max_syn_sent"] == 4800
    # Staying down does not announce it again.
    state, opened, _ = run(state, 1600, ee=row(ok=False))
    assert opened == []


def test_syn_sent_pile_up_counts_even_when_our_connect_got_through():
    """A ban that drops most SYNs still lets the odd one in."""
    assert fr.verdict(row(ok=True, syn=fr.SYN_SENT_ALARM)).startswith("SYN-SENT")
    assert fr.verdict(row(ok=True, syn=fr.SYN_SENT_ALARM - 1)) is None
    assert fr.verdict(row(ok=False)).startswith("connect")


def test_one_good_run_inside_a_wave_does_not_close_it():
    state, _, _ = run({}, 1000, ee=row(ok=False))
    state, _, _ = run(state, 1300, ee=row(ok=False))
    state, _, closed = run(state, 1600, ee=row())
    assert closed == []
    state, _, closed = run(state, 1900, ee=row(ok=False))
    assert closed == []
    state, _, closed = run(state, 2200, ee=row())
    state, _, closed = run(state, 2500, ee=row())
    assert len(closed) == 1
    assert closed[0]["ended_at"] == 2200 and closed[0]["started_at"] == 1000
    assert closed[0]["resolution"] == "recovered"
    assert state["recent_closed"] == closed


def test_a_node_we_could_not_ask_says_nothing():
    state, _, _ = run({}, 1000, ee=row(ok=False))
    state, opened, _ = fr.advance(state, NODES, {48: {"error": "ssh timeout"}}, 1300)
    assert opened == []
    state, opened, _ = fr.advance(state, NODES, {}, 1600)  # not probed at all
    assert opened == []
    state, opened, _ = run(state, 1900, ee=row(ok=False))
    assert len(opened) == 1  # the streak survived the gap


def test_replacing_the_front_closes_its_episode():
    state, _, _ = run({}, 1000, ee=row(ok=False))
    state, _, _ = run(state, 1300, ee=row(ok=False))
    state, opened, closed = run(state, 1600, ee=row(front="www.postimees.ee"))
    assert opened == []
    assert [ep["resolution"] for ep in closed] == ["front_replaced"]
    assert set(state["fronts"]) == {"48|www.postimees.ee:443"}


def test_a_node_removed_from_the_panel_takes_its_episode_along():
    state, _, _ = run({}, 1000, ee=row(ok=False))
    state, _, _ = run(state, 1300, ee=row(ok=False))
    state, _, closed = fr.advance(state, {10: NODES[10]}, {}, 1600)
    assert [ep["resolution"] for ep in closed] == ["node_removed"]
    assert state["fronts"] == {}


def test_closed_episodes_age_out_of_the_status():
    state, _, _ = run({}, 1000, ee=row(ok=False))
    state, _, _ = run(state, 1300, ee=row(ok=False))
    state, _, _ = run(state, 1600, ee=row())
    state, _, _ = run(state, 1900, ee=row())
    assert len(state["recent_closed"]) == 1
    later = 1600 + fr.RECENT_CLOSED_SEC + 1
    state, _, _ = run(state, later, ee=row())
    assert state["recent_closed"] == []


def test_status_lists_open_episodes_with_their_last_reading():
    state, _, _ = run({}, 1000, ee=row(ok=False))
    state, _, _ = run(state, 1300, ee=row(ok=False, syn=4800),
                      y0={"fronts": [row(front="api-maps.yandex.ru",
                                         ips=("87.250.251.134",))]})
    st = fr.status_of(state, 1300, 2, {})
    assert [ep["front"] for ep in st["open"]] == ["www.elisa.ee"]
    assert st["open"][0]["last"]["syn_sent"] == 4800
    assert {f["key"] for f in st["fronts"]} == {
        "48|www.elisa.ee:443", "10|api-maps.yandex.ru:443"}


def test_parse_remote_ignores_ssh_noise():
    out = "Warning: Permanently added\nREACH {\"fronts\": []}\n"
    assert fr.parse_remote(out) == {"fronts": []}
    assert fr.parse_remote("Connection refused") is None
    assert fr.parse_remote("REACH {broken") is None


# --- the script that runs on the node -------------------------------------

def _remote_ns():
    """The node-side functions, without the part that reads the live config."""
    head = fr.REMOTE.split("\ntry:\n    with open(\"/var/lib/marznode")[0]
    ns: dict = {}
    exec(head, ns)  # noqa: S102 - our own source
    return ns


def test_remote_decodes_proc_net_tcp_addresses():
    decode = _remote_ns()["decode"]
    # 194.150.66.65 as /proc/net/tcp writes it: one little-endian word.
    assert decode("414296C2") == "194.150.66.65"
    # The same address v4-mapped in /proc/net/tcp6.
    assert decode("0000000000000000FFFF0000414296C2") == "194.150.66.65"
    assert decode("00000000000000000000000001000000") == "::1"


def test_remote_counts_only_syn_sent(tmp_path, monkeypatch):
    ns = _remote_ns()
    tcp = tmp_path / "tcp"
    tcp.write_text(
        "  sl  local_address rem_address   st\n"
        "   0: 0100007F:1F90 414296C2:01BB 02 0\n"
        "   1: 0100007F:1F91 414296C2:01BB 02 0\n"
        "   2: 0100007F:1F92 414296C2:01BB 01 0\n"  # ESTABLISHED
        "   3: 0100007F:1F93 414296C2:0050 02 0\n"  # another port
    )
    real_open = open

    def fake_open(path, *a, **kw):
        if path == "/proc/net/tcp":
            return real_open(tcp, *a, **kw)
        raise OSError("absent")

    ns["open"] = fake_open
    counts = ns["syn_sent"]()
    assert counts == {("194.150.66.65", 443): 2, ("194.150.66.65", 80): 1}


def test_remote_reads_reality_fronts_from_the_config():
    fronts = _remote_ns()["fronts"]
    cfg = {"inbounds": [
        {"tag": "Estonia-1", "streamSettings": {
            "realitySettings": {"dest": "www.postimees.ee:443"}}},
        {"tag": "new-syntax", "streamSettings": {
            "realitySettings": {"target": "www.postimees.ee:443"}}},
        {"tag": "local-fallback", "streamSettings": {
            "realitySettings": {"dest": "8443"}}},
        {"tag": "loopback", "streamSettings": {
            "realitySettings": {"dest": "127.0.0.1:8443"}}},
        {"tag": "plain", "streamSettings": {"security": "none"}},
        {"tag": "no-stream"},
    ]}
    assert fronts(cfg) == {("www.postimees.ee", 443): ["Estonia-1", "new-syntax"]}
