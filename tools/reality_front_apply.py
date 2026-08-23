#!/usr/bin/env python3
"""Run ON the panel. Change what a bridge exit pretends to be.

An exit's disguise is a server-side matter end to end, which is what makes it
safe to touch: the REALITY handshake to an exit is made by the *entry* node's
outbound, not by anybody's phone. Every entry in the fleet sends the same
``serverName`` -- measured, not assumed: 13-14 outbounds per node, all
``apple.com`` -- so nothing on a user's device is involved and nothing has to
wait for a subscription to be re-read.

Two actions, and they are different in kind.

``--prune`` drops the names no peer ever sends. The foreign exits accept seven,
of which five (``microsoft.com``, ``www.microsoft.com``, ``dl.google.com``,
``api-maps.yandex.ru``, ``www.googletagmanager.com``) are dead weight: every
entry sends ``apple.com``, so removing them cannot break a handshake anybody
makes.

This is tidying, not a fix, and the distinction was worth measuring rather than
reasoning about. A prober gets ``dest``'s certificate back whatever name it
sends -- ``example.org`` and an invented name both returned ``www.apple.com``
from an exit that never listed either -- because REALITY relays anything it
cannot authenticate. So the list is not what a prober sees, and shortening it
buys clarity, nothing more. What a prober does see is the disguise itself: a
name whose real addresses are nowhere near this one, which is what ``--front``
is for.

``--front`` moves the disguise to another domain, in three phases, because the
list is what the server *accepts*: adding a name is safe, removing one refuses
every peer still sending it.

    phase 1  add the new name to the exit                (both accepted)
    phase 2  point the entries' outbounds at the new name (traffic moves)
    phase 3  drop the old name and repoint ``dest``       (disguise complete)

Nothing is applied without ``--apply``; without it the exact before/after is
printed. Candidates come from reality_front_probe.py -- and are re-checked here
from the exit itself before phase 1, because a ``dest`` that cannot do TLS 1.3
with X25519 and h2 takes the whole exit down for everyone.

usage:
    reality_front_apply.py --exit 212.192.11.201 --prune
    reality_front_apply.py --exit 212.192.11.201 --front www.allegro.pl --phase 1
    reality_front_apply.py --exit 212.192.11.201 --front www.allegro.pl --phase 1 --apply
"""
import argparse
import json
import sys

import marz_common as mc
# Одна и та же функция на оба инструмента: пробник считал www.allegro.pl
# годным по wildcard *.allegro.pl, а здесь простое вхождение подстроки
# забраковало корректную смену. Двум инструментам, которые обязаны сходиться
# в ответе «покрывает ли сертификат имя», нельзя иметь две реализации.
from reality_front_probe import covers

# The entry fleet: nodes whose outbounds carry traffic into the exits. Read from
# the database rather than hard-coded, so a new entry cannot be forgotten.
ENTRY_SQL = ("SELECT DISTINCT n.address FROM nodes n JOIN inbounds i "
             "ON i.node_id = n.id WHERE n.address IS NOT NULL;")

CHECK = r"""
d=%s
out=$(echo | openssl s_client -connect "$d:443" -servername "$d" -tls1_3 -alpn h2 2>/dev/null)
printf 'cipher=%%s\n' "$(printf '%%s' "$out" | sed -n 's/^New, TLSv1.3, Cipher is \(.*\)$/\1/p' | head -1)"
printf 'group=%%s\n' "$(printf '%%s' "$out" | sed -n 's/^Server Temp Key: \(.*\)$/\1/p' | head -1)"
printf 'alpn=%%s\n' "$(printf '%%s' "$out" | sed -n 's/^ALPN protocol: \(.*\)$/\1/p' | head -1)"
printf 'names=%%s\n' "$(printf '%%s' "$out" | openssl x509 -noout -subject -ext subjectAltName 2>/dev/null | tr -d ' ' | tr '\n' ',')"
"""


def entries():
    return [r[0] for r in mc.db_query(ENTRY_SQL) if r[0]]


def sent_names(entry_ips, exit_ip):
    """serverName values the entries actually send to this exit, and the tags."""
    names, tags = set(), {}
    for ip in entry_ips:
        try:
            cfg = mc.node_cfg(ip)
        except RuntimeError as e:
            print(f"  ! вход {ip} недоступен: {e}", file=sys.stderr)
            continue
        for o in cfg.get("outbounds", []):
            s = (o.get("settings") or {})
            vnext = (s.get("vnext") or s.get("servers") or [{}])
            if (vnext[0] or {}).get("address") != exit_ip:
                continue
            rs = ((o.get("streamSettings") or {}).get("realitySettings") or {})
            if rs.get("serverName"):
                names.add(rs["serverName"])
                tags.setdefault(ip, []).append(o.get("tag"))
    return names, tags


def verify_front(exit_ip, domain):
    """Refuse a dest the exit cannot actually complete a handshake with."""
    r = mc.ssh(exit_ip, CHECK % domain, timeout=40)
    got = dict(
        line.split("=", 1) for line in r.stdout.splitlines() if "=" in line
    )
    ok_tls = bool(got.get("cipher", "").strip())
    x25519 = "x25519" in got.get("group", "").lower()
    h2 = got.get("alpn", "").strip() == "h2"
    covered = covers(domain, got.get("names", ""))
    problems = [
        name for name, good in (
            ("TLS 1.3", ok_tls), ("X25519", x25519),
            ("h2", h2), ("сертификат покрывает имя", covered),
        ) if not good
    ]
    return problems


def reality_inbounds(cfg):
    out = []
    for i in cfg.get("inbounds", []):
        ss = i.get("streamSettings") or {}
        if ss.get("security") == "reality" and ss.get("realitySettings"):
            out.append(i)
    return out


def show(label, before, after):
    print(f"  {label}:")
    print(f"    было : {before}")
    print(f"    будет: {after}")


def do_prune(exit_ip, keep, apply_now):
    cfg = mc.node_cfg(exit_ip)
    changed = False
    for ib in reality_inbounds(cfg):
        rs = ib["streamSettings"]["realitySettings"]
        old = list(rs.get("serverNames") or [])
        # Keep what peers send, plus whatever shares the dest's own hostname:
        # dropping the name `dest` itself answers for would be a footgun.
        dest_host = (rs.get("dest") or "").rsplit(":", 1)[0]
        new = [n for n in old if n in keep or n == dest_host]
        if not new:
            print(f"  ! {ib.get('tag')}: после чистки список пуст — пропускаю")
            continue
        if new != old:
            show(f"{ib.get('tag')} serverNames", old, new)
            rs["serverNames"] = new
            changed = True
    if not changed:
        print("  нечего убирать")
        return True
    return finish(exit_ip, cfg, apply_now)


def do_front(exit_ip, domain, phase, entry_ips, apply_now):
    if phase == 1:
        problems = verify_front(exit_ip, domain)
        if problems:
            print(f"  ОТКАЗ: {domain} не годится как dest — нет: "
                  f"{', '.join(problems)}")
            return False
        print(f"  проверка {domain} с выхода: TLS 1.3, X25519, h2, "
              f"сертификат — всё на месте")
        cfg = mc.node_cfg(exit_ip)
        for ib in reality_inbounds(cfg):
            rs = ib["streamSettings"]["realitySettings"]
            old = list(rs.get("serverNames") or [])
            if domain in old:
                print(f"  {ib.get('tag')}: {domain} уже принимается")
                continue
            show(f"{ib.get('tag')} serverNames", old, old + [domain])
            rs["serverNames"] = old + [domain]
        return finish(exit_ip, cfg, apply_now)

    if phase == 2:
        ok = True
        for ip in entry_ips:
            try:
                cfg = mc.node_cfg(ip)
            except RuntimeError as e:
                print(f"  ! вход {ip}: {e}")
                ok = False
                continue
            touched = False
            for o in cfg.get("outbounds", []):
                s = (o.get("settings") or {})
                vnext = (s.get("vnext") or s.get("servers") or [{}])
                if (vnext[0] or {}).get("address") != exit_ip:
                    continue
                rs = ((o.get("streamSettings") or {}).get("realitySettings"))
                if not rs or rs.get("serverName") == domain:
                    continue
                print(f"  вход {ip} / {o.get('tag')}:")
                show("serverName", rs.get("serverName"), domain)
                rs["serverName"] = domain
                touched = True
            if touched:
                ok = finish(ip, cfg, apply_now) and ok
            else:
                print(f"  вход {ip}: нечего менять")
        return ok

    # phase 3
    cfg = mc.node_cfg(exit_ip)
    for ib in reality_inbounds(cfg):
        rs = ib["streamSettings"]["realitySettings"]
        old = list(rs.get("serverNames") or [])
        if domain not in old:
            print(f"  ОТКАЗ: {ib.get('tag')} ещё не принимает {domain} — "
                  f"сначала фаза 1")
            return False
        show(f"{ib.get('tag')} serverNames", old, [domain])
        show(f"{ib.get('tag')} dest", rs.get("dest"), f"{domain}:443")
        rs["serverNames"] = [domain]
        rs["dest"] = f"{domain}:443"
    return finish(exit_ip, cfg, apply_now)


def finish(ip, cfg, apply_now):
    if not apply_now:
        print(f"  (сухой прогон — {ip} не тронут; добавьте --apply)")
        return True
    ok, out = mc.deploy(ip, cfg)
    print(f"  раскатка {ip}: {'OK' if ok else 'ОШИБКА'}")
    if not ok:
        print("   ", out[-500:])
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exit", required=True, help="IP выходной ноды")
    ap.add_argument("--prune", action="store_true",
                    help="убрать имена, которые никто не посылает")
    ap.add_argument("--front", help="новый домен маскировки")
    ap.add_argument("--phase", type=int, choices=(1, 2, 3),
                    help="фаза смены фронта")
    ap.add_argument("--apply", action="store_true",
                    help="применить; без него только показать")
    args = ap.parse_args()
    if bool(args.prune) == bool(args.front):
        ap.error("нужен ровно один из --prune / --front")
    if args.front and not args.phase:
        ap.error("--front требует --phase")

    entry_ips = entries()
    sent, tags = sent_names(entry_ips, args.exit)
    print(f"=== выход {args.exit}")
    print(f"  входов в парке: {len(entry_ips)}; "
          f"посылают на этот выход: {sorted(sent) or 'никто'}")
    for ip, tt in sorted(tags.items()):
        print(f"    {ip}: {', '.join(t for t in tt if t)}")
    if not sent:
        print("  ! ни один вход не ходит на этот выход — проверьте адрес")
        return 1

    if args.prune:
        return 0 if do_prune(args.exit, sent, args.apply) else 1
    return 0 if do_front(args.exit, args.front, args.phase,
                         entry_ips, args.apply) else 1


if __name__ == "__main__":
    sys.exit(main())
