"""Bridge outbounds get one fingerprint; nothing else in the config moves."""
from __future__ import annotations

import copy
import os
import sys
import types

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
# the tool imports marz_common, which refuses to load without _secrets.py
sys.modules.setdefault("marz_common", types.ModuleType("marz_common"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import bridge_fingerprint as bf  # noqa: E402

CFG = {
    "inbounds": [{"tag": "RU->EE Bridge", "streamSettings": {"realitySettings": {"privateKey": "k"}}}],
    "outbounds": [
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "ee-out", "streamSettings": {"realitySettings": {
            "serverName": "www.elisa.ee", "fingerprint": "chrome", "publicKey": "p"}}},
        {"tag": "nl-1-out", "streamSettings": {"realitySettings": {
            "serverName": "www.bol.com", "fingerprint": "firefox", "publicKey": "q"}}},
    ],
}


def test_only_reality_outbounds_with_another_fingerprint_change():
    cfg = copy.deepcopy(CFG)
    assert bf.retarget(cfg, "firefox") == ["ee-out: chrome -> firefox"]
    ee = cfg["outbounds"][1]["streamSettings"]["realitySettings"]
    assert ee == {"serverName": "www.elisa.ee", "fingerprint": "firefox", "publicKey": "p"}
    assert cfg["inbounds"] == CFG["inbounds"] and cfg["outbounds"][0] == CFG["outbounds"][0]


def test_a_second_run_changes_nothing():
    cfg = copy.deepcopy(CFG)
    bf.retarget(cfg, "firefox")
    assert bf.retarget(cfg, "firefox") == []
