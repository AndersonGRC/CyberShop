"""Inventario y catálogo."""

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import _PEDIDO_PAGADO, _columnas, _existe


def productos_bajo_stock(umbral=5, **_):
    """Productos con stock bajo o agotados. Cuando el producto tiene definido su
    propio stock mínimo, ese manda: un producto que se vende por cajas puede
    estar bajo con 20 unidades."""
    u = max(0, min(int(umbral or 5), 1000))
    with get_db_cursor(dict_cursor=True) as cur:
        usa_minimo = 'stock_minimo' in _columnas(cur, 'productos')
        limite = 'GREATEST(%s, COALESCE(stock_minimo, 0))' if usa_minimo else '%s'
        campos = 'nombre, stock' + (', COALESCE(stock_minimo, 0) AS minimo' if usa_minimo else '')
        cur.execute(f"SELECT {campos} FROM productos WHERE stock <= {limite} ORDER BY stock ASC LIMIT 30", (u,))
        filas = cur.fetchall()
    productos = []
    for r in filas:
        item = {'nombre': r['nombre'], 'stock': int(r['stock'])}
        if usa_minimo and int(r['minimo'] or 0) > 0:
            item['stock_minimo'] = int(r['minimo'])
        productos.append(item)
    return {'umbral': u, 'cantidad': len(filas), 'productos': productos,
            'criterio': (f'Stock igual o menor a {u}, o al mínimo definido en cada producto.'
                         if usa_minimo else f'Stock igual o menor a {u}.')}


def sugerencia_reorden(**_):
    """Qué productos hay que reponer pronto: ritmo de venta de los últimos
    30 días (3 canales) vs stock actual → días de cobertura estimados.
    Lista los que se agotan en <15 días con una cantidad sugerida para
    cubrir ~30 días de venta. Consulta pura (sin LLM): también la usa la
    tarjeta del inventario web."""
    DIAS, HORIZONTE, OBJETIVO = 30, 15, 30
    with get_db_cursor(dict_cursor=True) as cur:
        # Unidades vendidas por producto (id si existe; si no, por nombre)
        partes = [f"""SELECT NULL::int pid, LOWER(TRIM(d.producto_nombre)) nom, d.cantidad cant
                      FROM detalle_pedidos d JOIN pedidos p ON p.id=d.pedido_id
                      WHERE {_PEDIDO_PAGADO} AND p.fecha_creacion >= CURRENT_DATE - INTERVAL '{DIAS} days'"""]
        if _existe(cur, 'detalle_venta_pos') and _existe(cur, 'ventas_pos'):
            partes.append(f"""SELECT dv.producto_id pid, LOWER(TRIM(dv.descripcion)) nom, dv.cantidad cant
                FROM detalle_venta_pos dv JOIN ventas_pos v ON v.id=dv.venta_id
                WHERE COALESCE(v.estado,'completada') <> 'anulada'
                  AND v.fecha >= CURRENT_DATE - INTERVAL '{DIAS} days'""")
        if _existe(cur, 'pos_desktop_sale_items') and _existe(cur, 'pos_desktop_sales'):
            partes.append(f"""SELECT di.product_id pid, LOWER(TRIM(di.name_snapshot)) nom, di.quantity cant
                FROM pos_desktop_sale_items di JOIN pos_desktop_sales s ON s.id=di.sale_id
                WHERE s.created_at_local >= CURRENT_DATE - INTERVAL '{DIAS} days'""")
        cur.execute(
            "SELECT pr.id, pr.nombre, pr.stock, SUM(v.cant) unidades "
            "FROM (" + " UNION ALL ".join(partes) + ") v "
            "JOIN productos pr ON (v.pid = pr.id) "
            "  OR (v.pid IS NULL AND LOWER(TRIM(pr.nombre)) = v.nom) "
            "GROUP BY pr.id, pr.nombre, pr.stock")
        filas = cur.fetchall()

    urgentes = []
    for r in filas:
        unidades = float(r['unidades'] or 0)
        stock = int(r['stock'] or 0)
        if unidades <= 0:
            continue
        diarias = unidades / DIAS
        cobertura = stock / diarias if diarias > 0 else None
        if cobertura is not None and cobertura < HORIZONTE:
            sugerida = max(1, int(round(diarias * OBJETIVO - stock)))
            urgentes.append({
                'nombre': r['nombre'], 'stock': stock,
                'vendidas_30_dias': int(unidades),
                'dias_cobertura': round(cobertura, 1),
                'cantidad_sugerida': sugerida,
            })
    urgentes.sort(key=lambda x: x['dias_cobertura'])
    return {
        'criterio': (f'Productos cuyo stock se agota en menos de {HORIZONTE} días '
                     f'al ritmo de venta de los últimos {DIAS} días. La cantidad '
                     f'sugerida cubre ~{OBJETIVO} días de venta.'),
        'cantidad': len(urgentes),
        'productos': urgentes[:15],
        'nota': (None if urgentes else
                 'Ningún producto se agota pronto al ritmo actual de ventas.'),
    }


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
