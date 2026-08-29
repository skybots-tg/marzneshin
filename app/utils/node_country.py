"""Which country a node sits in, read off the flag in its own name.

The panel has no column for it: ``nodes.address`` is an IP and ``nodes.name`` is
free text. What the fleet does have is a naming convention — every node is named
flag-first (``🇳🇱 AdminVPS NL-2``), the same convention host remarks follow — so
the flag emoji is the only place the country is actually written down. Geo
lookups are not an option here anyway: they are wrong often enough that
``fleet_taxonomy`` keeps a table of overrides for them.

Read the flag, not the slot suffix: the German nodes are named ``GE-1``/``GE-2``
after their exit slot, and ``GE`` is Georgia.
"""

from __future__ import annotations

from app.utils.fleet_taxonomy import flag_to_iso

__all__ = ["COUNTRY_NAMES_RU", "iso_to_flag", "country_label"]

# Russian names for the countries the fleet touches, plus the near neighbours a
# new node is likely to appear in. An ISO missing here still renders — as its
# own two letters next to the flag — so this table is a nicety, not a gate.
COUNTRY_NAMES_RU = {
    "AE": "ОАЭ",
    "AM": "Армения",
    "AT": "Австрия",
    "AZ": "Азербайджан",
    "BG": "Болгария",
    "BY": "Беларусь",
    "CA": "Канада",
    "CH": "Швейцария",
    "CY": "Кипр",
    "CZ": "Чехия",
    "DE": "Германия",
    "DK": "Дания",
    "EE": "Эстония",
    "ES": "Испания",
    "FI": "Финляндия",
    "FR": "Франция",
    "GB": "Великобритания",
    "GE": "Грузия",
    "GR": "Греция",
    "HK": "Гонконг",
    "HU": "Венгрия",
    "IE": "Ирландия",
    "IL": "Израиль",
    "IN": "Индия",
    "IT": "Италия",
    "JP": "Япония",
    "KZ": "Казахстан",
    "LT": "Литва",
    "LU": "Люксембург",
    "LV": "Латвия",
    "MD": "Молдова",
    "NL": "Нидерланды",
    "NO": "Норвегия",
    "PL": "Польша",
    "PT": "Португалия",
    "RO": "Румыния",
    "RS": "Сербия",
    "RU": "Россия",
    "SE": "Швеция",
    "SG": "Сингапур",
    "SK": "Словакия",
    "TR": "Турция",
    "UA": "Украина",
    "US": "США",
    "UZ": "Узбекистан",
}

# Shown when the name carries no flag, so the gap is visible in the alert
# instead of the country line quietly disappearing.
UNKNOWN_FLAG = "🏳️"


def iso_to_flag(iso: str | None) -> str:
    """``"NL"`` -> ``"🇳🇱"``. A white flag for anything that is not an ISO2."""
    letters = (iso or "").strip().upper()
    if len(letters) != 2 or not (letters.isascii() and letters.isalpha()):
        return UNKNOWN_FLAG
    return "".join(chr(ord(c) - ord("A") + 0x1F1E6) for c in letters)


def country_label(node_name: str | None) -> str:
    """``"🇳🇱 AdminVPS NL-2"`` -> ``"🇳🇱 Нидерланды"``, for an alert line."""
    iso = flag_to_iso(node_name or "")
    if not iso:
        return f"{UNKNOWN_FLAG} не определена"
    return f"{iso_to_flag(iso)} {COUNTRY_NAMES_RU.get(iso, iso)}"
