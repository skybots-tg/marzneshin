#!/usr/bin/env python3
"""Enumerate and probe entry->exit bridge hosts.

Runs ON THE PANEL. Every user-visible VPN location is a `hosts` row bound to
an `inbounds` row on a RU *entry* node. For "RU Direct" the entry node is also
the egress; for "RU->XX Bridge" the entry node tunnels out to a foreign *exit*
node. Either way the subscription hands the client exactly the parameters we
rebuild here, so probing them end-to-end answers the only question that
matters: does traffic actually come out the other side, and in which country.

`bridge_audit.py` is the CLI on top of this module.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional

import marz_common as mc

# A real service-1 user. Probing with a provisioned account (rather than an
# invented UUID) is what makes this an end-to-end check: xray rejects unknown
# clients, so a pass proves the panel->node user sync is intact too.
DEFAULT_USER = "68f85dea-ceeb-b5d3-d090-629fd5d52d65"

XRAY_BIN = "/tmp/xray_bridge_audit"

# Where the panel-side probe asks "which IP am I coming from". Two providers
# with different shapes so one being rate-limited does not fail the audit.
GEO_ENDPOINTS = [
    ("https://ipinfo.io/json", "ipinfo"),
    ("http://ip-api.com/json/?fields=status,countryCode,query", "ipapi"),
]

TIER_RE = {
    "universal": re.compile(r"UNIVERSAL\s+(\d+)", re.I),
    "elite": re.compile(r"ELITE\s+(\d+)", re.I),
    "fast": re.compile(r"FAST\s+(\d+)", re.I),
}

HOST_COLS = [
    "id", "remark", "address", "port", "sni", "fingerprint", "security",
    "reality_public_key", "reality_short_ids", "flow", "path", "host_network",
    "is_disabled", "weight",
]
INB_COLS = ["id", "tag", "config", "node_id", "exit_node_id"]
NODE_COLS = ["name", "address", "status"]


def _nv(x):
    return None if x in ("NULL", "", None) else x


def flag_to_iso(text: str) -> Optional[str]:
    """ISO2 of the first regional-indicator flag emoji in `text`."""
    ind = [chr(ord(c) - 0x1F1E6 + ord("A"))
           for c in text if 0x1F1E6 <= ord(c) <= 0x1F1FF]
    return "".join(ind[:2]) if len(ind) >= 2 else None


def exit_slot(remark: str) -> str:
    """The exit *slot* a remark advertises, e.g. 'FR-2', 'DE', 'RU'.

    Slot, not ISO: DE and DE-2 are distinct exit servers the user picks
    between, so the gap analysis must treat them as separate columns.
    """
    txt = remark
    for sep in ("\u267e\ufe0f", " - ", "\u2014"):
        if sep in txt:
            txt = txt.rsplit(sep, 1)[-1]
            break
    txt = re.sub(r"[^\x00-\x7f]", " ", txt)
    txt = re.sub(r"\[.*?\]|\(.*?\)|\bxhttp\b", " ", txt, flags=re.I)
    return re.sub(r"\s+", " ", txt).strip().upper() or "?"


def classify_tier(remark: str):
    for tier, pat in TIER_RE.items():
        m = pat.search(remark or "")
        if m:
            return tier, int(m.group(1))
    return None, None


@dataclass
class Target:
    """One probe-able (host, inbound) pair with its effective parameters."""
    host_id: int
    remark: str
    is_disabled: bool
    weight: int
    tier: str
    tier_index: int
    slot: str
    iso: Optional[str]

    inbound_id: int
    tag: str
    node_id: int
    node_name: str
    node_status: str
    exit_node_id: Optional[int]

    address: str
    port: Optional[int]
    network: str
    sni: str
    pbk: str
    sid: str
    fp: str
    flow: Optional[str]
    path: Optional[str]

    result: dict = field(default_factory=dict)

    @property
    def entry_key(self) -> str:
        return f"{self.tier}-{self.tier_index}"

    @property
    def is_bridge(self) -> bool:
        return "->" in self.tag

    @property
    def variant(self) -> str:
        return "xhttp" if self.network in ("xhttp", "splithttp") else "tcp"

    @property
    def label(self) -> str:
        return f"{self.entry_key}/{self.slot}/{self.variant}"

    def brief(self) -> dict:
        return {
            "host_id": self.host_id, "remark": self.remark,
            "is_disabled": self.is_disabled, "weight": self.weight,
            "tier": self.tier, "tier_index": self.tier_index,
            "entry_key": self.entry_key, "slot": self.slot, "iso": self.iso,
            "variant": self.variant, "inbound_id": self.inbound_id,
            "tag": self.tag, "node_id": self.node_id,
            "node_name": self.node_name, "node_status": self.node_status,
            "address": self.address, "port": self.port,
            "is_bridge": self.is_bridge, **self.result,
        }


def load_targets(tiers=("universal",), node_ids=None) -> list[Target]:
    """Read every host bound to an inbound and resolve its effective config.

    Host columns override the inbound's config JSON (that is exactly what the
    subscription builder does), so a probe fails for the same reason a user
    would fail.
    """
    sql = (
        "SELECT " + ", ".join(f"h.{c}" for c in HOST_COLS) + ", "
        + ", ".join(f"i.{c}" for c in INB_COLS) + ", "
        + ", ".join(f"n.{c}" for c in NODE_COLS) +
        " FROM hosts h JOIN inbounds i ON i.id = h.inbound_id "
        "JOIN nodes n ON n.id = i.node_id ORDER BY h.remark;"
    )
    out: list[Target] = []
    for row in mc.db_query(sql):
        if len(row) < len(HOST_COLS) + len(INB_COLS) + len(NODE_COLS):
            continue
        h = dict(zip(HOST_COLS, row))
        i = dict(zip(INB_COLS, row[len(HOST_COLS):]))
        n = dict(zip(NODE_COLS, row[len(HOST_COLS) + len(INB_COLS):]))

        tier, idx = classify_tier(h["remark"])
        if tier is None or tier not in tiers:
            continue
        if node_ids and int(i["node_id"]) not in node_ids:
            continue
        try:
            cfg = json.loads(i["config"])
        except Exception:
            cfg = {}

        sids = _nv(h["reality_short_ids"])
        host_sid = None
        if sids:
            try:
                parsed = json.loads(sids)
                if isinstance(parsed, list) and parsed:
                    host_sid = parsed[0]
            except Exception:
                host_sid = sids

        inb_sni = cfg.get("sni") or []
        network = _nv(h["host_network"]) or cfg.get("network") or "tcp"
        out.append(Target(
            host_id=int(h["id"]), remark=h["remark"],
            is_disabled=h["is_disabled"] == "1",
            weight=int(_nv(h["weight"]) or 0),
            tier=tier, tier_index=idx,
            slot=exit_slot(h["remark"]), iso=flag_to_iso(h["remark"]),
            inbound_id=int(i["id"]), tag=i["tag"], node_id=int(i["node_id"]),
            node_name=n["name"], node_status=n["status"],
            exit_node_id=int(i["exit_node_id"]) if _nv(i["exit_node_id"]) else None,
            address=h["address"] or n["address"],
            port=int(_nv(h["port"]) or cfg.get("port") or 0) or None,
            network=network,
            sni=_nv(h["sni"]) or (inb_sni[0] if inb_sni else ""),
            pbk=_nv(h["reality_public_key"]) or cfg.get("pbk") or "",
            sid=host_sid or cfg.get("sid") or "",
            fp=_nv(h["fingerprint"]) or cfg.get("fp") or "chrome",
            flow=_nv(h["flow"]) or cfg.get("flow"),
            path=_nv(h["path"]) or cfg.get("path"),
        ))
    return out


def ensure_xray() -> bool:
    """Copy the xray binary out of the local marznode container once."""
    if os.path.exists(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK):
        return True
    cn = subprocess.run(
        "docker ps --format '{{.Names}}' | grep -i marz | grep -vi db | head -1",
        shell=True, capture_output=True, text=True).stdout.strip()
    if not cn:
        return False
    subprocess.run(f"docker cp {cn}:/usr/local/bin/xray {XRAY_BIN}",
                   shell=True, capture_output=True)
    if os.path.exists(XRAY_BIN):
        os.chmod(XRAY_BIN, 0o755)
        return True
    return False


def build_client(t: Target, socks_port: int, user_uuid: str) -> dict:
    user = {"id": user_uuid, "encryption": "none"}
    stream = {
        "security": "reality",
        "realitySettings": {
            "serverName": t.sni, "fingerprint": t.fp or "chrome",
            "publicKey": t.pbk, "shortId": t.sid,
        },
    }
    if t.variant == "xhttp":
        stream["network"] = "xhttp"
        stream["xhttpSettings"] = {"mode": "auto", "path": t.path or "/"}
    else:
        stream["network"] = "tcp"
        if t.flow:
            user["flow"] = t.flow
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"tag": "s", "listen": "127.0.0.1", "port": socks_port,
                      "protocol": "socks", "settings": {"udp": False}}],
        "outbounds": [{
            "protocol": "vless", "tag": "p",
            "settings": {"vnext": [{"address": t.address, "port": t.port,
                                    "users": [user]}]},
            "streamSettings": stream,
        }],
    }


def _parse_geo(raw: str, shape: str):
    try:
        d = json.loads(raw)
    except Exception:
        return None, None
    if shape == "ipinfo":
        return d.get("country"), d.get("ip")
    if d.get("status") == "success":
        return d.get("countryCode"), d.get("query")
    return None, None


def _probe_once(t: Target, socks_port: int, user_uuid: str, timeout: int):
    cfg = build_client(t, socks_port, user_uuid)
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(cfg, f)
    f.close()
    logf = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
    p = subprocess.Popen([XRAY_BIN, "run", "-c", f.name],
                         stdout=logf, stderr=subprocess.STDOUT, text=True)
    time.sleep(1.8)
    country = ip = None
    started = time.time()
    try:
        if p.poll() is not None:
            logf.seek(0)
            return {"verdict": "fail", "error": "xray_client_exited",
                    "detail": logf.read()[-300:]}
        for url, shape in GEO_ENDPOINTS:
            try:
                r = subprocess.run(
                    ["curl", "-s", "--socks5-hostname",
                     f"127.0.0.1:{socks_port}", "--max-time", str(timeout), url],
                    capture_output=True, text=True, timeout=timeout + 5)
            except subprocess.TimeoutExpired:
                continue
            country, ip = _parse_geo(r.stdout.strip(), shape)
            if country:
                break
    finally:
        p.send_signal(signal.SIGTERM)
        try:
            p.communicate(timeout=4)
        except Exception:
            p.kill()
        logf.seek(0)
        tail = logf.read()[-400:]
        logf.close()
        for path in (f.name, logf.name):
            try:
                os.unlink(path)
            except OSError:
                pass

    elapsed = round(time.time() - started, 1)
    if not country:
        return {"verdict": "fail", "error": "no_egress", "detail": tail,
                "elapsed": elapsed}
    return {"verdict": "pass", "country": country, "egress_ip": ip,
            "elapsed": elapsed}


def probe(t: Target, socks_port: int, user_uuid: str = DEFAULT_USER,
          timeout: int = 12, attempts: int = 2) -> dict:
    """Probe one target, retrying transient failures.

    Verdicts:
      pass       traffic flows and the egress country matches the remark
      wrong_geo  traffic flows but exits in an unexpected country
      fail       no traffic at all
      skip       the row is not probe-able (missing reality parameters)
    """
    if not t.port or not t.pbk:
        return {"verdict": "skip", "error": "incomplete_config"}

    res = {}
    for n in range(attempts):
        res = _probe_once(t, socks_port, user_uuid, timeout)
        if res["verdict"] == "pass":
            break
        if n + 1 < attempts:
            time.sleep(1.5)
    res["attempts"] = n + 1

    if res["verdict"] != "pass":
        return res
    got, want = res.get("country"), t.iso
    if want and got != want:
        # FI/EE/NL exits sit on providers whose geo-IP disagrees with the
        # label; traffic still flows, so this is a warning, not an outage.
        res["verdict"] = "wrong_geo"
        res["expected_country"] = want
    if t.is_bridge and res.get("country") == "RU":
        res["verdict"] = "fail"
        res["error"] = "ru_leak"
        res["detail"] = "bridge egress stayed in RU (routing rule missing)"
    return res
