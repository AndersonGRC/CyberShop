"""
Resolución del tenant activo para cada request.

Cada instancia web tiene una única base de datos configurada. La identidad de
un JWT o de una sesión puede confirmar esa instancia, pero nunca elegir otra
base de datos para las rutas web o del panel.

Llamar desde app.before_request:
    from services.tenant_resolver import resolve_current_tenant
    app.before_request(resolve_current_tenant)
"""

import os
from flask import abort, g, session, request

_DEFAULT_TENANT = {
    'id':      int(os.getenv('DEFAULT_TENANT_ID', '1')),
    'slug':    os.getenv('DEFAULT_TENANT_SLUG', 'cyber-t001'),
    'db_name': os.getenv('DB_NAME', 'cybershop'),
}


def resolve_current_tenant():
    """Puebla g.current_tenant y rechaza credenciales de otra instancia."""
    g.current_tenant = _DEFAULT_TENANT.copy()
    # — Vía JWT (API) —
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:]
        try:
            from services.auth.jwt_handler import decode_access_token
            payload = decode_access_token(token)
        except Exception:
            pass  # Token inválido → el decorador @jwt_required lo rechazará
        else:
            # El JWT es una afirmación firmada, no autorización para abrir una
            # BD diferente desde el dominio de esta instancia.
            if (payload.get('tenant_id') != _DEFAULT_TENANT['id']
                    or payload.get('db_name') != _DEFAULT_TENANT['db_name']):
                abort(403)
            return

    # — Vía sesión HTML —
    # En las tablas locales el tenant_id de la sesión puede ser 1 aunque el id
    # global del control plane sea otro. Solo se compara el nombre de BD cuando
    # una sesión legacy lo conserva; la BD efectiva siempre es la configurada.
    session_db = session.get('tenant_db_name')
    if session_db and session_db != _DEFAULT_TENANT['db_name']:
        abort(403)
