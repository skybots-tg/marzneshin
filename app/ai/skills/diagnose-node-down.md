---
name: diagnose-node-down
description: Diagnose why Xray on a node is not working — users on that node cannot connect, the panel shows the node as unhealthy/disconnected, or the admin says "node X is down / stopped working / traffic dropped to zero". Walk the checklist in order, trust the verdicts, do not loop forever. Do NOT use when a single user's subscription is broken but other users on the same node work fine (use debug-broken-subscription instead).
---
# Diagnose a broken node

## Inputs
- `node_id` — the affected node. If the admin named it, resolve with
  `list_nodes(search="...")`.

## Two failure modes to keep straight
- A. marznode is fine but Xray itself crashed / refused to start
  (bad config, missing reality private key, port collision). The
  panel still sees the node as connected. Logs are readable via
  `get_node_logs(backend="xray")`.
- B. marznode itself is dead (container exited, systemd unit
  stopped, host rebooted). Panel shows the node as disconnected.
  `get_node_logs` returns "Node X is not connected" — you MUST go
  via SSH for anything deeper.

## Checklist — in this order, do not skip

1. One-shot verdict. `diagnose_node_issue(node_id)`. Read the
   returned `verdict`, `confidence`, `recommendation`, and the
   `signals` block. Do NOT call this tool more than twice per turn.

2. Act on the verdict:
   - `HEALTHY` → node is fine. Problem is client-side. Ask the
     admin to have the user reimport their subscription and try
     another network. STOP.
   - `LIKELY_DPI` → node is fine but upstream is censored.
     Report the drop numbers from `signals`, suggest rotating SNI,
     switching to a different port / protocol / node. Do NOT run
     more SSH probes — you cannot fix DPI from the panel.
   - `NODE_UNREACHABLE` / `NODE_DISCONNECTED` → marznode itself is
     down (failure mode B). Proceed to step 3.
   - `XRAY_DOWN` / `CONFIG_ERROR` → failure mode A. Proceed to
     step 4.
   - `INCONCLUSIVE` → tell the admin what's missing (usually SSH
     unlock or a 24h traffic baseline) and stop. Do NOT rerun.

3. Failure mode B (marznode is down). Only proceed with SSH.
   - `ssh_check_access(node_id)` first. If `ssh_ready=false`, ask
     the admin to click the SSH button in the chat header to
     unlock. STOP until unlocked.
   - Once unlocked, run `ssh_run_batch(node_id, commands=[
       {"name": "status",  "command": "systemctl status marznode --no-pager"},
       {"name": "journal", "command": "journalctl -u marznode --since '30 min ago' --no-pager | tail -n 200"},
       {"name": "docker_ps",   "command": "docker ps -a --filter name=marznode --format '{{.Names}}\\t{{.Status}}'"},
       {"name": "docker_logs", "command": "docker logs marznode --tail 200"}
     ])`.
   - Read the results — the real error line is almost always in
     journal or docker_logs. Report it verbatim and the most likely
     fix (restart container, fix unit, re-run installer).
   - Do NOT destructively restart anything without the admin's
     explicit ok.

4. Failure mode A (Xray down, marznode fine). Panel gives you the
   logs directly.
   - `get_node_logs(node_id, backend="xray", max_lines=200)` —
     Xray prints the exact start-up error in the tail (e.g.
     `failed to generate x25519 keys`, `listen: bind: address
     already in use`, `failed to parse config`, `common/net:
     invalid port range`).
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

5. After any fix, `restart_node_backend(node_id)` then
   `get_node_info` + `get_node_logs` again. Confirm Xray printed
   a "started" line and no new errors in the last 50 lines.

## Stop criteria
- You have a concrete verdict with evidence, OR
- You have hit a step that requires admin action (unlock SSH,
  reinstall Xray, restore config) — report and stop.

## Anti-patterns to avoid
- Do NOT call `diagnose_node_issue` in a loop hoping the verdict
  will change. It won't without a state change.
- Do NOT keep running SSH commands after a `LIKELY_DPI` verdict.
  DPI is upstream; the node is healthy.
- Do NOT ask the admin "should I restart?" as a chat question —
  `restart_node_backend` has its own confirmation modal.
