"""
Resolución del tenant activo para cada request.

Puebla g.current_tenant desde:
  1. Bearer JWT (requests de la API REST)
  2. Flask session (requests HTML legacy)
  3. Default de env vars (rutas públicas / antes del login)

Llamar desde app.before_request:
    from services.tenant_resolver import resolve_current_tenant
    app.before_request(resolve_current_tenant)
"""

import os
from flask import g, session, request

_DEFAULT_TENANT = {
    'id':      int(os.getenv('DEFAULT_TENANT_ID', '1')),
    'slug':    os.getenv('DEFAULT_TENANT_SLUG', 'cyber-t001'),
    'db_name': os.getenv('DB_NAME', 'cybershop'),
}


def resolve_current_tenant():
    """Puebla g.current_tenant. Sin excepciones: usa default si falla cualquier lookup."""
    # — Vía JWT (API) —
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:]
        try:
            from services.auth.jwt_handler import decode_access_token
            payload = decode_access_token(token)
            g.current_tenant = {
                'id':      payload.get('tenant_id'),
                'db_name': payload.get('db_name') or _DEFAULT_TENANT['db_name'],
                'slug':    payload.get('tenant_slug', _DEFAULT_TENANT['slug']),
            }
            return
        except Exception:
            pass  # Token inválido → el decorador @jwt_required lo rechazará

    # — Vía sesión HTML —
    if session.get('tenant_id'):
        g.current_tenant = {
            'id':      session['tenant_id'],
            'db_name': session.get('tenant_db_name', _DEFAULT_TENANT['db_name']),
            'slug':    session.get('tenant_slug',    _DEFAULT_TENANT['slug']),
        }
        return

    # — Default (rutas públicas, antes del login) —
    g.current_tenant = _DEFAULT_TENANT.copy()
