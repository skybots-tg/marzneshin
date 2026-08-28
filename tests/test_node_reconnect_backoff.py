"""Reconnecting to a node that is simply gone should get cheaper over time.

Nodes 13, 24 and 33 sat unreachable for weeks while the monitor loop retried
every fifteen seconds. Between them that was 34,503 warnings in 48 hours, which
buried the log lines that actually mattered -- including the alerts about an
audit that had been dead for three days.
"""
import logging

from app.marznode.grpclib import (
    RECONNECT_BASE_SEC,
    RECONNECT_MAX_SEC,
    RECONNECT_QUIET_EVERY,
    MarzNodeGRPCLIB,
)


class _Node:
    """Just enough of a node for the two helpers under test."""

    id = 33
    _connect_fail_streak = 0

    _reconnect_delay = MarzNodeGRPCLIB._reconnect_delay
    _note_connect_failure = MarzNodeGRPCLIB._note_connect_failure


def test_the_first_retry_is_prompt():
    """A blip must not be punished: the first wait is the old interval."""
    assert _Node()._reconnect_delay() == RECONNECT_BASE_SEC


def test_the_delay_grows_and_stops_at_the_ceiling():
    node = _Node()
    seen = []
    for _ in range(12):
        node._connect_fail_streak += 1
        seen.append(node._reconnect_delay())

    assert seen[0] == RECONNECT_BASE_SEC
    assert seen[1] == 2 * RECONNECT_BASE_SEC
    assert seen == sorted(seen), "the delay must never shrink while failing"
    assert seen[-1] == RECONNECT_MAX_SEC
    assert max(seen) == RECONNECT_MAX_SEC


def test_a_node_that_answers_returns_to_the_fast_cadence():
    """Backing off must not mean giving up on a node that comes back."""
    node = _Node()
    node._connect_fail_streak = 40
    assert node._reconnect_delay() == RECONNECT_MAX_SEC

    node._connect_fail_streak = 0          # what the loop does on success
    assert node._reconnect_delay() == RECONNECT_BASE_SEC


def test_a_permanent_outage_keeps_one_warning_in_twenty(caplog):
    """Still visible in the log -- just not 11,501 lines of it per node."""
    node = _Node()
    with caplog.at_level(logging.DEBUG, logger="app.marznode.grpclib"):
        for _ in range(RECONNECT_QUIET_EVERY * 2):
            node._note_connect_failure("connection timeout (5s)")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    # the first three attempts, then every twentieth
    assert len(warnings) == 3 + 2
    assert node._connect_fail_streak == RECONNECT_QUIET_EVERY * 2
