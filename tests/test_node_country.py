"""The country an alert shows, and where it comes from.

Node alerts used to name a node by id and IP alone, which tells whoever reads
them at 3am nothing about whether it matters. The country is not stored
anywhere — it is read off the flag emoji in the node's own name, so these tests
pin the convention that makes that legal.
"""

from __future__ import annotations

import pytest

from app.utils.node_country import country_label, iso_to_flag


@pytest.mark.parametrize("iso,expected", [
    ("NL", "🇳🇱"),
    ("ru", "🇷🇺"),
    (" de ", "🇩🇪"),
    ("XX", "🇽🇽"),          # not a country, but still a well-formed pair
    ("RUS", "🏳️"),
    ("Ру", "🏳️"),           # isalpha() is true for Cyrillic; isascii() is not
    ("", "🏳️"),
    (None, "🏳️"),
])
def test_iso_to_flag(iso, expected):
    assert iso_to_flag(iso) == expected


@pytest.mark.parametrize("name,expected", [
    ("🇳🇱 AdminVPS NL-2", "🇳🇱 Нидерланды"),
    ("🇷🇺 Yandex.Cloud Elite 1", "🇷🇺 Россия"),
    ("🇷🇴 Румыния-1 zetservers.com", "🇷🇴 Румыния"),
    # The German nodes are named after their exit slot, and GE is Georgia --
    # reading the flag rather than the suffix is the whole point.
    ("🇩🇪 DataForest.net GE-1", "🇩🇪 Германия"),
    ("Marz", "🏳️ не определена"),
    ("", "🏳️ не определена"),
    (None, "🏳️ не определена"),
])
def test_country_label(name, expected):
    assert country_label(name) == expected


def test_country_label_falls_back_to_the_iso_it_does_not_know():
    assert country_label("🇧🇷 São Paulo") == "🇧🇷 BR"
