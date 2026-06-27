#!/usr/bin/env python3
"""Run ON panel. For each (exit_ip, port): pull exit config, derive reality pub from
the inbound privkey, then from U4 spin an xray client (bridge user) to that exit and
report egress. Compares a known-good bridge (GE) vs FR."""
import base64
import json
import subprocess

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

KEY = "/root/.ssh/vpn_node_default"
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-i", KEY]
U4 = "45.150.239.178"
BRIDGE_UUID = "91040b97-0a20-6eac-dfb7-f4b4e56ecf42"

TARGETS = [("GE node27", "93.123.85.191", 50443),
           ("FR node23", "132.243.204.182", 44443),
           ("FR node14", "132.243.204.199", 47443)]


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def pull(ip):
    return json.loads(subprocess.run(SSH + [f"root@{ip}", "cat /var/lib/marznode/xray_config.json"],
                                     capture_output=True, text=True, timeout=25).stdout)


def pub_from_priv(priv_b64):
    raw = base64.urlsafe_b64decode(priv_b64 + "=" * (-len(priv_b64) % 4))
    sk = X25519PrivateKey.from_private_bytes(raw)
    return b64u(sk.public_key().public_bytes(serialization.Encoding.Raw,
                                             serialization.PublicFormat.Raw))


CLIENT_TPL = r'''
import json,os,signal,subprocess,tempfile,time
cn=subprocess.run("docker ps --format '{{.Names}}'|grep -i marz|head -1",shell=True,capture_output=True,text=True).stdout.strip()
subprocess.run(f"docker cp {cn}:/usr/local/bin/xray /tmp/xrt",shell=True)
cfg=%s
f=tempfile.NamedTemporaryFile("w",suffix=".json",delete=False);json.dump(cfg,f);f.close()
p=subprocess.Popen(["/tmp/xrt","run","-c",f.name],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
time.sleep(2.5)
try:
    r=subprocess.run(["curl","-s","--socks5-hostname","127.0.0.1:10901","--max-time","12","https://ipinfo.io/json"],capture_output=True,text=True,timeout=18)
    print("EGRESS:",r.stdout.strip() or "(empty/no-route)")
except Exception as e:
    print("EGRESS: TIMEOUT")
p.send_signal(signal.SIGTERM)
try:p.communicate(timeout=4)
except Exception:p.kill()
'''

for name, ip, port in TARGETS:
    cfg = pull(ip)
    ib = next((i for i in cfg["inbounds"] if i.get("port") == port), None)
    if not ib:
        print(f"{name}: no inbound on :{port}"); continue
    rs = ib["streamSettings"]["realitySettings"]
    pub = pub_from_priv(rs["privateKey"])
    sni = rs["serverNames"][0]
    sid = rs["shortIds"][0]
    client = {"log": {"loglevel": "warning"},
              "inbounds": [{"tag": "s", "listen": "127.0.0.1", "port": 10901,
                            "protocol": "socks", "settings": {"udp": True}}],
              "outbounds": [{"protocol": "vless", "tag": "p",
                             "settings": {"vnext": [{"address": ip, "port": port,
                                                     "users": [{"id": BRIDGE_UUID, "flow": "xtls-rprx-vision",
                                                                "encryption": "none"}]}]},
                             "streamSettings": {"network": "tcp", "security": "reality",
                                                "realitySettings": {"serverName": sni, "fingerprint": "chrome",
                                                                    "publicKey": pub, "shortId": sid}}}]}
    script = CLIENT_TPL % json.dumps(client)
    r = subprocess.run(SSH + [f"root@{U4}", "python3 -"], input=script,
                       capture_output=True, text=True, timeout=60)
    line = next((l for l in r.stdout.splitlines() if l.startswith("EGRESS:")), r.stdout.strip()[:120])
    print(f"{name} ({ip}:{port}) pub={pub[:10]}.. sni={sni} sid={sid}")
    print(f"   {line}")
