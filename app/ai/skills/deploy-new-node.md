---
name: deploy-new-node
description: Clone an existing node's Xray configuration to a newly added node from scratch — pre-clone certificate install, clone xray config, wire the new inbounds into the services that used the donor, push the current user set, and verify subscriptions actually pick up the new endpoint. Use when the admin says "add new node like X", "set up the new server same as node Y", "configure the new server from scratch", or similar. Do NOT use for fresh from-scratch Xray config design — only for cloning-from-donor. For the simpler "make this existing node look like that one" flow (no fresh install), use `clone-node-from-donor` instead.
---
# Deploy a new node by cloning an existing one

This is the full from-scratch flow: a host where marznode was just
installed, no panel cert on disk yet, no inbounds, no users. The
short variant ("nodes are both already healthy, just make them
identical") lives in the `clone-node-from-donor` skill — prefer it
if step 2 below already shows the new node as `healthy`.

## Preconditions the admin is responsible for
- Marznode is already installed on the target host (the admin ran the
  install script and set up the connection address/port).
- The donor node (the one being cloned) is healthy and already serving
  users — otherwise you are propagating a broken config.

## Inputs you need before you start
Collect upfront from the admin, and only ask for what you cannot infer:
- `donor_node_id` — the node whose Xray config will be cloned from. If
  the admin referred to it by name, resolve it with
  `list_nodes(search="...")`.
- Either `new_node_id` (if the node is already created in the panel) or
  the connection parameters (`name`, `address`, `port`,
  `connection_backend`) so you can call `create_node` yourself.
- A sample `username` (any real user) that should start getting the new
  node in their subscription — needed for the verification step.

## Checklist — do every step, do not stop half-way

### 1. Confirm donor health first.

`get_node_info(donor_node_id)`. If `status != healthy` or
`connected=false`, STOP and report; cloning a broken donor is
useless.

### 2. Create the new node if it does not exist yet.

`create_node(name, address, port, connection_backend)` — the
address/port is the marznode endpoint on the target host, not any
Xray port. Save the returned `id` as `new_node_id`.

### 3. First connection check, then cert install if needed.

`get_node_info(new_node_id)`. The first connection takes ~10-30s.

- If `status=healthy` within the first minute → cert is already
  in place (the install script set it up). Skip to step 5.
- If `status=unhealthy` after a minute → run
  `get_node_recent_errors(new_node_id)`. If `kind="sync"` with
  `StreamTerminatedError` / `_write_appdata` / `Connection lost`,
  or `kind="ssl"`, the new node was provisioned without the
  panel's current cert. Run
  `verify_panel_certificate(new_node_id)` to confirm — if
  `match=false` or `node_client_pem_present=false`, run
  `install_panel_certificate_on_node(new_node_id)` and wait
  ~15 s for the marznode service to come back up.
- If `kind="connect"` with `timeout` / `refused` after a minute →
  `diagnose_node_issue(new_node_id)`. STOP if the verdict is
  `NODE_UNREACHABLE` — the admin probably gave a wrong address
  or firewalled the gRPC port.

### 4. Wait for healthy.

After installing the cert (or if the cert was fine all along),
poll `get_node_info(new_node_id)` until `status=healthy`. Do not
proceed with `status=unhealthy`; the next steps will fail.

### 5. Run the all-in-one clone macro.

`onboard_node_from_donor(donor_node_id, new_node_id,
sample_username="...")`. This single call does:
- `clone_node_config` (xray JSON copy + restart target xray)
- `propagate_node_to_services` (attach target inbounds to every
  service the donor was in, matching by tag)
- `resync_node_users` (push the user set onto the target)
- subscription verification on `sample_username`.

Read the returned `steps[]` array. If `success=true` AND
`verify_subscription.match_in_subscription=true`, you are
essentially done. If anything failed, read
`clone-node-from-donor` for the per-step recovery hints.

### 6. Real-traffic sanity check (optional but valuable).

After ~3-5 minutes of live traffic, run
`xray_traffic_health(new_node_id, window_minutes=5)`. If
`accepted >> 0` and `rejected_ratio < 0.2`, the new node is
serving real users. If `rejected_ratio` is high with `invalid
request user id`, run `resync_node_users` once more — sometimes
the very first user push races with the xray restart.

### 7. Host-level audit (only if step 5 step-5 reported issues).

For any host that surfaced in `verify_subscription` as broken
(missing `pbk=`, `vless://None@...`, etc.), run
`validate_host(host_id)` to catch classic misconfigurations
(missing reality_public_key, absent UUID, wrong flow). Fix in
the host editor and re-run `inspect_user_subscription`.

## Stop criteria
- All steps succeeded; step 5 shows at least one fresh config for
  the new node's address; step 6 (if run) shows accepted traffic.
- Report back: new node id, its status, how many services were
  updated (from the macro's `propagate_node_to_services` step),
  one-line confirmation that subscriptions pick up the new
  endpoint, and (if collected) the accepted/rejected counts.

## Common pitfalls
- Skipping step 3's cert check on a fresh install — without the
  panel cert in `/var/lib/marznode/client.pem`, the panel will
  show `sync failed: AttributeError: _write_appdata` forever and
  no other step will succeed.
- Skipping step 5's `sample_username` argument means the
  subscription is never verified — the macro reports
  `success=true` based on internal signals only.
- Forgetting step 6 means you report "done" while the new node
  serves zero real users. A 30-second probe is cheap.
- `unmatched_donor_tags` in the macro's report — never silently
  ignore. The admin needs to know which services will be missing
  the new node.
- `OperationalError: max_statement_time exceeded` during step 5's
  resync on a large install — raise
  `SQLALCHEMY_STATEMENT_TIMEOUT` to 60-120s in the panel's
  `.env` and restart the panel container, then re-run
  `resync_node_users(new_node_id)` only — no need to redo the
  clone.
