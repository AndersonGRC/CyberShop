"""Indicadores adicionales de solo lectura para el panel del asistente.

Todas las consultas se ejecutan con el cursor del tenant resuelto por el request.
No se reciben identificadores de clientes ni se accede al plano de control.
"""

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import (
    Rango, _columnas, _existe, _label_periodo, _periodo, _sql_periodo,
    cambio_pct, etiqueta_rango, rango_anterior, rango_efectivo,
)
from services.ia_datos.ventas import _escritorio_sincronizado_hasta, _ventas_en


def _totales_ventas(cur, periodo):
    return _ventas_en(cur, _sql_periodo(periodo, 'fecha_creacion'),
                      _sql_periodo(periodo, 'fecha'),
                      _sql_periodo(periodo, 'created_at_local'))


def comparativo_ventas(periodo='mes', **_):
    """Ventas de tres canales frente a un tramo anterior de igual duración."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT CURRENT_DATE AS hoy')
        hoy = cur.fetchone()['hoy']
        desde, hasta = rango_efectivo(hoy, p)
        actual_n, actual_total, canales = _totales_ventas(
            cur, Rango(desde, hasta) if desde is not None else p)
        anterior = None
        antes_desde, antes_hasta = rango_anterior(desde, hasta, p)
        if antes_desde is not None:
            previo_n, previo_total, _ = _totales_ventas(cur, Rango(antes_desde, antes_hasta))
            anterior = {
                'periodo': etiqueta_rango(antes_desde, antes_hasta),
                'ventas': int(previo_n),
                'monto': formatear_moneda(previo_total),
                'cambio_ventas': cambio_pct(actual_n, previo_n),
                'cambio_monto': cambio_pct(actual_total, previo_total),
            }
        escritorio = _escritorio_sincronizado_hasta(cur)
    respuesta = {
        'periodo': _label_periodo(p),
        'ventas': int(actual_n),
        'monto': formatear_moneda(actual_total),
        'por_canal': canales,
        'comparacion_anterior': anterior,
        'nota': ('La comparación usa tramos de igual duración. Las ventas del POS de '
                 'escritorio aparecen cuando se sincronizan con el servidor.'),
    }
    if escritorio:
        respuesta['ventas_escritorio_recibidas_hasta'] = escritorio
    return respuesta


def ticket_promedio(periodo='mes', **_):
    """Importe medio por venta confirmada, incluyendo los tres canales."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        cantidad, total, canales = _totales_ventas(cur, p)
        escritorio = _escritorio_sincronizado_hasta(cur)
    respuesta = {
        'periodo': _label_periodo(p),
        'ventas': int(cantidad),
        'monto': formatear_moneda(total),
        'ticket_promedio': formatear_moneda(total / cantidad) if cantidad else None,
        'por_canal': canales,
        'nota': ('Ticket promedio = monto de ventas confirmadas dividido entre su cantidad. '
                 'No representa la utilidad. Las ventas de escritorio pueden llegar después '
                 'de la sincronización.'),
    }
    if escritorio:
        respuesta['ventas_escritorio_recibidas_hasta'] = escritorio
    if not cantidad:
        respuesta['confiabilidad'] = 'insuficiente'
        respuesta['conclusion'] = 'No hubo ventas confirmadas en ese período.'
    return respuesta


def anulaciones_pos(periodo='mes', **_):
    """Notas de crédito de anulaciones POS, por fecha real de la nota.

    Nunca se filtra por fecha de la venta original: eso haría que una venta
    antigua anulada hoy pareciera una anulación de un período anterior.
    """
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'notas_credito_pos'):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio no tiene notas de crédito POS registradas.'}
        columnas = _columnas(cur, 'notas_credito_pos')
        fecha = next((c for c in ('fecha_creacion', 'fecha_emision', 'created_at', 'fecha')
                      if c in columnas), None)
        if fecha is None and p != 'todo':
            return {'periodo': _label_periodo(p), 'confiabilidad': 'insuficiente',
                    'conclusion': ('Las notas de crédito POS no tienen una fecha consultable; '
                                   'solo puedo informar el total histórico.')}
        filtro = _sql_periodo(p, fecha) if fecha else 'TRUE'
        cur.execute(f"""SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS monto
                        FROM notas_credito_pos WHERE {filtro}""")
        fila = cur.fetchone()
    return {
        'periodo': _label_periodo(p),
        'anulaciones_pos': int(fila['n'] or 0),
        'monto_de_notas_credito': formatear_moneda(float(fila['monto'] or 0)),
        'nota': ('Cuenta notas de crédito POS por fecha de emisión. No incluye '
                 'cancelaciones de pedidos web ni del POS de escritorio; no se '
                 'resta otra vez de las ventas netas.'),
    }


def inventario_por_categoria(**_):
    """Disponibilidad y valor a precio de venta del stock por categoría."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT COALESCE(g.nombre, 'Sin categoría') AS categoria,
                              COUNT(*) AS productos,
                              COALESCE(SUM(GREATEST(COALESCE(p.stock, 0), 0)), 0) AS unidades,
                              COUNT(*) FILTER (WHERE COALESCE(p.stock, 0) <= 0) AS agotados,
                              COALESCE(SUM(GREATEST(COALESCE(p.stock, 0), 0)
                                           * COALESCE(p.precio, 0)), 0) AS valor
                       FROM productos p LEFT JOIN generos g ON g.id = p.genero_id
                       GROUP BY COALESCE(g.nombre, 'Sin categoría')
                       ORDER BY valor DESC""")
        filas = cur.fetchall()
    return {
        'categorias': len(filas),
        'productos': sum(int(r['productos']) for r in filas),
        'unidades_disponibles': sum(int(r['unidades']) for r in filas),
        'productos_agotados': sum(int(r['agotados']) for r in filas),
        'valor_a_precio_de_venta': formatear_moneda(sum(float(r['valor']) for r in filas)),
        'detalle': [{
            'categoria': r['categoria'],
            'productos': int(r['productos']),
            'unidades_disponibles': int(r['unidades']),
            'productos_agotados': int(r['agotados']),
            'valor_a_precio_de_venta': formatear_moneda(float(r['valor'])),
        } for r in filas[:20]],
        'nota': ('El valor usa precios de venta, no costos ni utilidad. Se muestran '
                 'hasta 20 categorías; los totales incluyen todas.'),
    }
