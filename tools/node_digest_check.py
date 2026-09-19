#!/usr/bin/env python3
"""Сверить набор юзеров на каждом узле с тем, что считает панель.

То же, что делает `app/tasks/node_drift.py` по расписанию, но разом по всему
парку и по требованию — когда надо ответить на вопрос «а точно ли у всех то,
что мы им отправляли», не дожидаясь пятиминутного тика и не читая логи.

Только чтение: открывает тот же mTLS-канал, что и панель, зовёт
``GetUsersDigest`` и сравнивает с ``crud.get_node_users``. Ничего не чинит —
для починки есть ``POST /nodes/{id}/resync`` и сама сверка.

Запускать внутри контейнера панели:

    docker cp tools/node_digest_check.py marzneshin-marzneshin-1:/tmp/
    docker exec -w /app -e PYTHONPATH=/app marzneshin-marzneshin-1 \
        python /tmp/node_digest_check.py

Узлы со старым marznode отвечают «RPC не поддерживается» — на них сверка не
работает, и это надо чинить обновлением узла, а не панели.
"""

import asyncio
import sys

from app.db import GetDB, crud, get_tls_certificate
from app.marznode.grpclib import MarzNodeGRPCLIB
from app.marznode.users_digest import digest_of_node_users

# Узел, который не ответил за это время, считается недоступным: его молчание —
# забота монитора канала, а не этой проверки.
TIMEOUT_SEC = 25


async def _check(node, certificate, want) -> tuple[bool, str]:
    client = MarzNodeGRPCLIB(
        node.id, node.address, node.port, certificate.key, certificate.certificate
    )
    try:
        count, digest = await asyncio.wait_for(
            client.get_users_digest(), TIMEOUT_SEC
        )
    except NotImplementedError:
        return True, f"{node.id:>3}  {node.address:<16} RPC не поддерживается"
    except Exception as exc:  # noqa: BLE001
        return True, (
            f"{node.id:>3}  {node.address:<16} недоступен: {type(exc).__name__}"
        )
    finally:
        try:
            await client.stop()
        except Exception:  # noqa: BLE001
            pass

    agreed = digest == want[1]
    mark = "совпало" if agreed else f"РАСХОЖДЕНИЕ (в панели {want[0]})"
    return agreed, f"{node.id:>3}  {node.address:<16} {count:>5} юзеров  {mark}"


async def main() -> int:
    with GetDB() as db:
        certificate = get_tls_certificate(db)
        nodes = list(crud.get_nodes(db=db, enabled=True))
        wants = {
            node.id: digest_of_node_users(crud.get_node_users(db, node.id))
            for node in nodes
        }

    results = await asyncio.gather(
        *(_check(node, certificate, wants[node.id]) for node in nodes)
    )
    for _, line in sorted(results, key=lambda r: r[1]):
        print(line)

    drifted = [line for agreed, line in results if not agreed]
    if drifted:
        print(f"\nразошлись: {len(drifted)} из {len(results)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
