#!/usr/bin/env python3
"""Give unmanaged exit servers the bridge user they will never be sent.

An exit's reality listener starts with an empty client list; the users allowed
through it are pushed at runtime by the panel over gRPC. Bridge traffic arrives
as one fixed identity, SHARED_USER_ID, and rides in on that same push. The
arrangement holds only while the exit is a node the panel knows about.

An exit that was never registered — or was removed from the panel while the
entry nodes kept their outbounds pointed at it — still listens, still completes
the reality handshake, and then rejects every bridge behind it, because the one
user it needs to recognise is never delivered. From a probe that is
indistinguishable from a network block, which is why it can sit unnoticed for
weeks.

Writing that user straight into the listener's config settles it: the exit
knows the bridge user from disk and stops depending on a conversation that is
never going to happen.

Managed exits are deliberately left alone. There the push works, so pinning
would add a second copy of the same identity for no gain.

    python3 bridge_exit_pin.py                  # who needs the pin
    python3 bridge_exit_pin.py --apply          # write it and restart xray
    python3 bridge_exit_pin.py --exit 1.2.3.4 --apply --force
"""
from __future__ import annotations

import argparse
import sys

import bridge_lib as bl
import marz_common as mc

# marznode reads usage counters back as "<user id>.<username>" and calls int()
# on the first field, so a free-form address here crashes its stats loop on
# every poll. Keeping the shape costs nothing and keeps the exit's reporting
# intact.
PIN_EMAIL = "0.bridge"


def exits_in_use() -> dict[tuple[str, int], list[str]]:
    """(exit ip, port) -> entry nodes whose outbounds aim there."""
    found: dict[tuple[str, int], list[str]] = {}
    entries = {}
    for t in bl.load_targets(tiers=("universal", "elite", "fast")):
        entries.setdefault(t.address, t.node_name)

    for address, name in sorted(entries.items()):
        try:
            cfg = mc.node_cfg(address)
        except Exception as exc:  # unreachable entry: nothing to learn here
            print(f"  cannot read {name} ({address}): {exc}")
            continue
        for ob in cfg.get("outbounds", []):
            for v in (ob.get("settings") or {}).get("vnext") or []:
                if any(u.get("id") == mc.SHARED_USER_ID
                       for u in v.get("users") or []):
                    found.setdefault((v["address"], int(v["port"])),
                                     []).append(name)
    return found


def managed_addresses() -> set[str]:
    return {row[0] for row in mc.db_query("SELECT address FROM nodes")}


def pin(address: str, port: int, apply: bool) -> bool:
    """Ensure the listener on `port` carries the bridge user. True if changed."""
    try:
        cfg = mc.node_cfg(address)
    except Exception as exc:
        print(f"  {address}: cannot read config ({exc})")
        return False

    ib = next((i for i in cfg.get("inbounds", [])
               if int(i.get("port") or 0) == port), None)
    if ib is None:
        print(f"  {address}: nothing listens on {port}")
        return False

    settings = ib.setdefault("settings", {})
    clients = settings.setdefault("clients", [])
    existing = next((c for c in clients if c.get("id") == mc.SHARED_USER_ID),
                    None)
    if existing and existing.get("email") == PIN_EMAIL:
        print(f"  {address}:{port} ({ib.get('tag')}): already pinned")
        return False
    if existing:
        print(f"  {address}:{port} ({ib.get('tag')}): pinned under "
              f"{existing.get('email')!r}, rewriting")
        clients.remove(existing)

    print(f"  {address}:{port} ({ib.get('tag')}): bridge user missing, "
          f"{len(clients)} static client(s) present")
    if not apply:
        return True

    clients.append({"id": mc.SHARED_USER_ID, "flow": "xtls-rprx-vision",
                    "email": PIN_EMAIL, "level": 0})
    ok, out = mc.deploy(address, cfg)
    print("    " + out.strip().replace("\n", "\n    "))
    if not ok:
        print(f"    FAILED to deploy to {address}; config left untouched")
        return False
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--exit", default="", help="only this exit address")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--force", action="store_true",
                   help="also pin exits the panel manages (rarely wanted)")
    args = p.parse_args()

    print("collecting exits referenced by bridge outbounds...")
    targets = exits_in_use()
    if not targets:
        print("no bridge outbounds found")
        return 1

    managed = managed_addresses()
    todo = []
    for (address, port), entries in sorted(targets.items()):
        if args.exit and address != args.exit:
            continue
        if address in managed and not args.force:
            continue
        todo.append((address, port, entries))

    if not todo:
        print("every exit in use is a node the panel manages — nothing to pin")
        return 0

    print(f"\n{len(todo)} exit(s) outside the panel's reach:")
    changed = 0
    for address, port, entries in todo:
        print(f"\n{address}:{port}  used by {len(entries)} entry node(s): "
              f"{', '.join(sorted(set(entries)))}")
        changed += bool(pin(address, port, args.apply))

    if not args.apply:
        print(f"\nDRY RUN: {changed} exit(s) would be pinned. Re-run with --apply.")
    else:
        print(f"\npinned {changed} exit(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
