---
name: clone-node-from-donor
description: Make node B look exactly like node A in one go — clone xray config, rotate reality keys per-node, attach target inbounds to the donor's services, replicate every donor host onto the target, push the user set, verify subscriptions. Use when the admin says "сделай как в той ноде", "make this new node identical to X", "copy node Y settings to node Z", or "склонируй ноду 12 на ноду 25". Does NOT install certificates — fresh marznode installs already have the right cert in place.
---
# Clone a node from a donor (the "сделай как там" macro)

The admin's manual procedure was: copy xray config → regenerate
reality keys on the new node → propagate inbounds to all services →
mirror every donor host (IP/port/name + reality params) onto the new
inbounds. That entire sequence collapses to a single
`onboard_node_from_donor` call.

## Inputs
- `donor_node_id` — the node to copy from (resolve with
  `list_nodes(search="...")`).
- `target_node_id` — the node to copy onto.
- `sample_username` (optional but strongly recommended) — any real
  user; we use it for the subscription verification step.
- `host_remark_pattern` (optional) — string template applied to every
  cloned host's remark. Supports placeholders `{donor_remark}`,
  `{target_name}`, `{target_address}`, `{tag}`. Empty pattern =
  donor remark unchanged.
  Examples:
    - `"{donor_remark} → {target_name}"` → "🚀 universal 4 → universal 5"
    - `"universal {target_name}"` → "universal 5"
    - `"{donor_remark}"` → keeps donor verbatim (default if you pass
      empty).
- `host_address_override` (optional) — override the target host's
  address. Default = target node's `nodes.address` (the marznode
  endpoint). Override only if the public-facing endpoint differs
  from the marznode address (e.g. dedicated TLS domain per node).
- `regenerate_reality_keys` (default `true`) — rotate reality keys
  per-node. Leave `true` unless the admin explicitly asks to keep
  donor keys.
- `clone_hosts` (default `true`) — leave `true`; otherwise only
  panel-default placeholder hosts will represent target inbounds in
  subscriptions.

If the admin gave you the donor + target by name and not the remark
pattern, ask one short question: **"Какой шаблон названия host'ов?
Например `{donor_remark} → {target_name}` сделает 'universal 4 →
universal 5'. Или оставим как у донора?"**. One question, then go.

## Happy path — two tool calls

### 1. Confirm both nodes are connected.

`get_node_info(donor_node_id)` AND `get_node_info(target_node_id)`.
Both must report `status=healthy` AND `connected=true`. The
`onboard_node_from_donor` preflight checks BOTH the registry
(`connected=true`) AND DB status — donor failures are the same
trap as target failures.

If EITHER node fails preflight:
- Run `enable_node(<failing_node_id>)` FIRST — re-instantiates the
  panel's in-memory gRPC client without touching the host. Wait
  ~15 s, then re-check `get_node_info`. This applies equally to
  donor and target — the preflight does NOT discriminate. Do NOT
  jump to SSH on the donor just because the macro fails on
  `donor_status: unhealthy` / `donor not in registry`; the donor
  is almost always fine and only the panel's view of it is stale.
- Still not healthy after `enable_node` → call
  `diagnose_node_issue(<failing_node_id>)` and switch to
  `diagnose-node-down`. A `PANEL_REGISTRY_DESYNC` verdict at
  this point means `enable_node` itself errored (cert load
  failure, etc.) — read its error, fix that, then retry. Do
  NOT request SSH purely because of `PANEL_REGISTRY_DESYNC`;
  the node host is not broken in that case.
- Do NOT call `verify_panel_certificate` /
  `install_panel_certificate_on_node` proactively from here, and
  do NOT request SSH on the donor before `enable_node` was tried.

### 2. Single-call clone.

`onboard_node_from_donor(donor_node_id, target_node_id,
sample_username="...", host_remark_pattern="...")`.

Steps it runs (in order, fails fast on first error):
1. preflight (both nodes in registry).
2. `clone_node_config` — donor xray JSON → target, restart target
   xray. The panel's `_sync()` then refreshes target inbound rows.
3. `regenerate_reality_keys_on_node` on target — rotates
   `privateKey` + `shortIds` for every vless+reality inbound,
   restarts xray again with the rotated config. Returns a per-tag
   mapping `{tag, reality_public_key, reality_short_ids}` that step
   5 consumes.
4. `propagate_node_to_services` — every service the donor was in
   gets the target's matching inbounds (by tag) AND every orphan
   target inbound (zero service bindings) is bound to the union of
   donor services. The orphan-binding pass is what prevents the
   "xray running, 0 clients pushed" failure mode.
5. `clone_donor_hosts_to_target` — every donor host is cloned onto
   the target's matching inbound. `address` ← `host_address_override`
   or target's `nodes.address`. `remark` ← rendered from
   `host_remark_pattern`. `reality_public_key` /
   `reality_short_ids` ← step 3 rotation. `host_network` / `flow` are
   coerced to match the target inbound's actual transport (e.g. donor
   TCP host on an XHTTP target inbound: `host_network → xhttp`,
   `flow=xtls-rprx-vision` is stripped). Same `services` binding as
   the donor host. Default placeholder hosts on the target are
   removed first.
6. `resync_node_users` — push full user set to target xray.
6.4. `ensure_node_firewall_for_xray_inbounds` — opens every xray
   inbound port in UFW on the target. Skipped silently when SSH is
   locked or creds missing (the admin will then have to open the
   ports manually). Idempotent — already-open ports are reported,
   no duplicate rules. Disable with `open_firewall=false` only when
   the firewall is managed out-of-band (cloud security group,
   dedicated ufw script).
6.5. `post_deploy_gate` — runs `verify_inbound_e2e` for every target
   inbound. Records per-tag failures but does not abort. Read
   `steps[].failures` and apply each `failed_checks[].remedy`.
7. (optional) verify subscription on `sample_username`.

Optional standalone follow-up: `verify_donor_target_parity(donor_node_id,
target_node_id)`. Cheap (2 gRPC reads, no writes). Surfaces drift
between donor and target xray live configs — inbound tags only on
one side, outbounds with the same tag pointing at different
endpoints, routing rules added on one side but not the other. Run
this any time the admin reports "this node was working yesterday"
or after a hand-edit on either side.

### 3. Interpret the report.

- `success=true` AND `verify_subscription.match_in_subscription=true`
  → **DONE**. Tell the admin: nodes synced, services updated count,
  cloned hosts count, user count synced, sample subscription contains
  target address.
- `failed_step="preflight"` → look at the report's
  `donor_connected` / `target_connected` and `donor_status` /
  `target_status`, plus the explicit `missing_from_registry` /
  `next_action` fields. Run `enable_node` on each missing side
  (donor and target are equally valid candidates — do NOT
  assume the failure is always on the target). Wait ~15 s and
  retry the macro. If `enable_node` itself errors, that error
  IS the cause — read it, fix the underlying issue (e.g.
  certificate load failure, address parse error), then retry.
  NEVER request SSH on a preflight failure before `enable_node`
  was tried — the node host is not the cause.
- `failed_step="clone_node_config"` → target xray rejected the
  config. Read error, usually port collision the donor doesn't have.
  Fix and retry.
- `failed_step="regenerate_reality_keys_on_node"` → target is
  currently running with the donor's keys (xray was already
  restarted in step 2). Either re-run the macro with
  `regenerate_reality_keys=false`, or call
  `regenerate_reality_keys_on_node(target_node_id)` directly once
  the underlying issue is fixed.
- `failed_step="propagate_node_to_services"` → DB error; bubble up.
- `failed_step="clone_donor_hosts_to_target"` → inbounds are
  attached to services but target subscriptions only show
  placeholder hosts. Re-run `clone_donor_hosts_to_target` standalone
  with the same parameters.
- `failed_step="resync_node_users"` → almost always SQL statement
  timeout. Tell the admin to raise `SQLALCHEMY_STATEMENT_TIMEOUT`
  (60-120s) and restart the panel container, then re-run
  `resync_node_users(target_node_id)` — no need to redo the whole
  onboarding.
- `ensure_node_firewall_for_xray_inbounds` returned
  `ssh_available=false` → SSH wasn't unlocked when the macro ran;
  the firewall step was skipped. If clients can't reach new ports,
  unlock SSH and re-run `ensure_node_firewall_for_xray_inbounds`
  standalone. If it returned `ufw_active=false`, the node has UFW
  installed but disabled — every port is currently open at the OS
  level, no action needed unless the admin wants to enable UFW
  (which this tool will NOT do automatically).
- `failed_step="post_deploy_gate"` → at least one target inbound
  failed end-to-end verification. Read `steps[].failures` (each entry
  has `inbound_tag` + a `failed_checks[]` array with per-layer
  `remedy` strings). Apply the remedies in order. The most common
  failure is `panel_service_binding` — fix with
  `propagate_node_to_services(from_node_id=donor, to_node_id=target,
  bind_orphan_target_inbounds=true)` then `resync_node_users(target)`,
  then re-run `verify_inbound_e2e` on the failed tags to confirm.
- `propagate_warning.unmatched_donor_tags` populated → donor had
  inbound tags the target xray config doesn't have. Services using
  those tags will silently NOT include the new node. Either fix tag
  drift in the cloned config, or warn the admin.
- `verify_subscription.match_in_subscription=false` → target inbound
  tags reached services but user's subscription doesn't include the
  new endpoint. Possible causes:
  (a) user not in any donor service (try a different sample),
  (b) clone_donor_hosts step skipped or failed and only placeholder
  hosts exist (`scan_hosts_for_issues(node_id=target_node_id)`),
  (c) cloned host has `is_disabled=true` (`validate_host` on the
  suspect).

## Stop criteria

- `onboard_node_from_donor` returned `success=true`,
  `post_deploy_gate.failed_inbound_count=0`, AND
  `verify_subscription.match_in_subscription=true`. Report done.
- A `failed_step` was returned — report it verbatim, plus the
  most likely fix from above. Do NOT silently retry the macro;
  fix the underlying issue first.
- `post_deploy_gate` reported failures (the macro itself returns
  `success=true` but `failed_step="post_deploy_gate"`) — apply
  per-tag remedies, then call `verify_inbound_e2e` on each fixed tag
  to confirm before reporting done.

## Common pitfalls

- Forgetting `sample_username` — the macro reports `success=true`
  based on internal-only signals; you never actually see a user's
  endpoint. Always pass a sample.
- Running with `regenerate_reality_keys=false` "for safety" — leaks
  the donor's private key to every cloned node, which defeats the
  per-node key isolation. Only do this when the admin explicitly
  asks.
- Running with `clone_hosts=false` — target inbounds end up with
  only the placeholder hosts (`address={SERVER_IP}`), so
  subscriptions don't include the new node properly. Only do this
  if the admin will create hosts manually.
- Calling `verify_panel_certificate` / `install_panel_certificate_on_node`
  proactively before step 1 — burns confirmations and restarts
  marznode for no reason on fresh installs. Only from
  `diagnose-node-down` after `enable_node` failed.
- Cloning between nodes with mismatched protocol licences (donor
  has hysteria2, target only has xray) — `unmatched_donor_tags`
  is the only signal. Read it.
