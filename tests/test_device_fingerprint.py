"""Compatibility tests for :mod:`app.utils.device_fingerprint`.

Golden vectors MUST match the identical set in marznode
(``tests/test_device_fingerprint.py``).  If you touch the algorithm,
update *both* repositories and regenerate the expected hashes using
``build_device_fingerprints_all``.
"""

from __future__ import annotations

import pytest

from app.utils.device_fingerprint import (
    DEFAULT_FINGERPRINT_VERSION,
    SUPPORTED_FINGERPRINT_VERSIONS,
    build_device_fingerprint,
    build_device_fingerprints_all,
    normalize_client_name,
)


GOLDEN_VECTORS: list[tuple[dict, dict[int, str]]] = [
    (
        dict(
            user_id=1,
            client_name="v2rayNG",
            tls_fingerprint="abc",
            os_guess="android",
            user_agent="v2rayNG/1.8.5",
        ),
        {
            1: "2e740ba0f613e5344768ff8baa46db61cee0a3d633e0320d249b191fae3398e3",
            2: "2e6e2cc50a5a3cbb1bb40fd5825c4692c0406d624cd6014741d62f1f921afcbb",
        },
    ),
    (
        dict(user_id=42),
        {
            1: "db07614276b63dfec17c6b143d22115430c7f4677eeec887a138623e89927b61",
            2: "fd91a9cca27b01de6cbc8c1cedf12272e8474780ad9e6a3125b393d90c3dd253",
        },
    ),
]


class TestGoldenVectors:
    @pytest.mark.parametrize("inputs,expected", GOLDEN_VECTORS)
    def test_v1_matches_golden(self, inputs, expected):
        fingerprint, version = build_device_fingerprint(**inputs, version=1)
        assert version == 1
        assert fingerprint == expected[1]

    @pytest.mark.parametrize("inputs,expected", GOLDEN_VECTORS)
    def test_v2_matches_golden(self, inputs, expected):
        fingerprint, version = build_device_fingerprint(**inputs, version=2)
        assert version == 2
        assert fingerprint == expected[2]

    @pytest.mark.parametrize("inputs,expected", GOLDEN_VECTORS)
    def test_all_versions_match_golden(self, inputs, expected):
        assert build_device_fingerprints_all(**inputs) == expected


class TestDefaults:
    def test_default_version_is_v2(self):
        _, version = build_device_fingerprint(user_id=1)
        assert version == DEFAULT_FINGERPRINT_VERSION == 2

    def test_supported_versions_tuple(self):
        assert set(SUPPORTED_FINGERPRINT_VERSIONS) == {1, 2}

    def test_unknown_version_raises(self):
        with pytest.raises(ValueError):
            build_device_fingerprint(user_id=1, version=99)


class TestNormalization:
    def test_case_insensitive_client_name_gives_same_v2(self):
        a, _ = build_device_fingerprint(user_id=7, client_name="v2rayNG", version=2)
        b, _ = build_device_fingerprint(user_id=7, client_name="V2RAYNG", version=2)
        assert a == b

    def test_whitespace_in_tls_stripped_v2(self):
        a, _ = build_device_fingerprint(user_id=1, tls_fingerprint="abc", version=2)
        b, _ = build_device_fingerprint(user_id=1, tls_fingerprint="  ABC  ", version=2)
        assert a == b

    def test_normalize_client_name_known_alias(self):
        assert normalize_client_name("v2rayng") == "v2rayNG"
        assert normalize_client_name("  SHADOWROCKET  ") == "Shadowrocket"

    def test_normalize_client_name_empty(self):
        assert normalize_client_name(None) is None
        assert normalize_client_name("") is None


class TestSeparatorCollisionFix:
    """v1 is vulnerable to ``|`` collisions; v2 must not be."""

    def test_v1_collides_on_pipe(self):
        a, _ = build_device_fingerprint(
            user_id=100, client_name="a", tls_fingerprint="b|c", version=1
        )
        b, _ = build_device_fingerprint(
            user_id=100, client_name="a|b", tls_fingerprint="c", version=1
        )
        assert a == b, "v1 collision is expected (documented legacy behaviour)"

    def test_v2_does_not_collide_on_pipe(self):
        a, _ = build_device_fingerprint(
            user_id=100, client_name="a", tls_fingerprint="b|c", version=2
        )
        b, _ = build_device_fingerprint(
            user_id=100, client_name="a|b", tls_fingerprint="c", version=2
        )
        assert a != b


class TestUnicodeSafety:
    def test_broken_surrogate_does_not_raise(self):
        fingerprint, _ = build_device_fingerprint(
            user_id=1, user_agent="bad\udcff surrogate"
        )
        assert len(fingerprint) == 64

    def test_broken_surrogate_both_versions(self):
        result = build_device_fingerprints_all(
            user_id=1, user_agent="bad\udcff surrogate"
        )
        assert set(result) == {1, 2}
        for fp in result.values():
            assert len(fp) == 64
