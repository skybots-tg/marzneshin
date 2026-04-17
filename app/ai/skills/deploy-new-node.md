---
name: deploy-new-node
description: Clone an existing node's Xray configuration to a newly added node, wire the new inbounds into the services that used the donor, push the current user set, and verify subscriptions actually pick up the new endpoint. Use when the admin says "add new node like X", "set up the new server same as node Y", "clone this node to the new one I just added", "configure the new server from scratch", or similar. Do NOT use for fresh from-scratch Xray config design — only for cloning-from-donor.
---
# Deploy a new node by cloning an existing one

## Preconditions the admin is responsible for
- Marznode is already installed on the target host (the admin ran the
  install script and set up the connection address/port).
- The donor node (the one being cloned) is healthy and already serving
  users — otherwise you are propagating a broken config.

## Inputs you need before you start
Collect upfront from the admin, and only ask for what you cannot infer:
- `donor_node_id` — the node whose Xray config will be cloned from. If the
  admin referred to it by name, resolve it with `list_nodes(search="...")`.
- Either `new_node_id` (if the node is already created in the panel) or
  the connection parameters (`name`, `address`, `port`, `connection_backend`)
  so you can call `create_node` yourself.
- A sample `username` (any real user) that should start getting the new
  node in their subscription — needed for the verification step.

## Checklist — do every step, do not stop half-way

1. Confirm donor health first. `get_node_info(donor_node_id)` — if
   `status != healthy` or `connected=false`, STOP and report; cloning a
   broken donor is useless.

2. Create the new node if it does not exist yet. `create_node(name,
   address, port, connection_backend)` — the address/port is the marznode
   endpoint on the target host, not any Xray port. Save the returned
   `id` as `new_node_id`.

3. Wait-and-check the new node is reachable.
   `get_node_info(new_node_id)` — if not connected within the first
   minute, call `diagnose_node_issue(new_node_id)` once. If the verdict
   is `NODE_UNREACHABLE`, STOP and report; the admin probably gave a
   wrong address / firewalled port.

4. Clone the donor's Xray config onto the new node.
   `clone_node_config(from_node_id=donor_node_id, to_node_id=new_node_id)`.
   This copies inbounds (with the same `tag`s) and basic outbounds.
   Report what was cloned from the return payload.

5. Restart the new node's Xray backend so the cloned config takes
   effect. `restart_node_backend(new_node_id, backend="xray")`. Wait
   a couple of seconds before the next check.

6. Verify Xray actually started on the new node.
   `get_node_info(new_node_id)` — look at `status`, then
   `get_node_logs(new_node_id, backend="xray", max_lines=80)` and
   check the tail for a "Xray started" / "started" line and no
   recent "failed to parse" / "listen: bind" errors. If Xray did not
   start, STOP and report the error line verbatim.

7. Attach the new node's inbounds to every service the donor was in.
   `propagate_node_to_services(from_node_id=donor_node_id,
   to_node_id=new_node_id)`. Read the returned `unmatched_donor_tags`
   and `services_updated` carefully. If any donor tag didn't match a
   tag on the new node, that means `clone_node_config` produced a
   slightly different tag set — fix it with
   `add_inbounds_to_service(service_id, inbound_ids=[...])` manually
   before proceeding.

8. Push the current user set onto the new node so it knows who is
   allowed to connect. `resync_node_users(new_node_id)`.

9. Verify users actually see the new node in their subscription. Pick
   the `username` the admin gave you (or a random real user from
   `list_users(limit=1)` if they didn't), then call
   `inspect_user_subscription(username, config_format="links")`.
   Confirm at least one VLESS/VMess/Trojan line contains
   `new_node`'s address. If the generated links are missing the new
   endpoint, the service wiring in step 7 is wrong — re-check with
   `get_service_info`.

10. For any issues found in step 9, also run `validate_host(host_id)`
    on the relevant host(s) to catch classic misconfigurations
    (missing reality_public_key, absent UUID, wrong flow).

## Stop criteria
- All 9 steps succeeded, step 9 shows at least one fresh config for
  the new node's address.
- Report back: new node id, its status, how many services were updated,
  how many users were synced, and a one-line confirmation that
  subscriptions pick up the new endpoint.

## Common pitfalls
- Forgetting step 7 (propagate to services) is the #1 cause of "agent
  set up the server but users never got it". Never skip it.
- Forgetting step 8 (resync users) means the new node has inbounds but
  no clients — Xray rejects connections.
- Skipping step 9 means you report "done" while users still see the
  old config. Always verify end-to-end.
- If `clone_node_config` produced unmatched tags (step 7 warning),
  never silently ignore — the admin needs to know there's a gap.
