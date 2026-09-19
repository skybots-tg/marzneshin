from app import marznode
from app.db import GetDB, crud, get_tls_certificate

# Первая сверка каждой ноды читает из БД её полный список юзеров под семафором
# на десять параллельных операций. Поднимать весь парк в одну секунду значит
# выстроить эти запросы в очередь ровно тогда, когда панель после рестарта
# разгребает наплыв подписок. Полсекунды между нодами разносят их даром.
STARTUP_STAGGER_SEC = 0.5
# Но ждать минуту, пока поднимется сотая нода, никто не должен.
STARTUP_STAGGER_MAX_SEC = 15.0


def startup_delay(index: int) -> float:
    """Задержка первого коннекта для ноды под номером ``index`` в парке."""
    return min(index * STARTUP_STAGGER_SEC, STARTUP_STAGGER_MAX_SEC)


async def nodes_startup():
    with GetDB() as db:
        certificate = get_tls_certificate(db)
        db_nodes = list(crud.get_nodes(db=db, enabled=True))
    # Session released — gRPC calls below won't hold a pool connection.
    for index, db_node in enumerate(db_nodes):
        await marznode.operations.add_node(
            db_node, certificate, start_delay=startup_delay(index)
        )
