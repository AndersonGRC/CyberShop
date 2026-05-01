"""
Manejo de JWT y refresh tokens para la API REST de CyberShop.

Soporta RS256 (producción, con par de claves RSA) y HS256 (desarrollo,
usando FLASK_SECRET_KEY). Si JWT_PRIVATE_KEY_PATH está definido y el
archivo existe, usa RS256 automáticamente.
"""

import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone

import jwt as pyjwt

ACCESS_TTL  = int(os.getenv('JWT_ACCESS_TTL_SECONDS', '900'))    # 15 min
REFRESH_TTL = int(os.getenv('JWT_REFRESH_TTL_SECONDS', '2592000'))  # 30 días


def _rsa_private_key():
    path = os.getenv('JWT_PRIVATE_KEY_PATH', '')
    if path and os.path.isfile(path):
        with open(path, 'rb') as f:
            return f.read()
    return None


def _rsa_public_key():
    path = os.getenv('JWT_PUBLIC_KEY_PATH', '')
    if path and os.path.isfile(path):
        with open(path, 'rb') as f:
            return f.read()
    return None


def _algorithm():
    return 'RS256' if _rsa_private_key() else 'HS256'


def _encode_key():
    if _algorithm() == 'RS256':
        return _rsa_private_key()
    secret = os.getenv('FLASK_SECRET_KEY')
    if not secret:
        raise RuntimeError('FLASK_SECRET_KEY no configurada para JWT HS256.')
    return secret


def _decode_key():
    if _algorithm() == 'RS256':
        key = _rsa_public_key()
        if not key:
            raise RuntimeError('JWT_PUBLIC_KEY_PATH no encontrada para RS256.')
        return key
    return _encode_key()


def create_access_token(user_id, tenant_id, rol_id, modules, db_name, device_id=None):
    """Genera un access token JWT firmado."""
    now = datetime.now(timezone.utc)
    payload = {
        'sub':       str(user_id),
        'tenant_id': tenant_id,
        'rol_id':    rol_id,
        'modules':   list(modules) if modules else [],
        'db_name':   db_name,
        'device_id': str(device_id) if device_id else None,
        'iat':       now,
        'exp':       now + timedelta(seconds=ACCESS_TTL),
        'jti':       secrets.token_hex(16),
    }
    return pyjwt.encode(payload, _encode_key(), algorithm=_algorithm())


def decode_access_token(token):
    """Valida y decodifica un access token. Lanza pyjwt.exceptions.* si falla."""
    return pyjwt.decode(
        token,
        _decode_key(),
        algorithms=[_algorithm()],
        options={'require': ['sub', 'exp', 'iat', 'tenant_id', 'rol_id']},
    )


def generate_refresh_token():
    """Retorna (raw_token, token_hash). Almacenar el hash; enviar el raw al cliente."""
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return raw, token_hash


def hash_token(raw_token):
    """SHA-256 del token para búsqueda en BD."""
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
