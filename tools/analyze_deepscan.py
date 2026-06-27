#!/usr/bin/env python3
"""Analyze a Reshu VPN DeepScan log into actionable verdicts for RU-DPI tuning.

The DeepScan in the Android client tests the *exact* hosts a user receives in
their /sub subscription, from a real RU network. That is the only test that
reproduces TSPU/DPI behavior on the client->entry hop, so this log is our
ground truth. This tool turns it into:

  1. Per entry-IP + transport verdict (alive / dead / DPI-throttled)
  2. Per transport-type summary (tcp vs xhttp vs grpc vs reality)
  3. Working exit countries (reachable through a live entry)
  4. Recommendations + ready-to-run SQL to disable dead hosts

Usage:
    python tools/analyze_deepscan.py <deepscan_log.txt>

Optional: a nodes map JSON (id->{address,name}) exported from the panel can be
passed as a 2nd arg to label entry IPs with node id/provider. Without it, the
tool still works purely from the log.
"""
import json
import re
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# DeepScan result line, e.g.:
#   OK 📶 ELITE 2 [156 GB] - RU [ 4G ] [84.201.177.241/tcp] 11658 KB/s
#   FAIL[TRANSPORT] 🛜 UNIVERSAL 2 ♾️ RU [45.81.33.150/tcp] — No data through proxy
#   FAIL[EXIT] ⚡️FAST 2 ♾️ - FI [2.57.242.209/tcp] 1035 KB/s — DPI/SNI block: ...
#   SKIP 🛜 UNIVERSAL 6 ♾️ TR [185.179.191.236/tcp] — dead entry-node pattern
RESULT_RE = re.compile(
    r'DeepScan:\s+'
    r'(OK|FAIL\[(?P<ftype>[A-Z]+)\]|SKIP)\s+'
    r'(?P<name>.*?)\s+'
    r'\[(?P<ip>\d+\.\d+\.\d+\.\d+)/(?P<transport>\w+)\]'
    r'(?:\s+(?P<speed>\d+)\s*KB/s)?'
    r'(?:\s*[—-]+\s*(?P<reason>.*))?$'
)
SUMMARY_RE = re.compile(r'Deep scan done in .*?:\s*(.*)$')


def clean(s):
    """Drop emoji / non-ascii so the report prints on any console."""
    return re.sub(r'\s+', ' ', re.sub(r'[^\x00-\x7f]', '', s)).strip()


def classify_reason(reason):
    """Bucket a failure reason into a coarse cause."""
    if not reason:
        return 'unknown'
    r = reason.lower()
    if 'no data through proxy' in r or 'входная нода' in r or 'dead entry' in r:
        return 'transport_dead'
    if 'dpi/sni block' in r:
        return 'dpi_sni_block'
    if 'dpi cut' in r or 'throttl' in r:
        return 'dpi_throttle'
    return 'other'


def load_nodes_map(path):
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return {}
    out = {}
    items = raw if isinstance(raw, list) else raw.values()
    for n in items:
        addr = n.get('address')
        if addr:
            out[addr] = {'id': n.get('id'), 'name': n.get('name', '')}
    return out


def main(log_path, nodes_path=None):
    nodes = load_nodes_map(nodes_path) if nodes_path else {}

    rows = []  # one dict per scanned host
    summary = None
    with open(log_path, encoding='utf-8') as f:
        for line in f:
            m = RESULT_RE.search(line)
            if m:
                verdict = 'OK' if line.split('DeepScan:')[1].strip().startswith('OK') \
                    else ('SKIP' if 'SKIP' in m.group(0)[:40] else 'FAIL')
                rows.append({
                    'name': m.group('name').strip(),
                    'ip': m.group('ip'),
                    'transport': m.group('transport'),
                    'verdict': verdict,
                    'ftype': m.group('ftype') or '',
                    'speed': int(m.group('speed')) if m.group('speed') else None,
                    'reason': (m.group('reason') or '').strip(),
                    'cause': classify_reason(m.group('reason')),
                })
                continue
            ms = SUMMARY_RE.search(line)
            if ms:
                summary = ms.group(1).strip()

    if not rows:
        print('No DeepScan result lines found. Is this a DeepScan export?')
        return

    def label(ip):
        n = nodes.get(ip)
        return f'node {n["id"]}' if n else ip[:15]

    # ---- 1. Per entry-IP + transport ----
    entry = defaultdict(lambda: {'ok': 0, 'fail': 0, 'skip': 0, 'causes': defaultdict(int)})
    for r in rows:
        key = (r['ip'], r['transport'])
        e = entry[key]
        if r['verdict'] == 'OK':
            e['ok'] += 1
        elif r['verdict'] == 'SKIP':
            e['skip'] += 1
        else:
            e['fail'] += 1
            e['causes'][r['cause']] += 1

    # ---- 2. Per transport type ----
    transport = defaultdict(lambda: {'ok': 0, 'fail': 0, 'skip': 0})
    for r in rows:
        t = transport[r['transport']]
        t['ok' if r['verdict'] == 'OK' else ('skip' if r['verdict'] == 'SKIP' else 'fail')] += 1

    # ---- 3. Working exits (OK rows) ----
    ok_rows = [r for r in rows if r['verdict'] == 'OK']

    bar = '=' * 72
    print(bar)
    print('DEEPSCAN ANALYSIS')
    if summary:
        print('client summary:', summary)
    print(f'parsed {len(rows)} host results, {len(ok_rows)} OK')
    print(bar)

    print('\n--- TRANSPORT TYPE VERDICT ---')
    print(f'{"transport":<10}{"OK":>5}{"FAIL":>6}{"SKIP":>6}{"verdict":>18}')
    for t, s in sorted(transport.items(), key=lambda kv: -kv[1]['ok']):
        tot = s['ok'] + s['fail']
        v = 'DEAD (DPI-blocked)' if s['ok'] == 0 and tot else \
            ('healthy' if s['ok'] >= s['fail'] else 'degraded')
        print(f'{t:<10}{s["ok"]:>5}{s["fail"]:>6}{s["skip"]:>6}{v:>18}')

    print('\n--- ENTRY-IP / TRANSPORT VERDICT ---')
    print(f'{"entry":<16}{"transport":<8}{"OK":>4}{"FAIL":>5}{"SKIP":>5}  verdict / dominant cause')
    dead_entries = []
    for (ip, t), s in sorted(entry.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        tot = s['ok'] + s['fail']
        if s['ok'] > 0:
            v = f'ALIVE ({s["ok"]} exits up)'
        elif tot or s['skip']:
            cause = max(s['causes'].items(), key=lambda kv: kv[1])[0] if s['causes'] else 'skipped'
            v = f'DEAD -> {cause}'
            dead_entries.append((ip, t, cause))
        else:
            v = 'no data'
        print(f'{label(ip):<16}{t:<8}{s["ok"]:>4}{s["fail"]:>5}{s["skip"]:>5}  {v}')

    print('\n--- WORKING EXITS (reachable through a live entry) ---')
    for r in sorted(ok_rows, key=lambda r: -(r['speed'] or 0)):
        sp = f'{r["speed"]} KB/s' if r['speed'] else ''
        print(f'  {clean(r["name"])[:46]:<46} {label(r["ip"]):<14} {r["transport"]:<6} {sp}')

    print('\n' + bar)
    print('RECOMMENDATIONS')
    print(bar)
    recs = []
    for t, s in transport.items():
        if s['ok'] == 0 and (s['ok'] + s['fail']) >= 3:
            recs.append(f'Transport "{t}" is 100% dead ({s["fail"]} fails) -> disable all {t} hosts.')
    alive_ips = {ip for (ip, t), s in entry.items() if s['ok'] > 0}
    # entry hop blocked by DPI (client->entry): rotate / re-mask the entry IP
    transport_dead_ips = sorted(
        {ip for ip, t, c in dead_entries if c == 'transport_dead'} - alive_ips)
    # exit filtered (entry connects, destination unreachable): swap exit, not entry
    exit_blocked_ips = sorted(
        {ip for ip, t, c in dead_entries if c in ('dpi_sni_block', 'dpi_throttle')} - alive_ips
        - set(transport_dead_ips))
    for ip in transport_dead_ips:
        recs.append(f'ENTRY DEAD {label(ip)} ({ip}): client->entry hop blocked -> rotate IP / re-mask.')
    for ip in exit_blocked_ips:
        recs.append(f'EXIT BLOCKED {label(ip)} ({ip}): entry OK but destination DPI-filtered -> '
                    f'route via a clean exit or drop this exit.')
    if not recs:
        recs.append('No fleet-wide dead patterns detected.')
    for i, r in enumerate(recs, 1):
        print(f'{i}. {r}')

    # ---- SQL suggestions ----
    print('\n--- SQL (review before running) ---')
    if any(s['ok'] == 0 and (s['ok'] + s['fail']) >= 3 for s in transport.values()):
        print("-- disable dead XHTTP hosts (transport blocked by DPI):")
        print("UPDATE hosts SET is_disabled=1 WHERE remark LIKE '%XHTTP%' OR remark LIKE '%xhttp%';")
    if transport_dead_ips:
        ips = ', '.join(f"'{ip}'" for ip in transport_dead_ips)
        print("-- hosts whose entry hop is DPI-blocked (verify in RU before disabling):")
        print(f"SELECT id, remark, address FROM hosts WHERE address IN ({ips});")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
