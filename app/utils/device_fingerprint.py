"""Device fingerprinting utilities.

Two fingerprint algorithms are supported:

* ``v1`` - legacy format.  Components are joined with ``"|"`` and hashed with
  SHA256.  Kept for backwards compatibility with existing device records.
* ``v2`` - current default.  Components are serialized as canonical JSON with
  the version baked into the payload, and the hash uses
  ``errors="replace"`` to guarantee the encoder never raises on malformed
  Unicode.  ``client_name`` is normalized the same way as before.

This module MUST stay byte-compatible with
``marznode/utils/device_fingerprint.py`` in marznode -- both sides compute
the hash and rely on it matching across the wire.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional, Union

__all__ = [
    "DEFAULT_FINGERPRINT_VERSION",
    "SUPPORTED_FINGERPRINT_VERSIONS",
    "build_device_fingerprint",
    "build_device_fingerprints_all",
    "guess_client_type",
    "extract_client_name",
    "normalize_client_name",
]

DEFAULT_FINGERPRINT_VERSION: int = 2
SUPPORTED_FINGERPRINT_VERSIONS: tuple[int, ...] = (1, 2)


_CLIENT_NAME_NORMALIZATION: dict[str, str] = {
    "v2rayng": "v2rayNG",
    "v2rayn": "v2rayN",
    "clashx": "ClashX",
    "clash for windows": "Clash for Windows",
    "clash-for-windows": "Clash for Windows",
    "shadowrocket": "Shadowrocket",
    "quantumult": "Quantumult",
    "sing-box": "sing-box",
    "matsuri": "Matsuri",
    "sagernet": "SagerNet",
    "nekobox": "NekoBox",
}


def _safe_encode(source: str) -> bytes:
    """Encode to UTF-8 tolerating malformed surrogate characters."""
    return source.encode("utf-8", errors="replace")


def _build_v1(
    user_id: int,
    client_name: Optional[str],
    tls_fingerprint: Optional[str],
    os_guess: Optional[str],
    user_agent: Optional[str],
) -> str:
    """Legacy algorithm - do not change.

    Byte-compatible with v1 fingerprints stored before the v2 migration.
    The only behavioural fix vs. the original is ``errors="replace"`` so
    broken UTF-8 in a user agent can no longer crash the caller; this is a
    no-op for every valid string.
    """
    components = [
        str(user_id),
        client_name or "",
        tls_fingerprint or "",
        os_guess or "",
        user_agent or "",
    ]
    source = "|".join(components)
    return hashlib.sha256(_safe_encode(source)).hexdigest()


def _build_v2(
    user_id: int,
    client_name: Optional[str],
    tls_fingerprint: Optional[str],
    os_guess: Optional[str],
    user_agent: Optional[str],
) -> str:
    """Current algorithm.

    Improvements over v1:

    * The version is part of the hashed payload, so future migrations cannot
      collide with historical v1 hashes.
    * Components are serialized as canonical JSON, which escapes the
      separator and removes the ``"a|b" + "" == "a" + "b"`` ambiguity
      present in v1.
    * ``client_name`` is run through :func:`normalize_client_name` so
      cosmetic differences (case, known synonyms) do not create duplicates.
    * Leading/trailing whitespace is stripped from textual fields and
      ``tls_fingerprint``/``os_guess`` are lower-cased for stability.
    """
    payload: dict[str, Union[int, str]] = {
        "v": 2,
        "uid": int(user_id),
        "cn": (normalize_client_name(client_name) or "").strip(),
        "tls": (tls_fingerprint or "").strip().lower(),
        "os": (os_guess or "").strip().lower(),
        "ua": (user_agent or "").strip(),
    }
    source = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(_safe_encode(source)).hexdigest()


_VERSION_BUILDERS = {
    1: _build_v1,
    2: _build_v2,
}


def build_device_fingerprint(
    user_id: int,
    client_name: Optional[str] = None,
    tls_fingerprint: Optional[str] = None,
    os_guess: Optional[str] = None,
    user_agent: Optional[str] = None,
    *,
    version: Optional[int] = None,
) -> tuple[str, int]:
    """Build a device fingerprint from various identifiers.

    Args:
        user_id: User ID
        client_name: Client application name (v2rayNG, sing-box, etc.)
        tls_fingerprint: TLS fingerprint if available
        os_guess: Operating system guess
        user_agent: User agent string
        version: Explicit fingerprint version (default:
            ``DEFAULT_FINGERPRINT_VERSION``).  Pass ``1`` to compute the
            legacy hash for backwards-compatibility lookups.

    Returns:
        Tuple of ``(fingerprint_hash, version)``.

    Raises:
        ValueError: if ``version`` is not supported.
    """
    resolved_version = DEFAULT_FINGERPRINT_VERSION if version is None else int(version)
    try:
        builder = _VERSION_BUILDERS[resolved_version]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported fingerprint version: {resolved_version!r} "
            f"(supported: {SUPPORTED_FINGERPRINT_VERSIONS})"
        ) from exc

    fingerprint = builder(
        user_id=user_id,
        client_name=client_name,
        tls_fingerprint=tls_fingerprint,
        os_guess=os_guess,
        user_agent=user_agent,
    )
    return fingerprint, resolved_version


def build_device_fingerprints_all(
    user_id: int,
    client_name: Optional[str] = None,
    tls_fingerprint: Optional[str] = None,
    os_guess: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[int, str]:
    """Compute fingerprints for every supported version.

    Used by the lookup side (tracker / device CRUD) so a single incoming
    request can be matched against either a v1 or v2 record in the
    database without requiring a blocking migration.
    """
    return {
        version: _VERSION_BUILDERS[version](
            user_id=user_id,
            client_name=client_name,
            tls_fingerprint=tls_fingerprint,
            os_guess=os_guess,
            user_agent=user_agent,
        )
        for version in SUPPORTED_FINGERPRINT_VERSIONS
    }


def guess_client_type(
    client_name: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """
    Guess client type from client name or user agent.
    
    Returns:
        Client type: android, ios, windows, macos, linux, other
    """
    if not client_name and not user_agent:
        return "other"
    
    identifier = f"{client_name or ''} {user_agent or ''}".lower()
    
    # Android clients
    if any(x in identifier for x in ["android", "v2rayng", "matsuri", "sagernet"]):
        return "android"
    
    # iOS clients
    if any(x in identifier for x in ["ios", "iphone", "ipad", "shadowrocket", "quantumult"]):
        return "ios"
    
    # Windows clients
    if any(x in identifier for x in ["windows", "v2rayn", "clash for windows", "clash-for-windows"]):
        return "windows"
    
    # macOS clients
    if any(x in identifier for x in ["macos", "darwin", "clashx"]):
        return "macos"
    
    # Linux clients
    if any(x in identifier for x in ["linux", "ubuntu", "debian"]):
        return "linux"
    
    return "other"


def extract_client_name(user_agent: Optional[str] = None) -> Optional[str]:
    """
    Try to extract client name from user agent.
    
    Common patterns:
    - v2rayNG/1.8.5
    - clash-meta/1.15.0
    - sing-box/1.5.0
    """
    if not user_agent:
        return None
    
    # Try to extract from common patterns
    parts = user_agent.split("/")
    if len(parts) >= 2:
        client = parts[0].strip()
        if client:
            return client
    
    # Try to extract from space-separated
    parts = user_agent.split()
    if parts:
        client = parts[0].strip()
        if client:
            return client
    
    return None


def normalize_client_name(client_name: Optional[str]) -> Optional[str]:
    """Normalize client name for consistency.

    Must stay identical to ``normalize_client_name`` in marznode.
    """
    if not client_name:
        return None
    name = client_name.lower().strip()
    return _CLIENT_NAME_NORMALIZATION.get(name, client_name)
