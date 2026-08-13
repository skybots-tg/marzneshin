#!/usr/bin/env python3
"""Fill an entry x exit gap by cloning a working bridge from a donor entry.

Invoked as `bridge_audit.py fill <entry> <slot...> --apply`.

The donor is any other RU entry node whose bridge to that exit passed the last
scan, so we only ever clone a route that is proven to carry traffic. On the
target node we recreate the inbound with a *fresh* reality keypair (never reuse
a donor's private key) plus the donor's outbound and routing rule, gate the
swap behind `xray -test`, then create the DB rows with the host hidden. The
host is only revealed once a live egress probe through it succeeds.
"""
from __future__ import annotations

import copy
import json
import re

import bridge_lib as bl
import bridge_probe as bp
import bridge_weights as bw
import marz_common as mc

DEFAULT_PORT_RANGE = range(23000, 23400)


def probe_from_ru(targets, user_uuid: str, vantages=None) -> None:
    """Fill in ``t.result`` for every target, judged from RU vantage points.

    Never probe from the panel here: it sits abroad, and RU providers drop a
    good share of foreign traffic, so a donor that works perfectly for
    subscribers would look dead and the fill would refuse to run.
    """
    vantages = vantages or bp.default_vantages(targets, limit=3)
    per_vantage = bp.probe_all(targets, vantages, user_uuid, workers=6,
                               timeout=12)
    bp.merge(targets, per_vantage)


def normalize_entry(key: str) -> str:
    """Accept 'U4', 'u-4', 'universal-4', 'E1' -> canonical entry key."""
    k = key.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(universal|elite|u|e)-?(\d+)", k)
    if not m:
        raise SystemExit(f"cannot parse entry key {key!r} (try U4 or universal-4)")
    tier = "universal" if m.group(1)[0] == "u" else "elite"
    return f"{tier}-{int(m.group(2))}"


def pick_donor(targets, slot, exclude_key, forced="", tier=""):
    """Best working (host, inbound) to clone for `slot`, tcp preferred.

    Same-tier donors win: the tiers differ in branding and in the service they
    belong to, and cloning across them produces a host wearing the wrong name.
    """
    cands = [t for t in targets
             if t.slot == slot and t.entry_key != exclude_key
             and t.result.get("verdict") in ("pass", "wrong_geo")]
    if forced:
        want = normalize_entry(forced)
        cands = [t for t in cands if t.entry_key == want]
    elif tier:
        cands = [t for t in cands if t.tier == tier] or cands
    if not cands:
        return None
    cands.sort(key=lambda t: (t.variant != "tcp", t.result.get("elapsed", 99)))
    return cands[0]


def target_entry_meta(targets, entry_key):
    for t in targets:
        if t.entry_key == entry_key:
            return t
    return None


def free_port(used: set[int], preferred: int) -> int:
    if preferred and preferred not in used:
        return preferred
    for p in DEFAULT_PORT_RANGE:
        if p not in used:
            return p
    raise SystemExit("no free port left on the target node")


def clone_remark(donor, target_tier: str, target_idx: int) -> str:
    """The name the new host should carry in subscriptions.

    Within one tier the donor's remark is reused verbatim except for the index,
    which preserves hand-written details like "(Я за границей)". Across tiers
    the branding is rebuilt from scratch, since an ELITE remark on a UNIVERSAL
    entry would be plainly wrong to the subscriber.
    """
    if donor.tier == target_tier:
        return re.sub(rf"\b(UNIVERSAL|ELITE|FAST)\s+{donor.tier_index}\b",
                      lambda m: f"{m.group(1)} {target_idx}",
                      donor.remark, flags=re.I)
    label = donor.slot + (" xhttp" if donor.variant == "xhttp" else "")
    builder = {"universal": mc.universal_remark, "elite": mc.elite_remark,
               "fast": mc.fast_remark}[target_tier]
    return builder(target_idx, donor.iso or "", label)


def entry_weight(targets, slot, fallback_idx) -> int:
    """Where the new host belongs in the subscription order.

    Weights follow `100 + (brand - 1) * 10 + slot_offset`; taking the group's
    most common weight instead would drop every new bridge on the block
    boundary, ahead of exits that are meant to precede it.
    """
    offsets, _ = bw.learn_offsets(targets)
    base = bw.brand_base(fallback_idx)
    return base + offsets.get(slot, 0)


def plan_one(slot, donor, tgt_meta, tgt_cfg, donor_cfg, used_ports, targets):
    """Return the node-config mutations + DB rows for one slot, or an error."""
    tag = donor.tag
    donor_ib = mc.find(donor_cfg["inbounds"], tag)
    if not donor_ib:
        return None, f"donor node {donor.node_id} has no inbound {tag!r}"
    out_tag = mc.routing_map(donor_cfg).get(tag)
    if not out_tag:
        return None, f"donor node {donor.node_id} has no route for {tag!r}"
    donor_ob = mc.find(donor_cfg["outbounds"], out_tag)
    if not donor_ob:
        return None, f"donor node {donor.node_id} has no outbound {out_tag!r}"

    existing = mc.find(tgt_cfg["inbounds"], tag)
    port = (existing or {}).get("port") or free_port(used_ports, donor_ib.get("port"))
    used_ports.add(port)

    return {
        "slot": slot, "tag": tag, "out_tag": out_tag, "port": port,
        "donor": donor, "donor_ib": donor_ib, "donor_ob": donor_ob,
        "inbound_exists": existing is not None,
        "remark": clone_remark(donor, tgt_meta.tier, tgt_meta.tier_index),
        "weight": entry_weight(targets, slot, tgt_meta.tier_index),
    }, None


def apply_node_config(tgt_cfg, plans, tgt_ip, apply: bool):
    """Add the inbounds/outbounds/routes to the target node config."""
    new = copy.deepcopy(tgt_cfg)
    have_out = {o.get("tag") for o in new["outbounds"]}
    routed = set(mc.routing_map(new))
    keys = mc.gen_keys(tgt_ip, len(plans)) if apply else \
        [("__PRIV__", "__PUB__")] * len(plans)

    for p, (priv, pub) in zip(plans, keys):
        p["pbk"], sid = pub, mc.rand_sid()
        p["sid"] = sid
        if not p["inbound_exists"]:
            ib = copy.deepcopy(p["donor_ib"])
            ib["port"] = p["port"]
            ib["settings"] = {"clients": [], "decryption": "none"}
            rs = ib["streamSettings"]["realitySettings"]
            rs["privateKey"], rs["shortIds"] = priv, [sid]
            new["inbounds"].append(ib)
        if p["out_tag"] not in have_out:
            new["outbounds"].append(copy.deepcopy(p["donor_ob"]))
            have_out.add(p["out_tag"])
        if p["tag"] not in routed:
            new["routing"]["rules"].append({
                "type": "field", "inboundTag": [p["tag"]],
                "outboundTag": p["out_tag"]})
            routed.add(p["tag"])
    return new


def db_sql(plans, node_id, address) -> str:
    sql = []
    for p in plans:
        donor = p["donor"]
        cfg = {
            "tag": p["tag"], "protocol": "vless", "port": p["port"],
            "network": donor.network, "tls": "reality",
            "sni": [donor.sni], "host": [], "path": donor.path,
            "header_type": None,
            "flow": donor.flow if donor.variant == "tcp" else None,
            "is_fallback": False, "fp": donor.fp,
            "pbk": p["pbk"], "sid": p["sid"],
        }
        sql.append(mc.insert_inbound_sql(node_id, p["tag"], cfg))
        sql.append(mc.link_service_sql(node_id, p["tag"]))
        # created hidden: the egress probe below is what reveals it
        sql.append(
            "INSERT INTO hosts (remark, address, port, sni, security, "
            "fingerprint, inbound_id, is_disabled, weight, universal, "
            "mlkem_enabled) SELECT "
            f"{mc.sqlstr(p['remark'])}, {mc.sqlstr(address)}, NULL, "
            f"{mc.sqlstr(donor.sni)}, 'inbound_default', "
            f"{mc.sqlstr(donor.fp)}, i.id, 1, {p['weight']}, 0, 0 "
            f"FROM inbounds i WHERE i.node_id={node_id} "
            f"AND i.tag={mc.sqlstr(p['tag'])} AND NOT EXISTS "
            "(SELECT 1 FROM (SELECT * FROM hosts) h WHERE h.inbound_id=i.id);")
    return "\n".join(sql) + "\n"


def verify_and_reveal(node_id, plans, user_uuid, apply: bool, vantages=None):
    """Probe each freshly created host; reveal the ones that carry traffic."""
    fresh = {t.tag: t for t in bl.load_targets(tiers=("universal", "elite"),
                                               node_ids={node_id})}
    wanted = [fresh[p["tag"]] for p in plans if p["tag"] in fresh]
    if wanted:
        probe_from_ru(wanted, user_uuid, vantages)
    ok, bad = [], []
    for p in plans:
        t = fresh.get(p["tag"])
        if not t:
            bad.append((p["slot"], "host row not found after insert"))
            continue
        v = t.result["verdict"]
        print(f"    probe {p['slot']:<8} -> {v} "
              f"{t.result.get('country') or t.result.get('error', '')}")
        (ok if v in ("pass", "wrong_geo") else bad).append(
            (p["slot"], t.host_id if v in ("pass", "wrong_geo")
             else t.result.get("error")))
    if ok and apply:
        ids = ",".join(str(h) for _, h in ok)
        mc.db(f"UPDATE hosts SET is_disabled=0 WHERE id IN ({ids});\n")
    return ok, bad


def run(args) -> int:
    entry_key = normalize_entry(args.entry)
    slots = [s.strip().upper() for s in args.slots]

    print(f"loading current state and probing donors for {entry_key} ...")
    targets = bl.load_targets(tiers=("universal", "elite"))
    tgt_meta = target_entry_meta(targets, entry_key)
    if not tgt_meta:
        raise SystemExit(f"unknown entry {entry_key}")
    if not bl.ensure_xray():
        raise SystemExit("cannot extract xray binary from a marznode container")

    # Probe only the slots we care about, on every entry, to find live donors.
    candidates = [t for t in targets if t.slot in slots]
    for t in targets:
        t.result = {"verdict": "unknown"}
    vantages = bp.default_vantages(targets, limit=3)
    if candidates:
        probe_from_ru(candidates, args.user, vantages)

    plans, errors = [], []
    tgt_cfg = mc.node_cfg(tgt_meta.address)
    used_ports = {ib.get("port") for ib in tgt_cfg["inbounds"]}
    for slot in slots:
        donor = pick_donor(targets, slot, entry_key, args.donor,
                           tier=tgt_meta.tier)
        if not donor:
            errors.append((slot, "no donor entry currently reaches this exit"))
            continue
        donor_cfg = mc.node_cfg(donor.address)
        plan, err = plan_one(slot, donor, tgt_meta, tgt_cfg, donor_cfg,
                             used_ports, targets)
        (plans.append(plan) if plan else errors.append((slot, err)))

    for slot, err in errors:
        print(f"  SKIP {slot}: {err}")
    if not plans:
        print("nothing to do")
        return 1

    print(f"\nplan for {entry_key} (node {tgt_meta.node_id} "
          f"{tgt_meta.node_name} @ {tgt_meta.address}):")
    for p in plans:
        print(f"  + {p['tag']:<26} :{p['port']:<6} -> {p['out_tag']:<10} "
              f"donor {p['donor'].entry_key:<12} remark {p['remark']}")
    if not args.apply:
        print("\nDRY RUN. Re-run with --apply.")
        return 0

    new_cfg = apply_node_config(tgt_cfg, plans, tgt_meta.address, True)
    ok, out = mc.deploy(tgt_meta.address, new_cfg)
    print("\n" + out.strip())
    if not ok:
        print("NODE DEPLOY FAILED — DB untouched")
        return 3

    r = mc.db(db_sql(plans, tgt_meta.node_id, tgt_meta.address))
    if r.returncode != 0:
        print("DB INSERT FAILED:", r.stderr[:400])
        return 4
    print("DB rows created (hosts hidden pending verification)")

    good, bad = verify_and_reveal(tgt_meta.node_id, plans, args.user, True,
                                  vantages)
    print(f"\nrevealed {len(good)} working bridge(s) on {entry_key}")
    for slot, err in bad:
        print(f"  still hidden: {slot} ({err})")
    return 0
