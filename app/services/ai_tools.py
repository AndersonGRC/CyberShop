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


# Pedidos web que cuentan como venta REAL (pago confirmado)
_PEDIDO_PAGADO = "estado_pago IN ('APROBADO','PAGADO','aprobado','pagado')"


def _existe(cur, tabla):
    """True si la tabla existe (algunos tenants no tienen todas las tablas)."""
    cur.execute("SELECT to_regclass(%s)", (f'public.{tabla}',))
    return cur.fetchone()[0] is not None


def _suma(cur, sql, cero=(0, 0)):
    """Ejecuta una suma; devuelve (n, total) o ceros si algo falla."""
    try:
        cur.execute(sql)
        r = cur.fetchone()
        return r['n'], float(r['t'])
    except Exception:
        return cero


def _ventas_en(cur, where_web, where_pos, where_desk):
    """Suma ventas de las 3 fuentes (web pagados + POS web + POS escritorio)
    bajo los filtros de fecha dados, tolerando tablas ausentes."""
    web_n, web_t = _suma(cur, f"SELECT COUNT(*) n, COALESCE(SUM(monto_total),0) t "
                              f"FROM pedidos WHERE {_PEDIDO_PAGADO} AND {where_web}")
    pos_n, pos_t = _suma(cur, f"SELECT COUNT(*) n, COALESCE(SUM(total),0) t FROM ventas_pos "
                              f"WHERE COALESCE(estado,'completada') <> 'anulada' AND {where_pos}") \
        if _existe(cur, 'ventas_pos') else (0, 0.0)
    desk_n, desk_t = _suma(cur, f"SELECT COUNT(*) n, COALESCE(SUM(total),0) t "
                                f"FROM pos_desktop_sales WHERE {where_desk}") \
        if _existe(cur, 'pos_desktop_sales') else (0, 0.0)
    web = {'n': web_n, 't': web_t}; pos = {'n': pos_n, 't': pos_t}; desk = {'n': desk_n, 't': desk_t}
    n = web['n'] + pos['n'] + desk['n']
    total = float(web['t']) + float(pos['t']) + float(desk['t'])
    desglose = {
        'web': {'n': web['n'], 'monto': formatear_moneda(float(web['t']))},
        'pos_mostrador': {'n': pos['n'], 'monto': formatear_moneda(float(pos['t']))},
        'pos_escritorio': {'n': desk['n'], 'monto': formatear_moneda(float(desk['t']))},
    }
    return n, total, desglose


def ventas_periodo(periodo='hoy', **_):
    """Ventas del período (web pagados + POS mostrador + POS escritorio).
    Incluye SIEMPRE el total histórico para no confundir cuando el período
    pedido da 0 (p. ej. preguntan 'este mes' pero las ventas fueron antes)."""
    p = _periodo(periodo)
    fweb = _PERIODO_SQL[p].format(col='fecha_creacion')
    fpos = _PERIODO_SQL[p].format(col='fecha')
    fdesk = _PERIODO_SQL[p].format(col='created_at_local')
    with get_db_cursor(dict_cursor=True) as cur:
        n, total, desglose = _ventas_en(cur, fweb, fpos, fdesk)
        # total histórico (todas las fechas)
        hn, htotal, _ = _ventas_en(cur, 'TRUE', 'TRUE', 'TRUE')
        # fecha de la última venta (de las fuentes que existan)
        partes = [f"SELECT MAX(fecha_creacion) f FROM pedidos WHERE {_PEDIDO_PAGADO}"]
        if _existe(cur, 'ventas_pos'):
            partes.append("SELECT MAX(fecha) FROM ventas_pos WHERE COALESCE(estado,'')<>'anulada'")
        if _existe(cur, 'pos_desktop_sales'):
            partes.append("SELECT MAX(created_at_local) FROM pos_desktop_sales")
        cur.execute("SELECT MAX(f)::date u FROM (" + " UNION ALL ".join(partes) + ") x")
        ultima = cur.fetchone()['u']
    return {
        'periodo': _label_periodo(p),
        'ventas_en_periodo': n,
        'total_en_periodo': formatear_moneda(total),
        'desglose_periodo': desglose,
        'ventas_historico_total': hn,
        'monto_historico_total': formatear_moneda(htotal),
        'ultima_venta': ultima.isoformat() if ultima else None,
        'nota': ('No hubo ventas en el período pedido, pero el negocio SÍ tiene '
                 'ventas en total (ver histórico).') if n == 0 and hn > 0 else None,
    }


def top_productos(periodo='todo', limite=5, **_):
    """Productos más vendidos (web + POS) por unidades. Por defecto histórico."""
    p = _periodo(periodo)
    lim = max(1, min(int(limite or 5), 20))
    fweb = _PERIODO_SQL[p].format(col='p.fecha_creacion')
    fpos = _PERIODO_SQL[p].format(col='v.fecha')
    fdesk = _PERIODO_SQL[p].format(col='s.created_at_local')
    with get_db_cursor(dict_cursor=True) as cur:
        partes = [f"""SELECT d.producto_nombre nombre, d.cantidad cant
                      FROM detalle_pedidos d JOIN pedidos p ON p.id=d.pedido_id
                      WHERE {_PEDIDO_PAGADO} AND {fweb}"""]
        if _existe(cur, 'detalle_venta_pos') and _existe(cur, 'ventas_pos'):
            partes.append(f"""SELECT dv.descripcion nombre, dv.cantidad cant
                FROM detalle_venta_pos dv JOIN ventas_pos v ON v.id=dv.venta_id
                WHERE COALESCE(v.estado,'completada') <> 'anulada' AND {fpos}""")
        if _existe(cur, 'pos_desktop_sale_items') and _existe(cur, 'pos_desktop_sales'):
            partes.append(f"""SELECT di.name_snapshot nombre, di.quantity cant
                FROM pos_desktop_sale_items di JOIN pos_desktop_sales s ON s.id=di.sale_id
                WHERE {fdesk}""")
        cur.execute("SELECT nombre, SUM(cant) unidades FROM (" + " UNION ALL ".join(partes) +
                    ") x WHERE nombre IS NOT NULL GROUP BY nombre ORDER BY unidades DESC LIMIT %s", (lim,))
        filas = cur.fetchall()
    return {'periodo': _label_periodo(p),
            'productos': [{'nombre': r['nombre'], 'unidades': int(r['unidades'])} for r in filas]}


def top_clientes(limite=5, **_):
    """Clientes que más han comprado (web + POS) por importe."""
    lim = max(1, min(int(limite or 5), 20))
    with get_db_cursor(dict_cursor=True) as cur:
        partes = [f"""SELECT COALESCE(NULLIF(TRIM(cliente_nombre),''),'Sin nombre') nombre,
                      monto_total monto, 1 compras FROM pedidos WHERE {_PEDIDO_PAGADO}"""]
        if _existe(cur, 'ventas_pos'):
            partes.append("""SELECT COALESCE(NULLIF(TRIM(cliente_nombre),''),'Mostrador') nombre,
                total monto, 1 compras FROM ventas_pos WHERE COALESCE(estado,'completada') <> 'anulada'""")
        cur.execute("SELECT nombre, SUM(monto) total, SUM(compras) compras FROM (" +
                    " UNION ALL ".join(partes) +
                    ") x GROUP BY nombre ORDER BY total DESC LIMIT %s", (lim,))
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
        cur.execute(f"SELECT COUNT(*) FROM pedidos WHERE {_PEDIDO_PAGADO}"); ped = cur.fetchone()['count']
        vpos = 0
        if _existe(cur, 'ventas_pos'):
            cur.execute("SELECT COUNT(*) FROM ventas_pos WHERE COALESCE(estado,'completada')<>'anulada'"); vpos = cur.fetchone()['count']
        vdesk = 0
        if _existe(cur, 'pos_desktop_sales'):
            cur.execute("SELECT COUNT(*) FROM pos_desktop_sales"); vdesk = cur.fetchone()['count']
    return {'productos': prod, 'categorias': cat, 'clientes_registrados': cli,
            'pedidos_web_pagados': ped, 'ventas_pos_mostrador': vpos,
            'ventas_pos_escritorio': vdesk,
            'ventas_totales': ped + vpos + vdesk}


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


# ── Diccionario de datos del negocio (contexto SIEMPRE presente) ──
# Documenta, en lenguaje claro, QUÉ información maneja la tienda, qué se PUEDE
# consultar (vía las herramientas) y qué es SENSIBLE y NUNCA se entrega.
# Por seguridad la IA no ejecuta SQL: solo elige herramientas; aun así este
# contexto la orienta y le marca límites explícitos.
CONTEXTO_DATOS = """MAPA DE DATOS DEL NEGOCIO (lo que puedes saber de esta tienda):
- Catálogo: productos (nombre, precio, stock, categoría, descripción) y categorías.
- Ventas por 3 canales: tienda web (pedidos pagados), POS de mostrador (web) y
  POS de escritorio (app). Cuando hables de "ventas" considera los 3 canales.
- Clientes registrados, pedidos y su estado de envío, inventario y su valor.

QUÉ PUEDES CONSULTAR: solo a través de tus herramientas (ventas por período,
productos más vendidos, clientes top, stock bajo, estado del catálogo, inventario,
conteos, pedidos por despachar). Si no hay una herramienta para algo, dilo con
honestidad; NO inventes datos ni cifras.

DATOS SENSIBLES — NUNCA los entregues ni intentes consultarlos: contraseñas o
hashes, datos de tarjetas o medios de pago, tokens/credenciales/llaves API,
documentos de identidad completos, ni datos personales privados de un cliente.
Si te los piden, niégate amablemente y ofrece lo que sí puedes mostrar.

REGLA DE PERÍODOS: 'hoy', 'esta semana' y 'este mes' son rangos del calendario
actual. Si un período da 0 ventas pero el negocio tiene ventas históricas,
acláralo (no afirmes que "nunca ha vendido")."""


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
