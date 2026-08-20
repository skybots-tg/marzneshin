"""Алиасы /bus зовут те же обработчики, что и /sub — и обязаны им подходить.

Каждый алиас — тонкая обёртка, которая просто передаёт аргументы дальше. Это
и подвело: обёртка звала обработчик позиционно, а когда в него добавили
``background_tasks``, в этот слот попал ``user_agent``. FastAPI ошибку не
поймает — обёртка валидна сама по себе, — так что ``/bus/{username}/{key}``
несколько месяцев отвечал 500 на каждый запрос, и клиент, дёрнувший подписку
без суффикса формата, не получал ни одного сервера.

Проверяем то, что сломалось: у обёртки должны быть объявлены все обязательные
параметры обработчика, который она вызывает.
"""

from __future__ import annotations

import inspect

import pytest

from app.routes import subscription as sub_routes

ALIASES = [
    (sub_routes.bus_user_subscription, sub_routes.user_subscription),
    (
        sub_routes.bus_user_subscription_with_client_type,
        sub_routes.user_subscription_with_client_type,
    ),
    (sub_routes.bus_user_subscription_info, sub_routes.user_subscription_info),
    (sub_routes.bus_user_get_usage, sub_routes.user_get_usage),
]


def required_params(func) -> set[str]:
    return {
        name
        for name, param in inspect.signature(func).parameters.items()
        if param.default is inspect.Parameter.empty
    }


@pytest.mark.parametrize(
    "alias,target",
    ALIASES,
    ids=lambda f: getattr(f, "__name__", str(f)),
)
def test_alias_declares_everything_target_requires(alias, target):
    missing = required_params(target) - set(inspect.signature(alias).parameters)
    assert not missing, (
        f"{alias.__name__} не объявляет {sorted(missing)}, "
        f"а {target.__name__} их требует — запрос упадёт в 500"
    )
