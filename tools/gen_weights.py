# -*- coding: utf-8 -*-
"""Re-band weights for ALL universal hosts so the subscription order is:
   [pre-universal servers] < U1 < U2 < U3 < U4 < U5 < U6 < U7 < [FAST series]

Ascending weight = earlier in the subscription. Each universal gets a 10-wide
band (U1:100-109 ... U7:160-169), entirely inside the free [90,199] range
(pre-universal hosts are <90, the FAST series is >=200). Within a universal a
small per-exit sub-weight keeps RU first and groups countries.
"""
import os

BASE = os.path.join(os.path.dirname(__file__), "..", ".tmp_uni_configs")
NODE_TO_U = {25: 1, 15: 2, 12: 3, 30: 4, 31: 5, 34: 6, 36: 7}

SUB = {
    "RU Direct": 0, "RU Direct (XHTTP)": 0,
    "RU->FL Bridge": 1, "RU->FL Bridge (XHTTP)": 1,
    "RU->FI-1 Bridge": 2, "RU->FI-2 Bridge": 2,
    "RU->EE Bridge": 3, "RU->EE Bridge (XHTTP)": 3,
    "RU->FR Bridge": 4, "RU->FR Bridge (XHTTP)": 4,
    "RU->FR-2 Bridge": 5,
    "RU->TR-1 Bridge": 6,
    "RU->US Bridge": 7, "RU->US-1 Bridge": 7, "RU->USA-2 Bridge": 7,
    "RU->PL-1 Bridge": 8, "RU->PL-1 Bridge (XHTTP)": 8, "RU->NL-1 Bridge": 8,
    "RU->GE-1 Bridge": 9, "RU->GE-1 Bridge (XHTTP)": 9, "RU->GE-2 Bridge": 9,
}


def read_text(path):
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except (UnicodeError, UnicodeDecodeError):
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def main():
    rows = read_text(os.path.join(BASE, "hosts3.tsv")).splitlines()
    hdr = rows[0].split("\t")
    hi, ni, ti = hdr.index("id"), hdr.index("node_id"), hdr.index("tag")
    lines = ["-- re-band universal host weights"]
    by_weight = {}
    skipped = []
    for ln in rows[1:]:
        p = ln.split("\t")
        if len(p) < 3:
            continue
        hid = int(p[hi]); node = int(p[ni]); tag = p[ti]
        if node not in NODE_TO_U:
            skipped.append((hid, node, tag)); continue
        u = NODE_TO_U[node]
        sub = SUB.get(tag, 9)
        w = 100 + (u - 1) * 10 + sub
        lines.append(f"UPDATE hosts SET weight={w} WHERE id={hid};")
        by_weight.setdefault(u, set()).add(w)
    with open(os.path.join(BASE, "03_weights.sql"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"updates: {len(lines)-1}, skipped(non-universal node): {skipped}")
    for u in sorted(by_weight):
        print(f"  U{u}: weights {sorted(by_weight[u])}")


if __name__ == "__main__":
    main()
