"""
API v1 — Health check endpoint.

GET /api/v1/health  → {status, db, redis, version}

Endpoint público (sin auth). Usado por Caddy, monitoreo externo y
el panel superadmin para verificar que el servicio está operativo.
"""

import os
from flask import Blueprint, jsonify

api_health_bp = Blueprint('api_health', __name__, url_prefix='/api/v1')

APP_VERSION = os.getenv('APP_VERSION', '1.0.0')


@api_health_bp.route('/health', methods=['GET'])
def health():
    result = {'status': 'ok', 'version': APP_VERSION, 'db': 'unknown', 'redis': 'unknown'}
    http_status = 200

    # Verificar DB tenant (la que sirve la app)
    try:
        from services.db_layer import get_tenant_conn
        conn = get_tenant_conn()
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
        conn.close()
        result['db'] = 'ok'
    except Exception:
        result['db'] = 'error'
        result['status'] = 'degraded'
        http_status = 503

    # Verificar Redis (opcional en Fase 1 local)
    redis_url = os.getenv('REDIS_URL', '')
    if redis_url:
        try:
            import redis as redis_lib
            r = redis_lib.from_url(redis_url, socket_connect_timeout=2)
            r.ping()
            result['redis'] = 'ok'
        except Exception:
            result['redis'] = 'error'
            # Redis caído no marca la app como degradada en Fase 1
    else:
        result['redis'] = 'not_configured'

    return jsonify(result), http_status
