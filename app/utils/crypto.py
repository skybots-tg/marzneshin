import base64
import json
import os

import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

_KDF_ITERATIONS = 480_000


def _derive_key(pin: str, salt: bytes, secret: str) -> bytes:
    """Derive a 256-bit AES key from PIN + server secret using PBKDF2."""
    combined = f"{pin}:{secret}".encode()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return kdf.derive(combined)


def encrypt_credentials(data: dict, pin: str, secret: str) -> tuple[str, str]:
    """
    Encrypt a dict of credentials with AES-256-GCM.
    Returns (base64-encoded ciphertext, base64-encoded salt).
    """
    salt = os.urandom(16)
    key = _derive_key(pin, salt, secret)

    plaintext = json.dumps(data).encode()
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext, None)

    payload = nonce + ct
    return base64.b64encode(payload).decode(), base64.b64encode(salt).decode()


def decrypt_credentials(encrypted_data: str, salt: str, pin: str, secret: str) -> dict:
    """
    Decrypt credentials. Raises ValueError on wrong PIN or corrupted data.
    """
    salt_bytes = base64.b64decode(salt)
    key = _derive_key(pin, salt_bytes, secret)

    payload = base64.b64decode(encrypted_data)
    nonce = payload[:12]
    ct = payload[12:]

    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, ct, None)
    except Exception as exc:
        raise ValueError("Decryption failed — wrong PIN or corrupted data") from exc

    return json.loads(plaintext)


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def verify_pin(pin: str, pin_hash: str) -> bool:
    return bcrypt.checkpw(pin.encode(), pin_hash.encode())
