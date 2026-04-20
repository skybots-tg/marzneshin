---
name: diagnose-node-down
description: Diagnose why Xray on a node is not working — users on that node cannot connect, the panel shows the node as unhealthy/disconnected, traffic dropped to zero, or the admin says "node X is down / sync failed / stopped working". Walk the checklist in order, trust the verdicts, do not loop forever. Do NOT use when a single user's subscription is broken but other users on the same node work fine (use debug-broken-subscription instead).
---
# Diagnose a broken node

## Inputs
- `node_id` — the affected node. If the admin named it, resolve with
  `list_nodes(search="...")`.

## Three failure modes to keep straight
- **A. marznode itself is dead** (container exited, systemd unit
  stopped, host rebooted). Panel shows the node as disconnected.
  `get_node_logs` returns "Node X is not connected" — you MUST go
  via SSH for anything deeper.
- **B. marznode is fine but Xray itself crashed / refused to start**
  (bad config, missing reality private key, port collision). The
  panel still sees the node as connected. Logs are readable via
  `get_node_logs(backend="xray")`.
- **C. marznode + Xray are both running, panel cannot sync** (mTLS
  mismatch, SQL statement timeout, gRPC stream reset). This is the
  silent killer. Panel logs spam `sync failed: ...` and the node
  stays detached forever even though everything looks fine on the
  server. The new health tools (step 1-2 below) target this case.

## Checklist — in this order, do not skip

### 1. Always start here: read the panel-side error history.

`get_node_recent_errors(node_id)`. This is FREE (no SSH, no RPC),
returns the last sync/connect/restart errors recorded in-memory by
the panel's gRPC client. Read the `kind` and `message` of the most
recent few entries:

- `kind="sync"` + message contains `StreamTerminatedError` /
  `Connection lost` / `_write_appdata`
  → mTLS mismatch is the prime suspect. **Jump to step 1.5.**
- `kind="sync"` + message contains `OperationalError` /
  `max_statement_time exceeded` / `Query execution was interrupted`
  → the SQL query that builds this node's user payload times out.
  Tell the admin to raise `SQLALCHEMY_STATEMENT_TIMEOUT` to
  60-120s in the panel's `.env` and restart the panel container.
  Then call `resync_node_users` to retry. STOP — no need to SSH.
- `kind="ssl"` → TLS-level failure. Almost always a cert/key
  problem. Jump to step 1.5.
- `kind="connect"` + `timeout` / `refused` → marznode is down or
  firewalled. Failure mode A. Jump to step 3.
- `node_not_loaded=true` → the panel doesn't have an in-memory
  client for this node. This is panel-side registry state, NOT a
  TLS or network problem. Run `enable_node(node_id)` — that
  re-instantiates the gRPC client with the current cert/key and
  registers it. Wait ~15 s, re-check `get_node_info`. Do NOT
  propose restarting the panel container; `enable_node` does the
  same thing for one node without affecting the others.
- empty `errors` → no recent failures recorded. Run
  `diagnose_node_issue` for the broader picture.

### 1.5. If step 1 hinted at mTLS / SSL: verify the certificate.

`verify_panel_certificate(node_id)`. SSH-backed; degrades to a
report with `ssh_available=false` if SSH is locked.

- `match=true` → mTLS is verified end-to-end. Stop considering
  TLS as a cause; do NOT call `install_panel_certificate_on_node`
  and do NOT propose a panel restart. Continue to step 2.
- `match=false` → the panel cert and the node's
  `/var/lib/marznode/client.pem` differ. This is the textbook
  cause of `sync failed: AttributeError: _write_appdata` /
  `StreamTerminatedError: Connection lost` loops. Fix in one
  shot: `install_panel_certificate_on_node(node_id)` — it backs
  up the old client.pem, ships the panel's current cert, and
  restarts the marznode service. After it returns, wait ~15s,
  then call `verify_panel_certificate` again to confirm match
  and `get_node_info` to confirm `status=healthy`.
- `node_client_pem_present=false` → node was never provisioned
  with a panel cert at all. Same fix:
  `install_panel_certificate_on_node`.
- `ssh_available=false` → ask the admin to unlock SSH, then
  retry. Without SSH you cannot rule out mTLS in this layer.

### 2. One-shot verdict from the existing diagnostics.

`diagnose_node_issue(node_id)`. Read `verdict`, `confidence`,
`recommendation`, `signals`. Do NOT call this tool more than twice
per turn.

Act on the verdict:

- `HEALTHY` → node is fine. If users still complain, problem is
  client-side. Ask the admin to have the user reimport their
  subscription and try another network. STOP.
- `LIKELY_DPI` → node is fine but upstream is censored. Report
  the drop numbers from `signals`, suggest rotating SNI,
  switching to a different port / protocol / node. Do NOT run
  more SSH probes — you cannot fix DPI from the panel.
- `NODE_UNREACHABLE` / `NODE_DISCONNECTED` → marznode itself is
  down (failure mode A). Proceed to step 3.
- `XRAY_DOWN` / `CONFIG_ERROR` → failure mode B. Proceed to
  step 4.
- `INCONCLUSIVE` → tell the admin what's missing (usually SSH
  unlock or a 24h traffic baseline) and stop. Do NOT rerun.

### 2.5. If everything looks healthy but users still cannot connect.

`xray_traffic_health(node_id, window_minutes=10)`. SSH-backed.
This catches the "xray is up but doesn't know any users" case —
which is invisible to `diagnose_node_issue` because the panel
*sees* xray running and the gRPC channel as connected.

- `rejected_ratio > 0.5` and `top_rejected_subjects` mentions
  `invalid request user id` or unknown user emails → xray has no
  user data. Either marznode never replayed the stored users
  into xray after a restart, or `resync_node_users` was never
  triggered. Run `resync_node_users(node_id)` and re-check after
  ~30s.
- `total = 0` → no traffic at all in the window. Either no
  clients are trying, or the inbound ports are firewalled —
  cross-check with `test_host_reachability` against the actual
  inbound port (NOT the gRPC port).
- Healthy ratio (`accepted >> rejected`) → xray is doing its
  job. Problem is elsewhere (panel-side rejection of the user,
  subscription generation, etc.) — switch to
  `debug-broken-subscription` skill.

### 3. Failure mode A (marznode is down). Only proceed with SSH.

- `ssh_check_access(node_id)` first. If `ssh_ready=false`, ask
  the admin to click the SSH button in the chat header to
  unlock. STOP until unlocked.
- Once unlocked, run `ssh_run_batch(node_id, commands=[
    {"name": "status",  "command": "systemctl status marznode --no-pager"},
    {"name": "journal", "command": "journalctl -u marznode --since '30 min ago' --no-pager | tail -n 200"},
    {"name": "docker_ps",   "command": "docker ps -a --filter name=marznode --format '{{.Names}}\\t{{.Status}}'"},
    {"name": "docker_logs", "command": "docker logs marznode --tail 200"}
  ])`.
- The real error line is almost always in journal or docker_logs.
  Report it verbatim and the most likely fix (restart container,
  fix unit, re-run installer).
- Do NOT destructively restart anything without the admin's
  explicit ok.

### 4. Failure mode B (Xray down, marznode fine).

- `get_node_logs(node_id, backend="xray", max_lines=200)` —
  Xray prints the exact start-up error in the tail (e.g.
  `failed to generate x25519 keys`, `listen: bind: address
  already in use`, `failed to parse config`).
- Also `get_node_logs(node_id, backend="marznode",
  max_lines=200)` — marznode shows its restart loop.
- Common fixes:
  * `failed to generate x25519 keys` /
    `Check that Xray is properly installed at
    /usr/local/bin/xray` — SSH, verify
    `ls -l /usr/local/bin/xray` and
    `/usr/local/bin/xray -version`. If missing/broken,
    ask the admin to reinstall Xray.
  * `address already in use` — SSH,
    `ss -ltnp | grep :<port>` to find the squatter. Do NOT
    kill processes without permission.
  * `failed to parse config` — the last `update_node_config`
    call probably broke something. Roll back by
    reading `get_node_config(node_id)` and restoring the
    previous JSON from memory / a backup.

### 5. After any fix, verify end-to-end.

`restart_node_backend(node_id)` then `get_node_info` +
`get_node_recent_errors` again. Confirm Xray printed a "started"
line, no new errors in the last 50 lines, and the recent_errors
buffer no longer accrues new entries.

## Stop criteria
- You have a concrete verdict with evidence, OR
- You have hit a step that requires admin action (unlock SSH,
  reinstall Xray, restore config, raise SQLALCHEMY_STATEMENT_TIMEOUT)
  — report and stop.

## Anti-patterns to avoid
- Do NOT call `diagnose_node_issue` in a loop hoping the verdict
  will change. It won't without a state change.
- Do NOT keep running SSH commands after a `LIKELY_DPI` verdict.
  DPI is upstream; the node is healthy.
- Do NOT ask the admin "should I restart?" as a chat question —
  `restart_node_backend` and `install_panel_certificate_on_node`
  have their own confirmation modals.
- Do NOT trust the bare panel error message at face value when it
  reads `AttributeError: 'NoneType' object has no attribute
  '_write_appdata'`. That's a cosmetic gpc-cleanup bug —
  `get_node_recent_errors` will show the unwrapped real cause
  (`StreamTerminatedError`, SQL timeout, etc.).
