---
name: debug-broken-subscription
description: Investigate why a specific user's subscription produces invalid / non-working configs (e.g. broken VLESS URLs with "None" as UUID, missing security=reality, missing sni/pbk/sid, clients say "no internet"). Use when the admin reports that a user cannot connect, that their configs look wrong, mentions a specific host generating bad links, OR when the admin only has a UUID / password / a single `vless://`-line pasted from a subscription and no username. Do NOT use for panel-wide outages or for node-down problems — use diagnose-node-down for those.
---
# Debug a broken subscription

## Inputs — what the admin actually gave you

| Admin gave you                         | First action                                                |
| -------------------------------------- | ----------------------------------------------------------- |
| `username`                             | Go straight to step 2.                                      |
| partial name / email fragment          | `list_users(search="...")` to resolve it.                   |
| a bare UUID, password, or one full     | `find_user_by_credential(credential=...)` — it accepts a    |
| `vless://uuid@...` / `trojan://...`    | UUID, a password, OR a full subscription URL and returns    |
| line                                   | matching usernames and any host-level credential hits.      |
| only `vless://None@...`                | You CANNOT resolve a username from this — there is          |
|                                        | literally no credential in the line. Tell the admin so and  |
|                                        | jump straight to step 0 (scan hosts) to find the likely     |
|                                        | misconfigured host.                                         |
| a specific host/node the admin suspects| Still try to get a username so you can confirm the bad      |
|                                        | line actually appears in a real subscription.               |

## Step 0 — when there is no username (optional but powerful)
If the admin reports a panel-wide symptom ("every user on node 30 has
`vless://None@`") or gave you only a host/node, run the bulk scanner
first — it often points straight at the broken host and skips the
per-user triage entirely:

- `scan_hosts_for_issues(node_id=<N>)` — every host on that node with
  at least one error-level issue.
- `scan_hosts_for_issues(protocol="vless", only_with_errors=True)` —
  every broken VLESS host in the panel.
- Paginate with `next_offset` until `has_more=false`. `total` in the
  envelope is the total hosts matching the SQL filter BEFORE the
  error filter, so don't assume page 1 is complete.

Pick the worst offenders (missing `reality_public_key`, missing
`reality_short_ids`, no `sni`, no `port`) and jump to step 6.

## Inputs
- `username` — the affected user. Resolve with `list_users(search="...")`
  or `find_user_by_credential(...)` if you only have a credential.
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
   - Single host: `validate_host(host_id)`.
   - Multiple suspect hosts (e.g. the whole node): one call to
     `scan_hosts_for_issues(node_id=<N>, only_with_errors=True)`
     replaces looping `validate_host` per id.
   Pay special attention to:
   - universal hosts (`universal=true, inbound_id=None`) — they
     historically needed `reality_public_key` + `reality_short_ids`
     on the host entry itself, otherwise reality parameters are lost.
   - VLESS+Reality hosts BOUND to an inbound with
     `reality_public_key=null` / `reality_short_ids=null` on the host
     row — this still produces `vless://None@`-style lines because
     `share.py` pulls the reality params from the host record.
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
- Don't ask the admin for a username if they already gave you a
  UUID / password / a `vless://<non-None>@...` line — run
  `find_user_by_credential` first. Only ask when the line is
  literally `vless://None@` (no credential) or when the scanner
  returns zero matches and `truncated=true` even after raising
  `max_scan`.
