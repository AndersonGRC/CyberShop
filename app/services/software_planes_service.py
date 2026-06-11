"""services/software_planes_service.py

Gestión de los planes del Software CyberShop que se muestran en /software.

Los planes viven en la tabla `software_planes` (DB del tenant). Si la tabla
no existe o está vacía, se crea y se siembra con los planes por defecto, de
modo que la página nunca queda sin contenido. Toda la página /software
(landing, JSON-LD y checkout PayU) lee desde aquí.
"""
from __future__ import annotations

from database import get_db_cursor


# Planes por defecto (semilla inicial). Una característica por elemento.
DEFAULT_PLANES = [
    {
        'plan_key': 'web-ecommerce', 'nombre': 'Web Corporativa E-commerce',
        'precio': 990000, 'periodo': 'año', 'destacado': False, 'comprable': True,
        'tiene_app': False, 'sort_order': 10,
        'ideal': 'Vende en línea con una página profesional.',
        'incluye': [
            'Tienda en línea integrada (carrito + pagos)',
            'Diseño personalizado a tu marca',
            'WhatsApp y redes sociales conectadas',
            'Panel de administración y capacitación',
            'Catálogo de productos ilimitado',
            'Pasarela de pagos PayU (PSE, tarjetas)',
        ],
    },
    {
        'plan_key': 'web-corporativa', 'nombre': 'Web Corporativa',
        'precio': 799000, 'periodo': 'año', 'destacado': False, 'comprable': True,
        'tiene_app': False, 'sort_order': 20,
        'ideal': 'Ideal para mostrar tu empresa online.',
        'incluye': [
            'Diseño visual profesional',
            'Sección de contacto directo',
            'Redes sociales integradas',
            'Dominio propio y acceso 24/7',
            'Optimización SEO básica',
            'Hosting y certificado SSL',
        ],
    },
    {
        'plan_key': 'software-cybershop', 'nombre': 'Software CyberShop',
        'precio': 150000, 'periodo': 'mes', 'destacado': False, 'comprable': True,
        'tiene_app': True, 'sort_order': 30,
        'ideal': 'Tu negocio completo: página web propia + E-commerce + POS web y de escritorio.',
        'incluye': [
            'Página web propia con tu marca y tus colores',
            'E-commerce con tu dominio (catálogo y tienda)',
            'Punto de venta (POS) web y de escritorio',
            'App de escritorio que funciona sin internet (offline)',
            'Inventario inteligente en tiempo real',
            'Módulo de restaurante y atención de mesas',
            'Contabilidad con retenciones y cierres',
            'Reportes y estadísticas de ventas',
            'Roles, permisos y sincronización en la nube',
        ],
    },
    {
        'plan_key': 'ultra', 'nombre': 'Ultra',
        'precio': 200000, 'periodo': 'mes', 'destacado': True, 'comprable': True,
        'tiene_app': True, 'sort_order': 40,
        'ideal': 'La experiencia completa: vende en línea, automatiza y conecta todo tu negocio.',
        'incluye': [
            'Todo lo incluido en el plan Software CyberShop',
            'Asistente IA: descripciones de producto, SEO y auto-respuestas',
            'Pasarela de pagos PayU — cobra en línea (PSE y tarjetas)',
            'Inicio de sesión y conexión con Google',
            'Integración CRM completa (clientes, oportunidades, tareas)',
            'Tienda online con pagos en línea activos',
            'Soporte prioritario y acompañamiento',
        ],
    },
]


def _ensure_table():
    with get_db_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS software_planes (
                id          SERIAL PRIMARY KEY,
                plan_key    VARCHAR(60) UNIQUE NOT NULL,
                nombre      VARCHAR(120) NOT NULL,
                precio      NUMERIC(12,2) NOT NULL DEFAULT 0,
                periodo     VARCHAR(20) NOT NULL DEFAULT 'mes',
                ideal       TEXT,
                incluye     TEXT,
                destacado   BOOLEAN NOT NULL DEFAULT FALSE,
                comprable   BOOLEAN NOT NULL DEFAULT TRUE,
                tiene_app   BOOLEAN NOT NULL DEFAULT FALSE,
                sort_order  INTEGER NOT NULL DEFAULT 0,
                activo      BOOLEAN NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _seed_if_empty():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT COUNT(*) AS n FROM software_planes')
        if cur.fetchone()['n'] > 0:
            return
        for p in DEFAULT_PLANES:
            cur.execute(
                """
                INSERT INTO software_planes
                    (plan_key, nombre, precio, periodo, ideal, incluye,
                     destacado, comprable, tiene_app, sort_order, activo)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (plan_key) DO NOTHING
                """,
                (p['plan_key'], p['nombre'], p['precio'], p['periodo'], p['ideal'],
                 '\n'.join(p['incluye']), p['destacado'], p['comprable'],
                 p['tiene_app'], p['sort_order']),
            )


def _bootstrap():
    """Crea la tabla y siembra defaults. Tolerante a fallos."""
    try:
        _ensure_table()
        _seed_if_empty()
        return True
    except Exception:
        return False


def _format_precio(precio):
    try:
        n = int(round(float(precio)))
    except (TypeError, ValueError):
        n = 0
    return '$' + format(n, ',d').replace(',', '.')


def _periodo_label(periodo):
    p = (periodo or 'mes').strip().lower()
    return '/ ' + (p[:1].upper() + p[1:])


def _row_to_plan(row):
    incluye = [ln.strip() for ln in (row.get('incluye') or '').splitlines() if ln.strip()]
    return {
        'id': row['id'],
        'plan_key': row['plan_key'],
        'id_key': row['plan_key'],          # compat con plan.id usado en templates
        'nombre': row['nombre'],
        'precio': float(row['precio'] or 0),
        'precio_fmt': _format_precio(row['precio']),
        'periodo': row['periodo'],
        'periodo_label': _periodo_label(row['periodo']),
        'ideal': row.get('ideal') or '',
        'incluye': incluye,
        'destacado': bool(row['destacado']),
        'comprable': bool(row['comprable']),
        'tiene_app': bool(row['tiene_app']),
        'sort_order': row['sort_order'],
        'activo': bool(row['activo']),
    }


def get_planes(include_inactive=False):
    """Planes para la página pública (o admin si include_inactive).

    Devuelve dicts con la forma que consumen software.html / comprar_plan.
    Si la BD falla, cae a DEFAULT_PLANES para no dejar la página vacía.
    """
    if not _bootstrap():
        return _default_as_plans(include_inactive)
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if include_inactive:
                cur.execute('SELECT * FROM software_planes ORDER BY sort_order ASC, id ASC')
            else:
                cur.execute('SELECT * FROM software_planes WHERE activo = TRUE ORDER BY sort_order ASC, id ASC')
            return [_row_to_plan(dict(r)) for r in cur.fetchall()]
    except Exception:
        return _default_as_plans(include_inactive)


def get_plan(plan_key, include_inactive=False):
    """Un plan por su clave. include_inactive permite traerlo aunque esté oculto."""
    _bootstrap()
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if include_inactive:
                cur.execute('SELECT * FROM software_planes WHERE plan_key = %s', (plan_key,))
            else:
                cur.execute('SELECT * FROM software_planes WHERE plan_key = %s AND activo = TRUE', (plan_key,))
            row = cur.fetchone()
            return _row_to_plan(dict(row)) if row else None
    except Exception:
        return next((p for p in _default_as_plans(include_inactive) if p['plan_key'] == plan_key), None)


def _default_as_plans(include_inactive):
    out = []
    for p in DEFAULT_PLANES:
        out.append({
            'id': None, 'plan_key': p['plan_key'], 'id_key': p['plan_key'],
            'nombre': p['nombre'], 'precio': float(p['precio']),
            'precio_fmt': _format_precio(p['precio']), 'periodo': p['periodo'],
            'periodo_label': _periodo_label(p['periodo']), 'ideal': p['ideal'],
            'incluye': p['incluye'], 'destacado': p['destacado'],
            'comprable': p['comprable'], 'tiene_app': p['tiene_app'],
            'sort_order': p['sort_order'], 'activo': True,
        })
    return out


# ── CRUD admin ────────────────────────────────────────────────
def _slugify(text):
    import re
    s = (text or '').strip().lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s or 'plan'


def _unique_key(base, cur, exclude_id=None):
    key = base
    i = 2
    while True:
        if exclude_id is not None:
            cur.execute('SELECT 1 FROM software_planes WHERE plan_key = %s AND id <> %s', (key, exclude_id))
        else:
            cur.execute('SELECT 1 FROM software_planes WHERE plan_key = %s', (key,))
        if not cur.fetchone():
            return key
        key = f"{base}-{i}"
        i += 1


def crear_plan(data):
    _bootstrap()
    with get_db_cursor() as cur:
        base = _slugify(data.get('plan_key') or data.get('nombre'))
        plan_key = _unique_key(base, cur)
        cur.execute(
            """
            INSERT INTO software_planes
                (plan_key, nombre, precio, periodo, ideal, incluye,
                 destacado, comprable, tiene_app, sort_order, activo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (plan_key, data['nombre'], data['precio'], data['periodo'],
             data.get('ideal', ''), data.get('incluye', ''),
             bool(data.get('destacado')), bool(data.get('comprable', True)),
             bool(data.get('tiene_app')), int(data.get('sort_order') or 0),
             bool(data.get('activo', True))),
        )
        return cur.fetchone()[0]


def actualizar_plan(plan_id, data):
    _bootstrap()
    with get_db_cursor() as cur:
        cur.execute(
            """
            UPDATE software_planes SET
                nombre=%s, precio=%s, periodo=%s, ideal=%s, incluye=%s,
                destacado=%s, comprable=%s, tiene_app=%s, sort_order=%s, activo=%s
            WHERE id=%s
            """,
            (data['nombre'], data['precio'], data['periodo'], data.get('ideal', ''),
             data.get('incluye', ''), bool(data.get('destacado')),
             bool(data.get('comprable', True)), bool(data.get('tiene_app')),
             int(data.get('sort_order') or 0), bool(data.get('activo', True)), plan_id),
        )


def eliminar_plan(plan_id):
    _bootstrap()
    with get_db_cursor() as cur:
        cur.execute('DELETE FROM software_planes WHERE id = %s', (plan_id,))


def toggle_activo(plan_id):
    _bootstrap()
    with get_db_cursor() as cur:
        cur.execute('UPDATE software_planes SET activo = NOT activo WHERE id = %s', (plan_id,))


def get_plan_por_id(plan_id):
    _bootstrap()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT * FROM software_planes WHERE id = %s', (plan_id,))
        row = cur.fetchone()
        return _row_to_plan(dict(row)) if row else None
