---
name: debug-broken-subscription
description: Investigate why a specific user's subscription produces invalid / non-working configs (e.g. broken VLESS URLs with "None" as UUID, missing security=reality, missing sni/pbk/sid, clients say "no internet"). Use when the admin reports that a user cannot connect, or that their configs look wrong, or mentions a specific host generating bad links. Do NOT use for panel-wide outages or for node-down problems — use diagnose-node-down for those.
---
# Debug a broken subscription for a specific user

## Inputs
- `username` — the affected user. Resolve with `list_users(search="...")`
  if the admin gave only a partial name.
- Optionally, the specific host/node the admin suspects.

## Checklist

1. Check the user is actually active. `get_user_info(username)` — if
   `is_active=false`, `expired=true`, or `data_limit_reached=true`,
   the "broken" configs may be intentional placeholders. Report and
   stop unless the admin explicitly says the user should be active.

2. Read the generated subscription as the agent (NOT into chat).
   `inspect_user_subscription(username, config_format="links")`.
   The returned text is the exact set of VLESS/VMess/Trojan/SS
   URLs the user would see. Scan it for these red flags:
   - `vless://None@` or `trojan://None@` — UUID/password missing.
   - VLESS URL with no `security=` parameter where there should be
     `security=reality` (compare to peer VLESS lines for the same
     node — they will usually show what the correct form looks like).
   - Missing `sni=`, `pbk=`, `sid=`, `fp=` on reality lines.
   - `address=0.0.0.0` / empty address.
   - Obviously truncated remarks (host.remark template broken).

3. For every host that produced a suspicious line, get its record.
   Use `list_hosts(remark="<piece of the remark>", limit=10)` or
   `list_hosts(inbound_id=<id>)` to find the host id, then
   `get_host_info(host_id)` for the full row.

4. Run the heuristic validator on each suspect host.
   `validate_host(host_id)` — returns a list of `issues` with
   severities and field names. Pay special attention to:
   - universal hosts (`universal=true, inbound_id=None`) — they
     historically needed `reality_public_key` + `reality_short_ids`
     on the host entry itself, otherwise reality parameters are lost.
   - VLESS+reality without `sni` / `fingerprint` / `flow`.
   - Trojan/Shadowsocks without `password`.

5. For non-universal hosts (bound to an inbound), also peek at the
   inbound's Xray config. `get_node_config(node_id, inbound_tag=...)`
   and verify `realitySettings.publicKey` / `realitySettings.shortIds`
   are set on the server side. Mismatch between host `reality_public_key`
   and inbound `realitySettings.privateKey` is a common failure mode.

6. Apply fixes via `modify_host(host_id, <fields>)`. Typical fixes:
   - Set `reality_public_key` + `reality_short_ids` on a universal host
     that was missing them.
   - Set `sni="..."` for reality hosts.
   - Set `fingerprint="chrome"` on reality hosts where it was `none`.
   - Clear a field back to the inbound default via
     `clear_fields=["<field>"]`.
   - Do NOT delete and re-create the host — that changes its id and
     breaks host chains and service associations.

7. Re-run `inspect_user_subscription(username)` after the fix to
   confirm the bad line is gone / now looks correct.

## Stop criteria
- Every suspicious line in step 2 has been explained and either
  fixed or flagged as out-of-scope (e.g. "host is intentionally
  disabled, user disabled, etc.").
- Final `inspect_user_subscription` output shows no `None@` / no
  missing reality params / no empty address.

## Known patterns that LLM keeps missing
- Universal hosts (`inbound_id=None`, `universal=true`) used to be
  generated without per-user UUID when `host.uuid` was blank — if
  you see `vless://None@` exactly on a universal host, make sure
  the backend is running a build that reads reality fields from
  the host record (not just from the inbound). If not, fixing the
  host alone will not help and the admin needs a code-level fix.
- Host `security` enum does NOT have "reality" — reality is
  inferred from the presence of `reality_public_key` on the host
  (or `tls=reality` on the bound inbound's config). If neither is
  set, the link comes out as plain VLESS with no security.
- `fingerprint=none` serializes as empty; to get `fp=chrome` in
  the URL you must set `fingerprint="chrome"`, not leave it at the
  default.

## What NOT to do
- Don't blame DPI just because ONE user's link is broken — DPI
  breaks the whole node, not one subscription. Use `diagnose_node_down`
  skill for that.
- Don't regenerate the user's subscription URL
  (`revoke_user_subscription`) to "fix" a broken config — the URL
  is fine; the generated content is the bug.
