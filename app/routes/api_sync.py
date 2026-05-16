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

VALID_ENTITIES = {'sale', 'inventory_movement', 'product', 'user', 'category', 'order'}
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

    return jsonify({
        'tenant_slug':   g.sync_tenant_slug,
        'tenant_nombre': nombre,
        'plan':          plan,
        'estado':        estado,
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
