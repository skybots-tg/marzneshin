"""The probe worker's bar for "this tunnel carries traffic".

bridge_runner.py is stdlib-only (it runs on bare VPN nodes), so it is loaded
straight off disk.
"""
from __future__ import annotations

import importlib.util
import os
import types

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "tools", "bridge_runner.py")
_spec = importlib.util.spec_from_file_location("bridge_runner", _PATH)
br = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(br)


def curl_answers(*outputs):
    """A stand-in for subprocess.run that replays curl's -w output in order."""
    calls = []
    queue = list(outputs)

    def run(cmd, **_kw):
        calls.append(cmd[-1])
        out = queue.pop(0)
        if isinstance(out, Exception):
            raise out
        return types.SimpleNamespace(stdout=out, returncode=0)

    return run, calls


def test_a_working_tunnel_carries_every_connection():
    run, calls = curl_answers("204 0", "204 0", "200 262144")
    assert br.sustained(12000, run=run) == len(br.SUSTAIN)
    assert len(calls) == len(br.SUSTAIN)


def test_a_throttled_leg_stops_at_the_first_dropped_connection():
    """AdminVPS on 2026-09-30: the lookup answered, the next connection died."""
    run, calls = curl_answers("000 0", "204 0", "200 262144")
    assert br.sustained(12000, run=run) == 0
    assert len(calls) == 1          # no point paying for the rest


def test_a_download_cut_short_does_not_count():
    run, _ = curl_answers("204 0", "204 0", "200 65536")
    assert br.sustained(12000, run=run) == len(br.SUSTAIN) - 1


def test_curl_timing_out_is_a_dropped_connection():
    run, _ = curl_answers("204 0", TimeoutError("curl hung"))
    assert br.sustained(12000, run=run) == 1


def test_the_job_budget_covers_the_extra_connections():
    assert br.SUSTAIN_WORST >= len(br.SUSTAIN) * br.SUSTAIN_TIMEOUT
