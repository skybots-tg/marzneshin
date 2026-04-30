"""Per-node TTL cache for the GetSystemStats RPC.

Multiple operators / browser tabs polling the nodes table at the same
time would otherwise produce one gRPC call per UI tick, per node. The
node already caches its own /proc reads (10 s TTL) but the panel-side
cache shaves off the gRPC round-trip too, which matters for nodes
that aren't on the same network as the panel.

Layered TTLs (panel: a few seconds, node: 10 s) mean the worst-case
extra load on a node is ~1 RPC every ``CACHE_TTL_SECONDS`` even if a
hundred admins are watching the page at once.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.models.node import NodeSystemStats

CACHE_TTL_SECONDS = 5.0


@dataclass
class _Entry:
    value: NodeSystemStats
    fetched_at: float


_cache: dict[int, _Entry] = {}
_locks: dict[int, asyncio.Lock] = {}


def _lock_for(node_id: int) -> asyncio.Lock:
    """Per-node lock so concurrent requests for the same node coalesce
    into a single upstream RPC instead of stampeding the cache."""
    lock = _locks.get(node_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[node_id] = lock
    return lock


def _fresh(entry: _Entry, now: float) -> bool:
    return (now - entry.fetched_at) < CACHE_TTL_SECONDS


async def get_or_fetch(
    node_id: int,
    fetcher: Callable[[], Awaitable[NodeSystemStats]],
) -> NodeSystemStats:
    """Return a cached snapshot, otherwise call ``fetcher`` exactly once.

    ``fetcher`` is the actual gRPC call; the cache layer doesn't know
    or care whether it goes over grpclib or grpcio.
    """
    now = time.monotonic()
    entry = _cache.get(node_id)
    if entry is not None and _fresh(entry, now):
        return entry.value

    async with _lock_for(node_id):
        # Double-check after acquiring the lock — another caller may
        # have populated the cache while we were waiting for it.
        now = time.monotonic()
        entry = _cache.get(node_id)
        if entry is not None and _fresh(entry, now):
            return entry.value

        value = await fetcher()
        _cache[node_id] = _Entry(value=value, fetched_at=now)
        return value


def invalidate(node_id: int | None = None) -> None:
    """Drop a single node's cached snapshot, or the whole cache if
    ``node_id`` is None. Called when a node is removed/modified so we
    don't keep serving stale data for an id that's been reassigned."""
    if node_id is None:
        _cache.clear()
        _locks.clear()
        return
    _cache.pop(node_id, None)
    _locks.pop(node_id, None)
