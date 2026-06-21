"""
API v1 — Endpoints de sincronizacion para la app de escritorio CyberShop.

Disenado para clientes POS que operan offline y necesitan:
  - PULL: bajar el catalogo de productos del tenant (cambios desde X fecha).
  - PUSH: subir ventas e inventario locales generados sin internet.

Auth: header `X-Sync-Key: <api_key>`.
  - Multi-tenant: lookup en saas_control_plane.sync_api_keys → resuelve tenant_id/db_name.
  - Backward-compat: si SYNC_API_KEY de env coincide, usa DEFAULT_TENANT.

Endpoints:
  GET  /api/v1/sync/health     -> verifica key, devuelve tenant
  GET  /api/v1/sync/products   -> productos modificados desde ?since=<iso>
  POST /api/v1/sync/outbox     -> recibe lote {entity, action, payload}[]
  GET  /api/v1/sync/branding   -> empresa + colores del tenant (cliente_config)
  GET  /api/v1/sync/config     -> info pública del tenant (slug, nombre)
  GET  /api/v1/sync/version    -> última versión disponible del desktop
"""

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import check_password_hash

from services.db_layer import control_plane_cursor, tenant_cursor

api_sync_bp = Blueprint('api_sync', __name__, url_prefix='/api/v1/sync')

VALID_ENTITIES = {'sale', 'inventory_movement', 'product', 'user', 'category', 'order', 'restaurant_op', 'contabilidad_op'}
VALID_ACTIONS = {'create', 'update', 'delete'}
DEFAULT_GENERO_NAME = 'POS Desktop'
DEFAULT_IMAGE = '/static/img/no-image.png'

# Constantes para el branding sync (claves que no existen en cliente_config y se completan con default)
_BRANDING_DESKTOP_DEFAULTS = {
    'peligro':  '#b42318',
    'fondo':    '#f8faff',
}

# Mapeo cliente_config.colores.<clave_web> -> branding.json.colores.<clave_desktop>
# Las claves no listadas aquí pasan tal cual.
_BRANDING_COLOR_MAP = {
    'secundario': 'sidebar_inicio',
    'botones':    'sidebar_fin',
}


# ──────────────────────────────────────────────
# Auth helper (multi-tenant)
# ──────────────────────────────────────────────

def _hash_key(raw_key):
    """SHA-256 hex del api_key (mismo formato que se persiste en sync_api_keys.key_hash)."""
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()


def _lookup_key_in_db(raw_key):
    """Devuelve (tenant_id, db_name, slug, key_id) o None si la key no existe/está inactiva."""
    key_hash = _hash_key(raw_key)
    try:
        with control_plane_cursor() as cur:
            cur.execute("""
                SELECT k.tenant_id, td.db_name, t.slug, k.id
                FROM sync_api_keys k
                JOIN tenant_databases td ON td.tenant_id = k.tenant_id
                JOIN tenants t           ON t.id        = k.tenant_id
                WHERE k.key_hash = %s AND k.active = TRUE
            """, (key_hash,))
            row = cur.fetchone()
        if not row:
            return None
        # cur con DictCursor: indexar por nombre y por posición funciona; ser explícito.
        return (row['tenant_id'], row['db_name'], row['slug'], row['id'])
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning('sync_api_keys lookup falló: %s (¿migración 0002 no aplicada?)', exc)
        return None


def _touch_key(key_id):
    """Actualiza last_used_at de la key. Best-effort, no bloquea la request si falla."""
    try:
        with control_plane_cursor() as cur:
            cur.execute(
                'UPDATE sync_api_keys SET last_used_at = NOW() WHERE id = %s',
                (key_id,),
            )
    except Exception:
        pass


def _legacy_env_key_matches(provided):
    """Backward-compat: si SYNC_API_KEY de env coincide, devuelve True."""
    expected = (os.getenv('SYNC_API_KEY') or '').strip()
    if not expected:
        return False
    return secrets.compare_digest(provided, expected)


def _default_tenant_info():
    return {
        'tenant_id': int(os.getenv('DEFAULT_TENANT_ID', '1')),
        'db_name':   os.getenv('DB_NAME', 'cybershop'),
        'slug':      os.getenv('DEFAULT_TENANT_SLUG', 'cyber-t001'),
    }


def require_sync_key(fn):
    """Decorator que valida X-Sync-Key y resuelve el tenant.

    Estrategia:
      1. Lookup en sync_api_keys (multi-tenant).
      2. Si no hay match, intenta la SYNC_API_KEY de env (legacy → DEFAULT_TENANT).

    Setea: g.sync_tenant_id, g.sync_db_name, g.sync_tenant_slug.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        provided = (request.headers.get('X-Sync-Key') or '').strip()
        if not provided:
            return jsonify({'error': {'code': 'invalid_key', 'message': 'API key ausente.'}}), 401

        match = _lookup_key_in_db(provided)
        if match:
            tenant_id, db_name, slug, key_id = match
            g.sync_tenant_id   = tenant_id
            g.sync_db_name     = db_name
            g.sync_tenant_slug = slug
            _touch_key(key_id)
            return fn(*args, **kwargs)

        if _legacy_env_key_matches(provided):
            info = _default_tenant_info()
            g.sync_tenant_id   = info['tenant_id']
            g.sync_db_name     = info['db_name']
            g.sync_tenant_slug = info['slug']
            return fn(*args, **kwargs)

        return jsonify({'error': {'code': 'invalid_key', 'message': 'API key invalida o inactiva.'}}), 401
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
                elif entity == 'category':
                    remote_id = _apply_category(cur, action, payload)
                elif entity == 'order':
                    remote_id = _apply_order(cur, action, payload)
                elif entity == 'restaurant_op':
                    remote_id = _apply_restaurant_op(cur, payload)
                elif entity == 'contabilidad_op':
                    remote_id = _apply_contabilidad_op(cur, payload)
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

    # Registrar en contabilidad como ingreso (idempotente por referencia)
    # Nota: sincronizar_movimiento_referencia abre su propia conexion/cursor
    # y commitea aparte. Si falla, no debe romper la sync de la venta.
    try:
        from routes.contabilidad import sincronizar_movimiento_referencia
        from datetime import datetime as _dt
        try:
            fecha_mov = _dt.fromisoformat((created_local or '').replace('Z', '+00:00')).date()
        except (TypeError, ValueError):
            fecha_mov = None
        sincronizar_movimiento_referencia(
            tipo='ingreso',
            categoria='venta_pos',
            descripcion=f'Venta POS desktop {receipt}',
            monto=total,
            fecha=fecha_mov,
            referencia_tipo='pos_desktop_sale',
            referencia_id=sale_id,
            usuario_id=None,
            auto_generado=True,
            notas=f'{len(items)} item(s)',
        )
    except Exception:
        # Contabilidad es opcional aqui; el log lo captura el helper
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
# Apply: category (CRUD sobre tabla generos)
# ──────────────────────────────────────────────

def _apply_category(cur, action, payload):
    """Sincroniza categoría (tabla generos).

    payload create/update: nombre (obligatorio), remote_id (opcional para update).
    payload delete: remote_id (obligatorio).
    Bloquea delete si la categoría tiene productos asociados.
    """
    if action == 'delete':
        remote_id = payload.get('remote_id')
        if not remote_id:
            raise ValueError('remote_id obligatorio para delete')
        cur.execute('SELECT COUNT(*) AS c FROM productos WHERE genero_id = %s', (int(remote_id),))
        cnt = int(cur.fetchone()['c'] or 0)
        if cnt > 0:
            raise ValueError(f'has_products: {cnt} producto(s) usan esta categoría')
        cur.execute('DELETE FROM generos WHERE id = %s', (int(remote_id),))
        return int(remote_id)

    nombre = (payload.get('nombre') or '').strip()
    if not nombre:
        raise ValueError('nombre obligatorio')
    if len(nombre) > 100:
        nombre = nombre[:100]

    if action == 'update':
        remote_id = payload.get('remote_id')
        if not remote_id:
            raise ValueError('remote_id obligatorio para update')
        # Si el nombre nuevo colisiona con otra categoría, error
        cur.execute(
            'SELECT id FROM generos WHERE LOWER(nombre) = LOWER(%s) AND id != %s',
            (nombre, int(remote_id)),
        )
        if cur.fetchone():
            raise ValueError(f'duplicate_name: ya existe una categoría con nombre "{nombre}"')
        cur.execute('UPDATE generos SET nombre = %s WHERE id = %s', (nombre, int(remote_id)))
        return int(remote_id)

    # CREATE — idempotente: si ya existe por nombre case-insensitive, devuelve el id (skipped vía duplicate).
    cur.execute('SELECT id FROM generos WHERE LOWER(nombre) = LOWER(%s)', (nombre,))
    row = cur.fetchone()
    if row:
        raise _DuplicateError(int(row['id']))
    cur.execute('INSERT INTO generos (nombre) VALUES (%s) RETURNING id', (nombre,))
    return int(cur.fetchone()['id'])


# ──────────────────────────────────────────────
# Apply: order (UPDATE de estado de pedidos web)
# ──────────────────────────────────────────────

def _apply_order(cur, action, payload):
    """Actualiza estado_pago / estado_envio de un pedido del ecommerce.

    Solo soporta action='update'. create/delete se rechazan (los pedidos los
    crea PayU, no el desktop).

    payload: remote_id, estado_pago, estado_envio, updated_at (cliente).
    """
    if action != 'update':
        raise ValueError(f'order solo soporta action=update, recibido {action}')

    remote_id = payload.get('remote_id')
    if not remote_id:
        raise ValueError('remote_id obligatorio')

    cur.execute(
        'SELECT id, fecha_actualizacion FROM pedidos WHERE id = %s',
        (int(remote_id),),
    )
    existing = cur.fetchone()
    if not existing:
        raise ValueError(f'pedido {remote_id} no existe')

    client_updated = _parse_iso(payload.get('updated_at'))
    if client_updated and existing['fecha_actualizacion'] and client_updated < existing['fecha_actualizacion']:
        raise _StaleError(int(existing['id']))

    sets, params = [], []
    if 'estado_pago' in payload and payload['estado_pago']:
        sets.append('estado_pago = %s')
        params.append(str(payload['estado_pago'])[:30])
    if 'estado_envio' in payload and payload['estado_envio']:
        sets.append('estado_envio = %s')
        params.append(str(payload['estado_envio'])[:30])

    if not sets:
        return int(existing['id'])  # nada que cambiar

    sets.append('fecha_actualizacion = CURRENT_TIMESTAMP')
    params.append(int(existing['id']))
    cur.execute(f"UPDATE pedidos SET {', '.join(sets)} WHERE id = %s", tuple(params))
    return int(existing['id'])


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


# ──────────────────────────────────────────────
# POST /auth — Login remoto desde desktop
# ──────────────────────────────────────────────
# Roles que NO pueden loguearse al desktop POS. Vacío: cualquier rol válido en
# `usuarios` puede autenticarse (clientes + staff). El endpoint sigue exigiendo
# credenciales correctas y estado='habilitado'.
DESKTOP_BLOCKED_ROLES: set[int] = set()


@api_sync_bp.route('/auth', methods=['POST'])
@require_sync_key
def auth_login():
    """Valida email/password contra la tabla `usuarios` del tenant.

    Body: {"email": "user@x.com", "password": "..."}

    Respuestas:
      200 → {user: {remote_id, email, nombre, rol_id, rol_nombre, estado}}
      400 → faltan campos
      401 → credenciales inválidas
      403 → cuenta inhabilitada o rol bloqueado para desktop
      500 → error de servidor
    """
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': {'code': 'missing_fields',
                                  'message': 'email y password son requeridos.'}}), 400

    try:
        with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
            cur.execute(
                """
                SELECT u.id, u.email, u.nombre, u.contraseña, u.estado, u.rol_id,
                       r.nombre AS rol_nombre
                FROM usuarios u
                LEFT JOIN roles r ON r.id = u.rol_id
                WHERE LOWER(u.email) = %s
                """,
                (email,),
            )
            user = cur.fetchone()
    except Exception as exc:
        current_app.logger.error('Sync auth DB error: %s', exc)
        return jsonify({'error': {'code': 'server_error',
                                  'message': 'Error del servidor.'}}), 500

    if not user or not check_password_hash(user['contraseña'], password):
        return jsonify({'error': {'code': 'invalid_credentials',
                                  'message': 'Correo o contraseña incorrectos.'}}), 401

    if (user['estado'] or '').strip().lower() != 'habilitado':
        return jsonify({'error': {'code': 'account_disabled',
                                  'message': 'Cuenta inhabilitada.'}}), 403

    if user['rol_id'] in DESKTOP_BLOCKED_ROLES:
        return jsonify({'error': {'code': 'role_not_allowed',
                                  'message': 'Tu rol no tiene acceso al desktop.'}}), 403

    try:
        with tenant_cursor(db_name=g.sync_db_name) as cur:
            cur.execute(
                'UPDATE usuarios SET ultima_conexion = NOW() WHERE id = %s',
                (user['id'],),
            )
    except Exception:
        pass  # last_login es informativo, no bloquear el login si falla

    return jsonify({
        'user': {
            'remote_id': int(user['id']),
            'email': user['email'],
            'nombre': user['nombre'] or '',
            'rol_id': int(user['rol_id']) if user['rol_id'] is not None else None,
            'rol_nombre': user['rol_nombre'] or 'Cajero',
            'estado': user['estado'],
        }
    }), 200


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


# ──────────────────────────────────────────────
# GET /branding — empresa + colores del tenant
# ──────────────────────────────────────────────

@api_sync_bp.route('/branding', methods=['GET'])
@require_sync_key
def branding():
    """Devuelve cliente_config (empresa + colores) en formato compatible con
    branding.json del desktop. También provee URL absoluta del logo del tenant."""
    empresa, colores_web = {}, {}
    try:
        with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
            cur.execute("""
                SELECT clave, valor, grupo
                FROM cliente_config
                WHERE grupo IN ('empresa', 'colores')
            """)
            for row in cur.fetchall():
                bucket = empresa if row['grupo'] == 'empresa' else colores_web
                bucket[row['clave']] = (row['valor'] or '').strip()
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning('No se pudo leer cliente_config para tenant %s: %s', g.sync_tenant_slug, exc)

    # Mapeo a las claves que espera el desktop
    colores_desktop = dict(_BRANDING_DESKTOP_DEFAULTS)  # peligro, fondo
    for clave_web, valor in colores_web.items():
        clave_desktop = _BRANDING_COLOR_MAP.get(clave_web, clave_web)
        if valor:
            colores_desktop[clave_desktop] = valor

    return jsonify({
        'empresa':   empresa,
        'colores':   colores_desktop,
        'logo_url':  request.url_root.rstrip('/') + '/static/img/Logo.png',
        'updated_at': _now_iso(),
    })


# ──────────────────────────────────────────────
# GET /config — info pública del tenant (sin secretos)
# ──────────────────────────────────────────────

@api_sync_bp.route('/config', methods=['GET'])
@require_sync_key
def config():
    """Información pública del tenant para mostrar en F7 del desktop."""
    nombre = ''
    try:
        with control_plane_cursor() as cur:
            cur.execute(
                'SELECT nombre, plan, estado FROM tenants WHERE id = %s',
                (g.sync_tenant_id,),
            )
            row = cur.fetchone()
            if row:
                nombre = row['nombre'] or ''
                plan = row['plan'] or 'standard'
                estado = row['estado'] or 'activo'
            else:
                plan, estado = 'standard', 'activo'
    except Exception:
        plan, estado = 'standard', 'activo'

    # Flags de módulos del plan (autoritativos en cliente_config del tenant).
    # El desktop los usa para ocultar/bloquear módulos fuera del plan. Aditivo:
    # ante cualquier fallo se devuelve {} y el desktop no aplica restricción.
    modules = {}
    try:
        from tenant_features import MODULE_DEFINITIONS, _as_bool
        wanted = sorted({
            m['config_key'] for m in MODULE_DEFINITIONS.values() if m.get('config_key')
        })
        stored = {}
        with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
            cur.execute(
                'SELECT clave, valor FROM cliente_config WHERE clave = ANY(%s)',
                (wanted,),
            )
            for row in cur.fetchall():
                stored[row['clave']] = row['valor']
        for meta in MODULE_DEFINITIONS.values():
            ck = meta.get('config_key')
            if ck:
                modules[ck] = _as_bool(stored.get(ck), meta.get('default', False))
    except Exception as exc:
        current_app.logger.warning(
            'No se pudieron leer modulos del tenant %s: %s', g.sync_tenant_slug, exc
        )
        modules = {}

    return jsonify({
        'tenant_slug':   g.sync_tenant_slug,
        'tenant_nombre': nombre,
        'plan':          plan,
        'estado':        estado,
        'modules':       modules,
        'server_time':   _now_iso(),
    })


# ──────────────────────────────────────────────
# GET /version — versión disponible del desktop
# ──────────────────────────────────────────────

# Lectura cacheada del version.json para evitar I/O en cada request.
_VERSION_CACHE = {'data': None, 'mtime': 0.0}


def _read_version_manifest():
    """Lee static/installers/version.json. Cacheado por mtime."""
    base = Path(current_app.root_path) / 'static' / 'installers' / 'version.json'
    if not base.exists():
        return None
    try:
        mtime = base.stat().st_mtime
    except OSError:
        return None
    if _VERSION_CACHE['data'] is not None and _VERSION_CACHE['mtime'] == mtime:
        return _VERSION_CACHE['data']
    try:
        data = json.loads(base.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    _VERSION_CACHE['data'] = data
    _VERSION_CACHE['mtime'] = mtime
    return data


@api_sync_bp.route('/version', methods=['GET'])
def version():
    """Endpoint PÚBLICO (sin auth) que devuelve la versión más reciente del desktop.

    No requiere X-Sync-Key porque el desktop puede chequear updates antes de
    que la key sea válida (ej. instalación nueva, key revocada).
    """
    manifest = _read_version_manifest()
    if not manifest:
        return jsonify({
            'latest':         '0.0.0',
            'min_required':   '0.0.0',
            'download_url':   '',
            'release_notes':  'No hay versión publicada.',
            'server_time':    _now_iso(),
        }), 200

    download_url = manifest.get('download_url', '')
    if download_url and not download_url.startswith(('http://', 'https://')):
        download_url = request.url_root.rstrip('/') + '/' + download_url.lstrip('/')

    return jsonify({
        'latest':          manifest.get('latest', '0.0.0'),
        'min_required':    manifest.get('min_required', '0.0.0'),
        'download_url':    download_url,
        'checksum_sha256': manifest.get('checksum_sha256', ''),
        'release_notes':   manifest.get('release_notes', ''),
        'server_time':     _now_iso(),
    })


# ──────────────────────────────────────────────
# GET /stats — agregados del tenant (dashboard del desktop)
# ──────────────────────────────────────────────

# Cache simple por tenant_db. Clave: db_name → (epoch_seg, payload).
_STATS_CACHE: dict = {}
_STATS_TTL_SEC = 30


def _safe_int(row, key, default=0):
    if not row:
        return default
    try:
        return int(row[key] or 0)
    except (KeyError, ValueError, TypeError):
        return default


def _safe_float(row, key, default=0.0):
    if not row:
        return default
    try:
        return float(row[key] or 0)
    except (KeyError, ValueError, TypeError):
        return default


@api_sync_bp.route('/stats', methods=['GET'])
@require_sync_key
def stats():
    """Métricas agregadas del tenant para el dashboard del desktop.

    Campos:
      ventas_web_hoy:     {count, total}      (pedidos con estado_pago=APROBADO de hoy)
      ventas_web_semana:  {count, total}      (últimos 7 días)
      pedidos_pendientes: int                 (APROBADO + envío POR_DESPACHAR)
      productos_total:    int                 (active=TRUE si la columna existe)
      productos_stock_bajo: int               (stock <= 5 hardcoded threshold)
      categorias_total:   int
      server_time:        iso

    Cacheado por tenant_db por 30 segundos.
    """
    import time
    now_epoch = time.time()
    cached = _STATS_CACHE.get(g.sync_db_name)
    if cached and (now_epoch - cached[0]) < _STATS_TTL_SEC:
        return jsonify(cached[1])

    payload = {
        'ventas_web_hoy':       {'count': 0, 'total': 0.0},
        'ventas_web_semana':    {'count': 0, 'total': 0.0},
        'pedidos_pendientes':   0,
        'productos_total':      0,
        'productos_stock_bajo': 0,
        'categorias_total':     0,
        'server_time':          _now_iso(),
    }

    with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
        # Ventas web hoy (pedidos APROBADO con fecha_creacion en hoy)
        try:
            cur.execute("""
                SELECT COUNT(*) AS c, COALESCE(SUM(monto_total),0) AS t
                FROM pedidos
                WHERE UPPER(estado_pago) = 'APROBADO'
                  AND fecha_creacion::date = CURRENT_DATE
            """)
            row = cur.fetchone()
            payload['ventas_web_hoy'] = {
                'count': _safe_int(row, 'c'),
                'total': _safe_float(row, 't'),
            }
        except Exception as exc:
            current_app.logger.warning('stats ventas_web_hoy: %s', exc)

        # Ventas web semana (últimos 7 días)
        try:
            cur.execute("""
                SELECT COUNT(*) AS c, COALESCE(SUM(monto_total),0) AS t
                FROM pedidos
                WHERE UPPER(estado_pago) = 'APROBADO'
                  AND fecha_creacion >= NOW() - INTERVAL '7 days'
            """)
            row = cur.fetchone()
            payload['ventas_web_semana'] = {
                'count': _safe_int(row, 'c'),
                'total': _safe_float(row, 't'),
            }
        except Exception as exc:
            current_app.logger.warning('stats ventas_web_semana: %s', exc)

        # Pedidos pendientes de despacho
        try:
            cur.execute("""
                SELECT COUNT(*) AS c
                FROM pedidos
                WHERE UPPER(estado_pago) = 'APROBADO'
                  AND UPPER(estado_envio) IN ('POR_DESPACHAR', 'PENDIENTE')
            """)
            payload['pedidos_pendientes'] = _safe_int(cur.fetchone(), 'c')
        except Exception as exc:
            current_app.logger.warning('stats pedidos_pendientes: %s', exc)

        # Productos totales (sin filtro active si la columna no existe)
        try:
            cur.execute("""
                SELECT COUNT(*) AS c FROM productos
                WHERE COALESCE(active, TRUE) = TRUE
            """)
            payload['productos_total'] = _safe_int(cur.fetchone(), 'c')
        except Exception:
            try:
                cur.execute("SELECT COUNT(*) AS c FROM productos")
                payload['productos_total'] = _safe_int(cur.fetchone(), 'c')
            except Exception as exc:
                current_app.logger.warning('stats productos_total: %s', exc)

        # Productos con stock bajo (umbral fijo de 5; ajustable cuando exista columna stock_minimo)
        try:
            cur.execute("SELECT COUNT(*) AS c FROM productos WHERE stock IS NOT NULL AND stock <= 5")
            payload['productos_stock_bajo'] = _safe_int(cur.fetchone(), 'c')
        except Exception as exc:
            current_app.logger.warning('stats productos_stock_bajo: %s', exc)

        # Categorías totales
        try:
            cur.execute('SELECT COUNT(*) AS c FROM generos')
            payload['categorias_total'] = _safe_int(cur.fetchone(), 'c')
        except Exception as exc:
            current_app.logger.warning('stats categorias_total: %s', exc)

    _STATS_CACHE[g.sync_db_name] = (now_epoch, payload)
    return jsonify(payload)


# ──────────────────────────────────────────────
# GET /restaurant/snapshot  (modulo de mesas — desktop)
# ──────────────────────────────────────────────

RESTAURANT_TABLE_STATES = {'disponible', 'ocupada', 'reservada', 'cuenta_solicitada'}
RESTAURANT_CONSUMPTION_STATES = {'pendiente', 'preparando', 'servido'}
RESTAURANT_PAYMENT_METHODS = {'EFECTIVO', 'TARJETA', 'TRANSFERENCIA', 'MIXTO'}


@api_sync_bp.route('/restaurant/snapshot', methods=['GET'])
@require_sync_key
def restaurant_snapshot():
    """Estado completo del modulo de mesas del tenant (snapshot, no incremental).

    Devuelve: mesas, ordenes abiertas, consumos de esas ordenes y el catalogo
    de productos para el selector. El volumen es bajo, asi que un snapshot
    completo evita estados parciales inconsistentes en el desktop.
    """
    out = {
        'tables': [], 'open_orders': [], 'consumptions': [], 'products': [],
        'server_time': _now_iso(), 'version': int(datetime.now(timezone.utc).timestamp()),
    }
    with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
        if not _regclass(cur, 'restaurant_tables'):
            return jsonify(out)  # modulo no instalado en este tenant

        cur.execute("""
            SELECT id, codigo, nombre, area, capacidad, forma, estado,
                   pos_x, pos_y, ancho, alto, rotacion, updated_at
            FROM restaurant_tables
            ORDER BY area, nombre
        """)
        for r in cur.fetchall():
            out['tables'].append({
                'id': int(r['id']), 'codigo': r['codigo'], 'nombre': r['nombre'],
                'area': r['area'], 'capacidad': int(r['capacidad'] or 0),
                'forma': r['forma'], 'estado': r['estado'],
                'pos_x': float(r['pos_x'] or 0), 'pos_y': float(r['pos_y'] or 0),
                'ancho': float(r['ancho'] or 0), 'alto': float(r['alto'] or 0),
                'rotacion': int(r['rotacion'] or 0), 'updated_at': _iso(r['updated_at']),
            })

        cur.execute("""
            SELECT id, table_id, estado, cliente_nombre, comensales, notas,
                   total_acumulado, opened_at, last_activity_at, updated_at
            FROM restaurant_table_orders
            WHERE estado = 'abierta'
            ORDER BY id
        """)
        open_order_ids = []
        for r in cur.fetchall():
            open_order_ids.append(int(r['id']))
            out['open_orders'].append({
                'id': int(r['id']), 'table_id': int(r['table_id']), 'estado': r['estado'],
                'cliente_nombre': r['cliente_nombre'], 'comensales': int(r['comensales'] or 1),
                'notas': r['notas'], 'total_acumulado': float(r['total_acumulado'] or 0),
                'opened_at': _iso(r['opened_at']), 'last_activity_at': _iso(r['last_activity_at']),
                'updated_at': _iso(r['updated_at']),
            })

        if open_order_ids:
            cur.execute("""
                SELECT id, order_id, table_id, producto_id, descripcion, cantidad,
                       precio_unitario, subtotal, estado, notas, ordered_at, served_at, updated_at
                FROM restaurant_table_consumptions
                WHERE order_id = ANY(%s)
                ORDER BY ordered_at
            """, (open_order_ids,))
            for r in cur.fetchall():
                out['consumptions'].append({
                    'id': int(r['id']), 'order_id': int(r['order_id']), 'table_id': int(r['table_id']),
                    'producto_id': int(r['producto_id']) if r['producto_id'] is not None else None,
                    'descripcion': r['descripcion'], 'cantidad': int(r['cantidad'] or 1),
                    'precio_unitario': float(r['precio_unitario'] or 0), 'subtotal': float(r['subtotal'] or 0),
                    'estado': r['estado'], 'notas': r['notas'],
                    'ordered_at': _iso(r['ordered_at']), 'served_at': _iso(r['served_at']) if r['served_at'] else None,
                    'updated_at': _iso(r['updated_at']),
                })

        # Catalogo de productos para el selector (activos con stock relevante)
        try:
            cur.execute("""
                SELECT id, nombre, precio, stock, referencia
                FROM productos
                ORDER BY nombre
            """)
            for r in cur.fetchall():
                out['products'].append({
                    'id': int(r['id']), 'nombre': r['nombre'],
                    'precio': float(r['precio'] or 0), 'stock': int(r['stock'] or 0),
                    'referencia': r.get('referencia'),
                })
        except Exception as exc:
            current_app.logger.warning('restaurant_snapshot productos: %s', exc)

    return jsonify(out)


# ──────────────────────────────────────────────
# Apply: restaurant_op  (operaciones del modulo de mesas via outbox)
# ──────────────────────────────────────────────

def _regclass(cur, table_name):
    cur.execute("SELECT to_regclass(%s) AS rc", (f'public.{table_name}',))
    row = cur.fetchone()
    return bool(row and row['rc'])


def _resolve_usuario_id(cur, payload):
    """Resuelve el id de usuarios a partir del payload (remote id o email)."""
    uid = payload.get('user_remote_id')
    if uid:
        try:
            cur.execute('SELECT id FROM usuarios WHERE id = %s', (int(uid),))
            row = cur.fetchone()
            if row:
                return int(row['id'])
        except (TypeError, ValueError):
            pass
    email = (payload.get('user_email') or '').strip()
    if email:
        cur.execute('SELECT id FROM usuarios WHERE LOWER(email) = LOWER(%s)', (email,))
        row = cur.fetchone()
        if row:
            return int(row['id'])
    return None


def _ensure_restaurant_ledger(cur):
    """Tabla de idempotencia para ops no-idempotentes (add_consumption).
    Aditiva (CREATE TABLE IF NOT EXISTS) — no destructiva."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_restaurant_applied_ops (
            client_op_uuid TEXT PRIMARY KEY,
            remote_id      INTEGER,
            applied_at     TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)


def _restaurant_open_order_id(cur, table_id):
    cur.execute("""
        SELECT id FROM restaurant_table_orders
        WHERE table_id = %s AND estado = 'abierta'
        ORDER BY id DESC LIMIT 1
    """, (table_id,))
    row = cur.fetchone()
    return int(row['id']) if row else None


def _restaurant_ensure_open_order(cur, table_id, payload):
    """Devuelve el id de la orden abierta de la mesa; la crea si no existe."""
    order_id = _restaurant_open_order_id(cur, table_id)
    if order_id:
        return order_id
    cur.execute('SELECT tenant_id FROM restaurant_tables WHERE id = %s', (table_id,))
    trow = cur.fetchone()
    if not trow:
        raise ValueError('Mesa no encontrada.')
    tenant_id = int(trow['tenant_id'])
    user_id = _resolve_usuario_id(cur, payload)
    cliente = (payload.get('cliente_nombre') or '').strip() or None
    comensales = int(payload.get('comensales') or 1)
    notas = (payload.get('notas') or '').strip() or None
    cur.execute("""
        INSERT INTO restaurant_table_orders
            (tenant_id, table_id, estado, cliente_nombre, comensales, notas, abierta_por)
        VALUES (%s, %s, 'abierta', %s, %s, %s, %s)
        RETURNING id
    """, (tenant_id, table_id, cliente, comensales, notas, user_id))
    order_id = int(cur.fetchone()['id'])
    cur.execute("UPDATE restaurant_tables SET estado = 'ocupada', updated_at = NOW() WHERE id = %s", (table_id,))
    return order_id


def _restaurant_refresh_total(cur, order_id):
    cur.execute("""
        UPDATE restaurant_table_orders o
        SET total_acumulado = COALESCE((
                SELECT SUM(subtotal) FROM restaurant_table_consumptions WHERE order_id = %s
            ), 0),
            last_activity_at = NOW(), updated_at = NOW()
        WHERE o.id = %s
        RETURNING total_acumulado
    """, (order_id, order_id))
    row = cur.fetchone()
    return float(row['total_acumulado'] or 0) if row else 0.0


def _restaurant_create_accounting(cur, order, user_id, payment_method):
    """Crea el movimiento contable de ingreso por venta de restaurante.
    Idempotente por (referencia_tipo, referencia_id). Espejo de
    services.restaurant_tables_service._create_accounting_movement."""
    if not _regclass(cur, 'contabilidad_movimientos'):
        return 'sin_contabilidad'
    ref_type, ref_id = 'restaurant_order', int(order['id'])
    cur.execute("""
        SELECT id FROM contabilidad_movimientos
        WHERE referencia_tipo = %s AND referencia_id = %s
        ORDER BY id DESC LIMIT 1
    """, (ref_type, ref_id))
    if cur.fetchone():
        return 'sincronizada'
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'contabilidad_movimientos'
    """)
    columns = {r['column_name'] for r in cur.fetchall()}
    total = float(order['total_acumulado'] or 0)
    values = {
        'tipo': 'ingreso', 'categoria': 'venta_restaurante',
        'descripcion': f"Venta restaurante mesa {order['codigo']} — {order.get('cliente_nombre') or 'Cliente'}",
        'monto': total, 'monto_bruto': total,
        'retefuente_pct': 0, 'retefuente_monto': 0, 'iva_pct': 0, 'iva_monto': 0,
        'reteiva_pct': 0, 'reteiva_monto': 0, 'reteica_pct': 0, 'reteica_monto': 0,
        'total_retenciones': 0, 'fecha': datetime.now(timezone.utc).date(),
        'referencia_tipo': ref_type, 'referencia_id': ref_id,
        'notas': f"Mesa {order['nombre']} / pago {payment_method}",
        'usuario_id': user_id, 'auto_generado': True,
    }
    order_cols = ['tipo', 'categoria', 'descripcion', 'monto_bruto', 'monto',
                  'retefuente_pct', 'retefuente_monto', 'iva_pct', 'iva_monto',
                  'reteiva_pct', 'reteiva_monto', 'reteica_pct', 'reteica_monto',
                  'total_retenciones', 'fecha', 'referencia_tipo', 'referencia_id',
                  'notas', 'usuario_id', 'auto_generado']
    selected = [c for c in order_cols if c in columns]
    placeholders = ', '.join(['%s'] * len(selected))
    cur.execute(
        f"INSERT INTO contabilidad_movimientos ({', '.join(selected)}) VALUES ({placeholders})",
        tuple(values[c] for c in selected),
    )
    return 'sincronizada'


def _apply_restaurant_op(cur, payload):
    """Aplica una operacion del modulo de mesas sobre el cursor del batch.

    payload: {op, table_id, ..., client_op_uuid, user_remote_id|user_email}
    Reglas de idempotencia:
      - open_table / set_table_state / set_consumption_state / close_table /
        cancel_order son idempotentes por naturaleza (clave por table_id/estado).
      - add_consumption usa el ledger sync_restaurant_applied_ops por uuid.
    """
    op = (payload.get('op') or '').strip()
    if not _regclass(cur, 'restaurant_tables'):
        raise ValueError('Modulo de restaurante no instalado en el servidor.')

    if op == 'open_table':
        table_id = int(payload['table_id'])
        return _restaurant_ensure_open_order(cur, table_id, payload)

    if op == 'add_consumption':
        uuid = (payload.get('client_op_uuid') or '').strip()
        if uuid:
            _ensure_restaurant_ledger(cur)
            cur.execute('SELECT remote_id FROM sync_restaurant_applied_ops WHERE client_op_uuid = %s', (uuid,))
            prev = cur.fetchone()
            if prev:
                raise _DuplicateError(int(prev['remote_id']) if prev['remote_id'] is not None else 0)
        table_id = int(payload['table_id'])
        cur.execute('SELECT id, codigo, tenant_id FROM restaurant_tables WHERE id = %s', (table_id,))
        table_row = cur.fetchone()
        if not table_row:
            raise ValueError('Mesa no encontrada.')
        tenant_id = int(table_row['tenant_id'])
        order_id = _restaurant_ensure_open_order(cur, table_id, payload)
        user_id = _resolve_usuario_id(cur, payload)
        cantidad = max(1, int(payload.get('cantidad') or 1))
        notas = (payload.get('notas') or '').strip() or None
        producto_id = payload.get('producto_id')
        descripcion = (payload.get('descripcion') or '').strip()
        precio_unitario = float(payload.get('precio_unitario') or 0)
        if producto_id:
            producto_id = int(producto_id)
            cur.execute('SELECT id, nombre, precio, stock FROM productos WHERE id = %s FOR UPDATE', (producto_id,))
            product = cur.fetchone()
            if not product:
                raise ValueError('Producto no encontrado.')
            stock_actual = int(product['stock'] or 0)
            if stock_actual < cantidad:
                raise ValueError(f"Stock insuficiente para '{product['nombre']}'. Disponible: {stock_actual}.")
            descripcion = product['nombre']
            precio_unitario = float(product['precio'] or 0)
            stock_nuevo = stock_actual - cantidad
            cur.execute('UPDATE productos SET stock = %s WHERE id = %s', (stock_nuevo, producto_id))
            try:
                cur.execute("""
                    INSERT INTO inventario_log
                        (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, usuario_id)
                    VALUES (%s, 'SALIDA', %s, %s, %s, %s, %s)
                """, (producto_id, cantidad, stock_actual, stock_nuevo,
                      f"Consumo mesa {table_row['codigo']} / orden {order_id}", user_id))
            except Exception:
                pass
        else:
            if not descripcion:
                raise ValueError('Debes indicar un producto o una descripcion libre.')
            if precio_unitario <= 0:
                raise ValueError('El precio del consumo debe ser mayor a cero.')
            producto_id = None
        subtotal = round(precio_unitario * cantidad, 2)
        cur.execute("""
            INSERT INTO restaurant_table_consumptions
                (tenant_id, order_id, table_id, producto_id, descripcion, cantidad,
                 precio_unitario, subtotal, estado, notas, creado_por)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pendiente', %s, %s)
            RETURNING id
        """, (tenant_id, order_id, table_id, producto_id, descripcion[:220], cantidad,
              precio_unitario, subtotal, notas, user_id))
        consumption_id = int(cur.fetchone()['id'])
        _restaurant_refresh_total(cur, order_id)
        cur.execute("UPDATE restaurant_tables SET estado = 'ocupada', updated_at = NOW() WHERE id = %s", (table_id,))
        if uuid:
            cur.execute("""
                INSERT INTO sync_restaurant_applied_ops (client_op_uuid, remote_id)
                VALUES (%s, %s) ON CONFLICT (client_op_uuid) DO NOTHING
            """, (uuid, consumption_id))
        return consumption_id

    if op == 'set_consumption_state':
        consumption_id = int(payload['consumption_id'])
        new_state = (payload.get('estado') or '').strip()
        if new_state not in RESTAURANT_CONSUMPTION_STATES:
            raise ValueError('Estado de consumo invalido.')
        served = 'NOW()' if new_state == 'servido' else 'served_at'
        cur.execute(f"""
            UPDATE restaurant_table_consumptions
            SET estado = %s, served_at = {served}, updated_at = NOW()
            WHERE id = %s
            RETURNING id
        """, (new_state, consumption_id))
        row = cur.fetchone()
        if not row:
            raise ValueError('Consumo no encontrado.')
        return int(row['id'])

    if op == 'set_table_state':
        table_id = int(payload['table_id'])
        new_state = (payload.get('estado') or '').strip()
        if new_state not in RESTAURANT_TABLE_STATES:
            raise ValueError('Estado de mesa invalido.')
        cur.execute("""
            UPDATE restaurant_tables SET estado = %s, updated_at = NOW()
            WHERE id = %s RETURNING id
        """, (new_state, table_id))
        row = cur.fetchone()
        if not row:
            raise ValueError('Mesa no encontrada.')
        return int(row['id'])

    if op == 'close_table':
        table_id = int(payload['table_id'])
        payment_method = (payload.get('payment_method') or 'EFECTIVO').strip().upper()
        if payment_method not in RESTAURANT_PAYMENT_METHODS:
            raise ValueError('Metodo de pago invalido.')
        cur.execute("""
            SELECT o.id, o.total_acumulado, o.cliente_nombre, t.codigo, t.nombre,
                   (SELECT COUNT(*) FROM restaurant_table_consumptions c WHERE c.order_id = o.id) AS total_items
            FROM restaurant_table_orders o
            JOIN restaurant_tables t ON t.id = o.table_id
            WHERE o.table_id = %s AND o.estado = 'abierta'
            LIMIT 1
        """, (table_id,))
        order = cur.fetchone()
        if not order:
            raise _DuplicateError(0)  # ya cerrada / sin cuenta abierta → idempotente
        if int(order['total_items'] or 0) <= 0:
            raise ValueError('No puedes cerrar una cuenta sin consumos registrados.')
        total = _restaurant_refresh_total(cur, order['id'])
        order = dict(order)
        order['total_acumulado'] = total
        user_id = _resolve_usuario_id(cur, payload)
        cur.execute("""
            UPDATE restaurant_table_orders
            SET estado = 'cerrada', cerrada_por = %s, closed_at = NOW(),
                payment_method = %s, total_acumulado = %s, updated_at = NOW()
            WHERE id = %s
        """, (user_id, payment_method, total, order['id']))
        _restaurant_create_accounting(cur, order, user_id, payment_method)
        cur.execute("UPDATE restaurant_tables SET estado = 'disponible', updated_at = NOW() WHERE id = %s", (table_id,))
        return int(order['id'])

    if op == 'cancel_order':
        table_id = int(payload['table_id'])
        reason = (payload.get('cancel_reason') or '').strip() or None
        user_id = _resolve_usuario_id(cur, payload)
        cur.execute("""
            SELECT id FROM restaurant_table_orders
            WHERE table_id = %s AND estado = 'abierta' LIMIT 1
        """, (table_id,))
        order = cur.fetchone()
        if not order:
            raise _DuplicateError(0)  # ya no hay cuenta abierta → idempotente
        cur.execute("""
            UPDATE restaurant_table_orders
            SET estado = 'cancelada', cancel_reason = %s, cancelled_at = NOW(),
                cancelled_by = %s, updated_at = NOW()
            WHERE id = %s
        """, (reason, user_id, order['id']))
        cur.execute("UPDATE restaurant_tables SET estado = 'disponible', updated_at = NOW() WHERE id = %s", (table_id,))
        return int(order['id'])

    raise ValueError(f'op de restaurante no soportada: {op}')


# ──────────────────────────────────────────────
# GET /contabilidad/snapshot  (modulo de contabilidad — desktop)
# ──────────────────────────────────────────────

CONTAB_MOV_LIMIT = 1000


@api_sync_bp.route('/contabilidad/snapshot', methods=['GET'])
@require_sync_key
def contabilidad_snapshot():
    """Estado del modulo de contabilidad del tenant: movimientos recientes,
    plantillas, cierres y categorias usadas."""
    out = {
        'movimientos': [], 'plantillas': [], 'cierres': [], 'categorias': [],
        'server_time': _now_iso(),
    }
    with tenant_cursor(db_name=g.sync_db_name, dict_cursor=True) as cur:
        if not _regclass(cur, 'contabilidad_movimientos'):
            return jsonify(out)

        cur.execute("""
            SELECT m.id, m.tipo, m.categoria, m.descripcion, m.monto_bruto, m.monto,
                   m.retefuente_pct, m.retefuente_monto, m.iva_pct, m.iva_monto,
                   m.reteiva_pct, m.reteiva_monto, m.reteica_pct, m.reteica_monto,
                   m.total_retenciones, m.fecha, m.referencia_tipo, m.referencia_id,
                   m.notas, m.usuario_id, m.auto_generado, m.created_at,
                   u.nombre AS usuario_nombre
            FROM contabilidad_movimientos m
            LEFT JOIN usuarios u ON u.id = m.usuario_id
            ORDER BY m.fecha DESC, m.created_at DESC
            LIMIT %s
        """, (CONTAB_MOV_LIMIT,))
        for r in cur.fetchall():
            out['movimientos'].append({
                'id': int(r['id']), 'tipo': r['tipo'], 'categoria': r['categoria'],
                'descripcion': r['descripcion'],
                'monto_bruto': float(r['monto_bruto'] or 0), 'monto': float(r['monto'] or 0),
                'retefuente_pct': float(r['retefuente_pct'] or 0), 'retefuente_monto': float(r['retefuente_monto'] or 0),
                'iva_pct': float(r['iva_pct'] or 0), 'iva_monto': float(r['iva_monto'] or 0),
                'reteiva_pct': float(r['reteiva_pct'] or 0), 'reteiva_monto': float(r['reteiva_monto'] or 0),
                'reteica_pct': float(r['reteica_pct'] or 0), 'reteica_monto': float(r['reteica_monto'] or 0),
                'total_retenciones': float(r['total_retenciones'] or 0),
                'fecha': r['fecha'].isoformat() if r['fecha'] else None,
                'referencia_tipo': r['referencia_tipo'], 'referencia_id': r['referencia_id'],
                'notas': r['notas'], 'usuario_id': r['usuario_id'],
                'usuario_nombre': r['usuario_nombre'],
                'auto_generado': bool(r['auto_generado']),
                'created_at': _iso(r['created_at']),
            })

        if _regclass(cur, 'contabilidad_plantillas'):
            cur.execute("""
                SELECT id, tipo, categoria, descripcion, monto_bruto, notas, activo, created_at
                FROM contabilidad_plantillas ORDER BY id
            """)
            for r in cur.fetchall():
                out['plantillas'].append({
                    'id': int(r['id']), 'tipo': r['tipo'], 'categoria': r['categoria'],
                    'descripcion': r['descripcion'], 'monto_bruto': float(r['monto_bruto'] or 0),
                    'notas': r['notas'], 'activo': bool(r['activo']), 'created_at': _iso(r['created_at']),
                })

        if _regclass(cur, 'contabilidad_cierres'):
            cur.execute("""
                SELECT c.id, c.nombre, c.fecha_inicio, c.fecha_fin, c.total_ingresos,
                       c.total_egresos, c.total_retenciones, c.saldo, c.notas, c.usuario_id,
                       c.created_at, u.nombre AS usuario_nombre
                FROM contabilidad_cierres c
                LEFT JOIN usuarios u ON u.id = c.usuario_id
                ORDER BY c.fecha_fin DESC
            """)
            for r in cur.fetchall():
                out['cierres'].append({
                    'id': int(r['id']), 'nombre': r['nombre'],
                    'fecha_inicio': r['fecha_inicio'].isoformat() if r['fecha_inicio'] else None,
                    'fecha_fin': r['fecha_fin'].isoformat() if r['fecha_fin'] else None,
                    'total_ingresos': float(r['total_ingresos'] or 0),
                    'total_egresos': float(r['total_egresos'] or 0),
                    'total_retenciones': float(r['total_retenciones'] or 0),
                    'saldo': float(r['saldo'] or 0), 'notas': r['notas'],
                    'usuario_id': r['usuario_id'], 'usuario_nombre': r['usuario_nombre'],
                    'created_at': _iso(r['created_at']),
                })

        try:
            cur.execute("SELECT DISTINCT categoria FROM contabilidad_movimientos WHERE categoria IS NOT NULL ORDER BY categoria")
            out['categorias'] = [r['categoria'] for r in cur.fetchall() if r['categoria']]
        except Exception:
            pass

    return jsonify(out)


# ──────────────────────────────────────────────
# Apply: contabilidad_op
# ──────────────────────────────────────────────

def _ensure_ops_ledger(cur):
    """Ledger generico de idempotencia para ops no-idempotentes. Aditivo."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_applied_ops (
            client_op_uuid TEXT PRIMARY KEY,
            remote_id      INTEGER,
            applied_at     TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)


def _contab_calc_impuestos(bruto, rtefte_pct, iva_pct, reteiva_pct, rteica_pct):
    """Replica de routes.contabilidad._calcular_impuestos."""
    def pct(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0
    bruto = float(bruto or 0)
    rtefte = round(bruto * pct(rtefte_pct) / 100, 2)
    iva = round(bruto * pct(iva_pct) / 100, 2)
    reteiva = round(iva * pct(reteiva_pct) / 100, 2)
    rteica = round(bruto * pct(rteica_pct) / 100, 2)
    total_ret = rtefte + reteiva + rteica
    neto = round(bruto - total_ret, 2)
    return {
        'retefuente_monto': rtefte, 'iva_monto': iva, 'reteiva_monto': reteiva,
        'reteica_monto': rteica, 'total_retenciones': total_ret, 'monto_neto': neto,
    }


def _contab_mes_rango(cur):
    """Primer y ultimo dia del mes actual (en el server)."""
    cur.execute("SELECT DATE_TRUNC('month', CURRENT_DATE)::date AS ini, (DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month - 1 day')::date AS fin")
    r = cur.fetchone()
    return r['ini'], r['fin']


def _apply_contabilidad_op(cur, payload):
    """Aplica una operacion de contabilidad sobre el cursor del batch.
    Espejo de routes/contabilidad.py. Idempotencia por client_op_uuid donde aplica."""
    op = (payload.get('op') or '').strip()
    if not _regclass(cur, 'contabilidad_movimientos'):
        raise ValueError('Modulo de contabilidad no instalado en el servidor.')
    user_id = _resolve_usuario_id(cur, payload)

    if op == 'create_movimiento':
        op_uuid = (payload.get('client_op_uuid') or '').strip()
        if op_uuid:
            _ensure_ops_ledger(cur)
            cur.execute('SELECT remote_id FROM sync_applied_ops WHERE client_op_uuid = %s', (op_uuid,))
            prev = cur.fetchone()
            if prev:
                raise _DuplicateError(int(prev['remote_id']) if prev['remote_id'] is not None else 0)
        tipo = (payload.get('tipo') or '').strip()
        if tipo not in ('ingreso', 'egreso'):
            raise ValueError('Tipo invalido.')
        descripcion = (payload.get('descripcion') or '').strip()
        if not descripcion:
            raise ValueError('La descripcion es obligatoria.')
        bruto = float(payload.get('monto_bruto') or 0)
        if bruto <= 0:
            raise ValueError('El monto debe ser mayor a cero.')
        categoria = (payload.get('categoria') or 'otro').strip() or 'otro'
        fecha = payload.get('fecha') or None
        notas = (payload.get('notas') or '').strip() or None
        if tipo == 'ingreso':
            rtefte = payload.get('retefuente_pct') or 0
            iva = payload.get('iva_pct') or 0
            reteiva = payload.get('reteiva_pct') or 0
            rteica = payload.get('reteica_pct') or 0
        else:
            rtefte = iva = reteiva = rteica = 0
        calc = _contab_calc_impuestos(bruto, rtefte, iva, reteiva, rteica)
        neto = calc['monto_neto'] if tipo == 'ingreso' else bruto
        cur.execute("""
            INSERT INTO contabilidad_movimientos
                (tipo, categoria, descripcion, monto_bruto, monto,
                 retefuente_pct, retefuente_monto, iva_pct, iva_monto,
                 reteiva_pct, reteiva_monto, reteica_pct, reteica_monto,
                 total_retenciones, fecha, notas, usuario_id, auto_generado)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s, CURRENT_DATE),%s,%s,FALSE)
            RETURNING id
        """, (tipo, categoria, descripcion, bruto, neto,
              float(rtefte or 0), calc['retefuente_monto'], float(iva or 0), calc['iva_monto'],
              float(reteiva or 0), calc['reteiva_monto'], float(rteica or 0), calc['reteica_monto'],
              calc['total_retenciones'], fecha, notas, user_id))
        mid = int(cur.fetchone()['id'])
        if op_uuid:
            cur.execute("INSERT INTO sync_applied_ops (client_op_uuid, remote_id) VALUES (%s,%s) ON CONFLICT (client_op_uuid) DO NOTHING", (op_uuid, mid))
        return mid

    if op == 'delete_movimiento':
        mid = int(payload['movimiento_id'])
        cur.execute('SELECT auto_generado FROM contabilidad_movimientos WHERE id = %s', (mid,))
        row = cur.fetchone()
        if not row:
            raise _DuplicateError(0)
        if row['auto_generado']:
            raise ValueError('Los movimientos automaticos (POS/PayU/restaurante) no se pueden eliminar.')
        cur.execute('DELETE FROM contabilidad_movimientos WHERE id = %s', (mid,))
        return mid

    if op == 'create_plantilla':
        if not _regclass(cur, 'contabilidad_plantillas'):
            raise ValueError('Tabla de plantillas no disponible.')
        tipo = (payload.get('tipo') or '').strip()
        if tipo not in ('ingreso', 'egreso'):
            raise ValueError('Tipo invalido.')
        bruto = float(payload.get('monto_bruto') or 0)
        if bruto <= 0:
            raise ValueError('El monto debe ser mayor a cero.')
        cur.execute("""
            INSERT INTO contabilidad_plantillas (tipo, categoria, descripcion, monto_bruto, notas, activo)
            VALUES (%s,%s,%s,%s,%s,TRUE) RETURNING id
        """, (tipo, (payload.get('categoria') or 'otro').strip() or 'otro',
              (payload.get('descripcion') or '').strip(), bruto,
              (payload.get('notas') or '').strip() or None))
        return int(cur.fetchone()['id'])

    if op == 'toggle_plantilla':
        pid = int(payload['plantilla_id'])
        cur.execute("UPDATE contabilidad_plantillas SET activo = NOT activo WHERE id = %s RETURNING id", (pid,))
        row = cur.fetchone()
        if not row:
            raise ValueError('Plantilla no encontrada.')
        return int(row['id'])

    if op == 'delete_plantilla':
        pid = int(payload['plantilla_id'])
        cur.execute('DELETE FROM contabilidad_plantillas WHERE id = %s', (pid,))
        return pid

    if op == 'generar_plantillas':
        if not _regclass(cur, 'contabilidad_plantillas'):
            raise ValueError('Tabla de plantillas no disponible.')
        mes_ini, mes_fin = _contab_mes_rango(cur)
        cur.execute("SELECT * FROM contabilidad_plantillas WHERE activo = TRUE")
        activas = cur.fetchall()
        generados = 0
        for p in activas:
            cur.execute("""
                SELECT id FROM contabilidad_movimientos
                WHERE referencia_tipo = 'plantilla' AND referencia_id = %s
                  AND fecha BETWEEN %s AND %s LIMIT 1
            """, (p['id'], mes_ini, mes_fin))
            if cur.fetchone():
                continue
            cur.execute("""
                INSERT INTO contabilidad_movimientos
                    (tipo, categoria, descripcion, monto_bruto, monto, fecha,
                     notas, referencia_tipo, referencia_id, usuario_id, auto_generado)
                VALUES (%s,%s,%s,%s,%s,CURRENT_DATE,%s,'plantilla',%s,%s,FALSE)
            """, (p['tipo'], p['categoria'], p['descripcion'], p['monto_bruto'],
                  p['monto_bruto'], p['notas'], p['id'], user_id))
            generados += 1
        return generados

    if op == 'create_cierre':
        if not _regclass(cur, 'contabilidad_cierres'):
            raise ValueError('Tabla de cierres no disponible.')
        nombre = (payload.get('nombre') or '').strip()
        fi = payload.get('fecha_inicio')
        ff = payload.get('fecha_fin')
        if not nombre or not fi or not ff:
            raise ValueError('Nombre y rango de fechas son obligatorios.')
        cur.execute("""
            SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto ELSE 0 END),0) AS ing,
                   COALESCE(SUM(CASE WHEN tipo='egreso' THEN monto ELSE 0 END),0) AS egr,
                   COALESCE(SUM(CASE WHEN tipo='ingreso' THEN total_retenciones ELSE 0 END),0) AS ret
            FROM contabilidad_movimientos WHERE fecha BETWEEN %s AND %s
        """, (fi, ff))
        row = cur.fetchone()
        ing, egr, ret = float(row['ing']), float(row['egr']), float(row['ret'])
        cur.execute("""
            INSERT INTO contabilidad_cierres
                (nombre, fecha_inicio, fecha_fin, total_ingresos, total_egresos,
                 total_retenciones, saldo, notas, usuario_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """, (nombre, fi, ff, ing, egr, ret, ing - egr,
              (payload.get('notas') or '').strip() or None, user_id))
        return int(cur.fetchone()['id'])

    if op == 'delete_cierre':
        cid = int(payload['cierre_id'])
        cur.execute('DELETE FROM contabilidad_cierres WHERE id = %s', (cid,))
        return cid

    raise ValueError(f'op de contabilidad no soportada: {op}')
