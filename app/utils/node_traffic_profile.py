"""What a node's traffic normally looks like at this hour of this week.

Alerts about traffic have to answer "is this unusual", and every fixed
threshold answers a different question instead. A node that carries five
gigabytes an hour by day and eighty megabytes at four in the morning is
perfectly healthy at both ends of that range: judged by an absolute floor it
is either always fine or alarming every night. That is where the false alarms
came from, and an alarm that cries at 04:00 every night is one nobody reads at
noon when it matters.

So the comparison here is always a node against *itself, at the same hours of
the day*, over the past week. Two readings come out of that:

* ``expected_now`` — what this hour usually carries. A silence alarm consults
  it before firing: silence at an hour that is normally silent is not news.
* ``ratio`` — the last couple of hours against the same hours of previous
  days. This is the one that catches an exit that broke rather than went
  quiet: France kept its port open, its keys, its users and its health check
  and simply stopped moving bytes, going from 200 GB a day to zero, and no
  absolute threshold anywhere in the fleet noticed for three days.

A node without a meaningful week behind it is left out of both, rather than
given a made-up number: a new node, or one whose hosts are all hidden, cannot
carry traffic by construction, and inventing a baseline for it manufactures
exactly the alarm this module exists to prevent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text

from app.db import GetDB

logger = logging.getLogger(__name__)

# Below this an hour's "normal" is noise — a handful of keepalives — and
# dividing by it invents drama out of a few kilobytes.
#
# 8 MiB was too low, and the fleet says where the real line is: at any given
# hour the working nodes carry 150 MB to 12 GB, and the next one down carries
# 1.6 MB. Node 38 lives in that gap — 15-30 MB in its busiest hours — so it
# crossed the old floor a few times a day and produced almost every alert
# there was: twelve of the day's silence warnings were its. A node that moves
# a thousandth of what its neighbours move is not worth waking anyone over,
# and its silence says nothing that its traffic did not already say.
BASELINE_FLOOR_BYTES_PER_HOUR = 64 << 20  # 64 MiB/h

# node_usages holds one row per node per hour, and the row for the hour we are
# in is still being written. Counting it compares a few minutes of traffic
# against whole hours of history and reports the entire fleet as collapsed —
# at two minutes past the hour, every node reads at half of normal. Everything
# here is measured over *completed* hours only.
HOUR_START = ("(NOW() - INTERVAL MINUTE(NOW()) MINUTE "
              "- INTERVAL SECOND(NOW()) SECOND)")


@dataclass(frozen=True)
class Reading:
    node_id: int
    recent_per_hour: float
    baseline_per_hour: float

    @property
    def ratio(self) -> float:
        """Recent hours as a share of normal. Check ``meaningful`` first.

        With nothing to compare against this answers "infinitely above
        normal", which is the safe direction: every caller here treats a high
        ratio as healthy, so a node with no history can never be alarmed about
        by accident.
        """
        if self.baseline_per_hour <= 0:
            return float("inf")
        return self.recent_per_hour / self.baseline_per_hour

    @property
    def meaningful(self) -> bool:
        return self.baseline_per_hour >= BASELINE_FLOOR_BYTES_PER_HOUR


def _rows(sql: str, params: dict) -> list:
    try:
        with GetDB() as db:
            return list(db.execute(text(sql), params))
    except Exception:
        logger.exception("node traffic profile query failed")
        return []


def expected_now(baseline_days: int = 7) -> dict[int, float]:
    """node_id -> bytes it usually moves during the current clock hour.

    Yesterday's 03:00 and the one before it, not yesterday's average: the
    point is to know whether *this* hour is normally busy.
    """
    sql = f"""
        SELECT node_id, COALESCE(SUM(uplink + downlink), 0) / :days
        FROM node_usages
        WHERE created_at < {HOUR_START} - INTERVAL 1 DAY
          AND created_at > NOW() - INTERVAL :window DAY
          AND HOUR(created_at) = HOUR(NOW())
        GROUP BY node_id
    """
    days = max(1, int(baseline_days))
    out: dict[int, float] = {}
    for node_id, avg in _rows(sql, {"days": days, "window": days + 1}):
        if node_id is None:
            continue
        out[int(node_id)] = float(avg or 0.0)
    return out


def traffic_vs_baseline(recent_hours: int = 2,
                        baseline_days: int = 7) -> dict[int, Reading]:
    """node_id -> recent hours against the same hours of the past week."""
    recent_hours = max(1, int(recent_hours))
    baseline_days = max(1, int(baseline_days))
    hours = ", ".join(f"HOUR({HOUR_START} - INTERVAL {h} HOUR)"
                      for h in range(1, recent_hours + 1))
    sql = f"""
        SELECT node_id,
               COALESCE(SUM(CASE WHEN created_at >= {HOUR_START}
                                       - INTERVAL :recent HOUR
                                  AND created_at < {HOUR_START}
                                 THEN uplink + downlink END), 0),
               COALESCE(SUM(CASE WHEN created_at < {HOUR_START}
                                       - INTERVAL 1 DAY
                                  AND HOUR(created_at) IN ({hours})
                                 THEN uplink + downlink END), 0)
        FROM node_usages
        WHERE created_at > NOW() - INTERVAL :window DAY
        GROUP BY node_id
    """
    # The reference window is those same clock hours on each of the past days.
    buckets = baseline_days * recent_hours
    out: dict[int, Reading] = {}
    for node_id, recent, past in _rows(
            sql, {"recent": recent_hours, "window": baseline_days + 1}):
        if node_id is None:
            continue
        out[int(node_id)] = Reading(
            node_id=int(node_id),
            recent_per_hour=float(recent or 0) / recent_hours,
            baseline_per_hour=float(past or 0) / buckets,
        )
    return out


def nodes_with_visible_hosts() -> set[int]:
    """Nodes a subscriber can actually reach, by either end of a bridge.

    A node whose every host is hidden moves nothing *by construction*, and
    alerting on its silence is the loop the audit already learned the hard
    way: hidden, therefore quiet, therefore never restored. Both ends count —
    an exit carries the traffic of hosts that live on the entries pointing at
    it, and has no hosts of its own.
    """
    sql = """
        SELECT DISTINCT n.id
        FROM nodes n
        JOIN inbounds i ON i.node_id = n.id OR i.exit_node_id = n.id
        JOIN hosts h ON h.inbound_id = i.id
        WHERE h.is_disabled = 0
    """
    return {int(r[0]) for r in _rows(sql, {}) if r[0] is not None}
