"""
Decoradores de autorización JWT para blueprints de la API REST.

@jwt_required         — verifica Bearer token y puebla g.jwt_payload / g.current_user_id
@jwt_role_required([rol_ids]) — igual + verifica que rol_id esté en la lista permitida
"""

from functools import wraps

import jwt as pyjwt
from flask import request, jsonify, g

from services.auth.jwt_handler import decode_access_token


def _bearer_error(code, message, status):
    return jsonify({'error': {'code': code, 'message': message}}), status


def jwt_required(f):
    """Exige Bearer token válido. Puebla g.jwt_payload y g.current_user_id."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return _bearer_error('MISSING_TOKEN', 'Se requiere Authorization: Bearer <token>.', 401)
        token = auth[7:]
        try:
            payload = decode_access_token(token)
        except pyjwt.ExpiredSignatureError:
            return _bearer_error('TOKEN_EXPIRED', 'El token de acceso ha expirado.', 401)
        except pyjwt.InvalidTokenError:
            return _bearer_error('INVALID_TOKEN', 'Token inválido o con firma incorrecta.', 401)
        g.jwt_payload      = payload
        g.current_user_id  = int(payload['sub'])
        g.current_tenant_id = payload.get('tenant_id')
        return f(*args, **kwargs)
    return decorated


def jwt_role_required(allowed_roles):
    """Exige Bearer token válido Y que rol_id esté en allowed_roles.

    Uso: @jwt_role_required([1, 2])
    """
    def decorator(f):
        @wraps(f)
        @jwt_required
        def decorated(*args, **kwargs):
            if g.jwt_payload.get('rol_id') not in allowed_roles:
                return _bearer_error(
                    'FORBIDDEN',
                    'No tienes permiso para realizar esta acción.',
                    403,
                )
            return f(*args, **kwargs)
        return decorated
    return decorator
