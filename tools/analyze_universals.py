#!/usr/bin/env python3
"""Cross-reference UNIVERSAL hosts with their inbounds.

Reads .tmp_hosts.tsv and .tmp_inb.tsv (tab-separated MariaDB --batch dumps)
and produces:
  - location matrix per UNIVERSAL number
  - effective config (port/sni/reality) per host, resolving inbound fallbacks
  - mismatch / dead-config warnings
"""
import json
import re
import sys
from collections import defaultdict, OrderedDict


def _open(path):
    raw = open(path, 'rb').read()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16').splitlines()
    return raw.decode('utf-8', errors='replace').splitlines()

NODE_TO_UNI = {
    25: 1,   # 89.191.225.218
    15: 2,   # 84.252.101.98
    12: 3,   # 5.35.125.174
    30: 4,   # 45.150.239.178  (the WORKING one)
    31: 5,   # 185.219.41.121
    34: 6,   # 193.233.246.18
    36: 7,   # 193.233.246.41
}
ADDR_TO_NODE = {
    '89.191.225.218': 25, '84.252.101.98': 15, '5.35.125.174': 12,
    '45.150.239.178': 30, '185.219.41.121': 31, '193.233.246.18': 34,
    '193.233.246.41': 36,
}


def nv(x):
    return None if x in ('NULL', '', None) else x


def load_inbounds(path):
    # inbound_id -> dict; also node->port->inbound
    inb = {}
    node_port = defaultdict(dict)
    for line in _open(path):
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 5:
                continue
            iid, node_id, tag, proto, cfg = parts[0], parts[1], parts[2], parts[3], parts[4]
            try:
                c = json.loads(cfg)
            except Exception:
                c = {}
            d = {
                'id': int(iid), 'node_id': int(node_id), 'tag': tag, 'proto': proto,
                'port': c.get('port'), 'network': c.get('network'),
                'tls': c.get('tls'), 'sni': c.get('sni'), 'pbk': c.get('pbk'),
                'sid': c.get('sid'), 'flow': c.get('flow'),
            }
            inb[int(iid)] = d
            if d['port'] is not None:
                node_port[int(node_id)][d['port']] = d
    return inb, node_port


def loc_from_remark(remark):
    # strip emojis, extract "UNIVERSAL N" and the trailing location token(s)
    txt = re.sub(r'[^\x00-\x7f]', '', remark).strip()
    m = re.search(r'UNIVERSAL\s+(\d+)\s+(.*)', txt)
    if not m:
        return None, None
    num = int(m.group(1))
    loc = m.group(2).strip()
    return num, loc


def main():
    inb, node_port = load_inbounds('.tmp_inb.tsv')
    hosts = []
    for line in _open('.tmp_hosts.tsv'):
            p = line.rstrip('\n').split('\t')
            if len(p) < 12:
                continue
            h = {
                'id': int(p[0]), 'inbound_id': nv(p[1]), 'remark': p[2],
                'address': p[3], 'port': nv(p[4]), 'sni': nv(p[5]),
                'fp': nv(p[6]), 'security': nv(p[7]), 'pbk': nv(p[8]),
                'sid': nv(p[9]), 'flow': nv(p[10]), 'disabled': p[11] == '1',
            }
            hosts.append(h)

    # resolve effective config
    rows = []
    for h in hosts:
        num, loc = loc_from_remark(h['remark'])
        iid = int(h['inbound_id']) if h['inbound_id'] else None
        inbd = inb.get(iid) if iid else None
        eff_port = h['port'] or (inbd['port'] if inbd else None)
        eff_sni = h['sni'] or (inbd['sni'] if inbd else None)
        eff_pbk = h['pbk'] or (inbd['pbk'] if inbd else None)
        network = inbd['network'] if inbd else None
        # validity: does the inbound exist & belong to right node?
        node_id = ADDR_TO_NODE.get(h['address'])
        warn = []
        if inbd is None:
            warn.append('NO_INBOUND')
        else:
            if inbd['node_id'] != node_id:
                warn.append(f'INBOUND_NODE_MISMATCH(inb_node={inbd["node_id"]},host_node={node_id})')
            if eff_port is None:
                warn.append('NO_PORT')
        rows.append({
            'num': num, 'loc': loc, 'hid': h['id'], 'disabled': h['disabled'],
            'eff_port': eff_port, 'network': network, 'sni': eff_sni,
            'inbtag': inbd['tag'] if inbd else None, 'warn': warn,
        })

    # ---- location matrix ----
    locs = sorted({r['loc'] for r in rows if r['loc']})
    by_num_loc = defaultdict(set)
    for r in rows:
        if r['num'] and r['loc'] and not r['disabled']:
            by_num_loc[(r['num'], r['loc'])].add(r['hid'])

    print('=' * 100)
    print('LOCATION MATRIX (enabled hosts only)  rows=UNIVERSAL, cols=location  [X=present]')
    print('=' * 100)
    nums = sorted({r['num'] for r in rows if r['num']})
    colw = max(len(l) for l in locs) + 1
    print('U\\loc'.ljust(6) + ''.join(l.ljust(colw) for l in locs))
    for n in nums:
        line = f'U{n}'.ljust(6)
        for l in locs:
            line += ('  X ' if (n, l) in by_num_loc else '  . ').ljust(colw)
        print(line)
    print()
    # counts
    print('Location count per UNIVERSAL (enabled):')
    for n in nums:
        cnt = sum(1 for l in locs if (n, l) in by_num_loc)
        print(f'  U{n}: {cnt} locations')
    print()

    # ---- missing locations U5 vs U2, U4 gaps ----
    def loctset(n):
        return {l for l in locs if (n, l) in by_num_loc}
    print('Gap analysis:')
    for ref in (2,):
        for tgt in (5, 4):
            miss = sorted(loctset(ref) - loctset(tgt))
            extra = sorted(loctset(tgt) - loctset(ref))
            print(f'  U{tgt} missing vs U{ref}: {miss}')
            print(f'  U{tgt} extra vs U{ref}:   {extra}')
    print()

    # ---- SNI per node ----
    print('Effective SNI used per UNIVERSAL (distinct):')
    sni_by_num = defaultdict(set)
    for r in rows:
        if r['num']:
            sni_by_num[r['num']].add(str(r['sni']))
    for n in nums:
        print(f'  U{n}: {sorted(sni_by_num[n])}')
    print()

    # ---- warnings ----
    print('=' * 100)
    print('CONFIG WARNINGS')
    print('=' * 100)
    wcount = 0
    for r in sorted(rows, key=lambda x: (x['num'] or 0, x['loc'] or '')):
        if r['warn']:
            wcount += 1
            dis = ' [DISABLED]' if r['disabled'] else ''
            print(f"  U{r['num']} {r['loc']:<14} hid={r['hid']:<4} port={r['eff_port']} net={r['network']} -> {','.join(r['warn'])}{dis}")
    if not wcount:
        print('  none')


if __name__ == '__main__':
    main()
