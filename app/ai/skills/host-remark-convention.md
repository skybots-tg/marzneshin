---
name: host-remark-convention
description: Create or edit a host's `remark` field while preserving the installation's existing naming convention (emoji, variation selectors, numbering scheme like "UNIVERSAL 3 / UNIVERSAL 4"). MUST be loaded whenever the admin asks to add a new host, edit an existing remark, or run a bulk substring replace across hosts ("replace X with Y across all hosts", "shorten country names to ISO codes", "rename Франция to FR everywhere", "add 'beta' suffix to every UNIVERSAL 4 remark"). The point is to NEVER invent a remark from scratch and NEVER retype emoji from your own chat output — always copy from an existing sibling or use the bulk-replace tools so the string travels through SQL, not through your tokenizer.
---
# Follow the installation's host-remark convention

## Why this matters
- Marzneshin admins keep `remark` fields tightly consistent across nodes
  and inbounds: same prefixes, same emoji, same order of tokens, same
  whitespace. Users visually scan the config list by these cues.
- Emoji have variation selectors (U+FE0F), skin-tone modifiers, zero-width
  joiners. Retyping them "by eye" from the LLM's own output silently
  drops those invisible codepoints and produces a visually-identical
  but subtly different string. The admin will notice when sorting
  breaks.
- This is not theoretical: every chat character you write is encoded
  through your tokenizer. Round-tripping `🇩🇪⚡️` through chat very often
  yields `🇩🇪⚡` (no U+FE0F) on the way out. The DB then stores a
  visually identical but byte-different string, and `==` comparisons,
  ORDER BY, and external tooling start producing surprising results.

## Rule: always copy from an existing sibling, never reconstruct.

## Creating a NEW host with a "universal N" / sequential remark

1. Enumerate existing siblings with the closest role:
   `list_hosts(remark="universal", limit=100)` or a more specific
   keyword the admin used (e.g. "moscow", "reserve", "premium").

2. Read 2-3 sibling `remark` fields verbatim. The highest-numbered
   one is your template.

3. Build the new `remark` by changing ONLY the numeric index (or the
   single part the admin asked about). Use Python-style substring
   replacement in your head: `old_template.replace("UNIVERSAL 3",
   "UNIVERSAL 4")`. Do NOT retype the emoji.

4. Show the admin the exact new remark as a preview (plain text, in
   single backticks) and call `create_host(remark=<new_remark>,
   ...)` without re-asking for confirmation — the write tool has
   its own modal.

## Editing the remark on a SINGLE existing host

1. `get_host_info(host_id)` — treat the returned `remark` as the
   literal source of truth.

2. Make the minimal edit in-place: copy the full returned string,
   change ONLY the specific characters the admin asked about.

3. `modify_host(host_id, remark=<edited>)`. Do not pass
   `clear_fields=["remark"]` — remark is required.

## "Replace X with Y across many hosts" — USE THE BULK TOOLS

This is the case where freelancing with `modify_host` per-host is most
likely to corrupt emoji and most likely to drown the admin in approval
modals. There are dedicated tools that perform the substring edit
inside the database — the matched substring never travels through your
output.

1. **Preview first** with `preview_remark_replace(old=..., new=...,
   scope=...)`:
   - `old` and `new` are LITERAL substrings — not regex.
   - `scope` is `'all'` (default), `'universal'`, or `'non_universal'`.
   - Optional narrowing: `inbound_id`, `node_id`, `case_sensitive`.
   - Returns each affected host's exact `before` / `after` straight
     from the DB.

2. **Show the diff** to the admin. You may quote the `before` /
   `after` from the tool result inside single backticks — those
   strings came from SQL, not from you, so emoji codepoints survive.
   Do NOT retype the diff manually; cite the tool result.

3. **Apply** with `bulk_replace_in_remarks(old=..., new=...,
   scope=...)` — same arg shape as the preview, single transaction,
   single approval modal for the whole batch.
   - The tool refuses to run if more than `max_changes` rows would
     change (default 200) — narrow the scope or raise the cap if
     that is intentional.
   - On success it returns the same `{host_id, before, after}`
     shape you can summarise back to the admin.

4. **Do NOT** loop `modify_host` for this case. 50+ individual
   approval modals is hostile UX, and every per-host edit forces
   you to retype the remark from your output, which is exactly the
   emoji-corruption bug we are avoiding.

### Worked example: shorten country names to ISO codes
- Admin: "Замени названия у hosts. Вместо полного названия страны —
  сокращение, например Франция → FR".
- Plan, in order:
  1. `preview_remark_replace(old="Франция", new="FR")` — show diff.
  2. `preview_remark_replace(old="Германия", new="DE")` — show diff.
  3. ... (one per country).
  4. `bulk_replace_in_remarks(old="Франция", new="FR")`,
     `bulk_replace_in_remarks(old="Германия", new="DE")`, ...
- Each `bulk_replace_in_remarks` produces ONE approval modal. The
  admin sees a single yes/no per country, not per host.

## Never do
- Never invent new emoji. If the admin says "add a German flag" and
  no German-flag host exists yet, ASK for one working sample remark
  from any flagged host, so you can copy the emoji codepoints from
  real data.
- Never normalise Unicode (NFC/NFD) while editing — round-tripping
  through your tokenizer is already lossy; adding normalisation
  makes it worse.
- Never paste the final remark back into chat with your own
  emoji output as a "preview". Either cite the tool's returned
  string in single backticks, or skip the preview entirely and
  rely on the approval modal — the modal shows the exact remark
  argument the way the API will see it.
- Never re-ask "should I apply now?" between the preview and the
  bulk-write call. The bulk-write has its own modal; that is the
  approval point. Asking in chat just burns a turn.
