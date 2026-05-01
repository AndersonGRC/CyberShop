"""
Utilidades criptográficas para CyberShop.

sha256_hex     — hash de refresh tokens para almacenamiento seguro en BD.
aes_gcm_*      — cifrado de contraseñas de BD de tenants en el control plane.
                 Usa KMS_KEY (32 bytes, base64) de la variable de entorno.
"""

import base64
import hashlib
import os
import secrets


def sha256_hex(value: str) -> str:
    """Retorna SHA-256 de un string, en hexadecimal."""
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _kms_key() -> bytes:
    raw = os.getenv('KMS_KEY', '')
    if not raw:
        raise RuntimeError('KMS_KEY no configurada. Genera con: python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"')
    return base64.b64decode(raw)


def aes_gcm_encrypt(plaintext: str) -> str:
    """Cifra plaintext con AES-256-GCM. Retorna base64(nonce||ciphertext)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_kms_key()).encrypt(nonce, plaintext.encode('utf-8'), None)
    return base64.b64encode(nonce + ct).decode('utf-8')


def aes_gcm_decrypt(ciphertext_b64: str) -> str:
    """Descifra un valor cifrado con aes_gcm_encrypt."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    data = base64.b64decode(ciphertext_b64)
    nonce, ct = data[:12], data[12:]
    return AESGCM(_kms_key()).decrypt(nonce, ct, None).decode('utf-8')
