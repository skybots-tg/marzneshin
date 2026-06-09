#!/usr/bin/env python3
"""Run ON THE PANEL. Connect as a real service-1 user to a given node inbound
(reading its reality params from the DB) and report the egress IP + country.

usage: verify_egress.py <node_id> <inbound_tag> [--user UUID] [--expect RO]
"""
import argparse
import json
import os
import signal
import subprocess
import tempfile
import time

import marz_common as mc

# a real service-1 user (test account)
DEFAULT_USER = "68f85dea-ceeb-b5d3-d090-629fd5d52d65"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("node_id", type=int)
    ap.add_argument("tag")
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--expect", default=None)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    rows = mc.db_query(
        "SELECT n.address, i.config FROM inbounds i JOIN nodes n ON n.id=i.node_id "
        "WHERE i.node_id=%d AND i.tag='%s';" % (args.node_id, args.tag))
    if not rows:
        print("inbound not found"); return
    addr, cfgjson = rows[0][0], rows[0][1]
    c = json.loads(cfgjson)
    port, pbk, sid = c["port"], c["pbk"], c["sid"]
    sni = (c.get("sni") or ["apple.com"])[0]
    flow = c.get("flow") or "xtls-rprx-vision"
    print(f"target {addr}:{port} tag={args.tag} sni={sni} pbk={pbk[:12]}.. sid={sid}")

    cn = subprocess.run("docker ps --format '{{.Names}}'|grep -i marz|head -1",
                        shell=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(f"docker cp {cn}:/usr/local/bin/xray /tmp/xrt", shell=True)

    user = {"id": args.user, "encryption": "none"}
    if flow:
        user["flow"] = flow
    client = {"log": {"loglevel": "warning"},
              "inbounds": [{"tag": "s", "listen": "127.0.0.1", "port": 10977,
                            "protocol": "socks", "settings": {"udp": True}}],
              "outbounds": [{"protocol": "vless", "tag": "p",
                             "settings": {"vnext": [{"address": addr, "port": port,
                                                     "users": [user]}]},
                             "streamSettings": {"network": "tcp", "security": "reality",
                                                "realitySettings": {"serverName": sni,
                                                                    "fingerprint": "chrome",
                                                                    "publicKey": pbk,
                                                                    "shortId": sid}}}]}
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(client, f); f.close()
    client["log"]["loglevel"] = "debug" if args.debug else "warning"
    logf = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
    p = subprocess.Popen(["/tmp/xrt", "run", "-c", f.name],
                         stdout=logf, stderr=subprocess.STDOUT, text=True)
    time.sleep(2.5)
    out = ""
    try:
        r = subprocess.run(["curl", "-s", "--socks5-hostname", "127.0.0.1:10977",
                            "--max-time", "15", "https://ipinfo.io/json"],
                           capture_output=True, text=True, timeout=20)
        out = r.stdout.strip()
    except subprocess.TimeoutExpired:
        out = "TIMEOUT"
    p.send_signal(signal.SIGTERM)
    try:
        p.communicate(timeout=4)
    except Exception:
        p.kill()
    os.unlink(f.name)
    if args.debug or not out or out == "TIMEOUT":
        logf.seek(0)
        log = logf.read()
        print("  --- xray client log ---")
        for ln in log.splitlines()[-12:]:
            print("   ", ln)
    logf.close()
    os.unlink(logf.name)

    country = ""
    try:
        country = json.loads(out).get("country", "")
    except Exception:
        pass
    verdict = ""
    if args.expect:
        verdict = "  => OK" if country == args.expect else f"  => MISMATCH (want {args.expect})"
    print("egress:", out or "(empty)", verdict)


if __name__ == "__main__":
    main()
