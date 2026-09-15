"""Finanzas: utilidad del período y márgenes por producto.

Las cifras de dinero salen del libro contable (`contabilidad_movimientos`), que
es la fuente del reporte /admin/contabilidad/ventas: una venta = un movimiento
de ingreso por canal, y una anulación = un egreso. Así la utilidad ya queda neta
de anulaciones sin restar dos veces.
"""

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import (
    _existe, _label_periodo, _periodo, _sql_periodo, cambio_pct, etiqueta_rango, rango_anterior,
    rango_efectivo,
)

# Espejo de routes/contabilidad.py (import diferido allá para no crear ciclos).
CANALES_VENTA = ('venta_pos', 'venta_restaurante', 'pedido_online', 'cuenta_cobro')
CANAL_LABEL = {'venta_pos': 'POS', 'venta_restaurante': 'Mesas', 'pedido_online': 'Tienda online',
               'cuenta_cobro': 'Cuentas de cobro'}
EGRESO_LABEL = {'nomina': 'Nómina', 'proveedor': 'Proveedores / insumos', 'arriendo': 'Arriendo',
                'servicios': 'Servicios', 'marketing': 'Marketing', 'impuestos': 'Impuestos',
                'prestamos': 'Préstamos', 'anulacion_pos': 'Anulaciones POS',
                'anulacion_restaurante': 'Anulaciones de mesas', 'gasto_caja': 'Gastos de caja',
                'retiro_banco': 'Retiros a banco', 'faltante_caja': 'Faltantes de caja',
                'otro_egreso': 'Otros egresos'}


def _totales(cur, desde, hasta):
    """(ingresos, egresos, n_ingresos, n_egresos) del libro entre dos fechas."""
    cur.execute("""SELECT tipo, COALESCE(SUM(monto), 0) AS total, COUNT(*) AS n
                   FROM contabilidad_movimientos
                   WHERE (%s::date IS NULL OR fecha >= %s) AND fecha <= %s
                   GROUP BY tipo""", (desde, desde, hasta))
    datos = {r['tipo']: (float(r['total']), int(r['n'])) for r in cur.fetchall()}
    ing, n_ing = datos.get('ingreso', (0.0, 0))
    egr, n_egr = datos.get('egreso', (0.0, 0))
    return ing, egr, n_ing, n_egr


def finanzas_periodo(periodo='mes', **_):
    """Ingresos, egresos y utilidad del período, comparados con el período
    anterior del mismo tamaño, con el desglose por canal y por gasto."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'contabilidad_movimientos'):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio aún no lleva la contabilidad en el sistema, '
                                  'así que no puedo calcular ingresos, egresos ni utilidad.'}
        cur.execute("SELECT CURRENT_DATE AS hoy")
        hoy = cur.fetchone()['hoy']
        desde, hasta = rango_efectivo(hoy, p)
        ing, egr, n_ing, n_egr = _totales(cur, desde, hasta)

        cur.execute("""SELECT categoria, COALESCE(SUM(monto), 0) AS total, COUNT(*) AS n
                       FROM contabilidad_movimientos
                       WHERE tipo = 'ingreso' AND (%s::date IS NULL OR fecha >= %s) AND fecha <= %s
                       GROUP BY categoria ORDER BY total DESC""", (desde, desde, hasta))
        ingresos_detalle = [{'concepto': CANAL_LABEL.get(r['categoria'], r['categoria'].replace('_', ' ').capitalize()),
                             'monto': formatear_moneda(float(r['total'])), 'movimientos': int(r['n'])}
                            for r in cur.fetchall()]
        cur.execute("""SELECT categoria, COALESCE(SUM(monto), 0) AS total, COUNT(*) AS n
                       FROM contabilidad_movimientos
                       WHERE tipo = 'egreso' AND (%s::date IS NULL OR fecha >= %s) AND fecha <= %s
                       GROUP BY categoria ORDER BY total DESC""", (desde, desde, hasta))
        egresos_detalle = [{'concepto': EGRESO_LABEL.get(r['categoria'], r['categoria'].replace('_', ' ').capitalize()),
                            'monto': formatear_moneda(float(r['total'])), 'movimientos': int(r['n'])}
                           for r in cur.fetchall()]

        cur.execute("""SELECT COALESCE(SUM(iva_monto), 0) AS iva,
                              COALESCE(SUM(total_retenciones), 0) AS retenciones
                       FROM contabilidad_movimientos
                       WHERE (%s::date IS NULL OR fecha >= %s) AND fecha <= %s""", (desde, desde, hasta))
        imp = cur.fetchone()

        comparacion = None
        a_desde, a_hasta = rango_anterior(desde, hasta, p)
        if a_desde is not None:
            a_ing, a_egr, _, _ = _totales(cur, a_desde, a_hasta)
            comparacion = {
                'periodo': etiqueta_rango(a_desde, a_hasta),
                'ingresos': formatear_moneda(a_ing), 'egresos': formatear_moneda(a_egr),
                'utilidad': formatear_moneda(a_ing - a_egr),
                'cambio_ingresos': cambio_pct(ing, a_ing),
                'cambio_utilidad': cambio_pct(ing - egr, a_ing - a_egr),
            }

    utilidad = ing - egr
    res = {
        'periodo': etiqueta_rango(desde, hasta),
        'ingresos': formatear_moneda(ing), 'egresos': formatear_moneda(egr),
        'utilidad': formatear_moneda(utilidad),
        'margen_de_utilidad': f'{utilidad / ing * 100:.0f}%' if ing > 0 else None,
        'movimientos': {'ingresos': n_ing, 'egresos': n_egr},
        'ingresos_por_concepto': ingresos_detalle,
        'egresos_por_concepto': egresos_detalle,
        'iva_registrado': formatear_moneda(float(imp['iva'] or 0)),
        'retenciones': formatear_moneda(float(imp['retenciones'] or 0)),
        'comparacion': comparacion,
        'nota': ('La utilidad es ingresos menos egresos del libro contable; las ventas anuladas '
                 'ya quedan descontadas porque la anulación se registra como egreso.'),
    }
    if n_ing == 0 and n_egr == 0:
        res['confiabilidad'] = 'insuficiente'
        res['conclusion'] = 'No hay movimientos contables registrados en ese período.'
    return res


def margenes_productos(periodo='mes', limite=10, **_):
    """Cuánto deja cada producto: precio de venta menos costo. Usa el costo que
    quedó guardado en la venta y, si falta, el costo actual del producto."""
    p = _periodo(periodo)
    lim = max(1, min(int(limite or 10), 20))
    with get_db_cursor(dict_cursor=True) as cur:
        if not (_existe(cur, 'detalle_venta_pos') and _existe(cur, 'ventas_pos')):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Todavía no hay ventas de mostrador con detalle para calcular márgenes.'}
        fpos = _sql_periodo(p, 'v.fecha')
        cur.execute(f"""
            SELECT COALESCE(NULLIF(TRIM(dv.descripcion), ''), pr.nombre, 'Sin nombre') AS nombre,
                   SUM(dv.cantidad) AS unidades,
                   SUM(dv.cantidad * dv.precio_unitario) AS ingreso,
                   SUM(dv.cantidad * COALESCE(NULLIF(dv.costo_unitario, 0), pr.costo, 0)) AS costo,
                   SUM(CASE WHEN COALESCE(NULLIF(dv.costo_unitario, 0), pr.costo, 0) > 0
                            THEN dv.cantidad * dv.precio_unitario ELSE 0 END) AS ingreso_con_costo
            FROM detalle_venta_pos dv
            JOIN ventas_pos v ON v.id = dv.venta_id
            LEFT JOIN productos pr ON pr.id = dv.producto_id
            WHERE COALESCE(v.estado, 'completada') <> 'anulada' AND {fpos}
            GROUP BY 1 ORDER BY 1""")
        filas = cur.fetchall()
        cur.execute("SELECT COUNT(*) AS n FROM productos WHERE COALESCE(costo, 0) <= 0")
        sin_costo = int(cur.fetchone()['n'])
        cur.execute("SELECT COUNT(*) AS n FROM productos")
        total_productos = int(cur.fetchone()['n'])

    productos, ingreso_total, costo_total, con_costo = [], 0.0, 0.0, 0.0
    for r in filas:
        ingreso = float(r['ingreso'] or 0)
        costo = float(r['costo'] or 0)
        ingreso_total += ingreso
        costo_total += costo
        con_costo += float(r['ingreso_con_costo'] or 0)
        productos.append({
            'nombre': r['nombre'], 'unidades': int(r['unidades'] or 0),
            'vendido': formatear_moneda(ingreso), 'costo': formatear_moneda(costo),
            'margen': formatear_moneda(ingreso - costo),
            'margen_pct': round((ingreso - costo) / ingreso * 100, 1) if ingreso > 0 else None,
            '_margen': ingreso - costo, '_sin_costo': costo <= 0,
        })
    if not productos:
        return {'periodo': _label_periodo(p), 'confiabilidad': 'insuficiente',
                'conclusion': 'No hubo ventas de mostrador en ese período.'}

    bajo_costo = [p_ for p_ in productos if not p_['_sin_costo'] and p_['_margen'] < 0]
    ordenados = sorted(productos, key=lambda x: -x['_margen'])
    limpiar = lambda lista: [{k: v for k, v in x.items() if not k.startswith('_')} for x in lista]  # noqa: E731
    cobertura = (con_costo / ingreso_total * 100) if ingreso_total > 0 else 0
    if cobertura >= 80:
        confiabilidad, conclusion = 'alta', f'El {cobertura:.0f}% de lo vendido tiene costo registrado.'
    elif cobertura >= 50:
        confiabilidad, conclusion = 'media', (f'Solo el {cobertura:.0f}% de lo vendido tiene costo registrado: '
                                              'el margen real puede ser distinto.')
    else:
        confiabilidad, conclusion = 'baja', (f'Apenas el {cobertura:.0f}% de lo vendido tiene costo registrado. '
                                             'Carga los costos de tus productos para que el margen sirva.')
    return {
        'periodo': _label_periodo(p),
        'vendido': formatear_moneda(ingreso_total), 'costo': formatear_moneda(costo_total),
        'margen_total': formatear_moneda(ingreso_total - costo_total),
        'margen_pct_total': round((ingreso_total - costo_total) / ingreso_total * 100, 1) if ingreso_total > 0 else None,
        'mas_rentables': limpiar(ordenados[:lim]),
        'menos_rentables': limpiar(ordenados[-3:][::-1]) if len(ordenados) > lim else [],
        'vendidos_por_debajo_del_costo': limpiar(bajo_costo[:5]),
        'productos_sin_costo_cargado': sin_costo, 'productos_totales': total_productos,
        'cobertura_de_costos': f'{cobertura:.0f}% de lo vendido',
        'confiabilidad': confiabilidad, 'conclusion': conclusion,
        'nota': 'Incluye solo ventas de mostrador y mesas: el POS de escritorio no envía el costo.',
    }
