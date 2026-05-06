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

VALID_ENTITIES = {'sale', 'inventory_movement', 'product', 'user'}
VALID_ACTIONS = {'create', 'update', 'delete'}
DEFAULT_GENERO_NAME = 'POS Desktop'
DEFAULT_IMAGE = '/static/img/no-image.png'


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

    Por defecto solo devuelve productos active=TRUE. Pasar
    ?include_inactive=1 para que el desktop pueda refrescar tombstones.
    Cursor: timestamp del producto mas reciente.
    """
    since = _parse_iso(request.args.get('since'))
    limit = min(int(request.args.get('limit', 1000)), 5000)
    include_inactive = request.args.get('include_inactive') == '1'

    where_parts = []
    params = []
    if since:
        where_parts.append('p.updated_at > %s')
        params.append(since)
    if not include_inactive:
        where_parts.append('p.active = TRUE')
    where_sql = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    sql = f"""
        SELECT p.id, p.referencia AS sku, p.barcode, p.nombre AS name, p.precio AS price,
               p.stock, p.descripcion, p.genero_id, g.nombre AS category,
               p.imagen, p.active, p.updated_at
        FROM productos p
        LEFT JOIN generos g ON g.id = p.genero_id
        {where_sql}
        ORDER BY p.updated_at ASC
        LIMIT %s
    """
    params.append(limit)
    with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    items = []
    cursor_iso = None
    for row in rows:
        updated_iso = _iso(row['updated_at'])
        cursor_iso = updated_iso
        items.append({
            'remote_id': int(row['id']),
            'sku': row['sku'],
            'barcode': row['barcode'] or '',
            'name': row['name'],
            'price': float(row['price'] or 0),
            'stock': int(row['stock'] or 0),
            'category': row['category'] or 'General',
            'genero_id': int(row['genero_id']) if row['genero_id'] else None,
            'description': row['descripcion'] or '',
            'image': row['imagen'] or '',
            'active': bool(row['active']),
            'updated_at': updated_iso,
        })

    return jsonify({
        'items': items,
        'count': len(items),
        'cursor': cursor_iso,
        'server_time': _now_iso(),
    })


def _iso(value):
    if value is None:
        return _now_iso()
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


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
                if entity == 'sale' and action == 'create':
                    remote_id = _apply_sale(cur, payload)
                elif entity == 'inventory_movement' and action == 'create':
                    remote_id = _apply_inventory_movement(cur, payload)
                elif entity == 'product':
                    remote_id = _apply_product(cur, action, payload)
                elif entity == 'user':
                    remote_id = _apply_user(cur, action, payload)
                else:
                    raise ValueError(f'combinacion no soportada: {entity}/{action}')
                results.append({
                    'local_id': local_id, 'status': 'applied',
                    'remote_id': remote_id, 'error': None,
                })
            except _DuplicateError as dup:
                results.append({
                    'local_id': local_id, 'status': 'skipped',
                    'remote_id': dup.remote_id, 'error': 'duplicate',
                })
            except _StaleError as stale:
                # LWW: el server ya tiene una version mas nueva; cliente debe pull
                results.append({
                    'local_id': local_id, 'status': 'stale',
                    'remote_id': stale.remote_id, 'error': 'newer_on_server',
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


class _StaleError(Exception):
    """LWW: el cliente envio una version mas vieja que la del server."""
    def __init__(self, remote_id):
        super().__init__(f'stale remote_id={remote_id}')
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
        quantity = int(it.get('quantity') or 0)
        product_id = None
        stock_before = None
        stock_after = None

        if sku:
            cur.execute('SELECT id, stock FROM productos WHERE referencia = %s', (sku,))
            prod = cur.fetchone()
            if prod:
                product_id = int(prod['id'])
                stock_before = int(prod['stock'] or 0)

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
                quantity,
                float(it.get('unit_price') or 0),
                float(it.get('line_total') or 0),
            ),
        )

        # Descontar stock central + audit en inventario_log si el producto existe
        if product_id and quantity > 0:
            cur.execute(
                'UPDATE productos SET stock = stock - %s WHERE id = %s',
                (quantity, product_id),
            )
            stock_after = (stock_before or 0) - quantity
            try:
                cur.execute(
                    """
                    INSERT INTO inventario_log
                      (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, usuario_id)
                    VALUES (%s, 'VENTA', %s, %s, %s, %s, NULL)
                    """,
                    (product_id, quantity, stock_before, stock_after,
                     f'POS desktop {receipt}'),
                )
            except Exception:
                # inventario_log es auditoria opcional; no fallar venta si schema cambia
                pass

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


# ──────────────────────────────────────────────
# Apply: producto (create/update/delete con LWW)
# ──────────────────────────────────────────────

def _apply_product(cur, action, payload):
    """Aplica un producto del desktop al VPS con Last-Write-Wins.

    payload obligatorio: sku. Opcional: barcode, name, price, stock, category,
    genero_id, description, image, active, updated_at (cliente).
    Match por referencia=sku. Si existe y server.updated_at > client.updated_at,
    lanza _StaleError sin escribir. Si no existe y action != delete, crea.
    """
    sku = (payload.get('sku') or '').strip()
    if not sku:
        raise ValueError('sku es obligatorio')

    client_updated = _parse_iso(payload.get('updated_at'))

    cur.execute(
        'SELECT id, updated_at, active FROM productos WHERE referencia = %s',
        (sku,),
    )
    existing = cur.fetchone()

    if action == 'delete':
        if not existing:
            return None  # nada que borrar
        if client_updated and existing['updated_at'] and client_updated < existing['updated_at']:
            raise _StaleError(int(existing['id']))
        cur.execute('UPDATE productos SET active = FALSE WHERE id = %s', (existing['id'],))
        return int(existing['id'])

    # CREATE / UPDATE
    name = (payload.get('name') or sku)[:100]
    price = float(payload.get('price') or 0)
    stock = int(payload.get('stock') or 0)
    barcode = (payload.get('barcode') or '').strip() or None
    description = (payload.get('description') or '')[:1000]
    image = (payload.get('image') or '').strip() or DEFAULT_IMAGE
    active = bool(payload.get('active', True))
    genero_id = payload.get('genero_id')

    if genero_id is None:
        # Si no especificaron, usar/crear genero default "POS Desktop"
        cur.execute('SELECT id FROM generos WHERE nombre = %s', (DEFAULT_GENERO_NAME,))
        g_row = cur.fetchone()
        if g_row:
            genero_id = int(g_row['id'])
        else:
            cur.execute('INSERT INTO generos (nombre) VALUES (%s) RETURNING id', (DEFAULT_GENERO_NAME,))
            genero_id = int(cur.fetchone()['id'])

    if existing:
        if client_updated and existing['updated_at'] and client_updated < existing['updated_at']:
            raise _StaleError(int(existing['id']))
        cur.execute(
            """
            UPDATE productos
            SET nombre = %s, precio = %s, stock = %s, barcode = %s,
                descripcion = %s, imagen = %s, active = %s, genero_id = %s
            WHERE id = %s
            """,
            (name, price, stock, barcode, description, image, active, genero_id, existing['id']),
        )
        return int(existing['id'])

    cur.execute(
        """
        INSERT INTO productos
          (referencia, nombre, precio, stock, barcode, descripcion,
           imagen, active, genero_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (sku, name, price, stock, barcode, description, image, active, genero_id),
    )
    return int(cur.fetchone()['id'])


# ──────────────────────────────────────────────
# Apply: usuario (solo perfil, sin password)
# ──────────────────────────────────────────────

def _apply_user(cur, action, payload):
    """Sincroniza perfil de usuario (sin password).

    payload: email, nombre, rol_nombre (string del rol), estado, updated_at.
    Match por email. Para crear, password_hash queda con un valor random
    invalido (el usuario debe resetearlo en el otro lado).
    """
    import secrets as _sec
    email = (payload.get('email') or '').strip().lower()
    if not email or '@' not in email:
        raise ValueError('email invalido')

    nombre = (payload.get('nombre') or payload.get('name') or email)[:100]
    rol_nombre = (payload.get('rol_nombre') or payload.get('role') or 'Cajero').strip()
    estado = (payload.get('estado') or 'habilitado').strip()
    client_updated = _parse_iso(payload.get('updated_at'))

    # Resolver rol_id por nombre
    cur.execute('SELECT id FROM roles WHERE LOWER(nombre) = LOWER(%s)', (rol_nombre,))
    r = cur.fetchone()
    if not r:
        # Fallback: rol "Cajero" o el primero disponible
        cur.execute("SELECT id FROM roles WHERE LOWER(nombre) = 'cajero' LIMIT 1")
        r = cur.fetchone()
        if not r:
            cur.execute('SELECT id FROM roles ORDER BY id LIMIT 1')
            r = cur.fetchone()
    if not r:
        raise ValueError('No hay roles definidos en el VPS')
    rol_id = int(r['id'])

    cur.execute('SELECT id, updated_at FROM usuarios WHERE LOWER(email) = LOWER(%s)', (email,))
    existing = cur.fetchone()

    if action == 'delete':
        if not existing:
            return None
        if client_updated and existing['updated_at'] and client_updated < existing['updated_at']:
            raise _StaleError(int(existing['id']))
        cur.execute("UPDATE usuarios SET estado = 'deshabilitado' WHERE id = %s", (existing['id'],))
        return int(existing['id'])

    if existing:
        if client_updated and existing['updated_at'] and client_updated < existing['updated_at']:
            raise _StaleError(int(existing['id']))
        cur.execute(
            """
            UPDATE usuarios SET nombre = %s, rol_id = %s, estado = %s
            WHERE id = %s
            """,
            (nombre, rol_id, estado, existing['id']),
        )
        return int(existing['id'])

    # Crear con password placeholder (no usable hasta reset)
    placeholder_hash = 'PLACEHOLDER_RESET_REQUIRED_' + _sec.token_hex(8)
    cur.execute(
        """
        INSERT INTO usuarios (nombre, email, "contraseña", rol_id, estado)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (nombre, email, placeholder_hash, rol_id, estado),
    )
    return int(cur.fetchone()['id'])


# ──────────────────────────────────────────────
# Endpoints GET pull-only (read from VPS to desktop)
# ──────────────────────────────────────────────

@api_sync_bp.route('/users', methods=['GET'])
@require_sync_key
def users():
    since = _parse_iso(request.args.get('since'))
    limit = min(int(request.args.get('limit', 1000)), 5000)

    where = ['u.estado != %s'] if not request.args.get('include_disabled') else []
    params = ['eliminado'] if not request.args.get('include_disabled') else []
    if since:
        where.append('u.updated_at > %s')
        params.append(since)
    where_sql = ('WHERE ' + ' AND '.join(where)) if where else ''
    sql = f"""
        SELECT u.id, u.email, u.nombre, u.estado, u.updated_at,
               r.nombre AS rol_nombre, u.rol_id
        FROM usuarios u
        LEFT JOIN roles r ON r.id = u.rol_id
        {where_sql}
        ORDER BY u.updated_at ASC
        LIMIT %s
    """
    params.append(limit)
    with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    items = []
    cursor_iso = None
    for row in rows:
        cursor_iso = _iso(row['updated_at'])
        items.append({
            'remote_id': int(row['id']),
            'email': row['email'],
            'nombre': row['nombre'],
            'rol_nombre': row['rol_nombre'] or 'Cajero',
            'estado': row['estado'] or 'habilitado',
            'updated_at': cursor_iso,
        })
    return jsonify({'items': items, 'count': len(items), 'cursor': cursor_iso, 'server_time': _now_iso()})


@api_sync_bp.route('/generos', methods=['GET'])
@require_sync_key
def generos():
    since = _parse_iso(request.args.get('since'))
    limit = min(int(request.args.get('limit', 500)), 5000)
    sql = "SELECT id, nombre, updated_at FROM generos"
    params = []
    if since:
        sql += " WHERE updated_at > %s"
        params.append(since)
    sql += " ORDER BY updated_at ASC LIMIT %s"
    params.append(limit)

    with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    items = []
    cursor_iso = None
    for row in rows:
        cursor_iso = _iso(row['updated_at'])
        items.append({
            'remote_id': int(row['id']),
            'nombre': row['nombre'],
            'updated_at': cursor_iso,
        })
    return jsonify({'items': items, 'count': len(items), 'cursor': cursor_iso, 'server_time': _now_iso()})


@api_sync_bp.route('/sales_web', methods=['GET'])
@require_sync_key
def sales_web():
    """Pedidos del ecommerce web (PayU). Read-only para el desktop."""
    since = _parse_iso(request.args.get('since'))
    limit = min(int(request.args.get('limit', 200)), 1000)
    sql = """
        SELECT id, referencia_pedido, cliente_nombre, cliente_email,
               estado_pago, estado_envio, monto_total, metodo_pago,
               fecha_creacion, fecha_actualizacion
        FROM pedidos
    """
    params = []
    if since:
        sql += " WHERE fecha_actualizacion > %s"
        params.append(since)
    sql += " ORDER BY fecha_actualizacion ASC LIMIT %s"
    params.append(limit)
    with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    items = []
    cursor_iso = None
    for row in rows:
        cursor_iso = _iso(row['fecha_actualizacion'])
        items.append({
            'remote_id': int(row['id']),
            'reference': row['referencia_pedido'],
            'customer_name': row['cliente_nombre'],
            'customer_email': row['cliente_email'],
            'status_payment': row['estado_pago'],
            'status_shipping': row['estado_envio'],
            'total': float(row['monto_total'] or 0),
            'payment_method': row['metodo_pago'],
            'created_at': _iso(row['fecha_creacion']),
            'updated_at': cursor_iso,
        })
    return jsonify({'items': items, 'count': len(items), 'cursor': cursor_iso, 'server_time': _now_iso()})


@api_sync_bp.route('/inventory_log', methods=['GET'])
@require_sync_key
def inventory_log():
    since = _parse_iso(request.args.get('since'))
    limit = min(int(request.args.get('limit', 500)), 2000)
    # Verificar que la tabla exista. Si no, devolver vacio.
    with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
        cur.execute("SELECT to_regclass('public.inventario_log') AS t")
        if not cur.fetchone()['t']:
            return jsonify({'items': [], 'count': 0, 'cursor': None, 'server_time': _now_iso()})
        sql = """
            SELECT il.id, il.producto_id, p.referencia AS sku, p.nombre AS product_name,
                   il.tipo, il.cantidad, il.stock_anterior, il.stock_nuevo,
                   il.motivo, il.fecha
            FROM inventario_log il
            LEFT JOIN productos p ON p.id = il.producto_id
        """
        params = []
        if since:
            sql += " WHERE il.fecha > %s"
            params.append(since)
        sql += " ORDER BY il.fecha ASC LIMIT %s"
        params.append(limit)
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    items = []
    cursor_iso = None
    for row in rows:
        cursor_iso = _iso(row['fecha'])
        # Normalizar a quantity_delta firmado: salida -> negativo, entrada -> positivo
        cantidad = int(row['cantidad'] or 0)
        tipo = (row['tipo'] or '').lower()
        delta = -cantidad if tipo in ('salida', 'venta', 'out') else cantidad
        items.append({
            'remote_id': int(row['id']),
            'sku': row['sku'],
            'product_name': row['product_name'],
            'tipo': row['tipo'],
            'quantity_delta': delta,
            'stock_anterior': row['stock_anterior'],
            'stock_nuevo': row['stock_nuevo'],
            'reason': row['motivo'],
            'created_at': cursor_iso,
        })
    return jsonify({'items': items, 'count': len(items), 'cursor': cursor_iso, 'server_time': _now_iso()})
