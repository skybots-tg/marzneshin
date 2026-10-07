"""Перевыпуск ссылки у того, кто упёрся в лимит трафика.

Такой пользователь не ``is_active``, но остаётся на безлимитных нодах
(``usage_coefficient = 0``). Раньше revoke пушил новый ключ только активным,
и ноды продолжали пускать по старому ключу, а новая ссылка не работала нигде.
"""

from types import SimpleNamespace

import pytest

from app.services import user_service


def _user(**overrides):
    fields = dict(
        username="u",
        is_active=True,
        data_limit_reached=False,
        enabled=True,
        expired=False,
        removed=False,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.fixture
def pushes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        user_service.crud, "revoke_user_sub", lambda db, user: user
    )
    monkeypatch.setattr(
        user_service.node_ops,
        "update_user",
        lambda user, remove=False, db=None: calls.append(remove),
    )
    monkeypatch.setattr(user_service, "notify", lambda **kwargs: None)
    monkeypatch.setattr(user_service, "fire_and_forget", lambda coro: None)
    monkeypatch.setattr(
        user_service.UserResponse, "model_validate", classmethod(lambda cls, u: u)
    )
    return calls


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"is_active": False, "data_limit_reached": True},
    ],
    ids=["active", "data-limit-only"],
)
def test_revoke_pushes_new_key_to_nodes(pushes, overrides):
    user_service.revoke_subscription(None, _user(**overrides), admin=None)

    assert pushes == [True, False]


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_active": False, "data_limit_reached": True, "expired": True},
        {"is_active": False, "data_limit_reached": True, "enabled": False},
        {"is_active": False, "expired": True},
    ],
    ids=["limit-and-expired", "limit-and-disabled", "expired"],
)
def test_revoke_leaves_off_node_users_alone(pushes, overrides):
    user_service.revoke_subscription(None, _user(**overrides), admin=None)

    assert pushes == []
