"""The node-side snippet picks the container that owns /var/lib/marznode.

2026-11-01, EE-1: ``marznode2`` (the IHC gateway) is listed first; a front change
wrote node 48's config and restarted marznode2 instead.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
from marz_container import MARZ_CONTAINER_SH  # noqa: E402

FAKE_DOCKER = r'''
docker() {
  case "$1" in
    ps) printf '%s\n' $NAMES ;;
    inspect) eval "echo \"\$MOUNT_$(echo "$4" | tr -c 'a-zA-Z0-9\n' _)\"" ;;
  esac
}
'''


def pick(names: list[str], mounts: dict[str, str]) -> str:
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    env = {**os.environ, "NAMES": " ".join(names)}
    for name, source in mounts.items():
        env["MOUNT_" + "".join(ch if ch.isalnum() else "_" for ch in name)] = source
    script = FAKE_DOCKER + MARZ_CONTAINER_SH + 'echo "$c"\n'
    return subprocess.run([bash, "-c", script], env=env, capture_output=True, text=True).stdout.strip()


def test_owner_of_var_lib_marznode_wins_over_first_listed():
    mounts = {"marznode2": "/var/lib/marznode2", "marznode-marznode-1": "/var/lib/marznode"}
    assert pick(["marznode2", "marznode-marznode-1"], mounts) == "marznode-marznode-1"


def test_single_container_without_the_mount_is_still_found():
    assert pick(["marznode-marznode-1"], {"marznode-marznode-1": "/opt/other"}) == "marznode-marznode-1"
