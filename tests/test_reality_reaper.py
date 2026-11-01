"""Which REALITY sockets the node-side reaper closes, and which it must leave alone.

The samples are `ss -Htni state established` lines from IHC RU-1 (node 47) on
2026-11-01: a client hello cut after one MSS, a live client that got its
ServerHello, and the idle dest socket xray kept for the cut one.
"""
from __future__ import annotations

import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import reality_reaper as rr  # noqa: E402

SS = """\
0      0      [::ffff:178.57.222.142]:22443   [::ffff:94.25.172.254]:16220
\t cubic wscale:10,7 rto:262 rtt:61.141/30.57 ato:40 mss:1348 pmtu:1500 rcvmss:1348 advmss:1448 cwnd:10 bytes_received:1348 segs_out:1 segs_in:3 data_segs_in:1 send 1763792bps lastsnd:1695962 lastrcv:1695919 lastack:1695919 pacing_rate 3527576bps delivered:1 app_limited
0      0      [::ffff:178.57.222.142]:12520     [::ffff:5.18.40.119]:15268
\t cubic wscale:9,7 rto:220 rtt:18/9 ato:40 mss:1448 bytes_sent:6240 bytes_acked:6241 bytes_received:98213 segs_out:40 segs_in:61 lastsnd:900000 lastrcv:900000 lastack:900000
0      0      [::ffff:178.57.222.142]:12520     [::ffff:5.18.40.120]:15269
\t cubic wscale:9,7 rto:220 rtt:18/9 ato:40 mss:1448 bytes_received:1448 segs_out:1 segs_in:2 lastsnd:30000 lastrcv:30000 lastack:30000
0      0      178.57.222.142:32870 87.250.251.134:443
\t ts sack cubic wscale:8,7 rto:203 rtt:3.248/1.624 mss:1398 bytes_acked:1 segs_out:8293 segs_in:8292 lastsnd:101884371 lastrcv:101884371 lastack:1441
0      0      178.57.222.142:32871 87.250.251.134:443
\t ts sack cubic mss:1398 bytes_sent:517 bytes_acked:518 bytes_received:5033 segs_out:9 lastsnd:101884371 lastrcv:101884371 lastack:1441
0      0      178.57.222.142:22 [::ffff:195.54.170.162]:51000
\t cubic mss:1448 lastsnd:999999 lastrcv:999999
"""

CFG = {"inbounds": [
    {"tag": "RU Direct", "port": 12520, "streamSettings": {
        "security": "reality", "realitySettings": {"dest": "api-maps.yandex.ru:443"}}},
    {"tag": "RU->EE Bridge", "port": "22443", "streamSettings": {
        "security": "reality", "realitySettings": {"target": "api-maps.yandex.ru:443"}}},
    {"tag": "plain", "port": 8080, "streamSettings": {"security": "none"}},
    {"tag": "range", "port": "1000-2000", "streamSettings": {"security": "reality"}},
]}

IDLE = rr.IDLE_SEC * 1000


def test_reality_inbounds_take_ports_and_dest_only_from_reality():
    assert rr.reality_inbounds(CFG) == {12520: ("api-maps.yandex.ru", 443), 22443: ("api-maps.yandex.ru", 443)}


def test_parse_ss_unmaps_ipv4_and_reads_counters():
    socks = rr.parse_ss(SS)
    assert len(socks) == 6
    first = socks[0]
    assert first["local"] == ("178.57.222.142", 22443)
    assert first["peer"] == ("94.25.172.254", 16220)
    assert first["info"]["bytes_received"] == 1348 and "bytes_sent" not in first["info"]
    assert first["info"]["lastrcv"] == 1695919


def test_only_silent_reality_sockets_past_idle_are_stuck():
    stuck = rr.stuck_inbound(rr.parse_ss(SS), {12520, 22443}, IDLE)
    # cut hello: yes; live client with a ServerHello: no; cut but only 30 s old: not yet;
    # sshd on :22 with no bytes either: not a REALITY port.
    assert [s["peer"] for s in stuck] == [("94.25.172.254", 16220)]


def test_orphan_dest_is_the_idle_never_used_socket_only():
    orphans = rr.orphan_dest(rr.parse_ss(SS), {("87.250.251.134", 443)}, IDLE)
    assert [s["local"] for s in orphans] == [("178.57.222.142", 32870)]


def test_kill_filter_names_each_socket_exactly():
    socks = rr.parse_ss(SS)
    assert rr.kill_filter([socks[0]]) == "( sport = :22443 and dport = :16220 and dst 94.25.172.254 )"
    v6 = {"local": ("::", 443), "peer": ("2a02:6b8::274", 443), "info": {}}
    assert rr.kill_filter([socks[0], v6]).endswith(" or ( sport = :443 and dport = :443 and dst [2a02:6b8::274] )")


def test_install_script_carries_units_and_runs_once():
    script = rr.install_script()
    assert "INSTALL_DIR" not in script and "SERVICE" not in script and "TIMER\n" not in script
    assert f"ExecStart=/usr/bin/python3 {rr.INSTALL_DIR}/reality_reaper.py run" in script
    assert "OnCalendar=*:04/5" in script
    assert "systemctl enable --now reality-reaper.timer" in script
    assert script.index("run --dry-run") < script.index("systemctl start reality-reaper.service")
