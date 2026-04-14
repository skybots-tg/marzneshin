from functools import lru_cache


@lru_cache(maxsize=None)
def get_secret_key():
    from app.db import GetDB
    from app.db.crud.system import get_jwt_secret_key

    with GetDB() as db:
        return get_jwt_secret_key(db)
