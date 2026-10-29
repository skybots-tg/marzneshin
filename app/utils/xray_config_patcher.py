"""Patch Xray backend config to enable/disable ad-blocking DNS and sniffing."""

import copy
import json

from app.models.node_filtering import DnsProvider
from app.utils import p2p_guard

_DEFAULT_DNS_SERVERS = ["1.1.1.1", "8.8.8.8"]

_ADS_ROUTING_RULE = {
    "domain": ["geosite:category-ads-all"],
    "outboundTag": "block",
}

_SNIFFING_BLOCK = {
    "enabled": True,
    "destOverride": ["http", "tls"],
}

# Xray routes its own DNS queries like user traffic. A node that blocks private
# addresses (127.0.0.0/8 on GE-2) then drops the queries to a local AdGuard, and
# every new connection waits out the 4 s DNS timeout before xray falls back to
# the system resolver. Tagged queries go straight out instead.
_DNS_TAG = "dns-internal"

# The bridge audit tells a working exit by asking these for its country (GEO in
# tools/bridge_runner.py). category-ads-all and AdGuard's lists count
# api.country.is as a tracker, so an ad-blocking exit failed every probe that
# drew it, and the audit kept DE-2 hidden behind a healthy bridge.
_AUDIT_GEO_DOMAINS = ["full:ipinfo.io", "full:api.country.is", "full:ip-api.com"]


def _dns_servers_for_provider(
    provider: DnsProvider,
    dns_address: str | None,
    adguard_home_port: int,
) -> list:
    match provider:
        case DnsProvider.adguard_home_local:
            return [{"address": "127.0.0.1", "port": adguard_home_port}]
        case DnsProvider.adguard_dns_public:
            return ["94.140.14.14", "94.140.15.15"]
        case DnsProvider.nextdns:
            config_id = dns_address or ""
            return [f"https://dns.nextdns.io/{config_id}"]
        case DnsProvider.cloudflare_security:
            return ["1.1.1.2", "1.0.0.2"]
        case DnsProvider.custom:
            return [dns_address] if dns_address else _DEFAULT_DNS_SERVERS
        case _:
            return _DEFAULT_DNS_SERVERS


def _has_ads_rule(rules: list[dict]) -> bool:
    for rule in rules:
        domains = rule.get("domain", [])
        if "geosite:category-ads-all" in domains:
            return True
    return False


def _remove_ads_rule(rules: list[dict]) -> list[dict]:
    return [
        r for r in rules
        if "geosite:category-ads-all" not in r.get("domain", [])
    ]


def _ensure_block_outbound(outbounds: list[dict]) -> list[dict]:
    for ob in outbounds:
        if ob.get("tag") == "block":
            return outbounds
    return outbounds + [{"tag": "block", "protocol": "blackhole"}]


def _ensure_sniffing_on_inbounds(inbounds: list[dict]) -> list[dict]:
    for inbound in inbounds:
        sniffing = inbound.get("sniffing", {})
        if not sniffing.get("enabled"):
            inbound["sniffing"] = copy.deepcopy(_SNIFFING_BLOCK)
    return inbounds


def _freedom_tag(config: dict) -> str | None:
    return next((ob["tag"] for ob in config.get("outbounds", [])
                 if ob.get("protocol") == "freedom" and ob.get("tag")), None)


def _allow_audit_lookups(config: dict, direct: str | None) -> None:
    """Let the audit's geo lookups through, right ahead of the ads rule."""
    rules = [r for r in config["routing"].get("rules", [])
             if r.get("domain") != _AUDIT_GEO_DOMAINS]
    ads = next((i for i, r in enumerate(rules)
                if "geosite:category-ads-all" in r.get("domain", [])), None)
    if direct is not None and ads is not None:
        rules.insert(ads, {"type": "field", "domain": list(_AUDIT_GEO_DOMAINS),
                           "outboundTag": direct})
    config["routing"]["rules"] = rules


def _route_dns_direct(config: dict, direct: str | None) -> None:
    """Send xray's own DNS queries out the freedom outbound, ahead of any block."""
    if direct is None:
        return
    tag = config["dns"].setdefault("tag", _DNS_TAG)
    rules = [r for r in config["routing"].get("rules", [])
             if r.get("inboundTag") != [tag]]
    config["routing"]["rules"] = [
        {"type": "field", "inboundTag": [tag], "outboundTag": direct}] + rules


def patch_config_enable(
    config_str: str,
    provider: DnsProvider,
    dns_address: str | None,
    adguard_home_port: int,
) -> str:
    """Patch Xray JSON config to enable ad-blocking."""
    config = json.loads(config_str)

    dns_servers = _dns_servers_for_provider(provider, dns_address, adguard_home_port)
    dns_section = config.get("dns", {})
    dns_section["servers"] = dns_servers
    config["dns"] = dns_section

    routing = config.get("routing", {})
    rules = routing.get("rules", [])
    if not _has_ads_rule(rules):
        rules.insert(0, copy.deepcopy(_ADS_ROUTING_RULE))
    routing["rules"] = rules
    config["routing"] = routing

    config["outbounds"] = _ensure_block_outbound(config.get("outbounds", []))
    config["inbounds"] = _ensure_sniffing_on_inbounds(config.get("inbounds", []))

    # Ad-blocking is a toggle; P2P blocking is not. Re-assert it on every write
    # so flipping this switch can never be what drops it (see app/utils/p2p_guard).
    p2p_guard.ensure(config)
    direct = _freedom_tag(config)
    _allow_audit_lookups(config, direct)
    _route_dns_direct(config, direct)

    return json.dumps(config, indent=4, ensure_ascii=False)


def patch_config_disable(config_str: str) -> str:
    """Revert Xray JSON config to defaults (no ad-blocking)."""
    config = json.loads(config_str)

    dns_section = config.get("dns", {})
    dns_section["servers"] = list(_DEFAULT_DNS_SERVERS)
    config["dns"] = dns_section

    routing = config.get("routing", {})
    rules = routing.get("rules", [])
    routing["rules"] = _remove_ads_rule(rules)
    config["routing"] = routing

    # Turning ad-blocking off must not turn P2P blocking off with it.
    p2p_guard.ensure(config)
    direct = _freedom_tag(config)
    _allow_audit_lookups(config, direct)
    _route_dns_direct(config, direct)

    return json.dumps(config, indent=4, ensure_ascii=False)
