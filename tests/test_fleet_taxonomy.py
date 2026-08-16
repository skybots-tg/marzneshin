"""What the fleet's naming conventions mean, pinned down.

Host remarks are the only place the topology is written down, so these parsers
decide which servers the audit even looks at. A remark that stops classifying
is a server that stops being checked — that is how three "ELITE ... РАБОТАЕТ
ВСЕГДА" entries went unaudited while two of them were broken.
"""

from __future__ import annotations

import pytest

from app.utils.fleet_taxonomy import (
    classify_tier,
    entry_key,
    exit_label,
    exit_slot,
    flag_to_iso,
    link_key,
)


@pytest.mark.parametrize("remark,expected", [
    ("🇷🇴 🛜 UNIVERSAL 2 ♾️ RO", ("universal", 2)),
    ("🇩🇪📶 ELITE 3 [GB] - DE-2 [ 4G ]", ("elite", 3)),
    ("🇫🇷⚡️FAST 1 ♾️ - FR", ("fast", 1)),
    ("🇩🇪📶 ELITE DE РАБОТАЕТ ВСЕГДА", ("elite", None)),
    ("🇵🇱📶 ELITE LUX - PL [ 4G ]", ("elite", None)),
    ("🇷🇴⚡️FAST RO-1 ♾️ - RO", ("fast", None)),
    ("Marz", (None, None)),
    ("", (None, None)),
])
def test_classify_tier(remark, expected):
    assert classify_tier(remark) == expected


@pytest.mark.parametrize("remark,expected", [
    ("🇷🇴 🛜 UNIVERSAL 2 ♾️ RO", "RO"),
    ("🇩🇪 🛜 UNIVERSAL 2 ♾️ DE-2", "DE-2"),
    ("🇩🇪 🛜 UNIVERSAL 2 ♾️ DE xhttp", "DE"),
    ("🇫🇮📶 ELITE 1 [GB] - FI-3 [ 4G ]", "FI-3"),
    ("🇹🇷⚡️FAST 1 ♾️ - TR | NO YT ADS", "TR | NO YT ADS"),
])
def test_exit_slot(remark, expected):
    """The slot is the exit server, stripped of transport and decoration."""
    assert exit_slot(remark) == expected


def test_exit_slot_ignores_the_transport_variant():
    """tcp and xhttp reach the same exit; the slot must not split them."""
    assert exit_slot("🇩🇪 🛜 UNIVERSAL 2 ♾️ DE") == exit_slot(
        "🇩🇪 🛜 UNIVERSAL 2 ♾️ DE xhttp")


def test_exit_label_keeps_what_the_user_sees():
    assert exit_label("🇩🇪 🛜 UNIVERSAL 2 ♾️ DE xhttp") == "DE xhttp"


@pytest.mark.parametrize("text,expected", [
    ("🇷🇴 UNIVERSAL 2", "RO"),
    ("🇩🇪🇷🇺 two flags", "DE"),
    ("no flag here", None),
    ("", None),
])
def test_flag_to_iso(text, expected):
    assert flag_to_iso(text) == expected


def test_entry_key_falls_back_to_the_node_when_unnumbered():
    assert entry_key("elite", 3) == "elite-3"
    assert entry_key("elite", None, 33) == "elite-n33"
    assert entry_key("elite", None) == "elite-?"


def test_link_key_separates_what_fails_separately():
    tcp = link_key(25, "FR", "tcp")
    assert tcp == "25>FR/tcp"
    assert link_key(25, "FR", "xhttp") != tcp     # same servers, own failure
    assert link_key(30, "FR", "tcp") != tcp       # different entry
    assert link_key(25, "FR-2", "tcp") != tcp     # different exit server
    assert link_key(17, None) == "17>direct/tcp"
