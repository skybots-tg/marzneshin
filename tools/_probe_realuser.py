"""Throwaway: probe node 43 with a UUID taken straight from its access log."""
import bridge_lib as bl

# email field in xray access.log is "<user_id>.<key>"; these are users that
# were successfully tunnelling through node 43 seconds before this run.
LIVE = [
    "d8c422cd-53e9-4af4-920a-b865b94b0ea7",
    "7406e9ca-49ef-4218-a197-92b1bb77f827",
    "fa07b112-f930-44ba-9a71-b7c5eed0d1d6",
]

bl.ensure_xray()
targets = [t for t in bl.load_targets(node_ids={43})
           if t.tag in ("RU Direct", "RU->GE-1 Bridge", "RU->RO Bridge")]
print(f"targets: {[(t.tag, t.port) for t in targets]}", flush=True)
for u in LIVE:
    for t in targets:
        r = bl.probe(t, 11993, user_uuid=u, attempts=1, timeout=8)
        print(f"  {u[:8]} {t.tag:<18} -> {r['verdict']} "
              f"{r.get('country') or r.get('error')}", flush=True)
