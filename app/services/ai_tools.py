"""Herramientas de solo-lectura del Asistente IA conversacional.

SEGURIDAD / AISLAMIENTO:
- Cada función consulta SOLO la BD del tenant actual vía get_db_cursor()
  (resuelto por el request). No reciben tenant_id.
- Son consultas FIJAS y parametrizadas. La IA NUNCA escribe SQL: solo elige el
  NOMBRE de una herramienta de este catálogo y parámetros simples (período,
  límite, umbral) que se validan/clampan aquí.
- Devuelven datos estructurados (dict). El orquestador se los pasa a la IA para
  redactar la respuesta, así las cifras son SIEMPRE reales (la IA no las inventa).

Las "ventas" combinan pedidos web aprobados (`pedidos`) + ventas de mostrador
(`ventas_pos`).
"""

from database import get_db_cursor
from helpers import formatear_moneda


# Filtros de período reutilizables (sobre una columna de fecha)
_PERIODO_SQL = {
    'hoy':    "DATE({col}) = CURRENT_DATE",
    'semana': "{col} >= date_trunc('week', CURRENT_DATE)",
    'mes':    "{col} >= date_trunc('month', CURRENT_DATE)",
    'todo':   "TRUE",
}


def _periodo(p):
    return p if p in _PERIODO_SQL else 'mes'


def _label_periodo(p):
    return {'hoy': 'hoy', 'semana': 'esta semana', 'mes': 'este mes', 'todo': 'en total'}[_periodo(p)]


# ── Ventas ─────────────────────────────────────────────────────
def ventas_periodo(periodo='hoy', **_):
    """Total e importe de ventas (web + POS) del período."""
    p = _periodo(periodo)
    fweb = _PERIODO_SQL[p].format(col='fecha_creacion')
    fpos = _PERIODO_SQL[p].format(col='fecha')
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(f"SELECT COUNT(*) n, COALESCE(SUM(monto_total),0) t "
                    f"FROM pedidos WHERE estado_pago='APROBADO' AND {fweb}")
        web = cur.fetchone()
        cur.execute(f"SELECT COUNT(*) n, COALESCE(SUM(total),0) t "
                    f"FROM ventas_pos WHERE COALESCE(estado,'completada') <> 'anulada' AND {fpos}")
        pos = cur.fetchone()
    total = float(web['t']) + float(pos['t'])
    n = web['n'] + pos['n']
    return {
        'periodo': _label_periodo(p),
        'num_ventas': n,
        'total': formatear_moneda(total),
        'ventas_web': web['n'], 'monto_web': formatear_moneda(float(web['t'])),
        'ventas_pos': pos['n'], 'monto_pos': formatear_moneda(float(pos['t'])),
    }


def top_productos(periodo='mes', limite=5, **_):
    """Productos más vendidos (web + POS) por unidades en el período."""
    p = _periodo(periodo)
    lim = max(1, min(int(limite or 5), 20))
    fweb = _PERIODO_SQL[p].format(col='p.fecha_creacion')
    fpos = _PERIODO_SQL[p].format(col='v.fecha')
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(f"""
            SELECT nombre, SUM(cant) unidades FROM (
                SELECT d.producto_nombre nombre, d.cantidad cant
                FROM detalle_pedidos d JOIN pedidos p ON p.id=d.pedido_id
                WHERE p.estado_pago='APROBADO' AND {fweb}
                UNION ALL
                SELECT dv.descripcion nombre, dv.cantidad cant
                FROM detalle_venta_pos dv JOIN ventas_pos v ON v.id=dv.venta_id
                WHERE COALESCE(v.estado,'completada') <> 'anulada' AND {fpos}
            ) x GROUP BY nombre ORDER BY unidades DESC LIMIT %s""", (lim,))
        filas = cur.fetchall()
    return {'periodo': _label_periodo(p),
            'productos': [{'nombre': r['nombre'], 'unidades': int(r['unidades'])} for r in filas]}


def top_clientes(limite=5, **_):
    """Clientes que más han comprado (web + POS) por importe."""
    lim = max(1, min(int(limite or 5), 20))
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT nombre, SUM(monto) total, SUM(compras) compras FROM (
                SELECT COALESCE(NULLIF(TRIM(cliente_nombre),''),'Sin nombre') nombre,
                       monto_total monto, 1 compras
                FROM pedidos WHERE estado_pago='APROBADO'
                UNION ALL
                SELECT COALESCE(NULLIF(TRIM(cliente_nombre),''),'Mostrador') nombre,
                       total monto, 1 compras
                FROM ventas_pos WHERE COALESCE(estado,'completada') <> 'anulada'
            ) x GROUP BY nombre ORDER BY total DESC LIMIT %s""", (lim,))
        filas = cur.fetchall()
    return {'clientes': [{'nombre': r['nombre'], 'total': formatear_moneda(float(r['total'])),
                          'compras': int(r['compras'])} for r in filas]}


# ── Inventario / catálogo ──────────────────────────────────────
def productos_bajo_stock(umbral=5, **_):
    """Productos con stock bajo o agotados."""
    u = max(0, min(int(umbral or 5), 1000))
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT nombre, stock FROM productos WHERE stock <= %s ORDER BY stock ASC LIMIT 30", (u,))
        filas = cur.fetchall()
    return {'umbral': u, 'cantidad': len(filas),
            'productos': [{'nombre': r['nombre'], 'stock': int(r['stock'])} for r in filas]}


def catalogo_pendiente(**_):
    """Qué falta por completar en el catálogo: productos sin descripción,
    sin imagen o sin categoría."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT COUNT(*) n FROM productos WHERE descripcion IS NULL OR TRIM(descripcion)=''")
        sin_desc = cur.fetchone()['n']
        cur.execute("""SELECT COUNT(*) n FROM productos p WHERE
                       (p.imagen IS NULL OR TRIM(p.imagen)='')
                       AND NOT EXISTS (SELECT 1 FROM producto_imagenes i WHERE i.producto_id=p.id)""")
        sin_img = cur.fetchone()['n']
        cur.execute("SELECT COUNT(*) n FROM productos WHERE genero_id IS NULL")
        sin_cat = cur.fetchone()['n']
        cur.execute("SELECT COUNT(*) n FROM productos")
        total = cur.fetchone()['n']
    return {'total_productos': total, 'sin_descripcion': sin_desc,
            'sin_imagen': sin_img, 'sin_categoria': sin_cat}


def resumen_inventario(**_):
    """Tamaño y valor del inventario."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT COUNT(*) n, COALESCE(SUM(stock),0) u,
                       COALESCE(SUM(precio*stock),0) valor,
                       COUNT(*) FILTER (WHERE stock=0) agotados
                       FROM productos""")
        r = cur.fetchone()
    return {'productos': int(r['n']), 'unidades_en_stock': int(r['u']),
            'valor_inventario': formatear_moneda(float(r['valor'])),
            'agotados': int(r['agotados'])}


def conteo_general(**_):
    """Números generales del negocio."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT COUNT(*) FROM productos"); prod = cur.fetchone()['count']
        cur.execute("SELECT COUNT(*) FROM generos"); cat = cur.fetchone()['count']
        cur.execute("SELECT COUNT(*) FROM usuarios WHERE rol_id=3"); cli = cur.fetchone()['count']
        cur.execute("SELECT COUNT(*) FROM pedidos WHERE estado_pago='APROBADO'"); ped = cur.fetchone()['count']
        cur.execute("SELECT COUNT(*) FROM ventas_pos WHERE COALESCE(estado,'completada')<>'anulada'"); vpos = cur.fetchone()['count']
    return {'productos': prod, 'categorias': cat, 'clientes_registrados': cli,
            'pedidos_web_aprobados': ped, 'ventas_pos': vpos}


def pedidos_por_despachar(**_):
    """Pedidos web pagados pendientes de envío."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT referencia_pedido, cliente_nombre, monto_total
                       FROM pedidos WHERE estado_pago='APROBADO'
                       AND estado_envio IN ('POR_DESPACHAR','PENDIENTE')
                       ORDER BY fecha_creacion DESC LIMIT 20""")
        filas = cur.fetchall()
    return {'cantidad': len(filas),
            'pedidos': [{'referencia': r['referencia_pedido'],
                         'cliente': r['cliente_nombre'],
                         'monto': formatear_moneda(float(r['monto_total']))} for r in filas]}


# ── Catálogo de herramientas (lo que la IA puede elegir) ───────
# code -> (función, descripción para la IA, params permitidos)
TOOLS = {
    'ventas_periodo':      (ventas_periodo,      "Ventas e ingresos de un período (hoy, semana, mes).", ['periodo']),
    'top_productos':       (top_productos,       "Productos más vendidos en un período.", ['periodo', 'limite']),
    'top_clientes':        (top_clientes,        "Clientes que más han comprado.", ['limite']),
    'productos_bajo_stock':(productos_bajo_stock, "Productos con stock bajo o agotados (parámetro: umbral).", ['umbral']),
    'catalogo_pendiente':  (catalogo_pendiente,  "Qué falta por completar en el catálogo (sin descripción, imagen o categoría).", []),
    'resumen_inventario':  (resumen_inventario,  "Tamaño y valor del inventario.", []),
    'conteo_general':      (conteo_general,      "Números generales: productos, categorías, clientes, pedidos.", []),
    'pedidos_por_despachar':(pedidos_por_despachar, "Pedidos web pagados pendientes de enviar.", []),
}


def catalogo_para_prompt():
    """Texto del catálogo de herramientas para el prompt de selección."""
    return "\n".join(f"- {code}: {desc}" for code, (_fn, desc, _p) in TOOLS.items())


def ejecutar(code, params):
    """Ejecuta una herramienta validada con sus parámetros (saneados)."""
    if code not in TOOLS:
        return None
    fn, _desc, permitidos = TOOLS[code]
    safe = {}
    if 'periodo' in permitidos:
        safe['periodo'] = _periodo((params or {}).get('periodo', 'hoy'))
    if 'limite' in permitidos:
        try: safe['limite'] = int((params or {}).get('limite', 5))
        except Exception: safe['limite'] = 5
    if 'umbral' in permitidos:
        try: safe['umbral'] = int((params or {}).get('umbral', 5))
        except Exception: safe['umbral'] = 5
    return fn(**safe)
