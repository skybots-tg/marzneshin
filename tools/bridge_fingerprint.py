#!/usr/bin/env python3
"""Run ON the panel. Set the uTLS fingerprint of an entry node's bridge outbounds.

The fingerprint is the TLS hello the entry sends to each exit. Chrome's hello
carries a post-quantum key share and no longer fits one TCP segment; on
AdminVPS (UNIVERSAL 1 and 5) a series of such hellos is cut after four or five
-- the second segment never arrives, the exit waits, the bridge goes quiet for
~90 s. Firefox's hello passes the same path 10/10 (2026-10-01). The same holds
for the client side, which is the hosts' ``fingerprint`` column.

Only reality outbounds are touched; keys, names and routing stay as they are.
Deploys through marz_common.deploy (xray -test, backup, swap, restart), so the
node's clients reconnect once. Dry-run unless --apply.

usage: bridge_fingerprint.py [--fp firefox] [--apply] <ip> [ip ...]
"""
import argparse
import sys

import marz_common as mc


def retarget(cfg: dict, fp: str) -> list[str]:
    """Set ``fp`` on every reality outbound; return the tags that changed."""
    changed = []
    for ob in cfg.get("outbounds", []):
        rs = (ob.get("streamSettings") or {}).get("realitySettings")
        if rs is not None and rs.get("fingerprint") != fp:
            changed.append(f"{ob.get('tag')}: {rs.get('fingerprint')} -> {fp}")
            rs["fingerprint"] = fp
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ips", nargs="+")
    ap.add_argument("--fp", default="firefox")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    failed = 0
    for ip in args.ips:
        cfg = mc.node_cfg(ip)
        changed = retarget(cfg, args.fp)
        print(f"== {ip}: {len(changed)} outbound(s) to change")
        for line in changed:
            print("   ", line)
        if not changed or not args.apply:
            continue
        ok, out = mc.deploy(ip, cfg)
        print("   deploy:", "OK" if ok else "FAILED")
        if not ok:
            print(out[-600:])
            failed += 1
    if not args.apply:
        print("\nDRY RUN. Re-run with --apply.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
