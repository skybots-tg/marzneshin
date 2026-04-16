"""Key / secret generation helpers for AI tools.

These are tiny, read-only helpers that don't touch the database. They
exist so the agent can populate Reality / UUID / password fields when
creating hosts or users without asking the admin to run `xray x25519`
or a uuidgen by hand.

Everything here is pure CPU — no network, no DB session.
"""
from __future__ import annotations

import base64
import secrets
import uuid

from sqlalchemy.orm import Session

from app.ai.tool_registry import register_tool


@register_tool(
    name="generate_uuid",
    description=(
        "Generate a fresh UUIDv4 suitable for VLESS/VMess `id` fields. "
        "Returns the canonical 8-4-4-4-12 hex representation."
    ),
    requires_confirmation=False,
)
async def generate_uuid(db: Session) -> dict:
    db.close()
    return {"uuid": str(uuid.uuid4())}


@register_tool(
    name="generate_reality_keypair",
    description=(
        "Generate a Curve25519 keypair for Xray Reality. "
        "Compatible with the `xray x25519` CLI output. "
        "Returns `private_key` (put into the Xray inbound `realitySettings.privateKey` "
        "on the NODE) and `public_key` (put into the host entry `reality_public_key` "
        "field in the panel so clients can see it). Both are URL-safe base64, no padding, "
        "matching Xray's expected format. "
        "`num_short_ids` (default 1, max 8) short_ids are also returned — "
        "random 8-byte hex strings for `reality_short_ids`. "
        "IMPORTANT: never echo the private key in chat unless the admin asked to see "
        "it — prefer applying it directly via update_node_config / modify_host."
    ),
    requires_confirmation=False,
)
async def generate_reality_keypair(db: Session, num_short_ids: int = 1) -> dict:
    from nacl.public import PrivateKey

    db.close()

    def _b64url_nopad(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    priv = PrivateKey.generate()
    private_key = _b64url_nopad(bytes(priv))
    public_key = _b64url_nopad(bytes(priv.public_key))

    count = max(1, min(int(num_short_ids or 1), 8))
    short_ids = [secrets.token_hex(8) for _ in range(count)]

    return {
        "private_key": private_key,
        "public_key": public_key,
        "short_ids": short_ids,
    }


@register_tool(
    name="generate_short_id",
    description=(
        "Generate a random Reality short_id. `length_bytes` must be in [1, 8] — "
        "Xray accepts 0–8 bytes (even length hex). Returns a hex string of "
        "2 * length_bytes characters."
    ),
    requires_confirmation=False,
)
async def generate_short_id(db: Session, length_bytes: int = 8) -> dict:
    db.close()
    n = max(1, min(int(length_bytes or 8), 8))
    return {"short_id": secrets.token_hex(n), "length_bytes": n}


@register_tool(
    name="generate_password",
    description=(
        "Generate a random URL-safe password of `length` characters "
        "(default 24, max 128). Use for Shadowsocks/Trojan/Hysteria2 host "
        "credentials when the admin asks for 'a fresh password'."
    ),
    requires_confirmation=False,
)
async def generate_password(db: Session, length: int = 24) -> dict:
    db.close()
    n = max(8, min(int(length or 24), 128))
    raw_bytes = max(1, (n * 3) // 4 + 1)
    password = secrets.token_urlsafe(raw_bytes)[:n]
    return {"password": password, "length": len(password)}
