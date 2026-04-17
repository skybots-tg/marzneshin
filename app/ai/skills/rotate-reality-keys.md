---
name: rotate-reality-keys
description: Rotate the Reality X25519 keypair for a given node's VLESS+Reality inbound — generate a new keypair, update the node's Xray config with the new privateKey, push the new publicKey to every host entry that refers to that inbound, and restart the backend. Use when the admin says "rotate reality keys on node X", "regenerate reality keys for inbound Y", "old keys leaked / compromised, make new ones". Do NOT use just to add new short_ids — for that simply `modify_host(reality_short_ids=...)`.
---
# Rotate Reality keypair for an inbound

## Inputs
- `node_id` — the node whose inbound needs new keys.
- `inbound_tag` — the specific Reality inbound on that node. If the
  admin didn't say, list inbounds with `list_inbounds(node_id=<id>)`
  and confirm with them which one.

## Checklist

1. Double-check it really is a Reality inbound.
   `get_node_config(node_id, inbound_tag=inbound_tag)` and look at
   `streamSettings.security` — must be `"reality"`. If not, STOP —
   this skill is only for Reality.

2. Generate a fresh keypair.
   `generate_reality_keypair(num_short_ids=1)`. The response has
   `private_key`, `public_key`, and `short_ids`. Keep the
   `private_key` inside your chain of thought — never echo it into
   chat, the admin should not be asked to confirm a new private key
   in plain text.

3. Patch the inbound's Xray config with the new private key. Use
   `update_node_config(node_id, inbound_tag=inbound_tag,
   patch={"streamSettings": {"realitySettings": {"privateKey":
   "<new>", "shortIds": ["<new short_id>"]}}})`. The exact shape of
   the patch follows what `get_node_config` returned in step 1 —
   preserve `dest`, `serverNames`, `fingerprint`, etc.; only
   overwrite `privateKey` and optionally `shortIds`. When unsure,
   re-read the full inbound first with
   `get_node_config(node_id, inbound_tag=inbound_tag)` and edit
   only those two fields.

4. Restart Xray so the new private key is actually loaded.
   `restart_node_backend(node_id, backend="xray")`.

5. Find every host entry that points at this inbound so clients
   stop sending the now-invalid old public key.
   `list_hosts(inbound_id=<inbound_id>, limit=100)` — walk the
   pages until `truncated=false`. Also, if any universal hosts in
   the panel were carrying a copy of the same `reality_public_key`,
   `list_hosts(universal_only=true, limit=100)` and filter locally
   by the OLD public key.

6. For each matched host, update its stored public key and short_ids.
   `modify_host(host_id, reality_public_key="<new>",
   reality_short_ids_json='["<new short_id>"]')`. One call per
   host. Each goes through its own confirmation modal — that is
   expected, do not batch or skip.

7. Verify. Pick any real user on this node
   (`list_users(limit=1)` or whichever the admin mentioned) and
   call `inspect_user_subscription(username,
   config_format="links")`. Confirm the VLESS lines for this node
   now embed the new `pbk=` value. Optional: `test_node_xray(node_id)`
   to confirm Xray is actually listening on the Reality port.

## Stop criteria
- Step 3 succeeded (new privateKey applied).
- Step 6 succeeded for every host returned in step 5.
- Step 7 shows the new `pbk=` in at least one generated link.
- Report back: new short_id(s), number of hosts updated, no
  client-side `pbk` matches the old value anymore.

## Safety
- Never share the `privateKey` in chat. The admin has no reason to
  see it — it lives in the node's Xray config.
- `publicKey` is safe to mention (it ends up in every client link
  anyway).
- Step 4 (restart) causes a brief disconnect for all users on that
  Reality inbound — warn the admin one sentence before calling it.
