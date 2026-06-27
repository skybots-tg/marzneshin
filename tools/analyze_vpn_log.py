#!/usr/bin/env python3
"""Parse a Reshu VPN client log export into a structured per-server summary.

Usage: python tools/analyze_vpn_log.py <logfile>
"""
import re
import sys
import json
from collections import defaultdict, OrderedDict

LINE_RE = re.compile(r'^(\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\s+[A-Z]/([A-Za-z]+):\s+(.*)$')


def strip_emoji(s):
    return re.sub(r'[^\x00-\x7f]', '', s).strip()


def main(path):
    events = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            m = LINE_RE.match(line.rstrip('\n'))
            if not m:
                continue
            ts, tag, msg = m.groups()
            events.append((ts, tag, msg))

    # Per-server aggregation
    servers = OrderedDict()  # name -> stats

    def srv(name):
        name = strip_emoji(name)
        if name not in servers:
            servers[name] = {
                'name': name,
                'ip': None,
                'connect_attempts': 0,
                'tls_probe_ok': 0,
                'tls_probe_ms': [],
                'service_probe_runs': 0,
                'service_probe_passed': 0,  # runs with rate>=threshold
                'service_probe_pass_counts': [],  # X out of 6 per run
                'marked_dead': 0,
                'blacklisted': 0,
                'throughputs': [],  # bytes/s while connected
            }
        return servers[name]

    current = None  # currently connected server name
    switch_re = re.compile(r'Server switch \([^)]*\):\s+(.*?)\s+\u2192\s+(.*)$')
    tlsok_re = re.compile(r'TLS-probe OK for\s+(.*?)\s+\((\d+)ms\)')
    connect_re = re.compile(r'Connecting to\s+(.*?)\s+\(([\d.]+):(\d+)\)')
    reconnected_re = re.compile(r'Reconnected successfully to\s+(.*)$')
    dead_re = re.compile(r'Server dead:\s+(.*?),')
    probe_re = re.compile(r'Service probe:\s+(\d+)/(\d+) passed \(rate=([\d.,]+),\s*threshold=([\d.]+)\)')

    timeline = []  # high-level connect timeline

    for ts, tag, msg in events:
        m = connect_re.search(msg)
        if m:
            name, ip, port = m.groups()
            s = srv(name)
            s['ip'] = f'{ip}:{port}'
            s['connect_attempts'] += 1
            current = strip_emoji(name)
            timeline.append((ts, 'CONNECT', strip_emoji(name), f'{ip}:{port}'))
            continue

        m = tlsok_re.search(msg)
        if m:
            name, ms = m.groups()
            s = srv(name)
            s['tls_probe_ok'] += 1
            s['tls_probe_ms'].append(int(ms))
            continue

        m = reconnected_re.search(msg)
        if m:
            current = strip_emoji(m.group(1))
            timeline.append((ts, 'RECONNECTED', current, ''))
            continue

        m = switch_re.search(msg)
        if m:
            frm, to = m.groups()
            timeline.append((ts, 'SWITCH', strip_emoji(frm), '-> ' + strip_emoji(to)))
            continue

        m = dead_re.search(msg)
        if m:
            s = srv(m.group(1))
            s['marked_dead'] += 1
            continue

        if 'Blacklisted' in msg and tag == 'WifiServerMemory':
            # blacklist is by uuid, can't map to name reliably here
            pass

        m = probe_re.search(msg)
        if m and current:
            passed, total, rate, thr = m.groups()
            s = servers.get(current)
            if s:
                s['service_probe_runs'] += 1
                s['service_probe_pass_counts'].append(int(passed))
                rate_f = float(rate.replace(',', '.'))
                if rate_f >= float(thr):
                    s['service_probe_passed'] += 1
            continue

        if tag == 'TelegramDcProbe' and 'thr=' in msg and current:
            tm = re.search(r'=(\d+)B/s', msg)
            if tm:
                s = servers.get(current)
                if s:
                    s['throughputs'].append(int(tm.group(1)))

    # Output
    print('=' * 70)
    print('PER-SERVER SUMMARY')
    print('=' * 70)
    hdr = f'{"server":<24}{"ip":<22}{"conn":>5}{"tlsOK":>6}{"svcRuns":>8}{"svcPass":>8}{"dead":>5}{"avgThr":>9}'
    print(hdr)
    print('-' * len(hdr))
    for name, s in servers.items():
        thr = s['throughputs']
        avg = f'{int(sum(thr)/len(thr)/1024)}KB/s' if thr else '-'
        pass_detail = '/'.join(str(x) for x in s['service_probe_pass_counts']) or '-'
        print(f'{name:<24}{(s["ip"] or "-"):<22}{s["connect_attempts"]:>5}{s["tls_probe_ok"]:>6}'
              f'{s["service_probe_runs"]:>8}{s["service_probe_passed"]:>8}{s["marked_dead"]:>5}{avg:>9}')
    print()
    print('Service-probe pass counts per run (X out of 6 reachable sites):')
    for name, s in servers.items():
        if s['service_probe_pass_counts']:
            print(f'  {name:<24} {s["service_probe_pass_counts"]}')
    print()
    print('=' * 70)
    print(f'TIMELINE ({len(timeline)} events)')
    print('=' * 70)
    for ts, kind, name, extra in timeline:
        print(f'{ts}  {kind:<12} {name} {extra}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'log.txt')
