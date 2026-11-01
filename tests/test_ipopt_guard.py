"""What the CVE-2026-98432 guard puts on a node."""
from __future__ import annotations

import os
import re
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import ipopt_guard as ig  # noqa: E402

PLACEHOLDERS = re.compile(r"\b(SCRIPT|DEFAULTS|MODEVAL|SERVICE|UNIT|COMMENT|MATCH)\b")


def test_node_script_has_no_placeholders_left():
    script = ig.node_script()
    assert not PLACEHOLDERS.search(script)
    assert f". {ig.DEFAULTS}" in script
    assert r"/\/\* ipopt-guard \*\//" in script


def test_drop_and_count_rules_match_the_same_packets():
    script = ig.node_script()
    drop = [ln for ln in script.splitlines() if "-j DROP" in ln]
    count = [ln for ln in script.splitlines() if "-I PREROUTING" in ln and "-j DROP" not in ln]
    assert len(drop) == 1 and len(count) == 1
    assert drop[0].strip().removesuffix(" -j DROP") == count[0].strip()
    assert '-p tcp -m u32 --u32 "0>>22&0x3C=24:60"' in drop[0]


@pytest.mark.parametrize("mode", ig.MODES)
def test_install_script(mode):
    script = ig.install_script(mode)
    assert not PLACEHOLDERS.search(script)
    assert f'echo "MODE={mode}" > {ig.DEFAULTS}' in script
    assert f"ExecStart={ig.SCRIPT} apply" in script
    assert "systemctl restart ipopt-guard.service" in script


def test_install_rejects_unknown_mode():
    with pytest.raises(ValueError):
        ig.install_script("log")


def test_header_length_match():
    # 0>>22&0x3C is IHL*4: 20 for a bare header, 24..60 once options are there
    for ihl, has_options in ((5, False), (6, True), (15, True)):
        word0 = (0x40 | ihl) << 24
        assert (24 <= ((word0 >> 22) & 0x3C) <= 60) is has_options
