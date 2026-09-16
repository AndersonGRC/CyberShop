"""Operación: rotación e inventario, ficha de un producto, pedidos, soporte,
facturación electrónica, cupones y lista de deseos.

Todo de solo lectura y tolerante a tablas o columnas ausentes: no todos los
clientes tienen los mismos módulos ni el mismo esquema.
"""

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import (
    _PEDIDO_PAGADO, _columnas, _existe, _label_periodo, _periodo, _sql_periodo,
)


def _unidades_vendidas_sql(cur, dias):
    """UNION de unidades vendidas por producto en los últimos `dias` (3 canales)."""
    partes = [f"""SELECT NULL::int pid, LOWER(TRIM(d.producto_nombre)) nom, d.cantidad cant,
                         d.cantidad * d.precio_unitario AS monto, p.fecha_creacion AS fecha
                  FROM detalle_pedidos d JOIN pedidos p ON p.id = d.pedido_id
                  WHERE {_PEDIDO_PAGADO} AND p.fecha_creacion >= CURRENT_DATE - INTERVAL '{dias} days'"""]
    if _existe(cur, 'detalle_venta_pos') and _existe(cur, 'ventas_pos'):
        partes.append(f"""SELECT dv.producto_id, LOWER(TRIM(dv.descripcion)), dv.cantidad,
                                 dv.cantidad * dv.precio_unitario, v.fecha
                          FROM detalle_venta_pos dv JOIN ventas_pos v ON v.id = dv.venta_id
                          WHERE COALESCE(v.estado,'completada') <> 'anulada'
                            AND v.fecha >= CURRENT_DATE - INTERVAL '{dias} days'""")
    if _existe(cur, 'pos_desktop_sale_items') and _existe(cur, 'pos_desktop_sales'):
        partes.append(f"""SELECT di.product_id, LOWER(TRIM(di.name_snapshot)), di.quantity,
                                 di.line_total, s.created_at_local
                          FROM pos_desktop_sale_items di JOIN pos_desktop_sales s ON s.id = di.sale_id
                          WHERE s.created_at_local >= CURRENT_DATE - INTERVAL '{dias} days'""")
    return ' UNION ALL '.join(partes)


def inventario_sin_rotacion(dias=60, limite=15, **_):
    """Plata dormida: productos con stock que no se venden hace mucho."""
    d = max(15, min(int(dias or 60), 365))
    lim = max(1, min(int(limite or 15), 30))
    with get_db_cursor(dict_cursor=True) as cur:
        union = _unidades_vendidas_sql(cur, d)
        tiene_costo = 'costo' in _columnas(cur, 'productos')
        valor = 'COALESCE(NULLIF(pr.costo, 0), pr.precio)' if tiene_costo else 'pr.precio'
        cur.execute(f"""
            SELECT pr.nombre, pr.stock, pr.precio, {valor} AS unitario
            FROM productos pr
            WHERE pr.stock > 0 AND NOT EXISTS (
                SELECT 1 FROM ({union}) v
                WHERE v.pid = pr.id OR (v.pid IS NULL AND LOWER(TRIM(pr.nombre)) = v.nom))
            ORDER BY pr.stock * {valor} DESC LIMIT %s""", (lim,))
        filas = cur.fetchall()
        cur.execute(f"""
            SELECT COUNT(*) AS n, COALESCE(SUM(pr.stock * {valor}), 0) AS capital
            FROM productos pr
            WHERE pr.stock > 0 AND NOT EXISTS (
                SELECT 1 FROM ({union}) v
                WHERE v.pid = pr.id OR (v.pid IS NULL AND LOWER(TRIM(pr.nombre)) = v.nom))""")
        tot = cur.fetchone()
    return {
        'criterio': f'Productos con stock que no registran ninguna venta en los últimos {d} días.',
        'productos_sin_rotacion': int(tot['n']),
        'capital_inmovilizado': formatear_moneda(float(tot['capital'] or 0)),
        'productos': [{'nombre': r['nombre'], 'stock': int(r['stock']),
                       'plata_detenida': formatear_moneda(float(r['unitario'] or 0) * int(r['stock']))}
                      for r in filas],
        'nota': ('La plata detenida se calcula con el costo cuando está cargado; si no, con el precio '
                 'de venta.') if tiene_costo else 'Sin costos cargados se estima con el precio de venta.',
    }


def movimientos_inventario(periodo='mes', **_):
    """Entradas, salidas y ajustes de inventario: qué se movió y por qué."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'inventario_log'):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Todavía no hay historial de movimientos de inventario.'}
        f = _sql_periodo(p, 'l.fecha')
        cur.execute(f"""SELECT UPPER(COALESCE(l.tipo, 'AJUSTE')) AS tipo, COUNT(*) AS n,
                               COALESCE(SUM(l.cantidad), 0) AS unidades
                        FROM inventario_log l WHERE {f} GROUP BY 1 ORDER BY unidades DESC""")
        por_tipo = [{'tipo': r['tipo'].capitalize(), 'movimientos': int(r['n']),
                     'unidades': int(r['unidades'] or 0)} for r in cur.fetchall()]
        if not por_tipo:
            return {'periodo': _label_periodo(p), 'confiabilidad': 'insuficiente',
                    'conclusion': 'No hubo movimientos de inventario en ese período.'}
        cur.execute(f"""SELECT COALESCE(NULLIF(TRIM(l.motivo), ''), 'sin motivo') AS motivo,
                               COUNT(*) AS n, COALESCE(SUM(l.cantidad), 0) AS unidades
                        FROM inventario_log l WHERE {f} GROUP BY 1 ORDER BY unidades DESC LIMIT 8""")
        por_motivo = [{'motivo': r['motivo'], 'movimientos': int(r['n']),
                       'unidades': int(r['unidades'] or 0)} for r in cur.fetchall()]
        cur.execute(f"""SELECT pr.nombre, COUNT(*) AS n, COALESCE(SUM(l.cantidad), 0) AS unidades
                        FROM inventario_log l JOIN productos pr ON pr.id = l.producto_id
                        WHERE {f} AND UPPER(COALESCE(l.tipo, '')) IN ('SALIDA', 'AJUSTE')
                        GROUP BY pr.id, pr.nombre ORDER BY unidades DESC LIMIT 5""")
        top_salidas = [{'producto': r['nombre'], 'movimientos': int(r['n']),
                        'unidades': int(r['unidades'] or 0)} for r in cur.fetchall()]
    return {
        'periodo': _label_periodo(p), 'por_tipo': por_tipo, 'por_motivo': por_motivo,
        'mas_salidas_y_ajustes': top_salidas,
        'nota': ('Las salidas y ajustes que no son ventas suelen ser mermas, daños o correcciones '
                 'de conteo: conviene revisar los motivos repetidos.'),
    }


def producto_detalle(producto='', **_):
    """Ficha completa de UN producto: ventas, stock, cobertura, margen y reseñas."""
    nombre = (producto or '').strip()
    if len(nombre) < 3:
        return {'confiabilidad': 'insuficiente',
                'conclusion': 'Dime el nombre del producto (al menos 3 letras).'}
    patron = f'%{nombre.lower()}%'
    with get_db_cursor(dict_cursor=True) as cur:
        cols = _columnas(cur, 'productos')
        campos = 'id, nombre, precio, stock' + (', costo' if 'costo' in cols else '') + \
                 (', stock_minimo' if 'stock_minimo' in cols else '')
        cur.execute(f"SELECT {campos} FROM productos WHERE LOWER(nombre) LIKE %s ORDER BY nombre LIMIT 6", (patron,))
        encontrados = cur.fetchall()
        if not encontrados:
            return {'producto_buscado': nombre, 'confiabilidad': 'insuficiente',
                    'conclusion': f'No tengo ningún producto que se llame «{nombre}».'}
        if len(encontrados) > 1:
            return {'producto_buscado': nombre,
                    'varios_productos_coinciden': [r['nombre'] for r in encontrados],
                    'conclusion': 'Hay varios productos con ese nombre: pregunta a cuál se refiere.'}
        pr = encontrados[0]
        # Sin costos ni margen: eso vive en margenes_productos, que exige permiso
        # de contabilidad. Aquí basta con saber cómo se está vendiendo.
        union = _unidades_vendidas_sql(cur, 90)
        cur.execute(f"""SELECT COALESCE(SUM(cant), 0) AS unidades, COALESCE(SUM(monto), 0) AS monto,
                               MAX(fecha) AS ultima
                        FROM ({union}) v WHERE v.pid = %s OR (v.pid IS NULL AND v.nom = %s)""",
                    (pr['id'], pr['nombre'].strip().lower()))
        v90 = cur.fetchone()
        resenas = None
        if _existe(cur, 'producto_comentarios'):
            cur.execute("""SELECT COUNT(*) AS n, AVG(calificacion) AS promedio
                           FROM producto_comentarios WHERE producto_id = %s AND COALESCE(aprobado, FALSE)""",
                        (pr['id'],))
            r = cur.fetchone()
            if int(r['n'] or 0):
                resenas = {'reseñas': int(r['n']), 'promedio': round(float(r['promedio']), 1)}
    unidades = float(v90['unidades'] or 0)
    stock = int(pr['stock'] or 0)
    diarias = unidades / 90 if unidades else 0
    minimo = pr.get('stock_minimo') if 'stock_minimo' in cols else None
    ultima = v90['ultima']
    cobertura = round(stock / diarias, 1) if diarias else None
    return {
        'producto': pr['nombre'], 'precio': formatear_moneda(float(pr['precio'] or 0)),
        'stock': stock,
        'stock_minimo': int(minimo) if minimo is not None else None,
        'unidades_vendidas_90_dias': int(unidades),
        'vendido_90_dias': formatear_moneda(float(v90['monto'] or 0)),
        'ultima_venta': ultima.date().isoformat() if hasattr(ultima, 'date') else (str(ultima) if ultima else None),
        'dias_de_cobertura': cobertura,
        'se_agota_pronto': bool(cobertura is not None and cobertura < 15),
        'calificacion': resenas,
        'nota': 'Para el costo y el margen de este producto, consulta el margen de productos.',
    }


def pedidos_estado(periodo='mes', **_):
    """Pedidos de la tienda web: en qué estado están y cuáles llevan mucho sin despachar."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        f = _sql_periodo(p, 'fecha_creacion')
        cur.execute(f"""SELECT COALESCE(estado_pago, 'SIN DATO') AS pago,
                               COALESCE(estado_envio, 'SIN DATO') AS envio,
                               COUNT(*) AS n, COALESCE(SUM(monto_total), 0) AS total
                        FROM pedidos WHERE {f} GROUP BY 1, 2 ORDER BY n DESC""")
        filas = cur.fetchall()
        if not filas:
            return {'periodo': _label_periodo(p), 'confiabilidad': 'insuficiente',
                    'conclusion': 'No hubo pedidos web en ese período.'}
        cur.execute("""SELECT referencia_pedido, cliente_nombre, monto_total, fecha_creacion
                       FROM pedidos WHERE estado_pago = 'APROBADO'
                         AND estado_envio IN ('POR_DESPACHAR', 'PENDIENTE')
                         AND fecha_creacion < NOW() - INTERVAL '48 hours'
                       ORDER BY fecha_creacion LIMIT 10""")
        atrasados = [{'pedido': r['referencia_pedido'], 'cliente': r['cliente_nombre'],
                      'monto': formatear_moneda(float(r['monto_total'] or 0)),
                      'esperando_desde': r['fecha_creacion'].date().isoformat()} for r in cur.fetchall()]
    return {
        'periodo': _label_periodo(p),
        'pedidos': sum(int(r['n']) for r in filas),
        'por_estado': [{'pago': r['pago'], 'envio': r['envio'], 'pedidos': int(r['n']),
                        'monto': formatear_moneda(float(r['total']))} for r in filas],
        'pagados_sin_despachar_hace_mas_de_48h': atrasados,
    }


def soporte_estado(**_):
    """Tickets de soporte: abiertos, sin respuesta y los más viejos."""
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'tickets_soporte'):
            return {'confiabilidad': 'insuficiente', 'conclusion': 'Este negocio no usa el módulo de soporte.'}
        cur.execute("""SELECT COALESCE(estado, 'abierto') AS estado, COUNT(*) AS n
                       FROM tickets_soporte GROUP BY 1 ORDER BY n DESC""")
        por_estado = [{'estado': r['estado'].capitalize(), 'tickets': int(r['n'])} for r in cur.fetchall()]
        if not por_estado:
            return {'confiabilidad': 'insuficiente', 'conclusion': 'No hay tickets de soporte registrados.'}
        sin_respuesta, viejos = 0, []
        if _existe(cur, 'ticket_respuestas'):
            cur.execute("""SELECT COUNT(*) AS n FROM tickets_soporte t
                           WHERE LOWER(COALESCE(t.estado, 'abierto')) <> 'cerrado'
                             AND NOT EXISTS (SELECT 1 FROM ticket_respuestas r
                                             WHERE r.ticket_id = t.id AND r.es_admin)""")
            sin_respuesta = int(cur.fetchone()['n'] or 0)
        cur.execute("""SELECT asunto, fecha_creacion,
                              EXTRACT(EPOCH FROM (NOW() - fecha_creacion)) / 3600 AS horas
                       FROM tickets_soporte WHERE LOWER(COALESCE(estado, 'abierto')) <> 'cerrado'
                       ORDER BY fecha_creacion LIMIT 5""")
        viejos = [{'asunto': r['asunto'], 'abierto_hace_horas': int(r['horas'] or 0),
                   'desde': r['fecha_creacion'].date().isoformat()} for r in cur.fetchall()]
    return {'por_estado': por_estado, 'sin_respuesta_del_negocio': sin_respuesta,
            'mas_antiguos_sin_cerrar': viejos}


def fe_pendiente(periodo='mes', **_):
    """Facturación electrónica: qué ventas ya tienen factura y cuáles no.
    Solo consulta el estado: no emite ni envía nada a la DIAN."""
    p = _periodo(periodo)
    resumen, total_sin = [], 0
    with get_db_cursor(dict_cursor=True) as cur:
        for tabla, col_fecha, etiqueta in (('ventas_pos', 'fecha', 'Mostrador y mesas'),
                                           ('pedidos', 'fecha_creacion', 'Tienda web')):
            if not _existe(cur, tabla) or 'factura_dian_id' not in _columnas(cur, tabla):
                continue
            filtro = _sql_periodo(p, col_fecha)
            extra = " AND COALESCE(estado,'completada') <> 'anulada'" if tabla == 'ventas_pos' \
                else f" AND {_PEDIDO_PAGADO}"
            cur.execute(f"""SELECT COUNT(*) FILTER (WHERE factura_dian_id IS NOT NULL) AS con,
                                   COUNT(*) FILTER (WHERE factura_dian_id IS NULL) AS sin,
                                   COUNT(*) AS total
                            FROM {tabla} WHERE {filtro}{extra}""")
            r = cur.fetchone()
            if int(r['total'] or 0):
                total_sin += int(r['sin'])
                resumen.append({'canal': etiqueta, 'ventas': int(r['total']),
                                'con_factura_electronica': int(r['con']), 'sin_factura': int(r['sin'])})
    if not resumen:
        return {'periodo': _label_periodo(p), 'confiabilidad': 'insuficiente',
                'conclusion': 'No encuentro ventas con información de facturación electrónica en ese período.'}
    return {'periodo': _label_periodo(p), 'por_canal': resumen, 'ventas_sin_factura': total_sin,
            'nota': 'Solo informo el estado; la emisión se hace desde el módulo de facturación.'}


def cupones_desempeno(periodo='mes', **_):
    """Cupones: cuánto se usaron y cuánto descuento significaron."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'cupones'):
            return {'confiabilidad': 'insuficiente', 'conclusion': 'Este negocio no usa cupones de descuento.'}
        cols_uso = _columnas(cur, 'cupones_uso') if _existe(cur, 'cupones_uso') else set()
        cur.execute("""SELECT COALESCE(estado, 'activo') AS estado, COUNT(*) AS n
                       FROM cupones GROUP BY 1 ORDER BY n DESC""")
        por_estado = [{'estado': r['estado'].capitalize(), 'cupones': int(r['n'])} for r in cur.fetchall()]
        usos, descuento, top = 0, 0.0, []
        if cols_uso:
            fecha = 'u.fecha' if 'fecha' in cols_uso else ('u.created_at' if 'created_at' in cols_uso else None)
            filtro = _sql_periodo(p, fecha) if fecha else 'TRUE'
            monto = 'COALESCE(u.descuento_aplicado, 0)' if 'descuento_aplicado' in cols_uso else '0'
            cur.execute(f"""SELECT COUNT(*) AS n, COALESCE(SUM({monto}), 0) AS total
                            FROM cupones_uso u WHERE {filtro}""")
            r = cur.fetchone()
            usos, descuento = int(r['n'] or 0), float(r['total'] or 0)
            cur.execute(f"""SELECT c.codigo, COUNT(*) AS n, COALESCE(SUM({monto}), 0) AS total
                            FROM cupones_uso u JOIN cupones c ON c.id = u.cupon_id
                            WHERE {filtro} GROUP BY c.codigo ORDER BY n DESC LIMIT 5""")
            top = [{'cupon': x['codigo'], 'usos': int(x['n']),
                    'descuento': formatear_moneda(float(x['total']))} for x in cur.fetchall()]
    return {'periodo': _label_periodo(p), 'cupones_por_estado': por_estado, 'usos_en_el_periodo': usos,
            'descuento_entregado': formatear_moneda(descuento), 'mas_usados': top,
            'nota': None if usos else 'Nadie usó cupones en ese período.'}


_CLAVES_ANONIMAS = ('mostrador', 'consumidor final', 'sin nombre', 'cliente', 'cliente mostrador',
                    'general', 'varios', '222222222222', '0')


def ventas_con_cliente(cur, dias=90):
    """(identificadas, totales) de los últimos `dias`. Una venta cuenta como
    identificada si tiene documento, correo o un nombre que no sea genérico."""
    anonimas = ', '.join('%s' for _ in _CLAVES_ANONIMAS)
    ident, total = 0, 0
    if _existe(cur, 'ventas_pos'):
        cols = _columnas(cur, 'ventas_pos')
        claves = []
        if 'cliente_documento' in cols:
            claves.append(r"NULLIF(REGEXP_REPLACE(cliente_documento, '\D', '', 'g'), '')")
        if 'cliente_email' in cols:
            claves.append("NULLIF(LOWER(TRIM(cliente_email)), '')")
        if 'cliente_nombre' in cols:
            claves.append("NULLIF(LOWER(TRIM(cliente_nombre)), '')")
        clave = f"COALESCE({', '.join(claves)})" if claves else 'NULL'
        cur.execute(f"""SELECT COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE {clave} IS NOT NULL
                                                AND {clave} NOT IN ({anonimas})) AS ident
                        FROM ventas_pos
                        WHERE COALESCE(estado, 'completada') <> 'anulada'
                          AND fecha >= CURRENT_DATE - INTERVAL '{int(dias)} days'""", _CLAVES_ANONIMAS)
        r = cur.fetchone()
        ident += int(r['ident'] or 0)
        total += int(r['total'] or 0)
    cur.execute(f"""SELECT COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE COALESCE(NULLIF(TRIM(cliente_email), ''),
                                                           NULLIF(TRIM(cliente_documento), '')) IS NOT NULL) AS ident
                    FROM pedidos WHERE {_PEDIDO_PAGADO}
                      AND fecha_creacion >= CURRENT_DATE - INTERVAL '{int(dias)} days'""")
    r = cur.fetchone()
    return ident + int(r['ident'] or 0), total + int(r['total'] or 0)


def calidad_datos(**_):
    """Qué le falta a los datos para que la IA y los reportes sirvan mejor:
    ventas sin cliente, productos sin costo, catálogo incompleto."""
    with get_db_cursor(dict_cursor=True) as cur:
        ident, total = ventas_con_cliente(cur)
        cols = _columnas(cur, 'productos')
        cur.execute("SELECT COUNT(*) AS n FROM productos")
        productos = int(cur.fetchone()['n'] or 0)
        sin_costo = None
        if 'costo' in cols:
            cur.execute("SELECT COUNT(*) AS n FROM productos WHERE COALESCE(costo, 0) <= 0")
            sin_costo = int(cur.fetchone()['n'] or 0)
        cur.execute("""SELECT COUNT(*) FILTER (WHERE descripcion IS NULL OR TRIM(descripcion) = '') AS sin_desc,
                              COUNT(*) FILTER (WHERE genero_id IS NULL) AS sin_cat FROM productos""")
        cat = cur.fetchone()
        sin_minimo = None
        if 'stock_minimo' in cols:
            cur.execute("SELECT COUNT(*) AS n FROM productos WHERE COALESCE(stock_minimo, 0) <= 0")
            sin_minimo = int(cur.fetchone()['n'] or 0)

    pct = (ident / total * 100) if total else 0
    pendientes = []
    if total and pct < 20:
        pendientes.append(f'Solo el {pct:.0f}% de tus ventas registra quién compró: sin eso no puedo '
                          'agrupar clientes ni decirte a quién recuperar. Pide el nombre o el documento al cobrar.')
    if sin_costo:
        pendientes.append(f'{sin_costo} de {productos} productos no tienen costo cargado: sin costo no hay '
                          'margen real ni utilidad por producto.')
    if cat['sin_desc']:
        pendientes.append(f"{int(cat['sin_desc'])} productos sin descripción (la IA puede escribirlas).")
    if cat['sin_cat']:
        pendientes.append(f"{int(cat['sin_cat'])} productos sin categoría: las comparaciones por categoría salen incompletas.")
    if sin_minimo:
        pendientes.append(f'{sin_minimo} productos sin stock mínimo definido: el aviso de "hay que reponer" '
                          'usa un umbral general en vez del tuyo.')
    return {
        'ventas_analizadas_90_dias': total,
        'ventas_con_cliente_identificado': ident,
        'porcentaje_con_cliente': f'{pct:.0f}%' if total else None,
        'productos': productos, 'productos_sin_costo': sin_costo,
        'productos_sin_descripcion': int(cat['sin_desc']), 'productos_sin_categoria': int(cat['sin_cat']),
        'productos_sin_stock_minimo': sin_minimo,
        'que_conviene_completar': pendientes,
        'conclusion': ('Tus datos están completos para lo que la IA necesita.' if not pendientes else
                       'Completar esto hace que las respuestas y los reportes sean más útiles.'),
    }


def deseos_demanda(**_):
    """Qué productos guardan los clientes en su lista de deseos, sobre todo los
    que están agotados: demanda que se está perdiendo."""
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'lista_deseos'):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio no tiene activa la lista de deseos.'}
        cur.execute("""SELECT pr.nombre, pr.stock, COUNT(*) AS personas
                       FROM lista_deseos ld JOIN productos pr ON pr.id = ld.producto_id
                       GROUP BY pr.id, pr.nombre, pr.stock ORDER BY personas DESC LIMIT 10""")
        filas = cur.fetchall()
    if not filas:
        return {'confiabilidad': 'insuficiente', 'conclusion': 'Todavía nadie ha guardado productos en su lista de deseos.'}
    agotados = [{'producto': r['nombre'], 'personas_esperando': int(r['personas'])}
                for r in filas if int(r['stock'] or 0) <= 0]
    return {
        'mas_deseados': [{'producto': r['nombre'], 'personas': int(r['personas']),
                          'stock': int(r['stock'] or 0)} for r in filas],
        'deseados_sin_stock': agotados,
        'nota': ('Los productos deseados y agotados son ventas que se están perdiendo.'
                 if agotados else None),
    }
