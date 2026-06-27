# -*- coding: utf-8 -*-
"""Generate idempotent SQL to:
  1) link every inbound on the U1/U2/U3 entry nodes to service 1
     (inbounds_services), and
  2) create the missing host rows (Part A: existing inbounds without a host;
     Part B: the freshly added bridge inbounds).

Reads .tmp_uni_configs/inb_targets.tsv (id,node_id,tag for nodes 25/15/12) and
hosts2.tsv (existing universal hosts: id,inbound_id,weight,address).

Hosts are created enabled (is_disabled=0), port=NULL (inherits the inbound's
listening port — robust against per-node port quirks), sni=api-maps.yandex.ru,
security=inbound_default, fingerprint=chrome. Weight is set provisionally and
re-banded by the separate weight pass.
"""
import os

BASE = os.path.join(os.path.dirname(__file__), "..", ".tmp_uni_configs")

NODE_TO_U = {25: 1, 15: 2, 12: 3}
NODE_TO_IP = {25: "89.191.225.218", 15: "84.252.101.98", 12: "5.35.125.174"}

# flag emojis
RU = "\U0001F1F7\U0001F1FA"
FI = "\U0001F1EB\U0001F1EE"
EE = "\U0001F1EA\U0001F1EA"
FR = "\U0001F1EB\U0001F1F7"
TR = "\U0001F1F9\U0001F1F7"
US = "\U0001F1FA\U0001F1F8"
PL = "\U0001F1F5\U0001F1F1"
NL = "\U0001F1F3\U0001F1F1"
DE = "\U0001F1E9\U0001F1EA"
SAT = "\U0001F6DC"      # 🛜
INF = "\u267E\uFE0F"    # ♾️

# tag -> (flag, label)
HOSTMAP = {
    "RU Direct": (RU, "RU (\u042f \u0437\u0430 \u0433\u0440\u0430\u043d\u0438\u0446\u0435\u0439)"),
    "RU Direct (XHTTP)": (RU, "RU xhttp"),
    "RU->FL Bridge": (FI, "FI"),
    "RU->FL Bridge (XHTTP)": (FI, "FI xhttp"),
    "RU->FI-1 Bridge": (FI, "FI-2"),
    "RU->FI-2 Bridge": (FI, "FI-3"),
    "RU->EE Bridge": (EE, "EE"),
    "RU->EE Bridge (XHTTP)": (EE, "EE xhttp"),
    "RU->FR Bridge": (FR, "FR"),
    "RU->FR Bridge (XHTTP)": (FR, "FR xhttp"),
    "RU->FR-2 Bridge": (FR, "FR-2"),
    "RU->TR-1 Bridge": (TR, "TR"),
    "RU->US Bridge": (US, "US"),
    "RU->US-1 Bridge": (US, "US"),
    "RU->USA-2 Bridge": (US, "US-2"),
    "RU->PL-1 Bridge": (PL, "PL"),
    "RU->PL-1 Bridge (XHTTP)": (PL, "PL xhttp"),
    "RU->NL-1 Bridge": (NL, "NL"),
    "RU->GE-1 Bridge": (DE, "DE"),
    "RU->GE-1 Bridge (XHTTP)": (DE, "DE xhttp"),
    "RU->GE-2 Bridge": (DE, "DE-2"),
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


def load_tsv(path):
    rows = read_text(path).splitlines()
    hdr = rows[0].split("\t")
    out = []
    for ln in rows[1:]:
        parts = ln.split("\t")
        if len(parts) == len(hdr):
            out.append(dict(zip(hdr, parts)))
    return out


def sqlstr(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


def main():
    inbs = load_tsv(os.path.join(BASE, "inb_targets.tsv"))
    hosts = load_tsv(os.path.join(BASE, "hosts2.tsv"))
    existing_host_inbids = {int(h["inbound_id"]) for h in hosts
                            if h["inbound_id"].isdigit()}

    svc_lines = ["-- link all U1/U2/U3 inbounds to service 1 (idempotent)"]
    host_lines = ["-- create missing universal hosts (Part A + Part B)"]
    n_hosts = 0
    for r in inbs:
        iid = int(r["id"]); node = int(r["node_id"]); tag = r["tag"]
        if node not in NODE_TO_U:
            continue
        svc_lines.append(
            f"INSERT IGNORE INTO inbounds_services (inbound_id, service_id) "
            f"VALUES ({iid}, 1);")
        if tag not in HOSTMAP:
            continue
        if iid in existing_host_inbids:
            continue
        flag, label = HOSTMAP[tag]
        u = NODE_TO_U[node]
        ip = NODE_TO_IP[node]
        remark = f"{flag} {SAT} UNIVERSAL {u} {INF} {label}"
        host_lines.append(
            "INSERT INTO hosts "
            "(remark, address, port, sni, security, fingerprint, inbound_id, "
            " is_disabled, weight, universal, mlkem_enabled) VALUES ("
            f"{sqlstr(remark)}, {sqlstr(ip)}, NULL, 'api-maps.yandex.ru', "
            f"'inbound_default', 'chrome', {iid}, 0, "
            f"{100 + (u - 1) * 10}, 0, 0);")
        n_hosts += 1

    with open(os.path.join(BASE, "01_services.sql"), "w", encoding="utf-8") as f:
        f.write("\n".join(svc_lines) + "\n")
    with open(os.path.join(BASE, "02_hosts.sql"), "w", encoding="utf-8") as f:
        f.write("\n".join(host_lines) + "\n")
    print(f"services links: {len(svc_lines)-1}, new hosts: {n_hosts}")


if __name__ == "__main__":
    main()
