"""Панель и нода должны считать отпечаток одинаково.

Формат живёт в двух репозиториях — ``app/marznode/users_digest.py`` здесь и
``marznode/utils/users_digest.py`` у ноды. Если они разойдутся, сверка начнёт
кричать о расхождении на каждой ноде парка и чинить то, что не сломано,
поэтому фикстура и ожидаемый хэш прибиты гвоздями с обеих сторон.
"""

from app.marznode.users_digest import digest_of_node_users, users_digest

FIXTURE = [(1, ["vless-tcp", "vless-reality"]), (2, ["vless-tcp"]), (10, [])]
# Тот же набор в tests/test_users_digest.py репозитория marznode даёт это же.
CROSS_REPO_DIGEST = (
    "4cd89b5a70228fae5b01b72d7b22bd21f38b0d19e1e06174e07b66e96b657708"
)


def test_the_format_matches_the_node_side():
    assert users_digest(FIXTURE) == CROSS_REPO_DIGEST


def test_order_of_users_and_tags_does_not_matter():
    shuffled = [
        (2, ["vless-tcp"]),
        (10, []),
        (1, ["vless-reality", "vless-tcp"]),
    ]
    assert users_digest(shuffled) == CROSS_REPO_DIGEST


def test_a_repeated_tag_is_the_same_set():
    """Юзер доходит до одного инбаунда через два сервиса — это один тег."""
    doubled = [
        (1, ["vless-tcp", "vless-reality", "vless-tcp"]),
        (2, ["vless-tcp"]),
        (10, []),
    ]
    assert users_digest(doubled) == CROSS_REPO_DIGEST


def test_losing_a_user_changes_it():
    assert users_digest(FIXTURE[:-1]) != CROSS_REPO_DIGEST


def test_losing_an_inbound_changes_it():
    """Ровно тот случай, который терялся: юзер есть, а инбаунд не доехал."""
    without = [(1, ["vless-tcp"]), (2, ["vless-tcp"]), (10, [])]
    assert users_digest(without) != CROSS_REPO_DIGEST


def test_it_reads_the_shape_get_node_users_returns():
    rows = [
        {"id": 1, "inbounds": ["vless-tcp", "vless-reality"]},
        {"id": 2, "inbounds": ["vless-tcp"]},
        {"id": 10, "inbounds": []},
    ]
    assert digest_of_node_users(rows) == (3, CROSS_REPO_DIGEST)
