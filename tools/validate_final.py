import json, os
BASE = os.path.join(os.path.dirname(__file__), "..", ".tmp_uni_configs")
IPS = ["89.191.225.218", "84.252.101.98", "5.35.125.174"]
TARGET_TAGS = {
    "RU->TR-1 Bridge","RU->USA-2 Bridge","RU->FR-2 Bridge","RU->PL-1 Bridge",
    "RU->NL-1 Bridge","RU->GE-1 Bridge","RU->GE-2 Bridge","RU->FI-1 Bridge",
    "RU->FI-2 Bridge","RU->GE-1 Bridge (XHTTP)","RU->PL-1 Bridge (XHTTP)",
}
for ip in IPS:
    cfg = json.load(open(os.path.join(BASE, f"{ip}.final.json"), encoding="utf-8"))
    ports = [ib["port"] for ib in cfg["inbounds"]]
    assert len(ports) == len(set(ports)), f"{ip}: DUPLICATE PORTS {ports}"
    in_tags = {ib["tag"] for ib in cfg["inbounds"]}
    out_tags = {ob["tag"] for ob in cfg["outbounds"]}
    routed = {}
    for r in cfg["routing"]["rules"]:
        for it in r["inboundTag"]:
            routed[it] = r["outboundTag"]
    # every inbound routed
    for t in in_tags:
        assert t in routed, f"{ip}: inbound {t} has NO routing rule"
        assert routed[t] in out_tags, f"{ip}: {t} -> {routed[t]} missing outbound"
    # every reality inbound has a real key + shortId
    for ib in cfg["inbounds"]:
        rs = ib.get("streamSettings", {}).get("realitySettings")
        if rs:
            assert rs["privateKey"] and "__" not in rs["privateKey"], f"{ip}: bad key {ib['tag']}"
            assert rs["shortIds"] and rs["shortIds"][0], f"{ip}: bad sid {ib['tag']}"
    # US must be on 55443
    us = next((ib for ib in cfg["inbounds"] if ib["tag"] in ("RU->US Bridge","RU->US-1 Bridge")), None)
    assert us and us["port"] == 55443, f"{ip}: US not on 55443 ({us})"
    have_targets = sorted(t for t in TARGET_TAGS if t in in_tags)
    print(f"{ip}: OK ports-unique={len(ports)} us@55443=yes target_tags_present={len(have_targets)}/{len(TARGET_TAGS)}")
print("ALL VALID")
