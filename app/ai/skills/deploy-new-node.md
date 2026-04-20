---
name: deploy-new-node
description: Onboard a freshly-installed marznode host as a new panel node by cloning an existing donor — register the node in the panel, wait for the first connection, then clone xray config + rotate per-node reality keys + propagate inbounds to services + replicate donor hosts onto the new inbounds + push users + verify a sample subscription. Use when the admin says "add new node like X", "set up the new server same as node Y", "configure the new server from scratch", or similar. Do NOT use for fresh from-scratch Xray config design — only for cloning-from-donor. For the simpler "make this existing node look like that one" flow (no new node creation), use `clone-node-from-donor` instead.
---
# Deploy a new node by cloning an existing one

Onboarding a brand-new marznode host should take three tool calls,
not nine. The marznode installer already places the matching panel
client cert at `/var/lib/marznode/client.pem`, so we don't touch
TLS unless the node fails to come up healthy.

## Preconditions the admin is responsible for
- Marznode is already installed on the target host (the admin ran
  the install script, so `/var/lib/marznode/client.pem` is in place
  and the marznode container/service is running on the connection
  address/port).
- The donor node (the one being cloned) is healthy and already
  serving users — otherwise you're propagating a broken config.

## Inputs you need before you start
Collect upfront from the admin, only ask for what you cannot infer:
- `donor_node_id` — node whose Xray config will be cloned. Resolve
  by name with `list_nodes(search="...")`.
- Either `new_node_id` (if already created in the panel) or
  connection params (`name`, `address`, `port`,
  `connection_backend`) so you can call `create_node` yourself.
- `sample_username` — any real user, used for the subscription
  verification step.
- `host_remark_pattern` (optional) — template for cloned host
  remarks. Supports `{donor_remark}`, `{target_name}`,
  `{target_address}`, `{tag}`. If the admin doesn't volunteer one,
  ask: **"Какой шаблон названия host'ов? Например
  `{donor_remark} → {target_name}` сделает 'universal 4 →
  universal 5'. Или оставим как у донора?"** — one short question.

## Happy path — three tool calls

### 1. Confirm donor health.

`get_node_info(donor_node_id)`. If `status != healthy`, STOP and
report; cloning a broken donor is useless.

### 2. Create the new node and wait for first connection.

If the new node does not exist yet:
`create_node(name, address, port, connection_backend)` — `address`
and `port` are the marznode endpoint on the target host, not any
xray port. Save the returned `id` as `new_node_id`.

Wait ~15 s, then poll `get_node_info(new_node_id)` (at most three
times, ~10 s apart) until `status=healthy`. The first connection
typically takes 10-30 s.

If after ~45 s it's still not healthy:
- `enable_node(new_node_id)` — forces the panel to re-instantiate
  the gRPC client. Wait another 15 s and re-check.
- Still not healthy → switch to the `diagnose-node-down` skill.
  That skill is the right place for `verify_panel_certificate` /
  `install_panel_certificate_on_node` / SSH probes — do NOT call
  them proactively from here; on fresh installs they almost
  always show `match=true` and waste a confirmation.

### 3. Run the all-in-one clone macro.

`onboard_node_from_donor(donor_node_id, new_node_id,
sample_username="...", host_remark_pattern="...")`.

This single call runs:
1. preflight — both nodes in registry.
2. `clone_node_config` — donor xray JSON → target, restart target
   xray. Panel `_sync()` then refreshes target inbound rows.
3. `regenerate_reality_keys_on_node` on target — rotates reality
   `privateKey` + `shortIds` per inbound (default ON; pass
   `regenerate_reality_keys=false` only if admin explicitly wants
   shared keys with donor).
4. `propagate_node_to_services` — every service the donor was in
   gets target's matching inbounds attached.
5. `clone_donor_hosts_to_target` — every donor host is cloned onto
   the target's matching inbound. `address` ←
   `host_address_override` or target's `nodes.address`. `remark`
   ← rendered from `host_remark_pattern`. Reality keys ← step 3
   rotation. Same `services` binding as donor host. Default
   placeholder hosts on target are removed first.
6. `resync_node_users` — push user set to target xray.
7. (optional) verify subscription on `sample_username`.

Read the returned `steps[]` array. If `success=true` AND
`verify_subscription.match_in_subscription=true`, you're essentially
done. If anything failed, read `clone-node-from-donor` for the
per-step recovery hints (it has the full failure → fix table).

### 4. Real-traffic sanity check (optional but valuable).

After ~3-5 minutes of live traffic, run
`xray_traffic_health(new_node_id, window_minutes=5)`. If
`accepted >> 0` and `rejected_ratio < 0.2`, the new node is serving
real users. If `rejected_ratio` is high with `invalid request user
id`, run `resync_node_users` once more — sometimes the very first
user push races with the xray restart.

## Stop criteria
- All three steps succeeded; the macro's `clone_donor_hosts_to_target`
  step shows `created_hosts_count > 0`; `verify_subscription` shows
  the target address in the sample subscription; step 4 (if run)
  shows accepted traffic.
- Report back: new node id and status, services updated count, hosts
  cloned count (from the macro report), one-line confirmation that
  subscriptions pick up the new endpoint, and (if collected)
  accepted/rejected counts.

## Common pitfalls
- Calling `verify_panel_certificate` / `install_panel_certificate_on_node`
  during step 2 "to be safe" — burns a confirmation and restarts
  marznode for no reason on a healthy fresh install. Only from
  `diagnose-node-down`, after `enable_node` failed.
- Skipping `sample_username` — subscription is never verified; macro
  reports `success=true` on internal signals only.
- Running with `clone_hosts=false` — target inbounds end up with
  only placeholder hosts and won't appear in subscriptions
  meaningfully.
- Running with `regenerate_reality_keys=false` — leaks the donor's
  private key to the new node. Only when admin explicitly asks for
  shared keys.
- Skipping step 4 means you report "done" while the new node serves
  zero real users. A 30-second probe is cheap.
- `unmatched_donor_tags` in the macro report — never silently
  ignore. Admin needs to know which services miss the new node.
- `OperationalError: max_statement_time exceeded` during step 3's
  resync on a large install — raise `SQLALCHEMY_STATEMENT_TIMEOUT`
  to 60-120s in the panel's `.env` and restart the panel
  container, then re-run `resync_node_users(new_node_id)` only —
  no need to redo the clone.
