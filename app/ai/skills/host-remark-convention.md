---
name: host-remark-convention
description: Create or edit a host's `remark` field while preserving the installation's existing naming convention (emoji, variation selectors, numbering scheme like "UNIVERSAL 3 / UNIVERSAL 4"). Use whenever the admin asks to add a new host or change the remark on existing ones — especially if they say "same as the others", "next one after X", "replace X with Y across all universal hosts". The point is to NEVER invent a remark from scratch or retype emoji — always copy from an existing sibling.
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

## Editing the remark on an EXISTING host

1. `get_host_info(host_id)` — treat the returned `remark` as the
   literal source of truth.

2. Make the minimal edit in-place: copy the full returned string,
   change ONLY the specific characters the admin asked about.

3. `modify_host(host_id, remark=<edited>)`. Do not pass
   `clear_fields=["remark"]` — remark is required.

## "Replace X with Y across all universal hosts"

1. `list_hosts(universal_only=true, limit=100)`. Walk pages until
   `truncated=false` / `next_offset=null`.

2. For each host whose `remark` contains X:
   - Compute new remark as `old_remark.replace(X, Y)` — literal
     substring, do NOT attempt a regex unless the admin explicitly
     said regex.
   - `modify_host(host_id, remark=<new>)`.

3. Summarise afterwards: how many hosts were touched, how many
   were skipped because they did not contain X.

## Never do
- Never invent new emoji. If the admin says "add a German flag" and
  no German-flag host exists yet, ASK for one working sample remark
  from any flagged host, so you can copy the emoji codepoints from
  real data.
- Never normalise Unicode (NFC/NFD) while editing — round-tripping
  through your tokenizer is already lossy; adding normalisation
  makes it worse.
- Never paste the final remark back into chat with your own
  emoji output — copy from the tool's returned string and show it
  between backticks so the admin can visually verify codepoints
  survived.
