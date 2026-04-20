"""Restart marznode on .98 (which will start xray with the on-disk config),
then verify ports listen + diagnose why xray was stopped earlier.
"""
import paramiko, sys, time, socket

NODE = "84.252.101.98"
PASS = "h0Qv14nCvjg5"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(NODE, username="root", password=PASS, timeout=30)

print("=== docker restart marznode container on .98 ===")
_, so, _ = c.exec_command(
    "docker restart $(docker ps --format '{{.Names}}' | grep -i marz | head -1) 2>&1",
    timeout=60,
)
print(so.read().decode(errors="replace"))

print("\n=== wait 15s for xray to come up ===")
time.sleep(15)

print("=== ports listening now ===")
_, so, _ = c.exec_command(
    "ss -lntp 2>/dev/null | awk 'NR==1 || $4 ~ /:(8443|8444|8449|8450|9443|9444|44433|44434)$/'",
    timeout=20,
)
print(so.read().decode(errors="replace"))

print("=== last 30 marznode log lines ===")
_, so, _ = c.exec_command(
    "docker logs --tail 30 $(docker ps --format '{{.Names}}' | grep -i marz | head -1) 2>&1",
    timeout=20,
)
print(so.read().decode(errors="replace"))

c.close()

print("\n=== external probe of .98 ports ===")
for p in [8443, 8444, 8449, 8450, 9443, 9444, 44433, 44434]:
    s = socket.socket(); s.settimeout(4)
    try:
        s.connect((NODE, p))
        s.send(b"\x16\x03\x01\x00\x05\x00\x00\x00\x00\x00")
        data = s.recv(64)
        print(f"  {NODE}:{p} -> CONNECT OK, server sent {len(data)} bytes")
    except socket.timeout:
        print(f"  {NODE}:{p} -> CONNECT OK, no read (timed out)")
    except Exception as e:
        print(f"  {NODE}:{p} -> FAIL ({e})")
    finally:
        s.close()
