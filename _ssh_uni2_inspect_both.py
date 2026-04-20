"""SSH into both UNIVERSAL 2 servers (.98 and .99), inspect xray container,
ports, and live config. Goal: understand why .98 is broken and prepare a sync.
"""
import paramiko, sys

SERVERS = [
    ("84.252.101.99", "BtvrxdCDKcG9", "PRIMARY (in panel as node 16)"),
    ("84.252.101.98", "h0Qv14nCvjg5", "SECONDARY (orphan)"),
]

def run(host, password, label):
    print("\n" + "=" * 70)
    print(f"=== {label} :: {host} ===")
    print("=" * 70)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(host, username="root", password=password, timeout=20)
    except Exception as e:
        print(f"  SSH connect FAILED: {e}")
        return
    cmds = [
        ("docker ps", "docker ps --format '{{.Names}}\\t{{.Image}}\\t{{.Status}}'"),
        ("listening ports (xray candidates)", "ss -lntp 2>/dev/null | awk 'NR==1 || $4 ~ /:(444|8443|8444|8449|8450|9443|9444|11443|14443|15443|16443|44433|44434|55443)$/'"),
        ("net interfaces (ip addrs)", "ip -4 addr | awk '/inet /{print $2, $NF}'"),
        ("docker compose location", "find / -maxdepth 5 -name docker-compose.yml -path '*marz*' 2>/dev/null"),
        ("xray config snippet (first inbound)", "find /var/lib/marznode /opt /root -maxdepth 6 -name 'xray*.json' 2>/dev/null | head -3 ; echo --- ; for f in $(find /var/lib/marznode /opt /root -maxdepth 6 -name 'xray*.json' 2>/dev/null | head -1); do echo FILE=$f; head -80 \"$f\"; done"),
        ("marznode logs (last 15 lines)", "for n in $(docker ps --format '{{.Names}}' | grep -i marz | head -1); do echo CONTAINER=$n; docker logs --tail 15 $n 2>&1; done"),
    ]
    for label2, cmd in cmds:
        print(f"\n--- {label2} ---")
        try:
            _, so, _ = c.exec_command(cmd, timeout=30)
            data = so.read().decode(errors="replace").strip()
            print(data if data else "(empty)")
        except Exception as e:
            print(f"  exec error: {e}")
    c.close()


for host, pw, label in SERVERS:
    run(host, pw, label)
