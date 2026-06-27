import base64
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


priv_b64 = "SNdy4S3nZjssC4dqpaVDucTBCz9XiAF37axOgwZlxHs"
raw = base64.urlsafe_b64decode(priv_b64 + "=" * (-len(priv_b64) % 4))
sk = X25519PrivateKey.from_private_bytes(raw)
pk = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
print("FR private:", priv_b64)
print("FR public :", b64u(pk))
print("current fr-out pub on U4: YNwi7rTLFpF27P1EJuur... (OLD dead server 109.61.110.125)")
