#!/usr/bin/env python3
"""Run ON panel. Full user-facing E2E: connect as a real service-1 user to U4's
RU->FR Bridge inbound (:9443) and report egress IP + country (expect FR)."""
import base64
import json
import os
import signal
import subprocess
import tempfile
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
U4 = "45.150.239.178"
REAL_SVC1 = "68f85dea-ceeb-b5d3-d090-629fd5d52d65"   # user26 test_ru_direct


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


cfg = json.loads(subprocess.run(SSH + [f"root@{U4}", "cat /var/lib/marznode/xray_config.json"],
                                capture_output=True, text=True, timeout=25).stdout)
ib = next(i for i in cfg["inbounds"] if i.get("tag") == "RU->FR Bridge")
rs = ib["streamSettings"]["realitySettings"]
raw = base64.urlsafe_b64decode(rs["privateKey"] + "=" * (-len(rs["privateKey"]) % 4))
pub = b64u(X25519PrivateKey.from_private_bytes(raw).public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw))
sni = rs["serverNames"][0]
sid = rs["shortIds"][0]
port = ib["port"]
print(f"U4 RU->FR Bridge :{port} pub={pub} sni={sni} sid={sid}")

# locate xray on panel's local marznode
cn = subprocess.run("docker ps --format '{{.Names}}'|grep -i marz|head -1",
                    shell=True, capture_output=True, text=True).stdout.strip()
subprocess.run(f"docker cp {cn}:/usr/local/bin/xray /tmp/xrt", shell=True)

client = {"log": {"loglevel": "warning"},
          "inbounds": [{"tag": "s", "listen": "127.0.0.1", "port": 10905,
                        "protocol": "socks", "settings": {"udp": True}}],
          "outbounds": [{"protocol": "vless", "tag": "p",
                         "settings": {"vnext": [{"address": U4, "port": port,
                                                 "users": [{"id": REAL_SVC1, "flow": "xtls-rprx-vision",
                                                            "encryption": "none"}]}]},
                         "streamSettings": {"network": "tcp", "security": "reality",
                                            "realitySettings": {"serverName": sni, "fingerprint": "chrome",
                                                                "publicKey": pub, "shortId": sid}}}]}
f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
json.dump(client, f); f.close()
p = subprocess.Popen(["/tmp/xrt", "run", "-c", f.name],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(2.5)
try:
    r = subprocess.run(["curl", "-s", "--socks5-hostname", "127.0.0.1:10905",
                        "--max-time", "15", "https://ipinfo.io/json"],
                       capture_output=True, text=True, timeout=20)
    print("E2E egress:", r.stdout.strip() or "(empty/no route)")
except subprocess.TimeoutExpired:
    print("E2E egress: TIMEOUT")
p.send_signal(signal.SIGTERM)
try:
    p.communicate(timeout=4)
except Exception:
    p.kill()
os.unlink(f.name)
