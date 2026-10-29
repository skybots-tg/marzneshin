"""xray's own DNS queries must never land in a block rule.

GE-2 blocked 127.0.0.0/8 and asked a local AdGuard for names: every new
connection through it waited out the 4 s DNS timeout. The patcher now tags the
DNS section and sends it out the freedom outbound ahead of every other rule.
"""

from __future__ import annotations

import json

from app.models.node_filtering import DnsProvider
from app.utils.xray_config_patcher import patch_config_disable, patch_config_enable

GE2_LIKE = {
    "inbounds": [{"tag": "GE-2", "port": 50443, "protocol": "vless"}],
    "outbounds": [{"tag": "direct", "protocol": "freedom",
                   "settings": {"domainStrategy": "UseIPv4"}},
                  {"tag": "block", "protocol": "blackhole"}],
    "routing": {"rules": [{"type": "field", "outboundTag": "block",
                           "ip": ["10.0.0.0/8", "127.0.0.0/8"]}]},
}


def enable(config=GE2_LIKE):
    out = patch_config_enable(json.dumps(config), DnsProvider.adguard_home_local,
                              None, 5353)
    return json.loads(out)


def test_local_adguard_queries_go_out_before_any_block_rule():
    c = enable()
    assert c["dns"]["servers"] == [{"address": "127.0.0.1", "port": 5353}]
    assert c["dns"]["tag"] == "dns-internal"
    assert c["routing"]["rules"][0] == {"type": "field",
                                        "inboundTag": ["dns-internal"],
                                        "outboundTag": "direct"}


def test_patching_twice_keeps_one_dns_rule():
    c = enable(enable())
    dns_rules = [r for r in c["routing"]["rules"]
                 if r.get("inboundTag") == ["dns-internal"]]
    assert len(dns_rules) == 1
    assert c["routing"]["rules"][0] == dns_rules[0]


def test_an_existing_dns_tag_is_reused():
    config = dict(GE2_LIKE, dns={"tag": "my-dns", "servers": ["1.1.1.1"]})
    c = enable(config)
    assert c["dns"]["tag"] == "my-dns"
    assert c["routing"]["rules"][0]["inboundTag"] == ["my-dns"]


def test_the_freedom_outbound_is_found_by_protocol_not_by_name():
    config = dict(GE2_LIKE, outbounds=[{"tag": "block", "protocol": "blackhole"},
                                       {"tag": "DIRECT", "protocol": "freedom"}])
    assert enable(config)["routing"]["rules"][0]["outboundTag"] == "DIRECT"


def test_without_a_freedom_outbound_nothing_is_routed():
    config = dict(GE2_LIKE, outbounds=[{"tag": "block", "protocol": "blackhole"}])
    c = enable(config)
    assert "tag" not in c["dns"]
    assert all(r.get("inboundTag") != ["dns-internal"] for r in c["routing"]["rules"])


def test_disabling_ad_blocking_keeps_the_dns_rule():
    c = json.loads(patch_config_disable(json.dumps(enable())))
    assert c["dns"]["servers"] == ["1.1.1.1", "8.8.8.8"]
    assert c["routing"]["rules"][0]["inboundTag"] == ["dns-internal"]


def audit_rule_index(rules):
    return next(i for i, r in enumerate(rules)
                if "full:api.country.is" in r.get("domain", []))


def ads_rule_index(rules):
    return next(i for i, r in enumerate(rules)
                if "geosite:category-ads-all" in r.get("domain", []))


def test_the_audit_geo_lookups_pass_just_ahead_of_the_ads_rule():
    rules = enable(enable())["routing"]["rules"]
    at = audit_rule_index(rules)
    assert at + 1 == ads_rule_index(rules)
    assert rules[at]["outboundTag"] == "direct"
    assert sum("full:api.country.is" in r.get("domain", []) for r in rules) == 1


def test_disabling_ad_blocking_drops_the_audit_rule_with_the_ads_rule():
    rules = json.loads(patch_config_disable(json.dumps(enable())))["routing"]["rules"]
    assert not any("full:api.country.is" in r.get("domain", []) for r in rules)
