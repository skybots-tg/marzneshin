"""Первым в подписке никогда не стоит российский сервер.

Клиенты подключаются к первой записи, и российский выход в этой роли — тупик:
человек ставил VPN как раз чтобы выйти из страны. Порядок задают веса, но
bridge-health прячет упавшие хосты в любой момент, и наверх всплывает тот, кто
остался — именно так RU и оказывался первым после падения ноды.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.utils.share import _is_home_country, _lead_with_foreign, _promote_foreign_head


def host(remark: str, weight: int = 1):
    return SimpleNamespace(remark=remark, weight=weight)


RU_ALWAYS = "🇷🇺📶 ELITE RU РАБОТАЕТ ВСЕГДА"
US_ALWAYS = "🇺🇸📶 ELITE US РАБОТАЕТ ВСЕГДА"
DE_ELITE = "🇩🇪📶 ELITE 1 [GB] - DE-2 [ 4G ]"
RU_UNIVERSAL = "🇷🇺 🛜 UNIVERSAL 1 ♾️ RU (Я за границей)"


@pytest.mark.parametrize("remark,expected", [
    (RU_ALWAYS, True),
    (RU_UNIVERSAL, True),
    (US_ALWAYS, False),
    (DE_ELITE, False),
    ("", False),
    ("ELITE RU без флага", False),
])
def test_is_home_country(remark, expected):
    assert _is_home_country(host(remark)) is expected


def test_ru_head_is_swapped_with_the_first_foreign():
    configs = [host(RU_ALWAYS), host(US_ALWAYS), host(DE_ELITE)]
    ordered = _lead_with_foreign(configs)
    assert [c.remark for c in ordered] == [US_ALWAYS, RU_ALWAYS, DE_ELITE]


def test_foreign_head_is_left_alone():
    configs = [host(US_ALWAYS), host(RU_ALWAYS)]
    assert _lead_with_foreign(configs) is configs


def test_only_the_head_moves_and_nothing_is_lost():
    """Российские выходы из списка не выкидываются — им просто не место первыми."""
    configs = [host(RU_ALWAYS), host(RU_UNIVERSAL), host(DE_ELITE), host(US_ALWAYS)]
    ordered = _lead_with_foreign(configs)
    assert [c.remark for c in ordered] == [
        DE_ELITE, RU_ALWAYS, RU_UNIVERSAL, US_ALWAYS,
    ]
    assert len(ordered) == len(configs)


def test_all_russian_list_is_returned_unchanged():
    configs = [host(RU_ALWAYS), host(RU_UNIVERSAL)]
    assert _lead_with_foreign(configs) is configs


def test_empty_list_is_safe():
    assert _lead_with_foreign([]) == []


def test_promote_foreign_head_fixes_the_list_after_handler_filtering():
    """clash и sing-box выкидывают неподдерживаемые транспорты — голову правим снова."""
    handler = SimpleNamespace(_configs=[host(RU_ALWAYS), host(DE_ELITE)])
    _promote_foreign_head(handler)
    assert [c.remark for c in handler._configs] == [DE_ELITE, RU_ALWAYS]


def test_promote_foreign_head_tolerates_a_handler_without_configs():
    _promote_foreign_head(SimpleNamespace())  # не должно бросать
