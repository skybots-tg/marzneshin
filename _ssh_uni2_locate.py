"""Locate UNIVERSAL 2: which node, hosts, xray config status, external probes."""
import socket, sys, paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("195.54.170.162", username="root", password="Q62DHgbuQT", timeout=30)
sftp = c.open_sftp()
script = (
    "import asyncio, json\n"
    "from app.db import GetDB, get_tls_certificate\n"
    "from app.db.models import Node, InboundHost, Inbound, Service\n"
    "from app.marznode.grpclib import MarzNodeGRPCLIB\n"
    "from sqlalchemy import or_\n"
    "\n"
    "async def main():\n"
    "    with GetDB() as db:\n"
    "        print('=== Nodes matching UNIVERSAL 2 ===')\n"
    "        nodes = db.query(Node).filter(Node.name.like('%UNIVERSAL 2%')).all()\n"
    "        for n in nodes:\n"
    "            print(f'  id={n.id} name={n.name!r} addr={n.address} port={n.port} status={n.status}')\n"
    "\n"
    "        print()\n"
    "        print('=== Hosts matching UNIVERSAL 2 ===')\n"
    "        hosts = db.query(InboundHost).filter(InboundHost.remark.like('%UNIVERSAL 2%')).order_by(InboundHost.weight).all()\n"
    "        addrs = set()\n"
    "        ports = set()\n"
    "        for h in hosts:\n"
    "            addrs.add(h.address)\n"
    "            ports.add(h.port)\n"
    "            print(f'  id={h.id} weight={h.weight} addr={h.address} port={h.port} disabled={h.is_disabled} universal={h.universal} sni={h.sni!r} fp={h.fingerprint} hp={h.host_protocol} flow={h.flow} pbk={(h.reality_public_key or \"\")[:18]}... sids={h.reality_short_ids} remark={h.remark!r}')\n"
    "        print(f'  -> distinct addresses: {sorted(addrs)} ports: {sorted([p for p in ports if p])}')\n"
    "\n"
    "        target_node = None\n"
    "        for n in nodes:\n"
    "            target_node = n\n"
    "            break\n"
    "        if not target_node and addrs:\n"
    "            for a in addrs:\n"
    "                if a:\n"
    "                    cand = db.query(Node).filter(Node.address == a).first()\n"
    "                    if cand:\n"
    "                        target_node = cand\n"
    "                        break\n"
    "        cert = get_tls_certificate(db)\n"
    "        if target_node:\n"
    "            print(f'\\n=== probing live xray on node id={target_node.id} addr={target_node.address} ===')\n"
    "            node = MarzNodeGRPCLIB(target_node.id, target_node.address, target_node.port, cert.key, cert.certificate)\n"
    "            try:\n"
    "                stats = await asyncio.wait_for(node.get_backend_stats('xray'), timeout=15)\n"
    "                print(f'  xray stats: {stats}')\n"
    "            except Exception as e:\n"
    "                print(f'  get_backend_stats failed: {type(e).__name__}: {e}')\n"
    "            try:\n"
    "                cfg_str, _ = await asyncio.wait_for(node.get_backend_config('xray'), timeout=15)\n"
    "                cfg = json.loads(cfg_str)\n"
    "                inb = sorted([(ib.get('port'), ib.get('tag')) for ib in cfg.get('inbounds', [])])\n"
    "                ob = [(o.get('tag'), o.get('protocol')) for o in cfg.get('outbounds', [])]\n"
    "                print(f'  inbounds: {inb}')\n"
    "                print(f'  outbounds: {ob}')\n"
    "                print(f'  routing rules: {len((cfg.get(\"routing\") or {}).get(\"rules\") or [])}')\n"
    "            except Exception as e:\n"
    "                print(f'  get_backend_config failed: {type(e).__name__}: {e}')\n"
    "        else:\n"
    "            print('No node match for UNIVERSAL 2 in panel DB.')\n"
    "\n"
    "asyncio.run(main())\n"
)
with sftp.open("/tmp/_uni2.py", "wb") as f:
    f.write(script.encode("utf-8"))
sftp.close()
_, so, _ = c.exec_command("docker cp /tmp/_uni2.py marzneshin-marzneshin-1:/tmp/_uni2.py", timeout=20)
so.channel.recv_exit_status()
_, so, _ = c.exec_command(
    "docker exec marzneshin-marzneshin-1 bash -c 'cd /app && PYTHONPATH=/app python -u /tmp/_uni2.py' 2>&1",
    timeout=60,
)
out = so.read().decode(errors="replace")
sys.stdout.buffer.write(out.encode("utf-8"))

import re
ips = sorted(set(re.findall(r"(\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b)", out)))
ports = sorted(set(int(x) for x in re.findall(r"port=(\d+)", out)))
print("\n--- external TCP probe of all UNIVERSAL 2 host ip:port pairs ---")
for ip in ips:
    if ip in ("127.0.0.1", "0.0.0.0", "195.54.170.162"):
        continue
    for p in ports:
        s = socket.socket(); s.settimeout(4)
        try:
            s.connect((ip, p))
            try:
                s.send(b"\x16\x03\x01\x00\x05\x00\x00\x00\x00\x00")
                data = s.recv(64)
                print(f"  {ip}:{p} -> CONNECT OK, server sent {len(data)} bytes")
            except Exception as e2:
                print(f"  {ip}:{p} -> CONNECT OK, no read ({e2})")
        except Exception as e:
            print(f"  {ip}:{p} -> FAIL ({e})")
        finally:
            s.close()
c.close()
