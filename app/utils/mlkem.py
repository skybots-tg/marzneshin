"""ML-KEM-768 + X25519 hybrid key generation for VLESS post-quantum encryption.

Wraps two Xray CLI commands and produces ready-to-use credential strings:

* ``decryption_string`` — goes into the *server* xray inbound config
  (``settings.decryption``)::

      mlkem768x25519plus.<mode>.<ticket>.<x25519_priv_b64>.<mlkem_seed_b64>

* ``encryption_string`` — handed out to *clients* via the subscription URL
  (e.g. ``encryption=`` query parameter)::

      mlkem768x25519plus.<mode>.<rtt>.<x25519_pub_b64>.<mlkem_client_eK_b64>

Format reference: ``XTLS/Xray-core`` v26.2.6+ VLESS encryption design
(``mlkem768x25519plus`` post-quantum hybrid).

The previous implementation in this module had two bugs that silently
produced unusable credentials:

1. It treated ``xray mlkem768`` output as ``publicKey``/``privateKey``
   pairs. The actual output is ``Seed`` (server-only secret used to derive
   the decapsulation key) and ``Client`` (the encapsulation key the client
   needs in its handshake). Mixing them up broke both sides of the
   exchange.
2. It returned raw key material, leaving callers to assemble the
   ``mlkem768x25519plus.…`` strings themselves. No caller did, so no
   working ``decryption``/``encryption`` value ever reached xray.

This rewrite fixes both: we parse the ``Key: value`` blocks emitted by
Xray (``mlkem768`` *and* ``x25519``) and assemble the final hybrid
credential strings here, where the format change can be reviewed in one
place.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)


class MlkemError(RuntimeError):
    """Raised when the underlying ``xray`` CLI invocation fails or its
    output cannot be parsed."""


class MlkemKeyPair(NamedTuple):
    """Compact 2-string view of a hybrid key bundle, kept for backwards
    compatibility with existing CRUD code paths.

    Attributes:
        public_key:  client-side ``encryption`` string (subscription URL)
        private_key: server-side ``decryption`` string (xray inbound)
    """

    public_key: str
    private_key: str


@dataclass(frozen=True)
class MlkemBundle:
    """Full set of fields produced by a single hybrid key generation."""

    x25519_private: str
    x25519_public: str
    mlkem_seed: str
    mlkem_client: str
    decryption_string: str
    encryption_string: str

    def as_keypair(self) -> MlkemKeyPair:
        return MlkemKeyPair(
            public_key=self.encryption_string,
            private_key=self.decryption_string,
        )


# Tunables. Defaults match the recommendations in the xray VLESS encryption
# design notes; advanced users can override them via env vars without
# touching the code.
DEFAULT_MODE = os.getenv("MLKEM_MODE", "native")
DEFAULT_TICKET = os.getenv("MLKEM_TICKET", "600s")
DEFAULT_RTT = os.getenv("MLKEM_RTT", "1rtt")

_PREFIX = "mlkem768x25519plus."
_KV_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")


def _get_xray_binary() -> str:
    return os.getenv("XRAY_BINARY", "xray")


def _run_xray(args: list[str]) -> str:
    """Run ``xray <args>`` and return stripped stdout, or raise ``MlkemError``."""
    cmd = [_get_xray_binary(), *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True
        )
    except FileNotFoundError as exc:
        raise MlkemError(
            f"xray binary not found ({cmd[0]}). Install xray and either set the "
            "XRAY_BINARY environment variable or add the binary to PATH."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise MlkemError(
            f"`{' '.join(cmd)}` exited with status {exc.returncode}: {stderr}"
        ) from exc

    out = (result.stdout or "").strip()
    if not out:
        raise MlkemError(f"`{' '.join(cmd)}` returned empty output")
    return out


def _parse_kv(text: str) -> dict[str, str]:
    """Parse the ``Key: value`` lines that xray emits for key generation.

    Both ``xray mlkem768`` and ``xray x25519`` print one ``Key: value`` per
    line. We accept either capitalisation and ignore unrelated lines so the
    parser keeps working if xray adds or reorders fields.
    """
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        m = _KV_RE.match(line)
        if m:
            pairs[m.group(1)] = m.group(2)
    return pairs


def _generate_mlkem768() -> Tuple[str, str]:
    """Return ``(seed, client_encapsulation_key)`` from ``xray mlkem768``.

    * ``seed`` (64 bytes, base64) — server-only secret, fed back into xray
      at startup to derive the decapsulation key. Goes into
      ``decryption_string``.
    * ``client`` (1184 bytes, base64) — public encapsulation key sent to
      clients. Goes into ``encryption_string``.
    """
    text = _run_xray(["mlkem768"])
    parsed = _parse_kv(text)

    seed = parsed.get("Seed") or parsed.get("seed")
    client = parsed.get("Client") or parsed.get("client")
    if not seed or not client:
        raise MlkemError(
            "Could not parse `xray mlkem768` output: missing Seed/Client "
            f"lines (got: {sorted(parsed)!r}; raw: {text!r})"
        )
    return seed, client


def _generate_x25519() -> Tuple[str, str]:
    """Return ``(private_key, public_key)`` from ``xray x25519``.

    Note: in newer xray builds the public half is labelled ``Password``
    (because it doubles as the password value clients use). We accept the
    legacy ``PublicKey`` label too, just in case.
    """
    text = _run_xray(["x25519"])
    parsed = _parse_kv(text)

    private = parsed.get("PrivateKey") or parsed.get("privateKey")
    public = (
        parsed.get("Password")
        or parsed.get("PublicKey")
        or parsed.get("publicKey")
    )
    if not private or not public:
        raise MlkemError(
            "Could not parse `xray x25519` output: missing "
            f"PrivateKey/Password lines (got: {sorted(parsed)!r}; raw: {text!r})"
        )
    return private, public


def _build_decryption(
    x25519_priv: str,
    mlkem_seed: str,
    mode: str = DEFAULT_MODE,
    ticket: str = DEFAULT_TICKET,
) -> str:
    return f"{_PREFIX}{mode}.{ticket}.{x25519_priv}.{mlkem_seed}"


def _build_encryption(
    x25519_pub: str,
    mlkem_client: str,
    mode: str = DEFAULT_MODE,
    rtt: str = DEFAULT_RTT,
) -> str:
    return f"{_PREFIX}{mode}.{rtt}.{x25519_pub}.{mlkem_client}"


def _looks_like_hybrid_string(s: Optional[str]) -> bool:
    """Cheap sanity check: the ``mlkem768x25519plus.<m>.<t>.<k1>.<k2>`` shape
    has at least five dot-separated segments and our prefix."""
    if not s or not s.startswith(_PREFIX):
        return False
    return s.count(".") >= 4


def generate_mlkem_bundle(
    mode: str = DEFAULT_MODE,
    ticket: str = DEFAULT_TICKET,
    rtt: str = DEFAULT_RTT,
) -> MlkemBundle:
    """Generate a fresh ML-KEM-768 + X25519 hybrid bundle.

    Intentionally **not** memoised — credentials must never be reused across
    hosts: a leaked decapsulation key would unlock every host that shared it.
    """
    mlkem_seed, mlkem_client = _generate_mlkem768()
    x25519_priv, x25519_pub = _generate_x25519()

    return MlkemBundle(
        x25519_private=x25519_priv,
        x25519_public=x25519_pub,
        mlkem_seed=mlkem_seed,
        mlkem_client=mlkem_client,
        decryption_string=_build_decryption(
            x25519_priv, mlkem_seed, mode=mode, ticket=ticket
        ),
        encryption_string=_build_encryption(
            x25519_pub, mlkem_client, mode=mode, rtt=rtt
        ),
    )


# --- backwards-compat surface ----------------------------------------------
def generate_mlkem_keypair(variant: str = "mlkem768") -> MlkemKeyPair:
    """Compatibility shim for older callers.

    ``variant`` is accepted but ignored — VLESS post-quantum encryption
    always uses the hybrid ``mlkem768x25519plus`` construction.
    """
    if variant != "mlkem768":
        logger.warning(
            "generate_mlkem_keypair(variant=%r): only mlkem768 is supported; "
            "falling back to it.",
            variant,
        )
    return generate_mlkem_bundle().as_keypair()


def ensure_mlkem_keys(
    public_key: Optional[str],
    private_key: Optional[str],
    variant: str = "mlkem768",
) -> MlkemKeyPair:
    """Return the existing pair if it is well-formed, else generate a new one.

    The legacy storage convention is preserved:

    * ``public_key``  → client ``encryption`` string (used in URLs)
    * ``private_key`` → server ``decryption`` string (used in xray inbound)

    Stored values from the *previous*, broken implementation will not pass
    the prefix check and are therefore regenerated transparently.
    """
    if _looks_like_hybrid_string(public_key) and _looks_like_hybrid_string(
        private_key
    ):
        return MlkemKeyPair(public_key=public_key, private_key=private_key)

    if public_key or private_key:
        logger.info(
            "ensure_mlkem_keys: stored MLKEM keys are missing or malformed "
            "(legacy/broken format); regenerating a fresh hybrid bundle."
        )

    return generate_mlkem_keypair(variant=variant)


__all__ = [
    "MlkemBundle",
    "MlkemError",
    "MlkemKeyPair",
    "ensure_mlkem_keys",
    "generate_mlkem_bundle",
    "generate_mlkem_keypair",
]
