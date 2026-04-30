"""
API v1 — Endpoints de autenticación JWT.

POST /api/v1/auth/login    → access_token + refresh_token
POST /api/v1/auth/refresh  → rota refresh y emite nuevo access_token
POST /api/v1/auth/logout   → revoca refresh_token
GET  /api/v1/auth/me       → datos del usuario autenticado
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, g
from werkzeug.security import check_password_hash

from services.auth.jwt_handler import (
    create_access_token, generate_refresh_token, hash_token, ACCESS_TTL, REFRESH_TTL,
)
from services.auth.decorators import jwt_required
from services.db_layer import control_plane_cursor, tenant_cursor

api_auth_bp = Blueprint('api_auth', __name__, url_prefix='/api/v1/auth')


def _err(code, message, status=400):
    return jsonify({'error': {'code': code, 'message': message}}), status


def _get_modules(db_name):
    """Obtiene módulos activos del tenant. Retorna lista vacía si falla."""
    try:
        with tenant_cursor(db_name=db_name, dict_cursor=True) as cur:
            cur.execute(
                "SELECT modulo_code FROM saas_tenant_modules WHERE estado = 'activo'"
            )
            return [row['modulo_code'] for row in cur.fetchall()]
    except Exception:
        return []


# ──────────────────────────────────────────────
# POST /api/v1/auth/login
# ──────────────────────────────────────────────

@api_auth_bp.route('/login', methods=['POST'])
def login():
    data       = request.get_json(silent=True) or {}
    email      = (data.get('email') or '').strip().lower()
    password   = data.get('password') or ''
    device_id  = data.get('device_id') or str(uuid.uuid4())
    device_name = data.get('device_name') or 'API Client'

    if not email or not password:
        return _err('MISSING_FIELDS', 'email y password son requeridos.', 400)

    try:
        with control_plane_cursor() as cur:
            cur.execute(
                '''
                SELECT u.id, u.email, u.contraseña, u.rol_id, u.tenant_id, u.estado,
                       t.slug  AS tenant_slug,
                       td.db_name
                FROM   usuarios_globales u
                JOIN   tenants          t  ON t.id  = u.tenant_id
                JOIN   tenant_databases td ON td.tenant_id = u.tenant_id
                WHERE  u.email = %s
                ''',
                (email,),
            )
            user = cur.fetchone()
    except Exception as exc:
        from flask import current_app
        current_app.logger.error('Login DB error: %s', exc)
        return _err('SERVER_ERROR', 'Error del servidor.', 500)

    if not user or not check_password_hash(user['contraseña'], password):
        return _err('INVALID_CREDENTIALS', 'Correo o contraseña incorrectos.', 401)

    if user['estado'] != 'habilitado':
        return _err('ACCOUNT_DISABLED', 'Tu cuenta está inhabilitada.', 403)

    modules      = _get_modules(user['db_name'])
    access_token = create_access_token(
        user_id=user['id'],
        tenant_id=user['tenant_id'],
        rol_id=user['rol_id'],
        modules=modules,
        db_name=user['db_name'],
        device_id=device_id,
    )
    raw_refresh, refresh_hash = generate_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=REFRESH_TTL)

    try:
        with control_plane_cursor() as cur:
            cur.execute(
                '''
                INSERT INTO refresh_tokens
                    (token_hash, user_id, device_id, device_name, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                ''',
                (refresh_hash, user['id'], device_id, device_name, expires_at),
            )
            cur.execute(
                'UPDATE usuarios_globales SET last_login_at = NOW() WHERE id = %s',
                (user['id'],),
            )
    except Exception as exc:
        from flask import current_app
        current_app.logger.error('Login token store error: %s', exc)
        return _err('SERVER_ERROR', 'Error al crear sesión.', 500)

    return jsonify({
        'access_token':  access_token,
        'refresh_token': raw_refresh,
        'token_type':    'Bearer',
        'expires_in':    ACCESS_TTL,
        'user': {
            'id':        user['id'],
            'email':     user['email'],
            'rol_id':    user['rol_id'],
            'tenant_id': user['tenant_id'],
            'modules':   modules,
        },
        'tenant': {
            'id':      user['tenant_id'],
            'slug':    user['tenant_slug'],
            'db_name': user['db_name'],
        },
    }), 200


# ──────────────────────────────────────────────
# POST /api/v1/auth/refresh
# ──────────────────────────────────────────────

@api_auth_bp.route('/refresh', methods=['POST'])
def refresh():
    data        = request.get_json(silent=True) or {}
    raw_refresh = data.get('refresh_token') or ''

    if not raw_refresh:
        return _err('MISSING_TOKEN', 'refresh_token es requerido.', 400)

    token_hash = hash_token(raw_refresh)

    try:
        with control_plane_cursor() as cur:
            cur.execute(
                '''
                SELECT rt.*, u.tenant_id, u.rol_id, u.estado,
                       td.db_name
                FROM   refresh_tokens   rt
                JOIN   usuarios_globales u  ON u.id  = rt.user_id
                JOIN   tenant_databases  td ON td.tenant_id = u.tenant_id
                WHERE  rt.token_hash = %s
                ''',
                (token_hash,),
            )
            record = cur.fetchone()

            if not record:
                return _err('INVALID_TOKEN', 'Token de refresco inválido.', 401)
            if record['revoked_at']:
                return _err('TOKEN_REVOKED', 'Token de refresco revocado.', 401)
            now = datetime.now(timezone.utc)
            exp = record['expires_at']
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < now:
                return _err('TOKEN_EXPIRED', 'Token de refresco expirado.', 401)
            if record['estado'] != 'habilitado':
                return _err('ACCOUNT_DISABLED', 'Cuenta inhabilitada.', 403)

            # Rotación: revocar viejo, crear nuevo
            new_raw, new_hash = generate_refresh_token()
            new_expires = now + timedelta(seconds=REFRESH_TTL)

            cur.execute(
                'UPDATE refresh_tokens SET revoked_at = NOW() WHERE token_hash = %s',
                (token_hash,),
            )
            cur.execute(
                '''
                INSERT INTO refresh_tokens
                    (token_hash, user_id, device_id, device_name, expires_at, last_used_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ''',
                (new_hash, record['user_id'], record['device_id'],
                 record['device_name'], new_expires),
            )
    except Exception as exc:
        from flask import current_app
        current_app.logger.error('Refresh error: %s', exc)
        return _err('SERVER_ERROR', 'Error del servidor.', 500)

    access_token = create_access_token(
        user_id=record['user_id'],
        tenant_id=record['tenant_id'],
        rol_id=record['rol_id'],
        modules=_get_modules(record['db_name']),
        db_name=record['db_name'],
        device_id=record['device_id'],
    )

    return jsonify({
        'access_token':  access_token,
        'refresh_token': new_raw,
        'token_type':    'Bearer',
        'expires_in':    ACCESS_TTL,
    }), 200


# ──────────────────────────────────────────────
# POST /api/v1/auth/logout
# ──────────────────────────────────────────────

@api_auth_bp.route('/logout', methods=['POST'])
@jwt_required
def logout():
    data        = request.get_json(silent=True) or {}
    raw_refresh = data.get('refresh_token') or ''

    if raw_refresh:
        token_hash = hash_token(raw_refresh)
        try:
            with control_plane_cursor() as cur:
                cur.execute(
                    'UPDATE refresh_tokens SET revoked_at = NOW() '
                    'WHERE token_hash = %s AND user_id = %s',
                    (token_hash, g.current_user_id),
                )
        except Exception as exc:
            from flask import current_app
            current_app.logger.error('Logout error: %s', exc)

    return jsonify({'message': 'Sesión cerrada exitosamente.'}), 200


# ──────────────────────────────────────────────
# GET /api/v1/auth/me
# ──────────────────────────────────────────────

@api_auth_bp.route('/me', methods=['GET'])
@jwt_required
def me():
    try:
        with control_plane_cursor() as cur:
            cur.execute(
                '''
                SELECT u.id, u.email, u.rol_id, u.tenant_id, u.estado, u.last_login_at,
                       t.slug    AS tenant_slug,
                       t.nombre  AS tenant_nombre,
                       td.db_name
                FROM   usuarios_globales u
                JOIN   tenants          t  ON t.id  = u.tenant_id
                JOIN   tenant_databases td ON td.tenant_id = u.tenant_id
                WHERE  u.id = %s
                ''',
                (g.current_user_id,),
            )
            user = cur.fetchone()
    except Exception:
        return _err('SERVER_ERROR', 'Error del servidor.', 500)

    if not user:
        return _err('NOT_FOUND', 'Usuario no encontrado.', 404)

    last_login = user['last_login_at']
    return jsonify({
        'user': {
            'id':           user['id'],
            'email':        user['email'],
            'rol_id':       user['rol_id'],
            'tenant_id':    user['tenant_id'],
            'estado':       user['estado'],
            'last_login_at': last_login.isoformat() if last_login else None,
        },
        'tenant': {
            'slug':    user['tenant_slug'],
            'nombre':  user['tenant_nombre'],
            'db_name': user['db_name'],
        },
    }), 200
