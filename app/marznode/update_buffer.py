"""Coalescing buffer for user updates pushed down the SyncUsers stream.

Both node clients used to hold an ``asyncio.Queue`` with a maxsize of one
(grpclib) or five (grpcio), filled with ``put_nowait`` and a ``QueueFull``
branch that logged a warning and dropped the update on the floor.

That is survivable for a single user edit and wrong for every bulk operation
the panel performs. Adding an inbound to a service walks every user of that
service and schedules one ``update_user`` coroutine per user per node; all of
them become runnable in the same event-loop tick, while the streaming task
gets to drain exactly one per tick. The first update landed, the rest were
dropped, and the node kept serving the old user set until somebody restarted
it or the connection blipped. From the outside that looked like "adding an
inbound to a service pushes it to some users only". The nightly expiry and
data-limit sweeps lost updates the same way.

This buffer removes the bound instead of the updates. It is keyed by user id,
so its size is bounded by the number of users on the node rather than by a
magic number, and a newer payload replaces an older one for the same user:
every payload carries that user's *complete* desired inbound set for this
node, so the last writer is the only one that matters.
"""

import asyncio
import logging
from collections import deque

logger = logging.getLogger(__name__)

# A backlog this deep means the stream is not draining -- the node is wedged
# or the link is saturated -- and is worth one line in the log. Coalescing
# keeps the buffer at most one entry per user, so on a normal install this is
# never reached.
DEFAULT_BACKLOG_WARN_AT = 10_000


class PendingUserUpdates:
    """Latest-wins, per-user buffer between ``update_user`` and the stream."""

    def __init__(
        self, node_id: int, backlog_warn_at: int = DEFAULT_BACKLOG_WARN_AT
    ):
        self._node_id = node_id
        self._payloads: dict[object, dict] = {}
        self._order: deque = deque()
        self._event = asyncio.Event()
        self._backlog_warn_at = backlog_warn_at
        self._warned = False
        self._anonymous = 0

    def __len__(self) -> int:
        return len(self._payloads)

    def _key(self, payload: dict):
        uid = getattr(payload.get("user"), "id", None)
        if uid is None:
            # No id to coalesce on: keep the payload under a key of its own
            # rather than letting an unidentifiable user overwrite another.
            self._anonymous += 1
            return ("anonymous", self._anonymous)
        return uid

    def push(self, payload: dict) -> None:
        key = self._key(payload)
        if key not in self._payloads:
            self._order.append(key)
        self._payloads[key] = payload
        self._event.set()

        depth = len(self._payloads)
        if not self._warned and depth >= self._backlog_warn_at:
            self._warned = True
            logger.warning(
                "Node %i: %d user updates are waiting on the sync stream; "
                "the node is not keeping up",
                self._node_id,
                depth,
            )
        elif self._warned and depth < self._backlog_warn_at // 2:
            self._warned = False

    async def pop(self) -> dict:
        """Wait for and return the oldest pending update."""
        while True:
            while self._order:
                key = self._order.popleft()
                payload = self._payloads.pop(key, None)
                if payload is not None:
                    return payload
            self._event.clear()
            # Producers only run at await points on this same loop, so the
            # clear above cannot race one -- the re-check is belt and braces.
            if self._order:
                continue
            await self._event.wait()

    def clear(self) -> None:
        """Forget everything pending.

        Called when the stream dies: whatever was queued describes a state
        the node no longer has, and the reconnect path replays the full user
        list through ``RepopulateUsers`` anyway.
        """
        self._payloads.clear()
        self._order.clear()
        self._event.clear()
        self._warned = False
