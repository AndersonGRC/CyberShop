"""
tenant_features.py - Feature flags tenant-aware para modulos opcionales.

Si la capa SaaS existe en la base de datos se usa ``saas_tenant_modules``.
Si todavia no existe, se mantiene compatibilidad con ``cliente_config``.
"""

from functools import lru_cache, wraps

from flask import current_app, flash, jsonify, redirect, request, session, url_for

from database import get_db_cursor


LOCAL_TENANT_ID = 1

MODULE_ORDERS = 'orders'
MODULE_POS = 'pos'
MODULE_QUOTES = 'quotes'
MODULE_BILLING = 'billing'
MODULE_COUPONS = 'coupons'
MODULE_INVENTORY = 'inventory'
MODULE_WISHLIST = 'wishlist'
MODULE_CONTENT = 'content'
MODULE_USERS = 'users'
MODULE_PAYROLL = 'payroll'
MODULE_CRM = 'crm'
MODULE_ACCOUNTING = 'accounting'
MODULE_SUPPORT = 'support'
MODULE_VIDEO = 'video'
MODULE_RESTAURANT_TABLES = 'restaurant_tables'
MODULE_FACTURACION_ELECTRONICA = 'facturacion_electronica'
MODULE_SHARE = 'share'

MODULE_DEFINITIONS = {
    MODULE_ORDERS: {
        'nombre': 'Pedidos',
        'descripcion': 'Gestion de pedidos web y seguimiento comercial.',
        'categoria': 'ventas',
        'config_key': 'pedidos_habilitado',
        'default': True,
        'orden': 10,
        'is_core': False,
    },
    MODULE_POS: {
        'nombre': 'Punto de Venta',
        'descripcion': 'Ventas rapidas, historial POS y facturacion mostrador.',
        'categoria': 'ventas',
        'config_key': 'pos_habilitado',
        'default': True,
        'orden': 20,
        'is_core': False,
    },
    MODULE_QUOTES: {
        'nombre': 'Cotizaciones',
        'descripcion': 'Creacion de cotizaciones PDF y seguimiento comercial.',
        'categoria': 'ventas',
        'config_key': 'cotizaciones_habilitado',
        'default': True,
        'orden': 30,
        'is_core': False,
    },
    MODULE_BILLING: {
        'nombre': 'Cuentas de Cobro',
        'descripcion': 'Documentos de cobro para contratistas y servicios.',
        'categoria': 'ventas',
        'config_key': 'cuentas_cobro_habilitado',
        'default': True,
        'orden': 40,
        'is_core': False,
    },
    MODULE_COUPONS: {
        'nombre': 'Cupones',
        'descripcion': 'Promociones y descuentos por codigo.',
        'categoria': 'ventas',
        'config_key': 'cupones_habilitado',
        'default': True,
        'orden': 50,
        'is_core': False,
    },
    MODULE_INVENTORY: {
        'nombre': 'Inventario',
        'descripcion': 'Catalogo, stock, generos y resenas de productos.',
        'categoria': 'catalogo',
        'config_key': 'inventario_habilitado',
        'default': True,
        'orden': 60,
        'is_core': False,
    },
    MODULE_WISHLIST: {
        'nombre': 'Wishlist',
        'descripcion': 'Favoritos de clientes y estadisticas de lista de deseos.',
        'categoria': 'catalogo',
        'config_key': 'wishlist_habilitado',
        'default': True,
        'orden': 70,
        'is_core': False,
    },
    MODULE_CONTENT: {
        'nombre': 'Contenido Web',
        'descripcion': 'Publicaciones, slides y servicios del sitio.',
        'categoria': 'contenido',
        'config_key': 'contenido_web_habilitado',
        'default': True,
        'orden': 80,
        'is_core': False,
    },
    MODULE_USERS: {
        'nombre': 'Usuarios',
        'descripcion': 'Gestion y creacion de usuarios administrativos.',
        'categoria': 'administracion',
        'config_key': 'usuarios_habilitado',
        'default': True,
        'orden': 90,
        'is_core': False,
    },
    MODULE_PAYROLL: {
        'nombre': 'Nomina',
        'descripcion': 'Empleados, periodos, novedades y liquidaciones.',
        'categoria': 'administracion',
        'config_key': 'nomina_habilitada',
        'default': True,
        'orden': 100,
        'is_core': False,
    },
    MODULE_CRM: {
        'nombre': 'CRM',
        'descripcion': 'Contactos, tareas y actividades comerciales.',
        'categoria': 'clientes',
        'config_key': 'crm_habilitado',
        'default': True,
        'orden': 110,
        'is_core': False,
    },
    MODULE_ACCOUNTING: {
        'nombre': 'Contabilidad',
        'descripcion': 'Movimientos, plantillas y cierres contables.',
        'categoria': 'finanzas',
        'config_key': 'contabilidad_habilitada',
        'default': True,
        'orden': 120,
        'is_core': False,
    },
    MODULE_SUPPORT: {
        'nombre': 'Soporte',
        'descripcion': 'Tickets de clientes y configuracion del canal de soporte.',
        'categoria': 'clientes',
        'config_key': 'soporte_habilitado',
        'default': True,
        'orden': 130,
        'is_core': False,
    },
    MODULE_VIDEO: {
        'nombre': 'Videollamadas',
        'descripcion': 'Salas de videollamadas e invitaciones con Jitsi.',
        'categoria': 'clientes',
        'config_key': 'video_habilitado',
        'default': True,
        'orden': 140,
        'is_core': False,
    },
    MODULE_RESTAURANT_TABLES: {
        'nombre': 'Mesas Restaurante',
        'descripcion': 'Plano interactivo de mesas, cuenta abierta y consumos por mesa.',
        'categoria': 'operacion',
        'config_key': 'restaurant_tables_habilitado',
        'default': True,
        'orden': 150,
        'is_core': False,
    },
    MODULE_FACTURACION_ELECTRONICA: {
        'nombre': 'Facturacion DIAN',
        'descripcion': 'Facturacion electronica integrada con el microservicio DIAN.',
        'categoria': 'finanzas',
        'config_key': 'facturacion_electronica',
        'default': False,
        'orden': 160,
        'is_core': False,
    },
    MODULE_SHARE: {
        'nombre': 'Compartir Archivos',
        'descripcion': 'Carpetas y archivos compartidos con clientes mediante link publico.',
        'categoria': 'clientes',
        'config_key': 'share_habilitado',
        'default': True,
        'orden': 145,
        'is_core': False,
    },
}


def _log_warning(message):
    try:
        current_app.logger.warning(message)
    except Exception:
        pass


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() not in {'false', '0', 'no', 'off'}


@lru_cache(maxsize=32)
def _table_exists(table_name):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT to_regclass(%s) AS regclass_name", (f'public.{table_name}',))
            row = cur.fetchone()
            return bool(row and row['regclass_name'])
    except Exception:
        return False


@lru_cache(maxsize=64)
def _table_has_column(table_name, column_name):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = %s
                      AND column_name = %s
                ) AS column_exists
            """, (table_name, column_name))
            row = cur.fetchone()
            return bool(row and row['column_exists'])
    except Exception:
        return False


def _feature_tables_ready():
    return _table_exists('saas_tenants') and _table_exists('saas_modules') and _table_exists('saas_tenant_modules')


@lru_cache(maxsize=1)
def _get_module_config_rows():
    config_keys = sorted({
        meta['config_key']
        for meta in MODULE_DEFINITIONS.values()
        if meta.get('config_key')
    })
    if not config_keys:
        return {}

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT clave, valor
                FROM cliente_config
                WHERE clave = ANY(%s)
            """, (config_keys,))
            return {row['clave']: row['valor'] for row in cur.fetchall()}
    except Exception as exc:
        _log_warning(f'No fue posible cargar flags de modulo desde cliente_config: {exc}')
        return {}


def _clear_cache():
    _table_exists.cache_clear()
    _table_has_column.cache_clear()
    _get_module_config_rows.cache_clear()


def _get_module_meta(module_code):
    return MODULE_DEFINITIONS.get(module_code)


def _resolve_config_state(meta, stored_flags=None):
    if not meta:
        return False
    stored_flags = stored_flags if stored_flags is not None else _get_module_config_rows()
    config_key = meta.get('config_key')
    if config_key:
        return _as_bool(stored_flags.get(config_key), meta.get('default', False))
    return bool(meta.get('default', False))


def _normalize_module_row(module_code, meta=None, row=None, stored_flags=None):
    meta = meta or _get_module_meta(module_code) or {}
    row = row or {}

    raw_is_active = row.get('is_active')
    if raw_is_active is None:
        is_active = _resolve_config_state(meta, stored_flags)
    else:
        is_active = bool(raw_is_active)

    return {
        'id': row.get('id'),
        'code': module_code,
        'nombre': row.get('nombre') or meta.get('nombre') or module_code,
        'descripcion': row.get('descripcion') or meta.get('descripcion') or '',
        'categoria': row.get('categoria') or meta.get('categoria') or 'general',
        'config_key': meta.get('config_key'),
        'is_core': row.get('is_core') if row.get('is_core') is not None else meta.get('is_core', False),
        'is_active': is_active,
        'orden': meta.get('orden', 9999),
        'updated_at': row.get('updated_at'),
    }


def _sort_modules(modules):
    modules.sort(key=lambda item: (item.get('orden', 9999), item.get('nombre', item.get('code', ''))))
    return modules


def _save_config_flag(cur, config_key, value, descripcion, orden):
    cur.execute("""
        UPDATE cliente_config
        SET valor = %s,
            tipo = 'boolean',
            grupo = 'modulos',
            descripcion = %s,
            orden = %s
        WHERE clave = %s
    """, (value, descripcion, orden, config_key))
    if cur.rowcount == 0:
        cur.execute("""
            INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
            VALUES (%s, %s, 'boolean', 'modulos', %s, %s)
        """, (config_key, value, descripcion, orden))


def get_default_tenant_id():
    if _feature_tables_ready():
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    SELECT id
                    FROM saas_tenants
                    WHERE is_default = TRUE
                    ORDER BY id
                    LIMIT 1
                """)
                row = cur.fetchone()
                if row and row['id']:
                    return row['id']
        except Exception as exc:
            _log_warning(f'No fue posible resolver tenant por defecto: {exc}')
    return LOCAL_TENANT_ID


def resolve_user_tenant_id(user_id):
    if not user_id:
        return get_default_tenant_id()

    try:
        if not _table_has_column('usuarios', 'tenant_id'):
            return get_default_tenant_id()
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT tenant_id FROM usuarios WHERE id = %s", (user_id,))
            row = cur.fetchone()
            return row['tenant_id'] if row and row['tenant_id'] else get_default_tenant_id()
    except Exception:
        return get_default_tenant_id()


def bind_session_tenant(usuario=None, user_id=None):
    tenant_id = None
    if usuario:
        try:
            tenant_id = usuario.get('tenant_id')
        except Exception:
            tenant_id = None
        if tenant_id is None:
            try:
                tenant_id = dict(usuario).get('tenant_id')
            except Exception:
                tenant_id = None
    if not tenant_id and user_id:
        tenant_id = resolve_user_tenant_id(user_id)
    tenant_id = tenant_id or get_default_tenant_id()
    session['tenant_id'] = tenant_id
    return tenant_id


def get_current_tenant_id():
    tenant_id = session.get('tenant_id')
    if tenant_id:
        return tenant_id

    tenant_id = resolve_user_tenant_id(session.get('usuario_id'))
    session['tenant_id'] = tenant_id
    return tenant_id


def _fallback_module_settings():
    stored_flags = _get_module_config_rows()
    modules = [
        _normalize_module_row(code, meta=meta, row={'id': index}, stored_flags=stored_flags)
        for index, (code, meta) in enumerate(MODULE_DEFINITIONS.items(), start=1)
    ]
    return _sort_modules(modules)


def get_module_settings(tenant_id=None):
    tenant_id = tenant_id or get_current_tenant_id() or get_default_tenant_id()
    if _feature_tables_ready():
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    SELECT m.id,
                           m.code,
                           m.nombre,
                           m.descripcion,
                           m.categoria,
                           m.is_core,
                           tm.is_active,
                           tm.updated_at
                    FROM saas_modules m
                    LEFT JOIN saas_tenant_modules tm
                      ON tm.module_id = m.id
                     AND tm.tenant_id = %s
                """, (tenant_id,))
                raw_rows = [dict(row) for row in cur.fetchall()]
                stored_flags = _get_module_config_rows()
                rows_by_code = {row['code']: row for row in raw_rows}
                modules = [
                    _normalize_module_row(code, meta=meta, row=rows_by_code.get(code), stored_flags=stored_flags)
                    for code, meta in MODULE_DEFINITIONS.items()
                ]
                known_codes = set(MODULE_DEFINITIONS)
                for row in raw_rows:
                    if row['code'] in known_codes:
                        continue
                    modules.append(_normalize_module_row(row['code'], row=row, stored_flags=stored_flags))
                return _sort_modules(modules)
        except Exception as exc:
            _log_warning(f'No fue posible cargar modulos SaaS para tenant {tenant_id}: {exc}')
    return _fallback_module_settings()


def is_module_active(module_code, tenant_id=None):
    tenant_id = tenant_id or get_current_tenant_id() or get_default_tenant_id()
    if _feature_tables_ready():
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    SELECT tm.is_active
                    FROM saas_modules m
                    LEFT JOIN saas_tenant_modules tm
                      ON tm.module_id = m.id
                     AND tm.tenant_id = %s
                    WHERE m.code = %s
                    LIMIT 1
                """, (tenant_id, module_code))
                row = cur.fetchone()
                if row is not None:
                    if row['is_active'] is not None:
                        return bool(row['is_active'])
                    return _resolve_config_state(_get_module_meta(module_code))
        except Exception as exc:
            _log_warning(f'No fue posible consultar flag {module_code} para tenant {tenant_id}: {exc}')

    return _resolve_config_state(_get_module_meta(module_code))


def get_active_module_codes(tenant_id=None):
    return {
        module['code']
        for module in get_module_settings(tenant_id)
        if module['is_active']
    }


def list_tenants():
    if _feature_tables_ready():
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    SELECT id, slug, nombre, estado, is_default, created_at
                    FROM saas_tenants
                    ORDER BY is_default DESC, nombre ASC
                """)
                rows = cur.fetchall()
                if rows:
                    return [dict(row) for row in rows]
        except Exception as exc:
            _log_warning(f'No fue posible listar tenants: {exc}')

    return [{
        'id': LOCAL_TENANT_ID,
        'slug': 'instancia-local',
        'nombre': 'Instancia actual',
        'estado': 'activo',
        'is_default': True,
        'created_at': None,
    }]


def list_modules_for_tenant(tenant_id):
    return get_module_settings(tenant_id)


def set_module_state(module_code, is_active):
    tenant_id = get_current_tenant_id() or get_default_tenant_id()
    return set_tenant_module_state(tenant_id, module_code, is_active)


def set_tenant_module_state(tenant_id, module_code, is_active):
    meta = MODULE_DEFINITIONS.get(module_code)
    if not meta:
        return False
    config_value = 'true' if is_active else 'false'
    config_key = meta['config_key']
    descripcion = meta['descripcion']
    orden = meta.get('orden', 0)

    if _feature_tables_ready():
        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (code)
                    DO UPDATE SET
                        nombre = EXCLUDED.nombre,
                        descripcion = EXCLUDED.descripcion,
                        categoria = EXCLUDED.categoria,
                        is_core = EXCLUDED.is_core,
                        updated_at = NOW()
                    RETURNING id
                """, (
                    module_code,
                    meta['nombre'],
                    meta['descripcion'],
                    meta['categoria'],
                    meta.get('is_core', False),
                ))
                module_id = cur.fetchone()[0]
                cur.execute("""
                    INSERT INTO saas_tenant_modules (tenant_id, module_id, is_active, created_at, updated_at)
                    VALUES (%s, %s, %s, NOW(), NOW())
                    ON CONFLICT (tenant_id, module_id)
                    DO UPDATE SET
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                """, (tenant_id, module_id, bool(is_active)))
                _save_config_flag(cur, config_key, config_value, descripcion, orden)
            _clear_cache()
            return True
        except Exception as exc:
            _log_warning(f"No fue posible actualizar el modulo {module_code} del tenant {tenant_id}: {exc}")
            return False

    try:
        with get_db_cursor() as cur:
            _save_config_flag(cur, config_key, config_value, descripcion, orden)
        _clear_cache()
        return True
    except Exception as exc:
        _log_warning(f"No fue posible actualizar el modulo local {module_code}: {exc}")
        return False


def module_required(module_code, redirect_endpoint='admin.dashboard_admin'):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            tenant_id = get_current_tenant_id()
            if is_module_active(module_code, tenant_id):
                return fn(*args, **kwargs)

            if request.is_json or request.path.endswith('/data') or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': False,
                    'error': 'module_disabled',
                    'module_code': module_code,
                }), 403

            flash('El modulo no esta activo para este tenant.', 'warning')
            return redirect(url_for(redirect_endpoint))
        return wrapped
    return decorator
