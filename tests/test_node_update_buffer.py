"""Adding an inbound to a service has to reach every user of that service.

It did not. Each node client held an ``asyncio.Queue`` one slot deep, filled
with ``put_nowait``; the streaming task drained one entry per event-loop tick
while the service edit scheduled one update per user in a single tick. The
first user landed on the node, the rest were logged as dropped, and the node
kept the old user set until it reconnected.
"""

import asyncio

import pytest

from app.marznode.grpclib import MarzNodeGRPCLIB
from app.marznode.update_buffer import PendingUserUpdates


class _User:
    def __init__(self, uid: int):
        self.id = uid


def _payload(uid: int, inbounds):
    return {
        "user": _User(uid),
        "inbounds": list(inbounds),
        "device_limit": None,
        "allowed_fingerprints": [],
    }


@pytest.mark.asyncio
async def test_a_burst_of_updates_survives_a_single_tick():
    """Every user of an edited service reaches the node, not just the first."""
    buffer = PendingUserUpdates(node_id=1)

    for uid in range(500):
        buffer.push(_payload(uid, ["vless-tcp"]))

    drained = [await buffer.pop() for _ in range(500)]

    assert [p["user"].id for p in drained] == list(range(500))


@pytest.mark.asyncio
async def test_the_newest_state_of_a_user_wins():
    """Payloads carry the full inbound set, so an older one is dead weight."""
    buffer = PendingUserUpdates(node_id=1)

    buffer.push(_payload(42, ["vless-tcp"]))
    buffer.push(_payload(7, ["vless-tcp"]))
    buffer.push(_payload(42, ["vless-tcp", "vless-reality"]))

    first = await buffer.pop()
    second = await buffer.pop()

    assert len(buffer) == 0
    # 42 keeps its place in line -- it was queued first -- with its late state.
    assert first["user"].id == 42
    assert first["inbounds"] == ["vless-tcp", "vless-reality"]
    assert second["user"].id == 7


@pytest.mark.asyncio
async def test_a_consumer_waits_instead_of_spinning():
    buffer = PendingUserUpdates(node_id=1)
    popped = asyncio.ensure_future(buffer.pop())

    await asyncio.sleep(0)
    assert not popped.done()

    buffer.push(_payload(3, []))
    assert (await asyncio.wait_for(popped, 1))["user"].id == 3


@pytest.mark.asyncio
async def test_a_dead_stream_forgets_what_it_never_sent():
    """Reconnecting replays the whole user list, so a backlog is stale."""
    buffer = PendingUserUpdates(node_id=1)
    buffer.push(_payload(1, ["vless-tcp"]))
    buffer.clear()

    popped = asyncio.ensure_future(buffer.pop())
    await asyncio.sleep(0)
    assert not popped.done()
    popped.cancel()


class _LiveTask:
    @staticmethod
    def done():
        return False


class _Node:
    """Just enough of a node client to exercise ``update_user``."""

    id = 9
    synced = True
    _streaming_task = _LiveTask()

    update_user = MarzNodeGRPCLIB.update_user

    def __init__(self):
        self._pending_updates = PendingUserUpdates(self.id)


@pytest.mark.asyncio
async def test_update_user_keeps_every_user_of_a_service_edit():
    node = _Node()

    await asyncio.gather(
        *(
            node.update_user(_User(uid), inbounds=["vless-tcp"])
            for uid in range(200)
        )
    )

    assert len(node._pending_updates) == 200


@pytest.mark.asyncio
async def test_update_user_drops_when_there_is_no_stream_to_write_to():
    node = _Node()
    node.synced = False

    await node.update_user(_User(1), inbounds=["vless-tcp"])

    assert len(node._pending_updates) == 0


def _appdata_error_over_cancellation() -> AttributeError:
    """Ровно то, что grpclib поднимает при отмене стрима.

    ``__aexit__`` зовёт ``reset_nowait`` на уже полумёртвом SSL-транспорте,
    пока разматывается CancelledError, и своей ошибкой её подменяет.
    """
    try:
        raise asyncio.CancelledError
    except asyncio.CancelledError:
        try:
            raise AttributeError(
                "'NoneType' object has no attribute '_write_appdata'"
            )
        except AttributeError as exc:
            return exc


def test_a_cancelled_stream_is_not_an_unexpected_error():
    """Иначе каждое переподключение узла пишет в лог трейсбек с ERROR."""
    from app.marznode.grpclib import _is_spurious_appdata_error, _was_cancelled

    exc = _appdata_error_over_cancellation()

    assert _is_spurious_appdata_error(exc)
    assert _was_cancelled(exc)


def test_a_real_failure_is_still_a_failure():
    from app.marznode.grpclib import _was_cancelled

    try:
        raise ConnectionResetError("node hung up")
    except ConnectionResetError as exc:
        assert not _was_cancelled(exc)
