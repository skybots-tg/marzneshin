---
name: marzneshin-deploy
description: Deploy and manage the Marzneshin VPN panel. Use when deploying code changes to the production server, managing nodes/hosts/inbounds via the database, restarting services, or troubleshooting the deployment pipeline. Always read before any server-side operations.
---

# Marzneshin Deployment & Server Operations

## Production Server

- **IP**: 195.54.170.162
- **User**: root
- **Password**: Q62DHgbuQT
- **SSH MCP**: use `user-ssh` MCP if configured, otherwise use paramiko from Python (Windows host has no `sshpass`)

## Architecture

```
┌─────────────────────────────────────────────────┐
│  195.54.170.162  (Production Panel Server)       │
│                                                   │
│  Docker services (docker compose):                │
│    marzneshin-marzneshin-1  — panel + API         │
│      image: skybots/marzneshin:fork               │
│      build context: /opt/marzneshin               │
│      Dockerfile: Dockerfile.preview               │
│      network_mode: host                           │
│      port: 40215 (UVICORN_PORT, behind nginx)     │
│                                                   │
│    marzneshin-db-1  — MariaDB                     │
│      image: mariadb:latest                        │
│      port: 127.0.0.1:3306                         │
│      root password: 12341234                      │
│      database: marzneshin                         │
│                                                   │
│    marznode (local)  — dawsh/marznode:latest       │
│      xray config: /var/lib/marznode/xray_config   │
│                                                   │
│  + remote marznodes on each VPN node server       │
└─────────────────────────────────────────────────┘
```

## Git Repository

- **Remote**: https://github.com/skybots-tg/marzneshin.git
- **Branch**: master
- **Local clone on server**: /opt/marzneshin

## Deploying Code Changes

### The `umarz` Command

Located at `/usr/local/bin/umarz`. This is the standard way to deploy:

```bash
ssh root@195.54.170.162
umarz
```

What `umarz` does:
1. `cd /opt/marzneshin && git pull --ff-only`
2. Checks if rebuild is needed (changes in Dockerfile, requirements.txt, app/, dashboard/, main.py)
3. If rebuild needed: `docker compose build marzneshin && docker compose up -d marzneshin`
4. If no rebuild needed: `docker compose up -d marzneshin`
5. Healthcheck with 60s timeout
6. Auto-rollback on failure (tags previous image as `marzneshin:rollback`)
7. Logs to `/var/log/umarz.log`

### Compose File Locations

- **Source (git)**: /opt/marzneshin/docker-compose.yml — NOT used for production
- **Production**: /etc/opt/marzneshin/docker-compose.yml — this is what `umarz` uses
  - Has MariaDB service, build context, volume mounts for patches
  - Image name: `skybots/marzneshin:fork`

### Workflow: Push Code → Deploy

```bash
# 1. On local machine (Windows):
git add <files> && git commit -m "feat: ..." && git push

# 2. On server (via SSH):
umarz
```

Or from local machine via paramiko:
```python
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('195.54.170.162', username='root', password='Q62DHgbuQT')
stdin, stdout, stderr = ssh.exec_command('umarz', timeout=120)
print(stdout.read().decode())
ssh.close()
```

## Database Access

### Direct SQL via Docker

```bash
docker exec marzneshin-db-1 mariadb -u root -p12341234 -e "SQL_HERE"
```

### Key Tables

- **nodes** — VPN node servers (id, name, address, port, status)
- **inbounds** — xray inbound configs per node (id, tag, protocol, config JSON, node_id)
- **hosts** — proxy endpoints for subscriptions (remark, address, port, sni, fingerprint, reality keys, etc.)
- **hosts_services** / **inbounds_services** — link hosts/inbounds to services
- **users** — VPN users

### Common Queries

```sql
-- List all nodes
SELECT id, name, address, status FROM nodes ORDER BY id;

-- Find hosts by name pattern
SELECT id, remark, address, port, sni, fingerprint, is_disabled
FROM hosts WHERE remark LIKE '%Elite%' ORDER BY id;

-- Get inbounds for a node
SELECT id, tag, protocol, config FROM inbounds WHERE node_id = 32;

-- Update host fingerprint
UPDATE hosts SET fingerprint = 'firefox' WHERE id = 233;
```

### Fingerprint Enum Values
none, chrome, firefox, safari, ios, android, edge, 360, qq, random, randomized

### Security Enum Values
inbound_default, none, tls

## Node Server Naming Convention

- **UNIVERSAL** nodes — general-purpose VPN nodes
- **ELITE** nodes — premium nodes (Yandex.Cloud, etc.) with Reality masking
- **VK-1** — VK Cloud node
- Bridge inbounds: `RU->XX Bridge` — traffic enters through RU node, exits through XX country

## Masking (Reality) Configuration

Hosts in the `hosts` table have these Reality-related fields:
- `sni` — TLS Server Name Indication (what domain the connection pretends to be)
- `fingerprint` — TLS fingerprint (chrome/firefox/etc.)
- `reality_public_key` — overrides inbound's `pbk` if set
- `reality_short_ids` — JSON list, overrides inbound's `sid` if set
- `flow` — e.g. `xtls-rprx-vision`
- `security` — `inbound_default` inherits from inbound, or `tls`/`none`

If host-level fields are NULL/empty, values fall back to the inbound's config JSON.

## Important Paths on Server

- `/opt/marzneshin/` — git repo (code)
- `/etc/opt/marzneshin/` — production docker-compose.yml + .env
- `/var/lib/marzneshin/` — panel data, DB files
- `/var/lib/marznode/` — marznode data, xray_config.json
- `/usr/local/bin/umarz` — deploy script
- `/var/log/umarz.log` — deploy log

## SSH from Windows

Use the native `ssh` command with the configured host alias `vpn_norway` (see `~/.ssh/config`):

```powershell
ssh vpn_norway "your command here"
```

The alias `vpn_norway` points to 195.54.170.162 with key `~/.ssh/vpn_norway`.

**NEVER use paramiko or passwords** — SSH keys are configured and work out of the box.

## Restarting Services

```bash
# Restart panel only
cd /etc/opt/marzneshin && docker compose restart marzneshin

# Full rebuild + restart
cd /etc/opt/marzneshin && docker compose build marzneshin && docker compose up -d marzneshin

# Restart marznode (local)
cd /etc/opt/marzneshin && docker compose restart marznode

# View logs
docker logs marzneshin-marzneshin-1 --tail 100 -f
```
