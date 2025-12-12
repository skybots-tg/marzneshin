import ssl
import base64
import os
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import ExtendedKeyUsageOID


def get_cert_SANs(cert: bytes):
    cert = x509.load_pem_x509_certificate(cert, default_backend())
    san_list = []
    for extension in cert.extensions:
        if isinstance(extension.value, x509.SubjectAlternativeName):
            san = extension.value
            for name in san:
                san_list.append(name.value)
    return san_list


def generate_certificate():
    key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name([])

    subject_key_id = x509.SubjectKeyIdentifier.from_public_key(
        key.public_key()
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=3650))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=False,
        )
        .add_extension(subject_key_id, critical=False)
        .add_extension(
            x509.ExtendedKeyUsage(
                [
                    ExtendedKeyUsageOID.SERVER_AUTH,
                    ExtendedKeyUsageOID.CLIENT_AUTH,
                ]
            ),
            critical=False,
        )
        .sign(private_key=key, algorithm=hashes.SHA256())
    )

    return {
        "cert": cert.public_bytes(serialization.Encoding.PEM).decode(),
        "key": key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
    }


def create_secure_context(
    client_cert: str,
    client_key: str,
    trusted: str,
) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=trusted)
    ctx.load_cert_chain(client_cert, client_key)
    ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20")
    ctx.set_alpn_protocols(["h2"])
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def encrypt_content(content: str | bytes, key: str) -> str:
    """
    Encrypt content using AES-256-GCM
    
    Args:
        content: Content to encrypt (string or bytes)
        key: Encryption key (will be hashed to 32 bytes)
    
    Returns:
        Base64-encoded encrypted content with format: nonce(12bytes)||ciphertext||tag(16bytes)
    """
    if isinstance(content, str):
        content = content.encode('utf-8')
    
    # Derive a 32-byte key from the provided key using SHA256
    key_hash = hashes.Hash(hashes.SHA256(), backend=default_backend())
    key_hash.update(key.encode('utf-8'))
    derived_key = key_hash.finalize()
    
    # Generate random nonce (12 bytes for GCM)
    nonce = os.urandom(12)
    
    # Encrypt
    aesgcm = AESGCM(derived_key)
    ciphertext = aesgcm.encrypt(nonce, content, None)
    
    # Return base64-encoded: nonce + ciphertext (which includes tag)
    encrypted_data = nonce + ciphertext
    return base64.b64encode(encrypted_data).decode('utf-8')


def decrypt_content(encrypted_content: str, key: str) -> bytes:
    """
    Decrypt content encrypted with encrypt_content
    
    Args:
        encrypted_content: Base64-encoded encrypted content
        key: Encryption key (same as used for encryption)
    
    Returns:
        Decrypted content as bytes
    """
    # Decode from base64
    encrypted_data = base64.b64decode(encrypted_content)
    
    # Extract nonce and ciphertext
    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]
    
    # Derive the same key
    key_hash = hashes.Hash(hashes.SHA256(), backend=default_backend())
    key_hash.update(key.encode('utf-8'))
    derived_key = key_hash.finalize()
    
    # Decrypt
    aesgcm = AESGCM(derived_key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    
    return plaintext
