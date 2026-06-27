#!/usr/bin/env python3
"""Runs ON a node. Spins an xray client to an FR exit via the exact fr-out params
and reports the egress IP/country. Args: <fr_ip> <fr_port> <uuid>."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

FR_IP, FR_PORT, UUID = sys.argv[1], int(sys.argv[2]), sys.argv[3]
PBK = "YNwi7rTLFpF27P1EJuurcoICSmvLm4iLkFKwHgXm7CQ"
SID = "3333333333333333"
SNI = "apple.com"

# locate xray (marznode container)
xray_local = None
for c in ("which xray", "ls /usr/local/bin/xray 2>/dev/null"):
    r = subprocess.run(c, shell=True, capture_output=True, text=True)
    if r.stdout.strip().startswith("/") and os.path.exists(r.stdout.strip().splitlines()[0]):
        xray_local = r.stdout.strip().splitlines()[0]
        break
if not xray_local:
    cn = subprocess.run("docker ps --format '{{.Names}}' | grep -i marz | head -1",
                        shell=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(f"docker cp {cn}:/usr/local/bin/xray /tmp/xrt", shell=True)
    xray_local = "/tmp/xrt"
print("xray:", xray_local)

socks = 10899
cfg = {"log": {"loglevel": "warning"},
       "inbounds": [{"tag": "s", "listen": "127.0.0.1", "port": socks,
                     "protocol": "socks", "settings": {"udp": True}}],
       "outbounds": [{"protocol": "vless", "tag": "proxy",
                      "settings": {"vnext": [{"address": FR_IP, "port": FR_PORT,
                                              "users": [{"id": UUID, "flow": "xtls-rprx-vision",
                                                         "encryption": "none"}]}]},
                      "streamSettings": {"network": "tcp", "security": "reality",
                                         "realitySettings": {"serverName": SNI, "fingerprint": "chrome",
                                                             "publicKey": PBK, "shortId": SID}}}]}
f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
json.dump(cfg, f); f.close()
proc = subprocess.Popen([xray_local, "run", "-c", f.name],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(2.5)
try:
    r = subprocess.run(["curl", "-s", "--socks5-hostname", f"127.0.0.1:{socks}",
                        "--max-time", "15", "https://ipinfo.io/json"],
                       capture_output=True, text=True, timeout=20)
    print("egress:", r.stdout.strip() or "(empty / no route -> user NOT provisioned or hop dead)")
except subprocess.TimeoutExpired:
    print("egress: TIMEOUT (no route)")
proc.send_signal(signal.SIGTERM)
try:
    log, _ = proc.communicate(timeout=4)
except Exception:
    proc.kill(); log = ""
os.unlink(f.name)
if "egress:" and (not log or True):
    print("xray-log:", (log or "").strip()[-400:])
