"""Relaying a cut-off node through a Russian one.

bridge_relay.py is stdlib-only (it runs on bare VPN nodes), so it is loaded
straight off disk. What must never break: each machine gets only its own rows,
a relay port is never reused, and the installer reaches relays and the panel
before the nodes that are only reachable through them.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
_spec = importlib.util.spec_from_file_location("bridge_relay", os.path.join(_TOOLS, "bridge_relay.py"))
brl = importlib.util.module_from_spec(_spec)
sys.modules["bridge_relay"] = brl
_spec.loader.exec_module(brl)

# the installer imports marz_common, which refuses to load without _secrets.py
sys.modules.setdefault("marz_common", types.ModuleType("marz_common"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import bridge_relay_install as inst  # noqa: E402

ENTRY, RELAY, PANEL, EXIT = "10.0.0.1", "10.0.0.2", inst.PANEL_IP, "10.0.0.9"
TABLE = f"""
# a comment line
{ENTRY}  {RELAY}  47201  {EXIT}   49443  dc15 nl-1-out   # trailing comment
{PANEL}  {RELAY}  47290  {ENTRY}  22     dc15 panel 22
"""


def test_the_fleet_table_parses_and_never_reuses_a_relay_port():
    with open(os.path.join(_TOOLS, "bridge_relay.routes"), encoding="utf-8") as f:
        routes = brl.parse_routes(f.read())
    nat = [r for r in routes if not r.via_wg]
    assert nat
    assert len({(r.relay, r.rport) for r in nat}) == len(nat)


def test_a_reused_relay_port_is_refused():
    with pytest.raises(ValueError, match="used twice"):
        brl.parse_routes(TABLE + f"{PANEL} {RELAY} 47201 {ENTRY} 53042 dup\n")


def test_a_bad_address_is_refused():
    with pytest.raises(ValueError):
        brl.parse_routes(f"{ENTRY} {RELAY} 47201 not-an-ip 443 x\n")


def test_the_source_only_redirects_its_own_connections():
    rules = brl.ruleset(brl.parse_routes(TABLE), ENTRY)
    added = [ln for ln in rules.splitlines() if ln.startswith("-A ")]
    assert added == [
        f'-A {brl.OUT} -d {EXIT}/32 -p tcp -m tcp --dport 49443 '
        f'-m comment --comment "bridge-relay dc15 nl-1-out" -j DNAT --to-destination {RELAY}:47201',
    ]


def test_the_relay_forwards_only_for_the_listed_sources():
    rules = brl.ruleset(brl.parse_routes(TABLE), RELAY)
    pre = [ln for ln in rules.splitlines() if ln.startswith(f"-A {brl.PRE} ")]
    assert f"-s {ENTRY}/32 -p tcp -m tcp --dport 47201" in pre[0]
    assert pre[0].endswith(f"--to-destination {EXIT}:49443")
    assert f"-s {PANEL}/32 -p tcp -m tcp --dport 47290" in pre[1]
    assert pre[1].endswith(f"--to-destination {ENTRY}:22")
    assert sum(ln.startswith(f"-A {brl.POST} ") and "MASQUERADE" in ln for ln in rules.splitlines()) == 2
    back = [ln for ln in rules.splitlines() if "RELATED,ESTABLISHED" in ln]
    assert [ln.split()[3] for ln in back] == [f"{ENTRY}/32", f"{PANEL}/32"]


def test_every_chain_is_declared_so_a_rerun_replaces_it():
    rules = brl.ruleset(brl.parse_routes(TABLE), "10.0.0.77")    # no rows at all
    for chain in (brl.OUT, brl.PRE, brl.POST, brl.FWD):
        assert f":{chain} - [0:0]" in rules
    assert rules.count("COMMIT") == 2


WG_TABLE = f"""
tunnel {ENTRY} {RELAY} 10.77.3.0/30 51873
{ENTRY}  {RELAY}  wg  {EXIT}  49443  u1 nl-1-out
"""


def test_a_wg_row_needs_its_tunnel():
    with pytest.raises(ValueError, match="no tunnel"):
        brl.parse_table(f"{ENTRY} {RELAY} wg {EXIT} 49443 orphan\n")


def test_a_tunnel_is_a_slash_30_with_its_own_interface():
    routes, tunnels = brl.parse_table(WG_TABLE)
    t = tunnels[0]
    assert (t.iface, t.relay_ip, t.src_ip) == ("brwg3", "10.77.3.1", "10.77.3.2")
    assert routes[0].via_wg
    with pytest.raises(ValueError, match="/30"):
        brl.parse_table(f"tunnel {ENTRY} {RELAY} 10.77.3.0/24 51873\n")


def test_through_a_tunnel_the_source_routes_instead_of_rewriting():
    routes, tunnels = brl.parse_table(WG_TABLE)
    rules = brl.ruleset(routes, ENTRY, tunnels)
    assert not [ln for ln in rules.splitlines() if ln.startswith("-A ")]
    assert brl.wg_routes(routes, tunnels, ENTRY) == {"brwg3": {EXIT}}


def test_the_relay_lets_only_the_listed_exit_out_of_the_tunnel():
    routes, tunnels = brl.parse_table(WG_TABLE)
    added = [ln for ln in brl.ruleset(routes, RELAY, tunnels).splitlines() if ln.startswith("-A ")]
    assert not [ln for ln in added if ln.startswith(f"-A {brl.PRE} ")]
    post = [ln for ln in added if ln.startswith(f"-A {brl.POST} ")]
    assert post == [f'-A {brl.POST} -s 10.77.3.2/32 -d {EXIT}/32 -p tcp -m tcp --dport 49443 '
                    f'-m comment --comment "bridge-relay u1 nl-1-out" -j MASQUERADE']
    fwd = [ln for ln in added if ln.startswith(f"-A {brl.FWD} ")]
    assert "-i brwg3" in fwd[0] and f"-d {EXIT}/32" in fwd[0]
    assert "-d 10.77.3.2/32 -m conntrack --ctstate RELATED,ESTABLISHED" in fwd[1]


def test_each_end_of_the_tunnel_gets_its_own_wg_config():
    _, tunnels = brl.parse_table(WG_TABLE)
    peers = {ENTRY: "E" * 43 + "=", RELAY: "R" * 43 + "="}
    relay = brl.wg_config(tunnels[0], RELAY, peers, "priv")
    assert "ListenPort = 51873" in relay and "AllowedIPs = 10.77.3.2/32" in relay
    assert peers[ENTRY] in relay and "Endpoint" not in relay
    src = brl.wg_config(tunnels[0], ENTRY, peers, "priv")
    assert f"Endpoint = {RELAY}:51873" in src and "ListenPort" not in src
    with pytest.raises(ValueError, match="peers file"):
        brl.wg_config(tunnels[0], ENTRY, {}, "priv")


def test_relays_and_panel_come_before_the_nodes_behind_them():
    routes = brl.parse_routes(TABLE)
    assert inst.order(routes) == [RELAY, PANEL, ENTRY]


def test_the_fleet_order_reaches_every_cut_off_node_after_its_relay():
    with open(os.path.join(_TOOLS, "bridge_relay.routes"), encoding="utf-8") as f:
        routes, tunnels = brl.parse_table(f.read())
    seq = inst.order(routes, tunnels)
    for t in tunnels:                        # a tunnel's relay is up before its source
        assert seq.index(t.relay) < seq.index(t.src)
    for r in routes:
        if r.src == inst.PANEL_IP:          # the panel reaches r.dst only via r.relay
            assert seq.index(r.relay) < seq.index(inst.PANEL_IP)
            if r.dst in seq:
                assert seq.index(inst.PANEL_IP) < seq.index(r.dst)
