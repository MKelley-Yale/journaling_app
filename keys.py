"""VAPID key handling for web push. Keys are generated once and reused."""
import os
import json
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

HERE = os.path.dirname(__file__)
KEYS_JSON = os.path.join(HERE, "vapid_keys.json")
PRIVATE_PEM = os.path.join(HERE, "vapid_private.pem")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def ensure_vapid_keys():
    """Generate the VAPID keypair on first run; return (public_b64url, private_pem_path)."""
    if os.path.exists(KEYS_JSON) and os.path.exists(PRIVATE_PEM):
        with open(KEYS_JSON) as f:
            data = json.load(f)
        return data["public_key"], PRIVATE_PEM

    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key()
    raw_pub = pub.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = _b64url(raw_pub)
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")

    with open(PRIVATE_PEM, "w") as f:
        f.write(pem)
    with open(KEYS_JSON, "w") as f:
        json.dump({"public_key": public_b64}, f)
    return public_b64, PRIVATE_PEM
