from .env import *  # noqa: F401,F403


def get_secret_key():
    from .db import get_secret_key as _get

    return _get()
