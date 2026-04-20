---
name: ml-dpi-hardening
description: Recommend and apply Xray inbound configurations resilient to ML-based DPI on Russian ISPs in 2026. Use when the admin says "what configs work in Russia now", "RKN started blocking X", "add a DPI-resistant inbound", or when a previously-working inbound on a UNIVERSAL/ELITE node started timing out from clients but xray is still healthy. Do NOT use for the routine "node is offline" failure mode — that's `diagnose-node-down`.
---
# ML-DPI hardening for Russian ISPs (2026)

This skill captures the field-tested patterns that survive the current
generation of ML-based DPI on RU ISPs (Rostelecom, MTS, Beeline,
Megafon, Yota, Tele2 included). It is intentionally conservative —
every recommendation here is one we already deploy on UNIVERSAL/ELITE
nodes and have observed surviving reflashes of TSPU rules.

The single most important rule: **diversity beats cleverness**. One
exotic inbound is a fingerprint. Three boring inbounds with different
SNI, different ports, different transports give the client a working
fallback.

## What survives in 2026

Ranked by current observed reliability on Russian residential ISPs:

1. **VLESS + Reality + XHTTP** (transport=`xhttp`, mode=`packet-up`).
   The Reality TLS fingerprint is indistinguishable from a real
   browser-to-CDN handshake; XHTTP packet-up framing avoids the
   classic h2 multiplexing fingerprint that TSPU now flags.
2. **VLESS + Reality + raw/tcp** with `flow=xtls-rprx-vision`.
   Still works, but is the most-fingerprinted Reality variant —
   keep it as a fallback, not the primary.
3. **VLESS + Reality + gRPC** with a non-default `serviceName`.
   Useful as a third option on a different port. Default service
   names like `grpc` / `xray` are now flagged.
4. **Trojan + WebSocket + TLS** behind a real Caddy/Nginx with a
   real LE certificate and a real fallback site. Works, but burns a
   real domain and TLS certificate per node — keep for users on
   networks that drop UDP/QUIC and where Reality is being actively
   probed.

What does **not** survive (do NOT add new inbounds for these):
- Plain VMess (any transport).
- Shadowsocks 2022 without an obfuscation layer (TSPU now classifies
  the AEAD framing on idle).
- VLESS + WebSocket + TLS with a self-signed cert or a wildcard
  Cloudflare cert — handshake fingerprint flagged.
- Reality with `dest` pointing at a sanctioned/blocked site
  (Cloudfront, Microsoft 365, etc. on the RKN list).

## Reality `dest` selection

The `dest`/`serverNames` choice is what the DPI sees as the apparent
destination. Wrong choice = your inbound looks like a tunnel to a
known-bad site.

Pick a `dest` that is:
- Reachable from the node's own network (test with `curl -I` from
  inside the node before deploying — if the node can't reach it,
  Reality fallback is broken).
- Not on RKN blocklists or in a sanctioned ASN.
- Has TLS 1.3 + h2 + valid LE cert (Reality requires h2 ALPN).
- Has stable behaviour — no aggressive geo-routing that returns
  different cert chains from different locations.

Currently safe `dest` pool (verified Q1 2026): `www.lovelive-anime.jp:443`,
`gateway.icloud.com:443`, `swdist.apple.com:443`,
`itunes.apple.com:443`. **Rotate every node to a different `dest`** —
all-nodes-on-the-same-`dest` is its own fingerprint.

## Mandatory hardening for every new Reality inbound

These settings reduce the inbound's own fingerprint regardless of
transport. Apply in `streamSettings.realitySettings`:

- `fingerprint`: `chrome` (default `random` is itself fingerprintable
  — it cycles through values in a detectable pattern).
- `shortIds`: at least 2 entries, mixed length (e.g. `["", "a1b2"]`).
  An empty short_id is required for clients that don't send one;
  having only the empty one looks like a default config.
- `spiderX`: leave empty unless you have a specific decoy path.
- `xver`: `0`. PROXY protocol breaks Reality fallback.

## XHTTP-specific hardening (transport=`xhttp`)

When `streamSettings.network=xhttp`, set:

- `xhttpSettings.mode`: `"packet-up"` for new inbounds. `auto` and
  `stream-up` are the older defaults that share fingerprint with
  every default tutorial config.
- `xhttpSettings.path`: a path that looks like a CDN asset path
  (`/assets/v2/main.js`, `/static/img/sprite.svg`). Avoid `/xhttp`,
  `/xray`, `/v2`, `/api`, `/ws` — all flagged.
- `xhttpSettings.host`: same as Reality `serverNames[0]` — the
  forwarded `Host` header must match the SNI.
- `xhttpSettings.headers`: include `User-Agent` mirroring a current
  Chrome stable build. Stale UAs (Chrome 110, Firefox 100) are now
  flagged.

## Per-port hygiene

- Spread inbounds across high, non-canonical ports
  (`8443`, `2087`, `2096`, `4433`, `8447`, etc.). 443 still works
  but a panel with five different inbounds all on 443 is its own
  fingerprint.
- Avoid sequential ports across nodes
  (node1=8001, node2=8002, node3=8003 — easy to enumerate and
  block as a block).
- After every new inbound that exposes a new port, run
  `ensure_node_firewall_for_xray_inbounds(node_id, dry_run=false)`
  on the target. The firewall step is what turns "xray is
  listening" into "clients can actually reach it" — the historical
  cause of the "pingable but nothing opens" reports on UNIVERSAL 4
  and UNIVERSAL 5.

## Routing — keep direct outbound for RU IPs

On RU-resident clients, Russian-IP destinations should bypass the
tunnel entirely (faster + reduces traffic the DPI sees per
connection). Confirm the node's xray config has a routing rule:
`{"type": "field", "ip": ["geoip:ru"], "outboundTag": "direct"}`
ABOVE any catch-all rule. Without it, every Yandex/VK request
becomes evidence the connection is a proxy.

## When the admin asks "what should I add?"

1. List the node's existing inbounds: `list_inbounds(node_id=<id>)`.
2. Pull the live config: `get_node_config(node_id=<id>)`.
3. Identify which categories are missing from the list above
   (Reality+XHTTP packet-up, Reality+raw, Reality+gRPC, Trojan+WS).
4. Propose ONE new inbound at a time — never bulk-add. Each new
   inbound is a new fingerprint surface; deploy → verify → wait
   for client feedback → deploy next.
5. For the proposed inbound, name a concrete `dest`/`serverNames`
   that is NOT already used by any other inbound on this node
   (`get_node_config` shows current usage).

## After deploying a new DPI-hardened inbound

Run, in order:
1. `restart_node_backend(node_id, backend="xray")` — reload the
   new inbound.
2. `ensure_node_firewall_for_xray_inbounds(node_id, dry_run=false)` —
   open the new port in UFW.
3. `propagate_node_to_services(target_node_id=<id>,
   bind_orphan_target_inbounds=true)` — bind the new inbound to
   the same services the existing inbounds on this node belong to,
   otherwise `RepopulateUsers` skips it and clients get zero
   subscription links.
4. `clone_donor_hosts_to_target` (if cloning from a donor with a
   matching tag) OR `add_host` manually for the new tag with
   `host_address` pointing at the node's public IP and a
   sensible remark per `host-remark-convention`.
5. `verify_inbound_e2e(node_id, inbound_tag=<new tag>,
   external_probe=true)` — confirms the four layers (panel ↔
   xray ↔ marznode ↔ external TCP) all align.
6. Hand a sample subscription URL to one trusted client per
   target ISP and wait 10 minutes. If `verify_inbound_e2e` shows
   `clients_count > 0` and the trusted client reports working
   speedtest, mark the inbound as `usage_coefficient=0.0` (free
   tier) for one week so users gravitate toward it before billing
   pressure forces them off.

## What to do if a previously-working inbound stops working

1. `verify_inbound_e2e(node_id, inbound_tag, external_probe=true)`.
   If `external_tcp_probe.ok=false` and the panel side looks
   healthy, the ISP is now dropping that port/SNI combo. Move on
   to step 2.
2. Don't try to fix the existing inbound's fingerprint — it's
   already burned. Add a new inbound with a different `dest`,
   different port, different `shortIds`. Leave the old one in
   place for a week so existing clients can switch over.
3. After a week, `delete_inbound(inbound_id)` for the burned one
   and `delete_host` for every host pointing at it. Do NOT
   silently regenerate Reality keys on the old inbound — DPI
   rules typically pin on `dest` + port + short_id pattern, not
   on the keypair itself, so a key rotation alone won't help.
