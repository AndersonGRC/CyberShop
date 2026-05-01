"""
restaurant_tables_service.py - API interna del modulo de mesas.

El blueprint de restaurante depende de este archivo, no del core POS.
Eso permite apagar el modulo o retirarlo sin introducir acoplamientos
directos con otras rutas del ERP.
"""

from datetime import date, datetime
from functools import lru_cache

from database import get_db_cursor


TABLE_STATES = {
    'disponible': 'Disponible',
    'ocupada': 'Ocupada',
    'reservada': 'Reservada',
    'cuenta_solicitada': 'Cuenta Solicitada',
}

CONSUMPTION_STATES = {
    'pendiente': 'Pendiente',
    'preparando': 'Preparando',
    'servido': 'Servido',
}

PAYMENT_METHODS = {
    'EFECTIVO': 'Efectivo',
    'TARJETA': 'Tarjeta',
    'TRANSFERENCIA': 'Transferencia',
    'MIXTO': 'Mixto',
}

ACCOUNTING_STATUSES = {
    'pendiente': 'Pendiente',
    'sincronizada': 'Sincronizada',
    'revertida': 'Revertida',
    'sin_contabilidad': 'Sin contabilidad',
    'no_aplica': 'No aplica',
}

SHAPES = {'round', 'square', 'rectangle'}
WAIT_TARGET_MINUTES = 35


def _empty_summary():
    return {
        'total_mesas': 0,
        'disponibles': 0,
        'ocupadas': 0,
        'reservadas': 0,
        'cuenta_solicitada': 0,
        'pendientes': 0,
        'cuentas_abiertas': 0,
    }


def _empty_report_summary():
    return {
        'ventas_cerradas': 0,
        'ventas_canceladas': 0,
        'ingresos_totales': 0.0,
        'anulaciones_totales': 0.0,
        'ticket_promedio': 0.0,
        'ordenes_abiertas': 0,
        'sincronizadas': 0,
        'pendientes_sync': 0,
    }


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


@lru_cache(maxsize=32)
def _get_table_columns(table_name):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
            """, (table_name,))
            return {row['column_name'] for row in cur.fetchall()}
    except Exception:
        return set()


def _module_schema_status():
    required_tables = (
        'restaurant_tables',
        'restaurant_table_orders',
        'restaurant_table_consumptions',
    )
    missing = [table for table in required_tables if not _table_exists(table)]
    return {
        'ready': not missing,
        'missing': missing,
        'message': (
            'El esquema del modulo de mesas no esta instalado. '
            'Ejecuta la migracion app/migrate_restaurant_tables_module.sql.'
        ) if missing else '',
    }


_RESTAURANT_TABLES_DEFAULTS_REPAIRED = False
_RESTAURANT_ORDER_DEFAULTS_REPAIRED = False
_RESTAURANT_CONSUMPTION_DEFAULTS_REPAIRED = False
_ACCOUNTING_MOVEMENTS_DEFAULTS_REPAIRED = False


def _repair_restaurant_tables_defaults():
    """Restaura defaults faltantes en restaurant_tables si la tabla fue
    creada en una versión previa sin SERIAL en `id` ni defaults en
    `meta`, `created_at`, `updated_at`. Idempotente y se ejecuta solo
    una vez por proceso."""
    global _RESTAURANT_TABLES_DEFAULTS_REPAIRED
    if _RESTAURANT_TABLES_DEFAULTS_REPAIRED:
        return
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT column_name, column_default, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'restaurant_tables'
            """)
            cols = {row['column_name']: row for row in cur.fetchall()}

            id_col = cols.get('id')
            if id_col and not id_col['column_default']:
                cur.execute("""
                    CREATE SEQUENCE IF NOT EXISTS restaurant_tables_id_seq
                """)
                cur.execute("""
                    ALTER SEQUENCE restaurant_tables_id_seq
                    OWNED BY restaurant_tables.id
                """)
                cur.execute("""
                    ALTER TABLE restaurant_tables
                    ALTER COLUMN id SET DEFAULT nextval('restaurant_tables_id_seq')
                """)
                cur.execute("""
                    SELECT setval(
                        'restaurant_tables_id_seq',
                        COALESCE((SELECT MAX(id) FROM restaurant_tables), 0) + 1,
                        false
                    )
                """)

            patches = {
                'meta': "'{}'::jsonb",
                'created_at': 'NOW()',
                'updated_at': 'NOW()',
                'area': "'Salon principal'",
                'capacidad': '4',
                'forma': "'square'",
                'estado': "'disponible'",
                'pos_x': '8',
                'pos_y': '10',
                'ancho': '16',
                'alto': '16',
                'rotacion': '0',
            }
            for col_name, default_expr in patches.items():
                col = cols.get(col_name)
                if col and not col['column_default']:
                    cur.execute(
                        f"ALTER TABLE restaurant_tables "
                        f"ALTER COLUMN {col_name} SET DEFAULT {default_expr}"
                    )
        _RESTAURANT_TABLES_DEFAULTS_REPAIRED = True
    except Exception:
        # No bloquear el módulo si la reparación falla; el error original
        # se reportará en el INSERT con un mensaje más claro.
        pass


def _repair_restaurant_table_orders_defaults():
    """Restaura defaults faltantes en restaurant_table_orders."""
    global _RESTAURANT_ORDER_DEFAULTS_REPAIRED
    if _RESTAURANT_ORDER_DEFAULTS_REPAIRED:
        return
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT column_name, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'restaurant_table_orders'
            """)
            cols = {row['column_name']: row for row in cur.fetchall()}

            id_col = cols.get('id')
            if id_col and not id_col['column_default']:
                cur.execute("""
                    CREATE SEQUENCE IF NOT EXISTS restaurant_table_orders_id_seq
                """)
                cur.execute("""
                    ALTER SEQUENCE restaurant_table_orders_id_seq
                    OWNED BY restaurant_table_orders.id
                """)
                cur.execute("""
                    ALTER TABLE restaurant_table_orders
                    ALTER COLUMN id SET DEFAULT nextval('restaurant_table_orders_id_seq')
                """)
                cur.execute("""
                    SELECT setval(
                        'restaurant_table_orders_id_seq',
                        COALESCE((SELECT MAX(id) FROM restaurant_table_orders), 0) + 1,
                        false
                    )
                """)

            patches = {
                'estado': "'abierta'",
                'comensales': '1',
                'total_acumulado': '0',
                'payment_method': "'EFECTIVO'",
                'accounting_status': "'pendiente'",
                'opened_at': 'NOW()',
                'last_activity_at': 'NOW()',
                'created_at': 'NOW()',
                'updated_at': 'NOW()',
            }
            for col_name, default_expr in patches.items():
                col = cols.get(col_name)
                if col and not col['column_default']:
                    cur.execute(
                        f"ALTER TABLE restaurant_table_orders "
                        f"ALTER COLUMN {col_name} SET DEFAULT {default_expr}"
                    )
        _RESTAURANT_ORDER_DEFAULTS_REPAIRED = True
    except Exception:
        pass


def _repair_restaurant_table_consumptions_defaults():
    """Restaura defaults faltantes en restaurant_table_consumptions."""
    global _RESTAURANT_CONSUMPTION_DEFAULTS_REPAIRED
    if _RESTAURANT_CONSUMPTION_DEFAULTS_REPAIRED:
        return
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT column_name, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'restaurant_table_consumptions'
            """)
            cols = {row['column_name']: row for row in cur.fetchall()}

            id_col = cols.get('id')
            if id_col and not id_col['column_default']:
                cur.execute("""
                    CREATE SEQUENCE IF NOT EXISTS restaurant_table_consumptions_id_seq
                """)
                cur.execute("""
                    ALTER SEQUENCE restaurant_table_consumptions_id_seq
                    OWNED BY restaurant_table_consumptions.id
                """)
                cur.execute("""
                    ALTER TABLE restaurant_table_consumptions
                    ALTER COLUMN id SET DEFAULT nextval('restaurant_table_consumptions_id_seq')
                """)
                cur.execute("""
                    SELECT setval(
                        'restaurant_table_consumptions_id_seq',
                        COALESCE((SELECT MAX(id) FROM restaurant_table_consumptions), 0) + 1,
                        false
                    )
                """)

            patches = {
                'cantidad': '1',
                'precio_unitario': '0',
                'subtotal': '0',
                'estado': "'pendiente'",
                'ordered_at': 'NOW()',
                'updated_at': 'NOW()',
            }
            for col_name, default_expr in patches.items():
                col = cols.get(col_name)
                if col and not col['column_default']:
                    cur.execute(
                        f"ALTER TABLE restaurant_table_consumptions "
                        f"ALTER COLUMN {col_name} SET DEFAULT {default_expr}"
                    )
        _RESTAURANT_CONSUMPTION_DEFAULTS_REPAIRED = True
    except Exception:
        pass


def _ensure_module_schema():
    status = _module_schema_status()
    if not status['ready']:
        raise ValueError(status['message'])
    _repair_restaurant_tables_defaults()
    _repair_restaurant_table_orders_defaults()
    _repair_restaurant_table_consumptions_defaults()
    return status


def _parse_int(value, default=None, minimum=None, maximum=None, field='valor'):
    if value in (None, ''):
        return default
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f'El campo {field} debe ser numérico.')
    if minimum is not None and parsed < minimum:
        raise ValueError(f'El campo {field} no puede ser menor a {minimum}.')
    if maximum is not None and parsed > maximum:
        raise ValueError(f'El campo {field} no puede ser mayor a {maximum}.')
    return parsed


def _parse_float(value, default=None, minimum=None, maximum=None, field='valor'):
    if value in (None, ''):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'El campo {field} debe ser numérico.')
    if minimum is not None and parsed < minimum:
        raise ValueError(f'El campo {field} no puede ser menor a {minimum}.')
    if maximum is not None and parsed > maximum:
        raise ValueError(f'El campo {field} no puede ser mayor a {maximum}.')
    return parsed


def _minutes_between(start_dt, end_dt=None):
    if not start_dt:
        return 0
    end_dt = end_dt or datetime.utcnow()
    if hasattr(start_dt, 'tzinfo') and start_dt.tzinfo is not None:
        start_dt = start_dt.replace(tzinfo=None)
    delta = end_dt - start_dt
    return max(0, int(delta.total_seconds() // 60))


def _wait_progress(minutes):
    if minutes <= 0:
        return 0
    return min(100, int((minutes / WAIT_TARGET_MINUTES) * 100))


def _build_area_options(rows):
    options = sorted({(row.get('area') or 'Salon principal').strip() for row in rows if row.get('area')})
    if 'Salon principal' not in options:
        options.insert(0, 'Salon principal')
    return options


def _inventory_log_enabled():
    return _table_exists('inventario_log')


def _record_inventory_log(cur, producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, usuario_id):
    if not _inventory_log_enabled():
        return
    cur.execute("""
        INSERT INTO inventario_log (
            producto_id, tipo, cantidad, stock_anterior,
            stock_nuevo, motivo, usuario_id, fecha
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
    """, (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, usuario_id))


def _get_effective_order_state(table_row):
    current_state = table_row['estado']
    if table_row.get('open_order_id') and current_state == 'disponible':
        return 'ocupada'
    return current_state


def _serialize_consumption(item):
    return {
        'id': item['id'],
        'descripcion': item['descripcion'],
        'cantidad': int(item['cantidad']),
        'precio_unitario': float(item['precio_unitario']),
        'subtotal': float(item['subtotal']),
        'estado': item['estado'],
        'estado_label': CONSUMPTION_STATES.get(item['estado'], item['estado'].title()),
        'notas': item['notas'] or '',
        'ordered_at': item['ordered_at'].isoformat() if item.get('ordered_at') else None,
    }


def get_product_catalog():
    """Retorna productos disponibles para agregar a una mesa, con categoría."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT p.id, p.nombre, p.precio, p.stock,
                       p.imagen,
                       p.genero_id,
                       COALESCE(g.nombre, 'Sin categoría') AS genero_nombre
                FROM productos p
                LEFT JOIN generos g ON g.id = p.genero_id
                WHERE p.stock > 0
                ORDER BY g.nombre ASC, p.nombre ASC
            """)
            return cur.fetchall()
    except Exception:
        return []


def list_floor_tables(area=None):
    """Carga mesas con su estado operativo y cuenta abierta actual."""
    status = _module_schema_status()
    if not status['ready']:
        return {
            'tables': [],
            'areas': ['Salon principal'],
            'summary': _empty_summary(),
            'schema_ready': False,
            'schema_message': status['message'],
        }

    params = []
    area_sql = ""
    if area:
        area_sql = " AND t.area = %s"
        params.append(area)

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(f"""
            SELECT t.*,
                   o.id AS open_order_id,
                   o.estado AS open_order_status,
                   o.cliente_nombre,
                   o.comensales,
                   o.notas AS order_notes,
                   o.opened_at,
                   o.last_activity_at,
                   o.total_acumulado,
                   {("o.payment_method," if _table_has_column('restaurant_table_orders', 'payment_method') else "NULL::VARCHAR AS payment_method,")}
                   COALESCE(stats.pending_count, 0) AS pending_count,
                   COALESCE(stats.preparing_count, 0) AS preparing_count,
                   COALESCE(stats.served_count, 0) AS served_count,
                   COALESCE(stats.total_items, 0) AS total_items,
                   stats.oldest_pending_at
            FROM restaurant_tables t
            LEFT JOIN restaurant_table_orders o
              ON o.table_id = t.id
             AND o.estado = 'abierta'
            LEFT JOIN LATERAL (
                SELECT COUNT(*) FILTER (WHERE c.estado = 'pendiente') AS pending_count,
                       COUNT(*) FILTER (WHERE c.estado = 'preparando') AS preparing_count,
                       COUNT(*) FILTER (WHERE c.estado = 'servido') AS served_count,
                       COUNT(*) AS total_items,
                       MIN(c.ordered_at) FILTER (WHERE c.estado IN ('pendiente', 'preparando')) AS oldest_pending_at
                FROM restaurant_table_consumptions c
                WHERE c.order_id = o.id
            ) stats ON TRUE
            WHERE 1 = 1
            {area_sql}
            ORDER BY t.area ASC, t.nombre ASC, t.id ASC
        """, tuple(params))
        tables = cur.fetchall()

        open_order_ids = [row['open_order_id'] for row in tables if row['open_order_id']]
        consumptions_map = {}
        if open_order_ids:
            cur.execute("""
                SELECT c.id,
                       c.order_id,
                       c.table_id,
                       c.producto_id,
                       c.descripcion,
                       c.cantidad,
                       c.precio_unitario,
                       c.subtotal,
                       c.estado,
                       c.notas,
                       c.ordered_at,
                       c.updated_at
                FROM restaurant_table_consumptions c
                WHERE c.order_id = ANY(%s)
                ORDER BY c.ordered_at ASC, c.id ASC
            """, (open_order_ids,))
            for row in cur.fetchall():
                consumptions_map.setdefault(row['order_id'], []).append(row)

    now = datetime.utcnow()
    normalized = []
    summary = _empty_summary()

    for row in tables:
        minutes_open = _minutes_between(row.get('opened_at'), now) if row.get('open_order_id') else 0
        minutes_pending = _minutes_between(row.get('oldest_pending_at'), now) if row.get('oldest_pending_at') else 0
        current_state = _get_effective_order_state(row)

        summary['total_mesas'] += 1
        if current_state == 'disponible':
            summary['disponibles'] += 1
        elif current_state == 'ocupada':
            summary['ocupadas'] += 1
        elif current_state == 'reservada':
            summary['reservadas'] += 1
        elif current_state == 'cuenta_solicitada':
            summary['cuenta_solicitada'] += 1
        summary['pendientes'] += int(row.get('pending_count') or 0)
        if row.get('open_order_id'):
            summary['cuentas_abiertas'] += 1

        normalized.append({
            'id': row['id'],
            'codigo': row['codigo'],
            'nombre': row['nombre'],
            'area': row['area'],
            'capacidad': row['capacidad'],
            'forma': row['forma'],
            'estado': current_state,
            'estado_label': TABLE_STATES.get(current_state, current_state.title()),
            'pos_x': float(row['pos_x']),
            'pos_y': float(row['pos_y']),
            'ancho': float(row['ancho']),
            'alto': float(row['alto']),
            'rotacion': int(row['rotacion'] or 0),
            'open_order': {
                'id': row['open_order_id'],
                'cliente_nombre': row.get('cliente_nombre') or '',
                'comensales': int(row.get('comensales') or 0),
                'notas': row.get('order_notes') or '',
                'payment_method': row.get('payment_method') or 'EFECTIVO',
                'total_acumulado': float(row.get('total_acumulado') or 0),
                'pending_count': int(row.get('pending_count') or 0),
                'preparing_count': int(row.get('preparing_count') or 0),
                'served_count': int(row.get('served_count') or 0),
                'total_items': int(row.get('total_items') or 0),
                'minutes_open': minutes_open,
                'minutes_pending': minutes_pending,
                'wait_progress': _wait_progress(minutes_pending or minutes_open),
                'consumptions': [
                    _serialize_consumption(item)
                    for item in consumptions_map.get(row['open_order_id'], [])
                ],
            } if row.get('open_order_id') else None,
        })

    return {
        'tables': normalized,
        'areas': _build_area_options(normalized),
        'summary': summary,
        'schema_ready': True,
        'schema_message': '',
    }


def list_restaurant_reports(filters=None):
    """Retorna reportes operativos y contables del módulo."""
    _ensure_module_schema()
    filters = filters or {}

    today = date.today()
    first_day = today.replace(day=1)
    date_from = (filters.get('date_from') or first_day.isoformat()).strip()
    date_to = (filters.get('date_to') or today.isoformat()).strip()
    area = (filters.get('area') or '').strip()
    status = (filters.get('status') or '').strip().lower()

    try:
        date.fromisoformat(date_from)
        date.fromisoformat(date_to)
    except ValueError:
        raise ValueError('Las fechas del reporte no tienen un formato válido.')

    if date_from > date_to:
        raise ValueError('La fecha inicial no puede ser mayor a la fecha final.')

    where = [
        "DATE(COALESCE(o.closed_at, o.cancelled_at, o.opened_at)) BETWEEN %s AND %s",
    ]
    params = [date_from, date_to]

    if area:
        where.append("t.area = %s")
        params.append(area)
    if status:
        where.append("o.estado = %s")
        params.append(status)

    payment_method_sql = "o.payment_method" if _table_has_column('restaurant_table_orders', 'payment_method') else "NULL::VARCHAR"
    cancel_reason_sql = "o.cancel_reason" if _table_has_column('restaurant_table_orders', 'cancel_reason') else "NULL::TEXT"
    cancelled_at_sql = "o.cancelled_at" if _table_has_column('restaurant_table_orders', 'cancelled_at') else "NULL::TIMESTAMP"
    accounting_status_sql = "o.accounting_status" if _table_has_column('restaurant_table_orders', 'accounting_status') else "NULL::VARCHAR"
    accounting_income_id_sql = (
        "o.accounting_income_movement_id"
        if _table_has_column('restaurant_table_orders', 'accounting_income_movement_id')
        else "NULL::INTEGER"
    )
    accounting_reversal_id_sql = (
        "o.accounting_reversal_movement_id"
        if _table_has_column('restaurant_table_orders', 'accounting_reversal_movement_id')
        else "NULL::INTEGER"
    )

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(f"""
            SELECT o.id,
                   o.table_id,
                   t.codigo AS codigo_mesa,
                   t.nombre AS nombre_mesa,
                   t.area,
                   o.estado,
                   o.cliente_nombre,
                   o.comensales,
                   o.notas,
                   o.total_acumulado,
                   o.opened_at,
                   o.last_activity_at,
                   o.closed_at,
                   {cancelled_at_sql} AS cancelled_at,
                   {cancel_reason_sql} AS cancel_reason,
                   {payment_method_sql} AS payment_method,
                   {accounting_status_sql} AS accounting_status,
                   {accounting_income_id_sql} AS accounting_income_movement_id,
                   {accounting_reversal_id_sql} AS accounting_reversal_movement_id,
                   COALESCE(stats.pending_count, 0) AS pending_count,
                   COALESCE(stats.preparing_count, 0) AS preparing_count,
                   COALESCE(stats.served_count, 0) AS served_count,
                   COALESCE(stats.total_items, 0) AS total_items
            FROM restaurant_table_orders o
            JOIN restaurant_tables t
              ON t.id = o.table_id
            LEFT JOIN LATERAL (
                SELECT COUNT(*) FILTER (WHERE c.estado = 'pendiente') AS pending_count,
                       COUNT(*) FILTER (WHERE c.estado = 'preparando') AS preparing_count,
                       COUNT(*) FILTER (WHERE c.estado = 'servido') AS served_count,
                       COUNT(*) AS total_items
                FROM restaurant_table_consumptions c
                WHERE c.order_id = o.id
            ) stats ON TRUE
            WHERE {" AND ".join(where)}
            ORDER BY COALESCE(o.closed_at, {cancelled_at_sql}, o.opened_at) DESC, o.id DESC
        """, tuple(params))
        orders = [dict(row) for row in cur.fetchall()]

    summary = _empty_report_summary()
    payment_breakdown = {}
    top_tables = {}

    for row in orders:
        total = float(row.get('total_acumulado') or 0)
        status_value = row.get('estado')
        accounting_status = row.get('accounting_status') or 'pendiente'
        duration_minutes = _minutes_between(row.get('opened_at'), row.get('closed_at') or row.get('cancelled_at') or datetime.utcnow())
        row['total_acumulado'] = total
        row['duration_minutes'] = duration_minutes
        row['payment_method_label'] = PAYMENT_METHODS.get(row.get('payment_method') or '', row.get('payment_method') or 'Sin definir')
        row['accounting_status_label'] = ACCOUNTING_STATUSES.get(accounting_status, accounting_status.replace('_', ' ').title())
        row['can_cancel_sale'] = status_value == 'cerrada'

        if status_value == 'cerrada':
            summary['ventas_cerradas'] += 1
            summary['ingresos_totales'] += total
        elif status_value == 'cancelada':
            summary['ventas_canceladas'] += 1
            summary['anulaciones_totales'] += total
        elif status_value == 'abierta':
            summary['ordenes_abiertas'] += 1

        if accounting_status in {'sincronizada', 'revertida'}:
            summary['sincronizadas'] += 1
        else:
            summary['pendientes_sync'] += 1

        method = row.get('payment_method') or 'SIN_METODO'
        payment_breakdown[method] = payment_breakdown.get(method, 0) + total

        table_key = row['codigo_mesa']
        top_tables[table_key] = top_tables.get(table_key, 0) + total

    if summary['ventas_cerradas'] > 0:
        summary['ticket_promedio'] = round(summary['ingresos_totales'] / summary['ventas_cerradas'], 2)

    payment_items = [
        {'code': key, 'label': PAYMENT_METHODS.get(key, key.replace('_', ' ').title()), 'total': round(total, 2)}
        for key, total in sorted(payment_breakdown.items(), key=lambda item: item[1], reverse=True)
    ]
    top_table_items = [
        {'codigo': key, 'total': round(total, 2)}
        for key, total in sorted(top_tables.items(), key=lambda item: item[1], reverse=True)[:5]
    ]

    return {
        'summary': summary,
        'orders': orders,
        'areas': _build_area_options([{'area': row['area']} for row in orders]),
        'filters': {
            'date_from': date_from,
            'date_to': date_to,
            'area': area,
            'status': status,
        },
        'payment_breakdown': payment_items,
        'top_tables': top_table_items,
    }


def _generate_next_table_code(cur):
    cur.execute("""
        SELECT COALESCE(
            MAX(NULLIF(REGEXP_REPLACE(codigo, '[^0-9]', '', 'g'), '')::INTEGER),
            0
        ) AS max_seq
        FROM restaurant_tables
    """)
    total = int(cur.fetchone()['max_seq'] or 0)
    return f"M-{total + 1:02d}"


def upsert_table_layout(user_id, payload):
    """Crea o actualiza una mesa del plano."""
    _ensure_module_schema()
    table_id = _parse_int(payload.get('table_id'), default=None, minimum=1, field='mesa')
    codigo = (payload.get('codigo') or '').strip().upper()
    nombre = (payload.get('nombre') or '').strip()
    area = (payload.get('area') or 'Salon principal').strip() or 'Salon principal'
    forma = (payload.get('forma') or 'square').strip().lower()
    estado = (payload.get('estado') or 'disponible').strip().lower()

    if forma not in SHAPES:
        raise ValueError('La forma de la mesa no es válida.')
    if estado not in TABLE_STATES:
        raise ValueError('El estado de la mesa no es válido.')

    capacidad = _parse_int(payload.get('capacidad'), default=4, minimum=1, maximum=30, field='capacidad')
    pos_x = min(96.0, max(0.0, _parse_float(payload.get('pos_x'), default=6, minimum=0, maximum=96, field='posición X')))
    pos_y = min(92.0, max(0.0, _parse_float(payload.get('pos_y'), default=8, minimum=0, maximum=92, field='posición Y')))
    ancho = min(30.0, max(8.0, _parse_float(payload.get('ancho'), default=16, minimum=8, maximum=30, field='ancho')))
    alto = min(30.0, max(8.0, _parse_float(payload.get('alto'), default=16, minimum=8, maximum=30, field='alto')))
    rotacion = _parse_int(payload.get('rotacion'), default=0, minimum=0, maximum=359, field='rotación')

    with get_db_cursor(dict_cursor=True) as cur:
        if not codigo:
            codigo = _generate_next_table_code(cur)
        if not nombre:
            nombre = f"Mesa {codigo}"

        cur.execute("""
            SELECT id
            FROM restaurant_tables
            WHERE codigo = %s
              AND (%s IS NULL OR id <> %s)
            LIMIT 1
        """, (codigo, table_id, table_id))
        if cur.fetchone():
            raise ValueError(f'Ya existe una mesa con el código {codigo}.')

        if table_id:
            cur.execute("""
                UPDATE restaurant_tables
                SET codigo = %s,
                    nombre = %s,
                    area = %s,
                    capacidad = %s,
                    forma = %s,
                    estado = %s,
                    pos_x = %s,
                    pos_y = %s,
                    ancho = %s,
                    alto = %s,
                    rotacion = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id
            """, (codigo, nombre, area, capacidad, forma, estado,
                  pos_x, pos_y, ancho, alto, rotacion, table_id))
        else:
            try:
                if _table_has_column('restaurant_tables', 'tenant_id'):
                    cur.execute("""
                        INSERT INTO restaurant_tables (
                            tenant_id, codigo, nombre, area, capacidad, forma,
                            estado, pos_x, pos_y, ancho, alto, rotacion, creado_por
                        )
                        VALUES (
                            COALESCE((SELECT tenant_id FROM restaurant_tables ORDER BY id ASC LIMIT 1), 1),
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        RETURNING id
                    """, (codigo, nombre, area, capacidad, forma,
                          estado, pos_x, pos_y, ancho, alto, rotacion, user_id))
                else:
                    cur.execute("""
                        INSERT INTO restaurant_tables (
                            codigo, nombre, area, capacidad, forma,
                            estado, pos_x, pos_y, ancho, alto, rotacion, creado_por
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (codigo, nombre, area, capacidad, forma,
                          estado, pos_x, pos_y, ancho, alto, rotacion, user_id))
            except Exception as exc:
                if 'not-null' in str(exc) and '"id"' in str(exc):
                    raise ValueError(
                        'La secuencia de IDs de mesas no está configurada. '
                        'Por favor ejecuta nuevamente la migración del módulo '
                        'de mesas (migrate_restaurant_tables_module.sql).'
                    ) from exc
                raise

        row = cur.fetchone()
        if not row:
            raise ValueError('No fue posible guardar la mesa.')
        return row['id']


def delete_table_layout(table_id):
    """Elimina una mesa del plano si no tiene historial operativo."""
    _ensure_module_schema()

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, codigo, nombre
            FROM restaurant_tables
            WHERE id = %s
            LIMIT 1
        """, (table_id,))
        table_row = cur.fetchone()
        if not table_row:
            raise ValueError('Mesa no encontrada.')

        cur.execute("""
            SELECT COUNT(*) AS total_orders,
                   COUNT(*) FILTER (WHERE estado = 'abierta') AS open_orders
            FROM restaurant_table_orders
            WHERE table_id = %s
        """, (table_id,))
        usage = cur.fetchone() or {}
        total_orders = int(usage.get('total_orders') or 0)
        open_orders = int(usage.get('open_orders') or 0)

        if open_orders > 0:
            raise ValueError('No puedes eliminar una mesa con una cuenta abierta.')
        if total_orders > 0:
            raise ValueError(
                'No puedes eliminar una mesa que ya tiene historial de órdenes. '
                'Puedes renombrarla o dejarla fuera de uso.'
            )

        cur.execute("""
            DELETE FROM restaurant_tables
            WHERE id = %s
            RETURNING id
        """, (table_id,))
        deleted = cur.fetchone()
        if not deleted:
            raise ValueError('No fue posible eliminar la mesa.')

    return {
        'table_id': table_row['id'],
        'codigo': table_row['codigo'],
        'nombre': table_row['nombre'],
    }


def _sync_open_order_context(cur, order_id, payload):
    payload = payload or {}
    if not order_id:
        return
    cliente_nombre = (payload.get('cliente_nombre') or '').strip() or None
    comensales = _parse_int(payload.get('comensales'), default=None, minimum=1, maximum=50, field='comensales')
    notas = (payload.get('order_notes') or payload.get('notas_orden') or '').strip() or None
    cur.execute("""
        UPDATE restaurant_table_orders
        SET cliente_nombre = COALESCE(%s, cliente_nombre),
            comensales = COALESCE(%s, comensales),
            notas = COALESCE(%s, notas),
            last_activity_at = NOW(),
            updated_at = NOW()
        WHERE id = %s
    """, (cliente_nombre, comensales, notas, order_id))


def _ensure_open_order(cur, table_id, user_id, payload=None):
    payload = payload or {}
    cur.execute("""
        SELECT id
        FROM restaurant_table_orders
        WHERE table_id = %s
          AND estado = 'abierta'
        LIMIT 1
    """, (table_id,))
    row = cur.fetchone()
    if row:
        _sync_open_order_context(cur, row['id'], payload)
        return row['id']

    cliente_nombre = (payload.get('cliente_nombre') or '').strip() or None
    comensales = _parse_int(payload.get('comensales'), default=1, minimum=1, maximum=50, field='comensales')
    notas = (payload.get('order_notes') or payload.get('notas_orden') or '').strip() or None

    if _table_has_column('restaurant_table_orders', 'tenant_id'):
        cur.execute("""
            INSERT INTO restaurant_table_orders (
                tenant_id, table_id, estado, cliente_nombre,
                comensales, notas, abierta_por
            )
            VALUES (
                COALESCE((SELECT tenant_id FROM restaurant_tables WHERE id = %s), 1),
                %s, 'abierta', %s, %s, %s, %s
            )
            RETURNING id
        """, (table_id, table_id, cliente_nombre, comensales, notas, user_id))
    else:
        cur.execute("""
            INSERT INTO restaurant_table_orders (
                table_id, estado, cliente_nombre,
                comensales, notas, abierta_por
            )
            VALUES (%s, 'abierta', %s, %s, %s, %s)
            RETURNING id
        """, (table_id, cliente_nombre, comensales, notas, user_id))
    order_id = cur.fetchone()['id']

    cur.execute("""
        UPDATE restaurant_tables
        SET estado = 'ocupada', updated_at = NOW()
        WHERE id = %s
    """, (table_id,))
    return order_id


def _refresh_order_total(cur, order_id):
    cur.execute("""
        SELECT COALESCE(SUM(subtotal), 0) AS total
        FROM restaurant_table_consumptions
        WHERE order_id = %s
    """, (order_id,))
    total = float(cur.fetchone()['total'] or 0)
    cur.execute("""
        UPDATE restaurant_table_orders
        SET total_acumulado = %s,
            last_activity_at = NOW(),
            updated_at = NOW()
        WHERE id = %s
    """, (total, order_id))
    return total


def _sync_accounting_fields(cur, order_id, status=None, income_movement_id=None, reversal_movement_id=None):
    assignments = []
    values = []

    if _table_has_column('restaurant_table_orders', 'accounting_status') and status is not None:
        assignments.append("accounting_status = %s")
        values.append(status)
    if _table_has_column('restaurant_table_orders', 'accounting_income_movement_id') and income_movement_id is not None:
        assignments.append("accounting_income_movement_id = %s")
        values.append(income_movement_id)
    if _table_has_column('restaurant_table_orders', 'accounting_reversal_movement_id') and reversal_movement_id is not None:
        assignments.append("accounting_reversal_movement_id = %s")
        values.append(reversal_movement_id)
    if _table_has_column('restaurant_table_orders', 'accounting_synced_at') and status in {'sincronizada', 'revertida'}:
        assignments.append("accounting_synced_at = NOW()")

    if not assignments:
        return

    cur.execute(f"""
        UPDATE restaurant_table_orders
        SET {", ".join(assignments)},
            updated_at = NOW()
        WHERE id = %s
    """, tuple(values + [order_id]))


def _repair_accounting_movements_defaults(cur):
    """Restaura secuencia/defaults faltantes en contabilidad_movimientos."""
    global _ACCOUNTING_MOVEMENTS_DEFAULTS_REPAIRED
    if _ACCOUNTING_MOVEMENTS_DEFAULTS_REPAIRED or not _table_exists('contabilidad_movimientos'):
        return

    cur.execute("""
        SELECT column_name, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'contabilidad_movimientos'
    """)
    cols = {row['column_name']: row for row in cur.fetchall()}
    if not cols:
        return

    id_col = cols.get('id')
    if id_col and not id_col['column_default']:
        cur.execute("""
            CREATE SEQUENCE IF NOT EXISTS contabilidad_movimientos_id_seq
        """)
        cur.execute("""
            ALTER SEQUENCE contabilidad_movimientos_id_seq
            OWNED BY contabilidad_movimientos.id
        """)
        cur.execute("""
            ALTER TABLE contabilidad_movimientos
            ALTER COLUMN id SET DEFAULT nextval('contabilidad_movimientos_id_seq')
        """)
        cur.execute("""
            SELECT setval(
                'contabilidad_movimientos_id_seq',
                COALESCE((SELECT MAX(id) FROM contabilidad_movimientos), 0) + 1,
                false
            )
        """)

    patches = {
        'auto_generado': 'FALSE',
        'created_at': 'NOW()',
        'monto_bruto': '0',
        'retefuente_pct': '0',
        'retefuente_monto': '0',
        'iva_pct': '0',
        'iva_monto': '0',
        'reteiva_pct': '0',
        'reteiva_monto': '0',
        'reteica_pct': '0',
        'reteica_monto': '0',
        'total_retenciones': '0',
    }
    for col_name, default_expr in patches.items():
        col = cols.get(col_name)
        if col and not col['column_default']:
            cur.execute(
                f"ALTER TABLE contabilidad_movimientos "
                f"ALTER COLUMN {col_name} SET DEFAULT {default_expr}"
            )

    _ACCOUNTING_MOVEMENTS_DEFAULTS_REPAIRED = True


def _create_accounting_movement(cur, movement_type, category, description, amount, reference_type, reference_id, user_id, notes=None):
    if not _table_exists('contabilidad_movimientos'):
        return {'status': 'sin_contabilidad', 'movement_id': None}

    _repair_accounting_movements_defaults(cur)

    cur.execute("""
        SELECT id
        FROM contabilidad_movimientos
        WHERE referencia_tipo = %s
          AND referencia_id = %s
        ORDER BY id DESC
        LIMIT 1
    """, (reference_type, reference_id))
    existing = cur.fetchone()
    if existing:
        return {'status': 'sincronizada', 'movement_id': existing['id']}

    columns = _get_table_columns('contabilidad_movimientos')
    column_values = {
        'tipo': movement_type,
        'categoria': category,
        'descripcion': description,
        'monto': amount,
        'monto_bruto': amount,
        'retefuente_pct': 0,
        'retefuente_monto': 0,
        'iva_pct': 0,
        'iva_monto': 0,
        'reteiva_pct': 0,
        'reteiva_monto': 0,
        'reteica_pct': 0,
        'reteica_monto': 0,
        'total_retenciones': 0,
        'fecha': date.today(),
        'referencia_tipo': reference_type,
        'referencia_id': reference_id,
        'notas': notes,
        'usuario_id': user_id,
        'auto_generado': True,
    }
    preferred_order = [
        'tipo', 'categoria', 'descripcion', 'monto_bruto', 'monto',
        'retefuente_pct', 'retefuente_monto',
        'iva_pct', 'iva_monto',
        'reteiva_pct', 'reteiva_monto',
        'reteica_pct', 'reteica_monto',
        'total_retenciones',
        'fecha', 'referencia_tipo', 'referencia_id',
        'notas', 'usuario_id', 'auto_generado',
    ]
    selected_columns = [name for name in preferred_order if name in columns]
    placeholders = ', '.join(['%s'] * len(selected_columns))
    cur.execute(f"""
        INSERT INTO contabilidad_movimientos ({", ".join(selected_columns)})
        VALUES ({placeholders})
        RETURNING id
    """, tuple(column_values[name] for name in selected_columns))
    row = cur.fetchone()
    return {'status': 'sincronizada', 'movement_id': row['id'] if row else None}


def add_consumption(user_id, table_id, payload):
    """Agrega un consumo a la cuenta abierta de una mesa."""
    _ensure_module_schema()
    product_id = payload.get('product_id')
    descripcion = (payload.get('descripcion') or '').strip()
    notas = (payload.get('notas') or '').strip() or None
    cantidad = _parse_int(payload.get('cantidad'), default=1, minimum=1, maximum=100, field='cantidad')

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, codigo, nombre, estado
            FROM restaurant_tables
            WHERE id = %s
        """, (table_id,))
        table_row = cur.fetchone()
        if not table_row:
            raise ValueError('Mesa no encontrada.')

        order_id = _ensure_open_order(cur, table_id, user_id, payload)

        producto_id = None
        precio_unitario = _parse_float(payload.get('precio_unitario'), default=0, minimum=0, field='precio')
        if product_id:
            producto_id = _parse_int(product_id, minimum=1, field='producto')
            cur.execute("""
                SELECT id, nombre, precio, stock
                FROM productos
                WHERE id = %s
                FOR UPDATE
            """, (producto_id,))
            product = cur.fetchone()
            if not product:
                raise ValueError('Producto no encontrado.')
            stock_actual = int(product['stock'] or 0)
            if stock_actual < cantidad:
                raise ValueError(f"Stock insuficiente para '{product['nombre']}'. Disponible: {stock_actual}.")

            descripcion = product['nombre']
            precio_unitario = float(product['precio'] or 0)
            subtotal = round(precio_unitario * cantidad, 2)
            stock_nuevo = stock_actual - cantidad

            cur.execute("""
                UPDATE productos
                SET stock = %s
                WHERE id = %s
            """, (stock_nuevo, producto_id))
            _record_inventory_log(
                cur,
                producto_id,
                'SALIDA',
                cantidad,
                stock_actual,
                stock_nuevo,
                f"Consumo mesa {table_row['codigo']} / orden {order_id}",
                user_id,
            )
        else:
            if not descripcion:
                raise ValueError('Debes indicar un producto o una descripción libre.')
            if precio_unitario <= 0:
                raise ValueError('El precio del consumo debe ser mayor a cero.')
            subtotal = round(precio_unitario * cantidad, 2)

        if _table_has_column('restaurant_table_consumptions', 'tenant_id'):
            cur.execute("""
                INSERT INTO restaurant_table_consumptions (
                    tenant_id, order_id, table_id, producto_id, descripcion,
                    cantidad, precio_unitario, subtotal, estado, notas, creado_por
                )
                VALUES (
                    COALESCE((SELECT tenant_id FROM restaurant_table_orders WHERE id = %s), 1),
                    %s, %s, %s, %s, %s, %s, %s, 'pendiente', %s, %s
                )
                RETURNING id
            """, (order_id, order_id, table_id, producto_id, descripcion,
                  cantidad, precio_unitario, subtotal, notas, user_id))
        else:
            cur.execute("""
                INSERT INTO restaurant_table_consumptions (
                    order_id, table_id, producto_id, descripcion,
                    cantidad, precio_unitario, subtotal, estado, notas, creado_por
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendiente', %s, %s)
                RETURNING id
            """, (order_id, table_id, producto_id, descripcion,
                  cantidad, precio_unitario, subtotal, notas, user_id))
        consumption_id = cur.fetchone()['id']
        total = _refresh_order_total(cur, order_id)

        cur.execute("""
            UPDATE restaurant_tables
            SET estado = 'ocupada', updated_at = NOW()
            WHERE id = %s
        """, (table_id,))

    return {
        'consumption_id': consumption_id,
        'order_id': order_id,
        'total_acumulado': total,
    }


def update_table_state(table_id, new_state):
    """Actualiza el estado visual de una mesa."""
    _ensure_module_schema()
    if new_state not in TABLE_STATES:
        raise ValueError('Estado de mesa inválido.')

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT EXISTS(
                SELECT 1
                FROM restaurant_table_orders
                WHERE table_id = %s
                  AND estado = 'abierta'
            ) AS has_open_order
        """, (table_id,))
        row = cur.fetchone()
        if row and row['has_open_order'] and new_state == 'disponible':
            raise ValueError('No puedes dejar la mesa disponible mientras tenga una cuenta abierta.')

        cur.execute("""
            UPDATE restaurant_tables
            SET estado = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING id
        """, (new_state, table_id))
        if not cur.fetchone():
            raise ValueError('Mesa no encontrada.')


def update_consumption_state(consumption_id, new_state):
    """Actualiza el estado operativo de un consumo."""
    _ensure_module_schema()
    if new_state not in CONSUMPTION_STATES:
        raise ValueError('Estado de consumo inválido.')

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            UPDATE restaurant_table_consumptions
            SET estado = %s,
                served_at = CASE WHEN %s = 'servido' THEN NOW() ELSE served_at END,
                updated_at = NOW()
            WHERE id = %s
            RETURNING order_id
        """, (new_state, new_state, consumption_id))
        row = cur.fetchone()
        if not row:
            raise ValueError('Consumo no encontrado.')

        total = _refresh_order_total(cur, row['order_id'])
    return total


def close_table_order(user_id, table_id, payload=None):
    """Cierra la cuenta abierta de una mesa y la libera."""
    _ensure_module_schema()
    payload = payload or {}
    payment_method = (payload.get('payment_method') or 'EFECTIVO').strip().upper()
    if payment_method not in PAYMENT_METHODS:
        raise ValueError('El método de pago no es válido.')

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT o.id,
                   o.total_acumulado,
                   o.cliente_nombre,
                   t.codigo,
                   t.nombre,
                   COALESCE(stats.pending_count, 0) AS pending_count,
                   COALESCE(stats.preparing_count, 0) AS preparing_count,
                   COALESCE(stats.total_items, 0) AS total_items
            FROM restaurant_table_orders o
            JOIN restaurant_tables t
              ON t.id = o.table_id
            LEFT JOIN LATERAL (
                SELECT COUNT(*) FILTER (WHERE c.estado = 'pendiente') AS pending_count,
                       COUNT(*) FILTER (WHERE c.estado = 'preparando') AS preparing_count,
                       COUNT(*) AS total_items
                FROM restaurant_table_consumptions c
                WHERE c.order_id = o.id
            ) stats ON TRUE
            WHERE o.table_id = %s
              AND o.estado = 'abierta'
            LIMIT 1
        """, (table_id,))
        order = cur.fetchone()
        if not order:
            raise ValueError('La mesa no tiene una cuenta abierta.')
        if int(order['total_items'] or 0) <= 0:
            raise ValueError('No puedes cerrar una cuenta sin consumos registrados.')

        total = _refresh_order_total(cur, order['id'])

        if _table_has_column('restaurant_table_orders', 'payment_method'):
            cur.execute("""
                UPDATE restaurant_table_orders
                SET estado = 'cerrada',
                    cerrada_por = %s,
                    closed_at = NOW(),
                    payment_method = %s,
                    total_acumulado = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (user_id, payment_method, total, order['id']))
        else:
            cur.execute("""
                UPDATE restaurant_table_orders
                SET estado = 'cerrada',
                    cerrada_por = %s,
                    closed_at = NOW(),
                    total_acumulado = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (user_id, total, order['id']))

        accounting = _create_accounting_movement(
            cur,
            'ingreso',
            'venta_restaurante',
            f"Venta restaurante mesa {order['codigo']} — {order['cliente_nombre'] or 'Cliente'}",
            total,
            'restaurant_order',
            order['id'],
            user_id,
            notes=f"Mesa {order['nombre']} / pago {payment_method}",
        )
        _sync_accounting_fields(cur, order['id'], status=accounting['status'], income_movement_id=accounting['movement_id'])

        cur.execute("""
            UPDATE restaurant_tables
            SET estado = 'disponible', updated_at = NOW()
            WHERE id = %s
        """, (table_id,))

        return {
            'order_id': order['id'],
            'codigo_mesa': order['codigo'],
            'nombre_mesa': order['nombre'],
            'total': total,
            'payment_method': payment_method,
            'accounting_status': accounting['status'],
        }


def cancel_open_table_order(user_id, table_id, payload=None):
    """Cancela una cuenta abierta y revierte stock no servido."""
    _ensure_module_schema()
    payload = payload or {}
    reason = (payload.get('motivo') or payload.get('reason') or '').strip()
    if not reason:
        raise ValueError('Debes indicar el motivo de la cancelación.')

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT o.id,
                   o.total_acumulado,
                   t.codigo,
                   t.nombre,
                   COALESCE(stats.served_count, 0) AS served_count
            FROM restaurant_table_orders o
            JOIN restaurant_tables t
              ON t.id = o.table_id
            LEFT JOIN LATERAL (
                SELECT COUNT(*) FILTER (WHERE c.estado = 'servido') AS served_count
                FROM restaurant_table_consumptions c
                WHERE c.order_id = o.id
            ) stats ON TRUE
            WHERE o.table_id = %s
              AND o.estado = 'abierta'
            LIMIT 1
        """, (table_id,))
        order = cur.fetchone()
        if not order:
            raise ValueError('La mesa no tiene una cuenta abierta para cancelar.')
        if int(order['served_count'] or 0) > 0:
            raise ValueError('No puedes cancelar una cuenta abierta con consumos ya servidos. Anula la venta desde reportes si ya fue cerrada.')

        cur.execute("""
            SELECT id, producto_id, cantidad
            FROM restaurant_table_consumptions
            WHERE order_id = %s
        """, (order['id'],))
        consumptions = cur.fetchall()

        for item in consumptions:
            producto_id = item.get('producto_id')
            if not producto_id:
                continue
            cur.execute("""
                SELECT stock
                FROM productos
                WHERE id = %s
                FOR UPDATE
            """, (producto_id,))
            product = cur.fetchone()
            if not product:
                continue
            stock_actual = int(product['stock'] or 0)
            stock_nuevo = stock_actual + int(item['cantidad'] or 0)
            cur.execute("""
                UPDATE productos
                SET stock = %s
                WHERE id = %s
            """, (stock_nuevo, producto_id))
            _record_inventory_log(
                cur,
                producto_id,
                'ENTRADA',
                int(item['cantidad'] or 0),
                stock_actual,
                stock_nuevo,
                f"Cancelación orden mesa {order['codigo']}",
                user_id,
            )

        assignments = [
            "estado = 'cancelada'",
            "cancel_reason = %s" if _table_has_column('restaurant_table_orders', 'cancel_reason') else None,
            "cancelled_at = NOW()" if _table_has_column('restaurant_table_orders', 'cancelled_at') else None,
            "cancelled_by = %s" if _table_has_column('restaurant_table_orders', 'cancelled_by') else None,
            "updated_at = NOW()",
        ]
        assignments = [item for item in assignments if item]
        values = []
        if _table_has_column('restaurant_table_orders', 'cancel_reason'):
            values.append(reason)
        if _table_has_column('restaurant_table_orders', 'cancelled_by'):
            values.append(user_id)
        values.append(order['id'])
        cur.execute(f"""
            UPDATE restaurant_table_orders
            SET {", ".join(assignments)}
            WHERE id = %s
        """, tuple(values))
        _sync_accounting_fields(cur, order['id'], status='no_aplica')

        cur.execute("""
            UPDATE restaurant_tables
            SET estado = 'disponible', updated_at = NOW()
            WHERE id = %s
        """, (table_id,))

        return {
            'order_id': order['id'],
            'codigo_mesa': order['codigo'],
            'nombre_mesa': order['nombre'],
            'total': float(order['total_acumulado'] or 0),
            'reason': reason,
        }


def cancel_closed_order(user_id, order_id, payload=None):
    """Anula una venta cerrada y registra la reversión contable."""
    _ensure_module_schema()
    payload = payload or {}
    reason = (payload.get('motivo') or payload.get('reason') or '').strip()
    if not reason:
        raise ValueError('Debes indicar el motivo de la anulación.')

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT o.id,
                   o.table_id,
                   o.total_acumulado,
                   o.estado,
                   t.codigo,
                   t.nombre
            FROM restaurant_table_orders o
            JOIN restaurant_tables t
              ON t.id = o.table_id
            WHERE o.id = %s
            LIMIT 1
        """, (order_id,))
        order = cur.fetchone()
        if not order:
            raise ValueError('La venta de mesa no existe.')
        if order['estado'] == 'cancelada':
            raise ValueError('La venta ya fue anulada.')
        if order['estado'] != 'cerrada':
            raise ValueError('Solo puedes anular ventas de mesas que ya estén cerradas.')

        reversal = _create_accounting_movement(
            cur,
            'egreso',
            'anulacion_restaurante',
            f"Anulación venta restaurante mesa {order['codigo']}",
            float(order['total_acumulado'] or 0),
            'restaurant_order_refund',
            order['id'],
            user_id,
            notes=reason,
        )

        assignments = [
            "estado = 'cancelada'",
            "cancel_reason = %s" if _table_has_column('restaurant_table_orders', 'cancel_reason') else None,
            "cancelled_at = NOW()" if _table_has_column('restaurant_table_orders', 'cancelled_at') else None,
            "cancelled_by = %s" if _table_has_column('restaurant_table_orders', 'cancelled_by') else None,
            "updated_at = NOW()",
        ]
        assignments = [item for item in assignments if item]
        values = []
        if _table_has_column('restaurant_table_orders', 'cancel_reason'):
            values.append(reason)
        if _table_has_column('restaurant_table_orders', 'cancelled_by'):
            values.append(user_id)
        values.append(order['id'])
        cur.execute(f"""
            UPDATE restaurant_table_orders
            SET {", ".join(assignments)}
            WHERE id = %s
        """, tuple(values))
        _sync_accounting_fields(cur, order['id'], status='revertida', reversal_movement_id=reversal['movement_id'])

    return {
        'order_id': order['id'],
        'codigo_mesa': order['codigo'],
        'nombre_mesa': order['nombre'],
        'total': float(order['total_acumulado'] or 0),
        'reason': reason,
        'accounting_status': reversal['status'],
    }
