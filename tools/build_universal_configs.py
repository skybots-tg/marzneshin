"""Build new xray_config.json for U1/U2/U3 RU entry nodes, adding the missing
multihop bridges to reach full parity with U4/U6/U7.

Strategy: read each node's CURRENT config (downloaded into .tmp_uni_configs/),
deep-copy it, then append the missing bridges:
  - inbound  (reality listener, canonical port, fresh shortId, placeholder priv key)
  - outbound (canonical exit, copied from the U6 reference config)
  - routing rule inboundTag -> outboundTag

Private keys are left as placeholders __KEY_n__ to be filled with real
`xray x25519` private keys generated ON each node. ShortIds are random hex.

For U2 only: the existing "RU->US Bridge" inbound is migrated from port 12443
to 55443 (canonical), freeing 12443 for the new "RU->USA-2 Bridge". The inbound
TAG is preserved so the DB inbound row + host + service links survive.

Output: .tmp_uni_configs/<ip>.new.json  and  .tmp_uni_configs/<ip>.keys.txt
(the keys file lists how many private keys are required, one placeholder per line).
"""
import copy
import json
import os
import secrets

BASE = os.path.join(os.path.dirname(__file__), "..", ".tmp_uni_configs")
REF_U6 = "193.233.246.18"   # node34: full tcp set on canonical ports
REF_U4 = "45.150.239.178"   # node30: ge-1 xhttp + pl-1 xhttp

TARGETS = {
    "89.191.225.218": "U1",  # node 25
    "84.252.101.98":  "U2",  # node 15
    "5.35.125.174":   "U3",  # node 12
}

# Canonical extra bridges (beyond base ee/fl/fr/direct that every node has).
# (ref_ip, ref_inbound_tag)  -> template source.
CANON_BRIDGES = [
    (REF_U6, "RU->TR-1 Bridge"),
    (REF_U6, "RU->USA-2 Bridge"),
    (REF_U6, "RU->FR-2 Bridge"),
    (REF_U6, "RU->PL-1 Bridge"),
    (REF_U6, "RU->NL-1 Bridge"),
    (REF_U6, "RU->GE-1 Bridge"),
    (REF_U6, "RU->GE-2 Bridge"),
    (REF_U6, "RU->FI-1 Bridge"),
    (REF_U6, "RU->FI-2 Bridge"),
    (REF_U6, "RU->US Bridge"),
    (REF_U4, "RU->GE-1 Bridge (XHTTP)"),
    (REF_U4, "RU->PL-1 Bridge (XHTTP)"),
]


def load(ip):
    with open(os.path.join(BASE, f"{ip}.json"), encoding="utf-8") as f:
        return json.load(f)


def routing_map(cfg):
    m = {}
    for r in cfg.get("routing", {}).get("rules", []):
        for it in r.get("inboundTag", []):
            m[it] = r.get("outboundTag")
    return m


def find_inbound(cfg, tag):
    for ib in cfg["inbounds"]:
        if ib["tag"] == tag:
            return ib
    return None


def find_outbound(cfg, tag):
    for ob in cfg["outbounds"]:
        if ob["tag"] == tag:
            return ob
    return None


def rand_sid():
    return secrets.token_hex(8)  # 16 hex chars


def main():
    ref6 = load(REF_U6)
    ref4 = load(REF_U4)
    rt6, rt4 = routing_map(ref6), routing_map(ref4)
    refs = {REF_U6: (ref6, rt6), REF_U4: (ref4, rt4)}

    # Build the canonical bridge specs once: inbound template + outbound + route.
    specs = []  # each: {tag, port, network, outbound, inbound_template, outbound_json}
    for ref_ip, tag in CANON_BRIDGES:
        rcfg, rrt = refs[ref_ip]
        ib = copy.deepcopy(find_inbound(rcfg, tag))
        ob_tag = rrt[tag]
        ob = copy.deepcopy(find_outbound(rcfg, ob_tag))
        # scrub the template's reality private key / shortIds (set later)
        rs = ib["streamSettings"]["realitySettings"]
        rs["privateKey"] = "__PLACEHOLDER__"
        rs["shortIds"] = ["__PLACEHOLDER__"]
        ib["settings"] = {"clients": [], "decryption": "none"}
        specs.append({
            "tag": tag,
            "port": ib["port"],
            "network": ib["streamSettings"]["network"],
            "outbound_tag": ob_tag,
            "inbound": ib,
            "outbound": ob,
        })

    summary = {}
    for ip, uname in TARGETS.items():
        cfg = load(ip)
        existing_in_tags = {ib["tag"] for ib in cfg["inbounds"]}
        existing_out_tags = {ob["tag"] for ob in cfg["outbounds"]}
        existing_ports = {ib.get("port") for ib in cfg["inbounds"]}

        new_cfg = copy.deepcopy(cfg)
        key_idx = 0
        added = []

        # --- US handling: a node may already expose US under tag
        # "RU->US Bridge" or the legacy "RU->US-1 Bridge". In either case we
        # KEEP the existing tag (so the DB inbound + host + service links
        # survive — reconciliation is by tag) and only normalise its listening
        # port to the canonical 55443. We must then NOT add a second US bridge.
        US_TAGS = {"RU->US Bridge", "RU->US-1 Bridge"}
        existing_us_tag = next((t for t in US_TAGS if t in existing_in_tags), None)
        if existing_us_tag:
            us_ib = find_inbound(new_cfg, existing_us_tag)
            if us_ib and us_ib.get("port") != 55443:
                old = us_ib["port"]
                us_ib["port"] = 55443
                existing_ports.discard(old)
                existing_ports.add(55443)
                added.append(f"MIGRATE {existing_us_tag} port {old}->55443")

        for spec in specs:
            tag = spec["tag"]
            if tag in existing_in_tags:
                continue  # already present (e.g. U2 already has tr-1/ge-1/...)
            if tag == "RU->US Bridge" and existing_us_tag:
                continue  # US already provided under existing tag
            if spec["port"] in existing_ports:
                raise SystemExit(
                    f"{uname}: port {spec['port']} for {tag} already in use!")
            ib = copy.deepcopy(spec["inbound"])
            rs = ib["streamSettings"]["realitySettings"]
            rs["privateKey"] = f"__KEY_{key_idx}__"
            rs["shortIds"] = [rand_sid()]
            key_idx += 1
            new_cfg["inbounds"].append(ib)
            existing_ports.add(spec["port"])

            if spec["outbound_tag"] not in existing_out_tags:
                new_cfg["outbounds"].append(copy.deepcopy(spec["outbound"]))
                existing_out_tags.add(spec["outbound_tag"])

            new_cfg["routing"]["rules"].append({
                "type": "field",
                "inboundTag": [tag],
                "outboundTag": spec["outbound_tag"],
            })
            added.append(f"ADD {tag} :{spec['port']} {spec['network']} -> {spec['outbound_tag']}")

        out_path = os.path.join(BASE, f"{ip}.new.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(new_cfg, f, indent=2, ensure_ascii=False)
        keys_path = os.path.join(BASE, f"{ip}.keys.txt")
        with open(keys_path, "w", encoding="utf-8") as f:
            f.write(str(key_idx) + "\n")

        summary[ip] = {"u": uname, "keys_needed": key_idx, "ops": added}

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
