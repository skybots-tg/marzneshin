#!/usr/bin/env python3
"""Run ON the panel. Add missing multihop bridges to an entry node, end-to-end:
  node xray_config.json (inbound+outbound+route, fresh reality keypair, yandex SNI)
  + DB inbounds row + inbounds_services link + universal host row.

Reference templates are taken from U6 (193.233.246.18), which carries the full
canonical bridge set on canonical ports with the proven yandex masking.

Dry-run unless --apply. usage: add_bridges.py [--apply] <U4|U5>
"""
import copy, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from _secrets import DB_ROOT_PW
except ImportError as _e:
    raise SystemExit(
        "Missing _secrets.py at repo root. Create it with DB_ROOT_PW=... "
        "(it is gitignored on purpose)."
    ) from _e

KEY = "/root/.ssh/vpn_node_default"
REF_IP = "193.233.246.18"  # U6 full reference (now yandex)
DB = ["docker", "exec", "-i", "marzneshin-db-1", "mariadb", "-u", "root", f"-p{DB_ROOT_PW}", "marzneshin"]
GOOD_DEST = "api-maps.yandex.ru:443"
GOOD_SNI = ["api-maps.yandex.ru", "ads.x5.ru"]

TARGETS = {
    "U4": {"ip": "45.150.239.178", "node_id": 30, "uni": 4,
           "bridges": ["RU->US Bridge", "RU->USA-2 Bridge"]},
    "U5": {"ip": "185.219.41.121", "node_id": 31, "uni": 5,
           "bridges": ["RU->TR-1 Bridge", "RU->USA-2 Bridge", "RU->PL-1 Bridge",
                       "RU->NL-1 Bridge", "RU->GE-1 Bridge", "RU->GE-2 Bridge",
                       "RU->FI-1 Bridge", "RU->FI-2 Bridge", "RU->US Bridge"]},
}

# flags + labels (mirror tools/gen_db_sql.py)
RU="\U0001F1F7\U0001F1FA"; FI="\U0001F1EB\U0001F1EE"; EE="\U0001F1EA\U0001F1EA"
FR="\U0001F1EB\U0001F1F7"; TR="\U0001F1F9\U0001F1F7"; US="\U0001F1FA\U0001F1F8"
PL="\U0001F1F5\U0001F1F1"; NL="\U0001F1F3\U0001F1F1"; DE="\U0001F1E9\U0001F1EA"
SAT="\U0001F6DC"; INF="\u267E\uFE0F"
HOSTMAP = {
    "RU->FL Bridge": (FI,"FI"), "RU->FI-1 Bridge": (FI,"FI-2"), "RU->FI-2 Bridge": (FI,"FI-3"),
    "RU->EE Bridge": (EE,"EE"), "RU->FR Bridge": (FR,"FR"), "RU->FR-2 Bridge": (FR,"FR-2"),
    "RU->TR-1 Bridge": (TR,"TR"), "RU->US Bridge": (US,"US"), "RU->USA-2 Bridge": (US,"US-2"),
    "RU->PL-1 Bridge": (PL,"PL"), "RU->NL-1 Bridge": (NL,"NL"),
    "RU->GE-1 Bridge": (DE,"DE"), "RU->GE-2 Bridge": (DE,"DE-2"),
}


def ssh(ip, cmd, inp=None, timeout=90):
    return subprocess.run(["ssh","-o","ConnectTimeout=10","-o","BatchMode=yes","-i",KEY,
        f"root@{ip}",cmd], input=inp, capture_output=True, text=True, timeout=timeout)


def db(sql, timeout=40):
    return subprocess.run(DB, input=sql, capture_output=True, text=True, timeout=timeout)


def node_cfg(ip):
    r = ssh(ip, "cat /var/lib/marznode/xray_config.json")
    return json.loads(r.stdout)


def routing_map(cfg):
    m = {}
    for r in cfg.get("routing", {}).get("rules", []):
        for it in r.get("inboundTag", []):
            m[it] = r.get("outboundTag")
    return m


def find(seq, tag):
    return next((x for x in seq if x.get("tag") == tag), None)


def gen_keys(ip, n):
    """Generate n x25519 keypairs inside the marznode container."""
    cmd = ('c=$(docker ps --format "{{.Names}}" | grep -i marz | head -1); '
           f'for i in $(seq 1 {n}); do docker exec "$c" xray x25519; echo "==="; done')
    r = ssh(ip, cmd)
    pairs = []
    priv = pub = None
    for line in r.stdout.splitlines():
        line = line.strip()
        m1 = re.match(r'PrivateKey:\s*(\S+)', line)
        m2 = re.match(r'(?:Password \(PublicKey\)|PublicKey):\s*(\S+)', line)
        if m1: priv = m1.group(1)
        elif m2: pub = m2.group(1)
        elif line == "===":
            if priv and pub: pairs.append((priv, pub))
            priv = pub = None
    return pairs


def rand_sid():
    import secrets
    return secrets.token_hex(8)


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    sel = [a for a in args if not a.startswith("--")]
    if len(sel) != 1 or sel[0] not in TARGETS:
        print("usage: add_bridges.py [--apply] <U4|U5>"); sys.exit(1)
    T = TARGETS[sel[0]]
    ip, node_id, uni = T["ip"], T["node_id"], T["uni"]

    ref = node_cfg(REF_IP); rrt = routing_map(ref)
    cfg = node_cfg(ip)
    have_in = {ib["tag"] for ib in cfg["inbounds"]}
    have_out = {ob["tag"] for ob in cfg["outbounds"]}
    have_ports = {ib.get("port") for ib in cfg["inbounds"]}

    todo = [t for t in T["bridges"] if t not in have_in]
    skipped = [t for t in T["bridges"] if t in have_in]
    if skipped:
        print(f"  already present, skipping: {skipped}")
    if not todo:
        print("  nothing to add"); return

    pairs = gen_keys(ip, len(todo)) if apply else [("__PRIV__","__PUB__")]*len(todo)
    if apply and len(pairs) != len(todo):
        print(f"  KEYGEN FAILED: got {len(pairs)} keys for {len(todo)} bridges"); sys.exit(2)

    new = copy.deepcopy(cfg)
    db_inbounds, db_hosts, plan = [], [], []
    for i, tag in enumerate(todo):
        ref_ib = find(ref["inbounds"], tag)
        if not ref_ib:
            print(f"  REF MISSING {tag}, skip"); continue
        port = ref_ib["port"]
        if port in have_ports:
            print(f"  PORT CONFLICT {port} for {tag}, skip"); continue
        ob_tag = rrt[tag]
        priv, pub = pairs[i]
        sid = rand_sid()
        net = ref_ib["streamSettings"]["network"]
        flow = ref_ib["settings"].get("clients", [{}])[0].get("flow") if ref_ib["settings"].get("clients") else None
        # node inbound
        ib = copy.deepcopy(ref_ib)
        rs = ib["streamSettings"]["realitySettings"]
        rs["privateKey"] = priv; rs["shortIds"] = [sid]
        rs["dest"] = GOOD_DEST; rs["serverNames"] = list(GOOD_SNI)
        ib["settings"] = {"clients": [], "decryption": "none"}
        new["inbounds"].append(ib)
        have_ports.add(port)
        # node outbound + route
        if ob_tag not in have_out:
            new["outbounds"].append(copy.deepcopy(find(ref["outbounds"], ob_tag)))
            have_out.add(ob_tag)
        new["routing"]["rules"].append({"type":"field","inboundTag":[tag],"outboundTag":ob_tag})
        # DB inbound config JSON (flow: vision for tcp, null for xhttp)
        dbcfg = {"tag":tag,"protocol":"vless","port":port,
                 "network":net,"tls":"reality","sni":list(GOOD_SNI),"host":[],
                 "path": None,"header_type":None,
                 "flow": ("xtls-rprx-vision" if net=="tcp" else None),
                 "is_fallback":False,"fp":"chrome","pbk":pub,"sid":sid}
        db_inbounds.append((tag, json.dumps(dbcfg, ensure_ascii=False)))
        flag, label = HOSTMAP[tag]
        remark = f"{flag} {SAT} UNIVERSAL {uni} {INF} {label}"
        db_hosts.append((tag, remark))
        plan.append(f"ADD {tag} :{port} {net} -> {ob_tag}  pbk={pub[:12]}..")

    print(f"  {len(plan)} bridges to add on {sel[0]} ({ip}):")
    for p in plan: print("   ", p)

    # build SQL
    sql = []
    for tag, cfgjson in db_inbounds:
        c = cfgjson.replace("\\","\\\\").replace("'","''")
        sql.append(f"INSERT INTO inbounds (protocol, tag, config, node_id) "
                   f"VALUES ('VLESS', '{tag}', '{c}', {node_id});")
    for tag, _ in db_inbounds:
        sql.append(f"INSERT IGNORE INTO inbounds_services (inbound_id, service_id) "
                   f"SELECT id,1 FROM inbounds WHERE node_id={node_id} AND tag='{tag}';")
    w = 100 + (uni-1)*10
    for tag, remark in db_hosts:
        rm = remark.replace("'","''")
        sql.append(
            "INSERT INTO hosts (remark,address,port,sni,security,fingerprint,"
            "inbound_id,is_disabled,weight,universal,mlkem_enabled) "
            f"SELECT '{rm}','{ip}',NULL,'api-maps.yandex.ru','inbound_default','chrome',"
            f"i.id,0,{w},0,0 FROM inbounds i WHERE i.node_id={node_id} AND i.tag='{tag}';")
    sql_text = "\n".join(sql) + "\n"

    if not apply:
        print("\n  --- SQL (dry-run) ---")
        print(sql_text)
        return

    # 1) deploy node config
    deploy = r'''
set -u
c=$(docker ps --format '{{.Names}}' | grep -i marz | head -1)
[ -n "$c" ] || { echo FATAL_NO_CONTAINER; exit 1; }
cat > /tmp/xray_new.json
docker cp /tmp/xray_new.json "$c:/tmp/xray_new.json" >/dev/null
if docker exec "$c" xray run -test -c /tmp/xray_new.json >/tmp/t.log 2>&1 \
   || docker exec "$c" xray -test -config /tmp/xray_new.json >/tmp/t.log 2>&1; then
  echo TEST_OK
else
  echo TEST_FAILED; tail -6 /tmp/t.log; exit 2
fi
TS=$(date +%Y%m%d-%H%M%S)
cp -a /var/lib/marznode/xray_config.json /var/lib/marznode/xray_config.json.bak-$TS
echo "backup: xray_config.json.bak-$TS"
cp -f /tmp/xray_new.json /var/lib/marznode/xray_config.json
docker restart "$c" >/dev/null && echo RESTARTED
sleep 6
docker ps --filter "name=$c" --format '{{.Names}} {{.Status}}'
'''
    out = ssh(ip, deploy, inp=json.dumps(new, ensure_ascii=False, indent=2), timeout=120)
    print(out.stdout)
    if "TEST_OK" not in out.stdout:
        print("  NODE DEPLOY FAILED — DB NOT TOUCHED"); print(out.stderr[:400]); sys.exit(3)

    # 2) DB
    r = db(sql_text)
    print("  DB:", "OK" if r.returncode == 0 else "FAILED")
    if r.returncode != 0:
        print(r.stderr[:600])


if __name__ == "__main__":
    main()
