#!/usr/bin/env python3
"""Перепись подключений по портам xray на ноде (входной или выходной).

Считаем не байты, а КТО дотянулся: раз в минуту снимаем established-сокеты,
группируем по локальному порту и храним хэши адресов-источников. Хэш, а не
адрес: для вывода «на 443 пришли те, кого нет на высоких портах» достаточно
множеств, а хранить чужие IP на ноде незачем.

Пишет одну JSON-строку на срез в /var/log/port_census.jsonl. Порт — это
конкретный хост подписки, подсеть /24 — оператор и регион клиента, число
срезов — сколько минут соединение держалось. Из этого vpn_project собирает
«у какого оператора в каком регионе какой сервер работает» — для меток в
приложении и для ИИ-поддержки.

Ставится на весь парк `port_census_install.py`: systemd-служба и logrotate
(сутки, три поколения; вчерашний файл остаётся несжатым, его дочитывает сбор).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections import defaultdict

OUT = "/var/log/port_census.jsonl"
SALT = "port-census-2026-09"
INTERVAL = 60
# 0 — без срока: так её запускает служба. Срок был нужен, пока перепись
# жила разовым опытом в nohup и сама должна была остановиться.
DURATION = int(os.environ.get("CENSUS_DURATION", 0))

# С фильтром state колонка State не печатается: Recv-Q Send-Q Local Peer.
def _split_addr(token: str) -> tuple[str, int] | None:
    host, sep, port = token.rpartition(":")
    if not sep or not port.isdigit():
        return None
    return host.strip("[]"), int(port)


def listening_ports() -> set[int]:
    """Порты, которые слушает именно xray.

    Раньше брали все слушающие: тогда в перепись попадали служебные порты
    агента ноды, и в метках появлялись «серверы», которых у клиента нет.
    """
    out = subprocess.run(
        ["ss", "-lntp"], capture_output=True, text=True, timeout=30,
    ).stdout
    ports = set()
    for line in out.splitlines()[1:]:
        if "xray" not in line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        addr = _split_addr(parts[3])
        if not addr or addr[1] == 22:
            continue
        # API xray слушает на loopback — это не вход для клиентов
        if addr[0].startswith("127.") or addr[0] in ("::1", "localhost"):
            continue
        ports.add(addr[1])
    return ports


def snapshot(inbound_ports: set[int]) -> dict[int, set[str]]:
    out = subprocess.run(
        ["ss", "-tn", "state", "established"],
        capture_output=True, text=True, timeout=30,
    ).stdout
    by_port: dict[int, set[str]] = defaultdict(set)
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        local = _split_addr(parts[2])
        peer = _split_addr(parts[3])
        if not local or not peer or local[1] not in inbound_ports:
            continue
        by_port[local[1]].add(peer[0])
    return by_port


def digest(addr: str) -> str:
    return hashlib.sha256((SALT + addr).encode()).hexdigest()[:16]


def net24(addr: str) -> str:
    """Подсеть /24 вместо адреса: оператора по ней видно, человека — нет."""
    parts = addr.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0/24"
    return addr.rsplit(":", 1)[0] + "::/64"


def main() -> None:
    deadline = time.time() + DURATION if DURATION else None
    while deadline is None or time.time() < deadline:
        started = time.time()
        try:
            by_port = snapshot(listening_ports())
            row = {
                "ts": int(started),
                "ports": {
                    str(p): {
                        "conns": len(peers),
                        "peers": sorted(digest(a) for a in peers),
                        "nets": sorted({net24(a) for a in peers}),
                    }
                    for p, peers in sorted(by_port.items())
                },
            }
            with open(OUT, "a") as f:
                f.write(json.dumps(row) + "\n")
        except Exception as e:  # перепись не должна падать из-за одного среза
            with open(OUT, "a") as f:
                f.write(json.dumps({"ts": int(started), "error": repr(e)[:200]}) + "\n")
        time.sleep(max(1, INTERVAL - (time.time() - started)))


if __name__ == "__main__":
    main()
