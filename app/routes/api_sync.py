"""
API v1 — Endpoints de sincronizacion para la app de escritorio CyberShop.

Disenado para clientes POS que operan offline y necesitan:
  - PULL: bajar el catalogo de productos del tenant (cambios desde X fecha).
  - PUSH: subir ventas e inventario locales generados sin internet.

Auth: header `X-Sync-Key: <api_key>` validado contra SYNC_API_KEY de env.
Single-tenant en esta version: la key da acceso al DEFAULT_TENANT.
Para multi-tenant, mover a tabla `sync_api_keys(key_hash, tenant_id)`.

Endpoints:
  GET  /api/v1/sync/health     -> verifica key, devuelve tenant
  GET  /api/v1/sync/products   -> productos modificados desde ?since=<iso>
  POST /api/v1/sync/outbox     -> recibe lote {entity, action, payload}[]
"""

import os
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, g, jsonify, request

from services.db_layer import tenant_cursor

api_sync_bp = Blueprint('api_sync', __name__, url_prefix='/api/v1/sync')

VALID_ENTITIES = {'sale', 'inventory_movement'}
VALID_ACTIONS = {'create'}


# ──────────────────────────────────────────────
# Auth helper
# ──────────────────────────────────────────────

def _get_expected_key():
    return (os.getenv('SYNC_API_KEY') or '').strip()


def _get_default_db_name():
    return os.getenv('DB_NAME', 'cybershop')


def require_sync_key(fn):
    """Decorator que valida X-Sync-Key contra SYNC_API_KEY de env.

    Si pasa, setea g.sync_db_name al tenant default. Para multi-tenant
    extender resolviendo la key a un tenant_id especifico.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = _get_expected_key()
        if not expected:
            return jsonify({'error': {'code': 'sync_disabled', 'message': 'SYNC_API_KEY no configurada en el servidor.'}}), 503

        provided = (request.headers.get('X-Sync-Key') or '').strip()
        if not provided or not secrets.compare_digest(provided, expected):
            return jsonify({'error': {'code': 'invalid_key', 'message': 'API key invalida o ausente.'}}), 401

        g.sync_db_name = _get_default_db_name()
        return fn(*args, **kwargs)
    return wrapper


# ──────────────────────────────────────────────
# Helpers de fecha/tenant
# ──────────────────────────────────────────────

def _parse_iso(value):
    if not value:
        return None
    try:
        # Acepta '2026-05-04T10:00:00' o con zona/Z
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────
# GET /health
# ──────────────────────────────────────────────

@api_sync_bp.route('/health', methods=['GET'])
@require_sync_key
def health():
    return jsonify({
        'status': 'ok',
        'tenant_db': g.sync_db_name,
        'server_time': _now_iso(),
    })


# ──────────────────────────────────────────────
# GET /products
# ──────────────────────────────────────────────

@api_sync_bp.route('/products', methods=['GET'])
@require_sync_key
def products():
    """Devuelve productos del tenant modificados desde ?since=<iso>.

    Si ?since esta ausente o invalida, devuelve todo el catalogo.
    Cursor: timestamp del producto mas reciente para usar en la siguiente call.
    """
    since = _parse_iso(request.args.get('since'))
    limit = min(int(request.args.get('limit', 1000)), 5000)

    with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
        if since:
            cur.execute(
                """
                SELECT p.id, p.referencia AS sku, p.nombre AS name, p.precio AS price,
                       p.stock, p.descripcion, p.genero_id, g.nombre AS category,
                       p.updated_at
                FROM productos p
                LEFT JOIN generos g ON g.id = p.genero_id
                WHERE p.updated_at > %s
                ORDER BY p.updated_at ASC
                LIMIT %s
                """,
                (since, limit),
            )
        else:
            cur.execute(
                """
                SELECT p.id, p.referencia AS sku, p.nombre AS name, p.precio AS price,
                       p.stock, p.descripcion, p.genero_id, g.nombre AS category,
                       p.updated_at
                FROM productos p
                LEFT JOIN generos g ON g.id = p.genero_id
                ORDER BY p.updated_at ASC
                LIMIT %s
                """,
                (limit,),
            )
        rows = cur.fetchall()

    items = []
    cursor_iso = None
    for row in rows:
        updated = row['updated_at']
        if hasattr(updated, 'isoformat'):
            updated_iso = updated.isoformat()
        else:
            updated_iso = str(updated) if updated else _now_iso()
        cursor_iso = updated_iso
        items.append({
            'remote_id': int(row['id']),
            'sku': row['sku'],
            'name': row['name'],
            'price': float(row['price'] or 0),
            'stock': int(row['stock'] or 0),
            'category': row['category'] or 'General',
            'description': row['descripcion'] or '',
            'updated_at': updated_iso,
        })

    return jsonify({
        'items': items,
        'count': len(items),
        'cursor': cursor_iso,
        'server_time': _now_iso(),
    })


# ──────────────────────────────────────────────
# POST /outbox
# ──────────────────────────────────────────────

@api_sync_bp.route('/outbox', methods=['POST'])
@require_sync_key
def outbox():
    """Recibe un lote de items de la outbox del cliente.

    Body: {"items": [{"local_id":1, "entity":"sale|inventory_movement",
                       "action":"create", "payload": {...}}, ...]}
    Response: {"results": [{"local_id":1, "status":"applied|skipped|error",
                            "remote_id":42, "error":null}, ...]}
    """
    body = request.get_json(silent=True) or {}
    items = body.get('items') or []
    if not isinstance(items, list):
        return jsonify({'error': {'code': 'bad_request', 'message': 'items debe ser una lista'}}), 400

    results = []
    with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
        for item in items:
            local_id = item.get('local_id')
            entity = item.get('entity')
            action = item.get('action')
            payload = item.get('payload') or {}

            if entity not in VALID_ENTITIES or action not in VALID_ACTIONS:
                results.append({
                    'local_id': local_id, 'status': 'error', 'remote_id': None,
                    'error': f'entity/action no soportada: {entity}/{action}',
                })
                continue

            try:
                if entity == 'sale':
                    remote_id = _apply_sale(cur, payload)
                elif entity == 'inventory_movement':
                    remote_id = _apply_inventory_movement(cur, payload)
                else:
                    raise ValueError('entity no soportada')
                results.append({
                    'local_id': local_id, 'status': 'applied',
                    'remote_id': remote_id, 'error': None,
                })
            except _DuplicateError as dup:
                # Idempotencia: si ya se aplico antes, devolver el remote_id existente
                results.append({
                    'local_id': local_id, 'status': 'skipped',
                    'remote_id': dup.remote_id, 'error': 'duplicate',
                })
            except Exception as exc:  # noqa: BLE001
                results.append({
                    'local_id': local_id, 'status': 'error',
                    'remote_id': None, 'error': str(exc)[:200],
                })

    return jsonify({'results': results, 'server_time': _now_iso()})


# ──────────────────────────────────────────────
# Apply helpers
# ──────────────────────────────────────────────

class _DuplicateError(Exception):
    def __init__(self, remote_id):
        super().__init__(f'duplicate remote_id={remote_id}')
        self.remote_id = remote_id


def _apply_sale(cur, payload):
    """Inserta una venta del POS desktop.

    payload esperado:
      {receipt: 'LOCAL-0001', total: 50000.0,
       created_at_local: '2026-05-04T10:00:00',
       items: [{sku, name, quantity, unit_price, line_total}, ...]}
    """
    receipt = (payload.get('receipt') or '').strip()
    total = float(payload.get('total') or 0)
    created_local = payload.get('created_at_local')
    items = payload.get('items') or []
    if not receipt or not items:
        raise ValueError('receipt e items son obligatorios')

    cur.execute('SELECT id FROM pos_desktop_sales WHERE receipt_number = %s', (receipt,))
    row = cur.fetchone()
    if row:
        raise _DuplicateError(int(row['id']))

    cur.execute(
        """
        INSERT INTO pos_desktop_sales (receipt_number, total, created_at_local)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (receipt, total, created_local),
    )
    sale_id = int(cur.fetchone()['id'])

    for it in items:
        sku = (it.get('sku') or '').strip()
        product_id = None
        if sku:
            cur.execute('SELECT id FROM productos WHERE referencia = %s', (sku,))
            prod = cur.fetchone()
            if prod:
                product_id = int(prod['id'])
        cur.execute(
            """
            INSERT INTO pos_desktop_sale_items
              (sale_id, product_id, sku_snapshot, name_snapshot,
               quantity, unit_price, line_total)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                sale_id, product_id,
                sku or None,
                (it.get('name') or '')[:200],
                int(it.get('quantity') or 0),
                float(it.get('unit_price') or 0),
                float(it.get('line_total') or 0),
            ),
        )

    return sale_id


def _apply_inventory_movement(cur, payload):
    """Inserta un movimiento de inventario del POS desktop.

    payload esperado:
      {sku: 'PROD-001', quantity_delta: -5, reason: 'Venta LOCAL-0001',
       created_at_local: '...', client_movement_id: 'desktop-12'}
    """
    sku = (payload.get('sku') or '').strip()
    delta = int(payload.get('quantity_delta') or 0)
    reason = (payload.get('reason') or 'Ajuste desktop')[:200]
    created_local = payload.get('created_at_local')
    client_mov_id = (payload.get('client_movement_id') or '').strip()

    if not client_mov_id:
        raise ValueError('client_movement_id es obligatorio para idempotencia')

    cur.execute(
        'SELECT id FROM pos_desktop_inventory_movements WHERE client_movement_id = %s',
        (client_mov_id,),
    )
    row = cur.fetchone()
    if row:
        raise _DuplicateError(int(row['id']))

    product_id = None
    if sku:
        cur.execute('SELECT id FROM productos WHERE referencia = %s', (sku,))
        prod = cur.fetchone()
        if prod:
            product_id = int(prod['id'])

    cur.execute(
        """
        INSERT INTO pos_desktop_inventory_movements
          (client_movement_id, product_id, sku_snapshot, quantity_delta,
           reason, created_at_local)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_mov_id, product_id, sku or None, delta, reason, created_local),
    )
    return int(cur.fetchone()['id'])
