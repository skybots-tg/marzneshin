#!/usr/bin/env python3
"""Keep host weights on the pattern the subscription list is built from.

Weights decide the order a client shows the servers in, and the fleet follows
one rule:

    weight = 100 + (brand_index - 1) * 10 + slot_offset

The brand block keeps each UNIVERSAL group together; the slot offset fixes the
order of exits inside a group, so RU sits first and DE last no matter which
group the user is looking at. Hosts created by hand — or by an earlier version
of bridge_fill, which copied the group's most common weight — land on the block
boundary instead and bunch up at the top of their group.

The offset table is not hard-coded: it is read back from the brand that carries
the most distinct offsets, which is by definition the one whose ordering was
maintained. That way a new exit only has to be numbered once, on any one group.

    python3 bridge_weights.py            # report hosts that are off-pattern
    python3 bridge_weights.py --apply    # renumber them
    python3 bridge_weights.py --tier elite
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

import bridge_lib as bl
import marz_common as mc

BLOCK = 10
BASE = 100


def brand_base(index: int) -> int:
    return BASE + (index - 1) * BLOCK


def learn_offsets(targets) -> tuple[dict[str, int], int]:
    """slot -> offset, taken from the best-maintained brand.

    A brand that has been kept in order shows a different offset for most of
    its exits. One whose weights were flattened shows a single value for all of
    them, so counting distinct offsets ranks the brands by trustworthiness.
    """
    by_brand: dict[int, dict[str, int]] = defaultdict(dict)
    for t in targets:
        if not t.weight:
            continue
        off = t.weight - brand_base(t.tier_index)
        if 0 <= off < BLOCK:
            by_brand[t.tier_index][t.slot] = off

    ranked = sorted(by_brand, key=lambda b: (-len(set(by_brand[b].values())),
                                             -len(by_brand[b]), b))
    if not ranked:
        return {}, 0
    reference = ranked[0]
    offsets = dict(by_brand[reference])
    # Slots the reference brand does not serve fall back to any brand that
    # does, preferring the next best-maintained one.
    for b in ranked[1:]:
        for slot, off in by_brand[b].items():
            offsets.setdefault(slot, off)
    return offsets, reference


def canonical(t, offsets: dict[str, int]):
    if t.slot not in offsets:
        return None
    return brand_base(t.tier_index) + offsets[t.slot]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tier", default="universal",
                   choices=["universal", "elite", "fast"])
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    targets = bl.load_targets(tiers=(args.tier,))
    if not targets:
        print(f"no {args.tier} hosts")
        return 1

    offsets, reference = learn_offsets(targets)
    if not offsets:
        print("cannot infer the offset table: no host sits inside a block")
        return 2
    print(f"offset table learned from {args.tier}-{reference}:")
    print("  " + "  ".join(f"{s}={o}" for s, o in
                           sorted(offsets.items(), key=lambda kv: (kv[1], kv[0]))))

    wrong, unknown = [], []
    for t in targets:
        want = canonical(t, offsets)
        if want is None:
            unknown.append(t)
        elif t.weight != want:
            wrong.append((t, want))

    if unknown:
        print(f"\n{len(unknown)} host(s) on an exit with no known position "
              f"— give one of them a weight by hand and re-run:")
        for t in sorted(unknown, key=lambda x: x.remark):
            print(f"  #{t.host_id:<5} {t.remark[:44]:<46} slot {t.slot}")

    if not wrong:
        print("\nevery weight is on pattern")
        return 0

    print(f"\n{len(wrong)} host(s) off pattern:")
    for t, want in sorted(wrong, key=lambda x: (x[0].tier_index, x[1])):
        vis = "" if not t.is_disabled else "  (hidden)"
        print(f"  #{t.host_id:<5} {t.remark[:44]:<46} "
              f"{t.weight} -> {want}{vis}")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply.")
        return 0

    sql = "\n".join(f"UPDATE hosts SET weight={w} WHERE id={t.host_id};"
                    for t, w in wrong)
    r = mc.db(sql + "\n")
    if r.returncode != 0:
        print("DB UPDATE FAILED:", r.stderr[:400])
        return 4
    print(f"\nrenumbered {len(wrong)} host(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
