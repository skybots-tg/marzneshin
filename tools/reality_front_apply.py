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


def load_plan(path):
    """Выход -> фронт, из файла назначений; ключи на _ — комментарии."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v["front"] for k, v in raw.items()
            if not k.startswith("_") and isinstance(v, dict)}


def plan_phase1(plan, apply_now):
    """Добавить новое имя каждому выходу. Перезапуск — только выходы."""
    ok = True
    for exit_ip, domain in sorted(plan.items()):
        print(f"\n=== выход {exit_ip} -> {domain}")
        problems = verify_front(exit_ip, domain)
        if problems:
            print(f"  ОТКАЗ: {domain} не годится как dest — нет: "
                  f"{', '.join(problems)}")
            ok = False
            continue
        try:
            cfg = mc.node_cfg(exit_ip)
        except RuntimeError as e:
            print(f"  ! недоступен: {e}")
            ok = False
            continue
        touched = False
        for ib in reality_inbounds(cfg):
            rs = ib["streamSettings"]["realitySettings"]
            old = list(rs.get("serverNames") or [])
            if domain in old:
                print(f"  {ib.get('tag')}: {domain} уже принимается")
                continue
            show(f"{ib.get('tag')} serverNames", old, old + [domain])
            rs["serverNames"] = old + [domain]
            touched = True
        ok = (finish(exit_ip, cfg, apply_now) if touched else True) and ok
    return ok


def plan_phase2(plan, entry_ips, apply_now):
    """Перевести исходящие входов — ВСЕ разом на каждом входе.

    Здесь и стоит вся экономия. Гонять фазу 2 выход за выходом означало бы
    перезапускать каждый вход по разу на выход: тринадцать выходов на
    одиннадцать входов — сто сорок три обрыва у пользователей вместо
    одиннадцати. Один вход, один конфиг, один перезапуск.
    """
    ok = True
    for ip in entry_ips:
        try:
            cfg = mc.node_cfg(ip)
        except RuntimeError as e:
            print(f"  ! вход {ip}: {e}")
            ok = False
            continue
        moved = []
        for o in cfg.get("outbounds", []):
            s = (o.get("settings") or {})
            vnext = (s.get("vnext") or s.get("servers") or [{}])
            addr = (vnext[0] or {}).get("address")
            domain = plan.get(addr)
            if not domain:
                continue
            rs = ((o.get("streamSettings") or {}).get("realitySettings"))
            if not rs or rs.get("serverName") == domain:
                continue
            moved.append(f"{o.get('tag')}: {rs.get('serverName')} -> {domain}")
            rs["serverName"] = domain
        print(f"\n=== вход {ip}: исходящих к переводу {len(moved)}")
        for line in moved:
            print(f"    {line}")
        if moved:
            ok = finish(ip, cfg, apply_now) and ok
    return ok


def plan_phase3(plan, apply_now, skip=(), keep=()):
    """Перевести dest на новый фронт. Перезапуск — только выходы.

    ``keep`` оставляет старые имена принимаемыми, и это не небрежность. Список
    serverNames зонду не виден — проверено: выход отдаёт сертификат dest на
    любое имя, включая отсутствующее в списке. Значит укорачивание списка не
    даёт защиты, а стоит вполне реального: три входа (37.46.135.220,
    23.152.200.52, 84.23.55.162) недоступны и фазу 2 не получили, так что
    посылают ещё apple.com. Убрать это имя — значит гарантировать, что их
    цепочки не поднимутся, если ноды вернутся. Существенная часть фазы 3 —
    именно dest, а не длина списка.

    ``skip`` не трогает выход, через который сейчас работает человек: его
    перезапуск обрывает канал ровно тому, кто раскатку и ведёт.
    """
    ok = True
    for exit_ip, domain in sorted(plan.items()):
        if exit_ip in skip:
            print(f"\n=== выход {exit_ip}: пропущен по --skip-exit")
            continue
        print(f"\n=== выход {exit_ip} -> только {domain}")
        try:
            cfg = mc.node_cfg(exit_ip)
        except RuntimeError as e:
            print(f"  ! недоступен: {e}")
            ok = False
            continue
        refuse = False
        for ib in reality_inbounds(cfg):
            rs = ib["streamSettings"]["realitySettings"]
            if domain not in (rs.get("serverNames") or []):
                print(f"  ОТКАЗ: {ib.get('tag')} ещё не принимает {domain} — "
                      f"сначала фаза 1")
                refuse = True
        if refuse:
            ok = False
            continue
        for ib in reality_inbounds(cfg):
            rs = ib["streamSettings"]["realitySettings"]
            old_names = list(rs.get("serverNames") or [])
            new_names = [domain] + [n for n in keep if n in old_names
                                    and n != domain]
            show(f"{ib.get('tag')} serverNames", old_names, new_names)
            show(f"{ib.get('tag')} dest", rs.get("dest"), f"{domain}:443")
            rs["serverNames"] = new_names
            rs["dest"] = f"{domain}:443"
        ok = finish(exit_ip, cfg, apply_now) and ok
    return ok


def sync_db_sni(ip, cfg, apply_now):
    """Свести копии фронта в панели с тем, что узел теперь принимает.

    Один и тот же факт лежит в трёх местах, а решает только одно: серверные
    имена в realitySettings на узле. ``inbounds.config.sni`` — то, что унаследует
    хост с пустым sni; ``hosts.sni`` — то, что мы велим посылать клиенту. Ни
    того, ни другого раскатка не касалась, и на фазе 3 двадцать хостов остались
    с именем, которое только что выбросили из списка. Порт при этом отвечает,
    поэтому пробы звали узлы здоровыми, пока весь тир FAST лежал пять суток.

    Хостам имя не подставляется, а стирается: пустой ``hosts.sni`` наследует
    ``inbounds.config.sni``, и следующая ротация будет править одно место, а не
    догонять литералы по каталогу.
    """
    names = {}
    for ib in reality_inbounds(cfg):
        got = (ib.get("streamSettings", {}).get("realitySettings", {})
               .get("serverNames"))
        if ib.get("tag") and got:
            names[ib["tag"]] = list(got)
    if not names:
        return True

    tags = ",".join(mc.sqlstr(t) for t in names)
    rows = mc.db_query(
        "SELECT i.id, i.tag, i.config FROM inbounds i JOIN nodes n "
        f"ON n.id = i.node_id WHERE n.address = {mc.sqlstr(ip)} "
        f"AND i.tag IN ({tags});")

    stmts, notes = [], []
    for iid, tag, cfg_json in rows:
        try:
            icfg = json.loads(cfg_json)
        except ValueError:
            print(f"  ВНИМАНИЕ: inbounds.config инбаунда {iid} не читается — пропуск")
            continue
        want = names[tag]
        if list(icfg.get("sni") or []) != want:
            icfg["sni"] = want
            stmts.append("UPDATE inbounds SET config = "
                         f"{mc.sqlstr(json.dumps(icfg, ensure_ascii=False))} "
                         f"WHERE id = {iid};")
            notes.append(f"  инбаунд {iid} {tag}: sni -> {','.join(want)}")

        for hid, hsni in mc.db_query(
                f"SELECT id, sni FROM hosts WHERE inbound_id = {iid} "
                "AND sni IS NOT NULL AND sni <> '';"):
            sent = [x.strip() for x in hsni.split(",") if x.strip()]
            if any(x in want for x in sent):
                continue
            stmts.append(f"UPDATE hosts SET sni = NULL WHERE id = {hid};")
            notes.append(f"  хост {hid}: sni {hsni} больше не принимается — стираю")

    if not stmts:
        return True
    for n in notes:
        print(n)
    if not apply_now:
        print("  (сухой прогон — панель не тронута)")
        return True
    r = mc.db("\n".join(stmts) + "\n")
    if r.returncode != 0:
        print("  ОШИБКА панели:", r.stderr[:300])
        return False
    print(f"  панель: {len(stmts)} правк(и) применены")
    return True


def finish(ip, cfg, apply_now):
    if not apply_now:
        print(f"  (сухой прогон — {ip} не тронут; добавьте --apply)")
        return sync_db_sni(ip, cfg, apply_now)
    ok, out = mc.deploy(ip, cfg)
    print(f"  раскатка {ip}: {'OK' if ok else 'ОШИБКА'}")
    if not ok:
        print("   ", out[-500:])
        return ok
    # Узел принял конфиг — теперь панель обязана говорить то же самое.
    return sync_db_sni(ip, cfg, apply_now)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exit", help="IP выходной ноды")
    ap.add_argument("--plan", help="файл назначений выход->фронт для всего парка")
    ap.add_argument("--prune", action="store_true",
                    help="убрать имена, которые никто не посылает")
    ap.add_argument("--front", help="новый домен маскировки")
    ap.add_argument("--phase", type=int, choices=(1, 2, 3),
                    help="фаза смены фронта")
    ap.add_argument("--skip-exit", action="append", default=[],
                    help="не трогать этот выход (например, тот, через "
                         "который сейчас работаете)")
    ap.add_argument("--keep-name", action="append", default=[],
                    help="фаза 3: оставить это имя принимаемым")
    ap.add_argument("--only-entry",
                    help="фаза 2 только для этого входа (канарейка)")
    ap.add_argument("--apply", action="store_true",
                    help="применить; без него только показать")
    args = ap.parse_args()
    if args.plan:
        if not args.phase:
            ap.error("--plan требует --phase")
        plan = load_plan(args.plan)
        print(f"назначений в плане: {len(plan)}")
        entry_ips = ([args.only_entry] if args.only_entry else entries())
        if args.phase == 1:
            return 0 if plan_phase1(plan, args.apply) else 1
        if args.phase == 2:
            return 0 if plan_phase2(plan, entry_ips, args.apply) else 1
        return 0 if plan_phase3(plan, args.apply, tuple(args.skip_exit),
                                tuple(args.keep_name)) else 1

    if not args.exit:
        ap.error("нужен --exit или --plan")
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
    # Фаза 2 перезапускает вход, а это короткий обрыв у ВСЕХ его
    # пользователей, не только у тех, кто сейчас на этом выходе. Поэтому
    # переводить парк имеет смысл по одному входу, убедившись на первом.
    targets = [args.only_entry] if args.only_entry else entry_ips
    return 0 if do_front(args.exit, args.front, args.phase,
                         targets, args.apply) else 1


if __name__ == "__main__":
    sys.exit(main())
