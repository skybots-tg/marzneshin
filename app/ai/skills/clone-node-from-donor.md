---
name: clone-node-from-donor
description: Make node B look exactly like node A in one go — clone xray config, attach to the same services, push the user set, verify subscriptions. Use when the admin says "сделай как в той ноде", "make this new node identical to X", "copy node Y settings to node Z", or "склонируй ноду 12 на ноду 25". Does NOT install certificates — combine with `install_panel_certificate_on_node` upfront if the new node is a fresh install.
---
# Clone a node from a donor (the "сделай как там" macro)

The admin almost never wants you to walk a 9-step checklist by hand
for this — they want one call, one confirmation, one report. The
`onboard_node_from_donor` tool collapses the whole flow into a single
agent call. Use this skill only to bracket that call with the right
preflight and post-checks.

## Inputs
- `donor_node_id` — the node to copy from. Resolve names with
  `list_nodes(search="...")`.
- `target_node_id` — the node to copy onto.
- `sample_username` (optional but strongly recommended) — any real
  user the admin trusts; we use it for the subscription verification
  step.

## Quick path (90% of cases)

### 1. Preflight: both nodes connected.

`get_node_info(donor_node_id)` AND `get_node_info(target_node_id)`.
Both must report a non-disabled status. The donor's
`backends[*].running` must be `true`. If the target's status is
`unhealthy`, do NOT proceed with the clone — diagnose the target
first via the `diagnose-node-down` skill (the most common cause for
a fresh node is mTLS mismatch — fix with
`install_panel_certificate_on_node` and re-check).

### 2. Single-call clone.

`onboard_node_from_donor(donor_node_id, target_node_id,
sample_username="...")`.

This runs, in one transaction-ish flow:
1. preflight (both nodes in registry),
2. `clone_node_config` (xray JSON donor→target, restarts target xray),
3. `propagate_node_to_services` (every service the donor was in now
   includes the target's matching inbounds, by tag),
4. `resync_node_users` (target xray gets the full user set),
5. subscription verification on `sample_username`.

Read the returned `steps[]`. Each entry has `name` + `ok`.

### 3. Interpret the report.

- `success=true` and step 5 reports `match_in_subscription=true` →
  **DONE**. Tell the admin: nodes synced, services updated count,
  user count synced, sample subscription contains target address.
- `success=false` with `failed_step="preflight"` → at least one
  node is not in the panel's in-memory registry. Check
  `get_node_recent_errors` on the failing one.
- `success=false` with `failed_step="clone_node_config"` → target
  rejected the xray config. Read the error; usually a port
  collision the donor doesn't have. Fix the conflict on the
  target (or change inbound ports in the cloned config) and
  retry.
- `success=false` with `failed_step="propagate_node_to_services"`
  → DB-level error; bubble it up verbatim.
- `success=false` with `failed_step="resync_node_users"` → almost
  always SQL statement timeout for large user sets. Tell the
  admin to raise `SQLALCHEMY_STATEMENT_TIMEOUT` (60-120s) and
  restart the panel container, then re-run
  `resync_node_users(target_node_id)` — no need to redo the
  whole onboarding.
- `propagate_warning` step present with `unmatched_donor_tags`
  populated → the donor had inbound tags that the freshly-cloned
  target xray config does NOT have. Services using those tags
  will silently NOT include the new node. Either fix the tag
  drift in the cloned config (`get_node_config` + `update_node_
  config`) and re-run `propagate_node_to_services` manually, or
  warn the admin loudly.
- `verify_subscription.match_in_subscription=false` → target
  inbound tags reached the services but the user's subscription
  doesn't include the new endpoint. Possible causes:
  (a) the user is not in any service that the donor was in
  (verify with `inspect_user_subscription` for a different
  sample),
  (b) a host bound to the new inbound has `is_disabled=true` or
  is missing reality_public_key. Run
  `scan_hosts_for_issues(node_id=target_node_id)` and
  `validate_host` on the suspects.

## When the new node is a fresh install (no cert yet)

`install_panel_certificate_on_node(target_node_id)` BEFORE step 1.
Then wait ~15 s, run `get_node_info(target_node_id)` until the
status flips to `healthy`, then proceed with the quick path.

This is essentially the merged "deploy + clone" workflow:

1. `install_panel_certificate_on_node(target_node_id)` (only
   needed if `verify_panel_certificate` reported `match=false`
   or `node_client_pem_present=false`)
2. wait 15 s
3. `get_node_info(target_node_id)` until `status=healthy`
4. `onboard_node_from_donor(donor_node_id, target_node_id,
   sample_username="...")`
5. `xray_traffic_health(target_node_id, window_minutes=10)` after
   ~5 minutes, to confirm clients are actually using the new
   endpoint and getting `accepted`.

## Stop criteria

- `onboard_node_from_donor` returned `success=true` AND step 5
  showed the target address in the sample subscription. Report
  done.
- A `failed_step` was returned — report the failed step verbatim,
  the error, and the most likely fix from above. Do NOT silently
  retry the macro; one or both nodes is in a state where the
  fix has to happen first.

## Common pitfalls

- Forgetting the `sample_username` argument means we never
  actually verify a user sees the new endpoint — the macro will
  report `success=true` based on internal-only signals. Always
  pass a sample.
- "Just redo it" — re-running the macro after a partial failure
  is *usually* safe (each step is idempotent), but if step 2
  failed you may have broken xray on the target. Inspect with
  `get_node_logs(target_node_id, backend="xray")` before retry.
- Cloning between nodes with mismatched protocol licences (e.g.
  donor has hysteria2, target only has xray) — the `unmatched_
  donor_tags` warning is the only signal. Read it.
