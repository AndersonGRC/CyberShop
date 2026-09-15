"""Caja: estado del turno abierto, cuadres recientes y medios de pago.

Solo lectura: a diferencia de routes/caja.py, aquí nunca se crean tablas. Si el
cliente nunca ha usado caja, se responde que no hay datos.
"""

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import _columnas, _existe, _label_periodo, _periodo, _sql_periodo

_METODO_LABEL = {'efectivo': 'Efectivo', 'tarjeta': 'Tarjeta', 'nequi': 'Nequi',
                 'daviplata': 'Daviplata', 'transferencia': 'Transferencia', 'credito': 'Crédito'}


def _label_metodo(codigo):
    codigo = (codigo or 'sin_dato').strip().lower()
    return _METODO_LABEL.get(codigo, codigo.replace('_', ' ').capitalize())


def caja_estado(**_):
    """Turno de caja abierto (desde cuándo, ventas, gastos y cuánto debería
    haber en efectivo) y los últimos cuadres con su diferencia."""
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'caja_sesiones'):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio todavía no usa el módulo de caja.'}
        cur.execute("""SELECT id, base_inicial, fecha_apertura, notas_apertura
                       FROM caja_sesiones WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1""")
        abierta = cur.fetchone()

        turno = None
        if abierta:
            sid = abierta['id']
            ventas, efectivo = [], 0.0
            if _existe(cur, 'ventas_pos') and 'caja_sesion_id' in _columnas(cur, 'ventas_pos'):
                cur.execute("""SELECT COALESCE(metodo_pago, 'sin_dato') AS metodo,
                                      COALESCE(SUM(total), 0) AS total, COUNT(*) AS n
                               FROM ventas_pos
                               WHERE caja_sesion_id = %s AND COALESCE(estado, 'completada') <> 'anulada'
                               GROUP BY 1 ORDER BY total DESC""", (sid,))
                for r in cur.fetchall():
                    ventas.append({'metodo': _label_metodo(r['metodo']), 'monto': formatear_moneda(float(r['total'])),
                                   'ventas': int(r['n'])})
                    if (r['metodo'] or '').lower() == 'efectivo':
                        efectivo += float(r['total'])
            movimientos = {'entrada': 0.0, 'salida': 0.0}
            detalle_mov = []
            if _existe(cur, 'caja_movimientos'):
                cur.execute("""SELECT tipo, categoria, COALESCE(SUM(monto), 0) AS total, COUNT(*) AS n
                               FROM caja_movimientos WHERE caja_sesion_id = %s
                               GROUP BY tipo, categoria ORDER BY total DESC""", (sid,))
                for r in cur.fetchall():
                    movimientos[r['tipo']] = movimientos.get(r['tipo'], 0.0) + float(r['total'])
                    detalle_mov.append({'tipo': 'entrada' if r['tipo'] == 'entrada' else 'salida',
                                        'concepto': (r['categoria'] or '').replace('_', ' ').capitalize(),
                                        'monto': formatear_moneda(float(r['total'])), 'veces': int(r['n'])})
            base = float(abierta['base_inicial'] or 0)
            esperado = base + efectivo + movimientos['entrada'] - movimientos['salida']
            cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - %s)) / 3600 AS horas", (abierta['fecha_apertura'],))
            horas = float(cur.fetchone()['horas'] or 0)
            turno = {
                'abierta_desde': abierta['fecha_apertura'].isoformat(sep=' ', timespec='minutes'),
                'horas_abierta': round(horas, 1),
                'base_inicial': formatear_moneda(base),
                'ventas_del_turno': ventas,
                'efectivo_de_ventas': formatear_moneda(efectivo),
                'entradas_extra': formatear_moneda(movimientos['entrada']),
                'salidas_y_gastos': formatear_moneda(movimientos['salida']),
                'movimientos': detalle_mov,
                'efectivo_que_deberia_haber': formatear_moneda(esperado),
            }

        cur.execute("""SELECT fecha_cierre, efectivo_esperado, efectivo_contado, diferencia, total_ventas
                       FROM caja_sesiones WHERE estado <> 'abierta' AND fecha_cierre IS NOT NULL
                       ORDER BY fecha_cierre DESC LIMIT 5""")
        cierres, descuadres = [], 0
        for r in cur.fetchall():
            dif = float(r['diferencia'] or 0)
            descuadres += 1 if abs(dif) >= 1 else 0
            cierres.append({
                'fecha': r['fecha_cierre'].isoformat(sep=' ', timespec='minutes'),
                'esperado': formatear_moneda(float(r['efectivo_esperado'] or 0)),
                'contado': formatear_moneda(float(r['efectivo_contado'] or 0)),
                'diferencia': formatear_moneda(dif),
                'resultado': 'cuadró' if abs(dif) < 1 else ('sobrante' if dif > 0 else 'faltante'),
            })
    return {
        'caja_abierta': bool(turno), 'turno': turno, 'ultimos_cierres': cierres,
        'cierres_descuadrados': descuadres,
        'nota': ('El efectivo que debería haber es la base más las ventas en efectivo del turno, '
                 'más entradas y menos salidas.') if turno else
                ('No hay ningún turno de caja abierto en este momento.'),
    }


def metodos_pago(periodo='mes', **_):
    """Con qué le pagan: efectivo, tarjeta, transferencias… en mostrador y mesas."""
    p = _periodo(periodo)
    totales, fuentes = {}, []
    with get_db_cursor(dict_cursor=True) as cur:
        if _existe(cur, 'ventas_pos'):
            fuentes.append('mostrador y mesas')
            cur.execute(f"""SELECT COALESCE(NULLIF(TRIM(metodo_pago), ''), 'sin_dato') AS metodo,
                                   COALESCE(SUM(total), 0) AS total, COUNT(*) AS n
                            FROM ventas_pos
                            WHERE COALESCE(estado, 'completada') <> 'anulada' AND {_sql_periodo(p, 'fecha')}
                            GROUP BY 1""")
            for r in cur.fetchall():
                t, n = totales.get(r['metodo'], (0.0, 0))
                totales[r['metodo']] = (t + float(r['total']), n + int(r['n']))
        if _existe(cur, 'pedidos'):
            fuentes.append('tienda web')
            cur.execute(f"""SELECT COALESCE(NULLIF(TRIM(metodo_pago), ''), 'sin_dato') AS metodo,
                                   COALESCE(SUM(monto_total), 0) AS total, COUNT(*) AS n
                            FROM pedidos
                            WHERE estado_pago IN ('APROBADO','PAGADO','aprobado','pagado')
                              AND {_sql_periodo(p, 'fecha_creacion')}
                            GROUP BY 1""")
            for r in cur.fetchall():
                t, n = totales.get(r['metodo'], (0.0, 0))
                totales[r['metodo']] = (t + float(r['total']), n + int(r['n']))
    suma = sum(t for t, _ in totales.values())
    if not suma:
        return {'periodo': _label_periodo(p), 'confiabilidad': 'insuficiente',
                'conclusion': 'No hay ventas con medio de pago registrado en ese período.'}
    filas = sorted(totales.items(), key=lambda kv: -kv[1][0])
    return {
        'periodo': _label_periodo(p), 'total': formatear_moneda(suma),
        'metodos': [{'metodo': _label_metodo(m), 'monto': formatear_moneda(t), 'ventas': n,
                     'porcentaje': f'{t / suma * 100:.0f}%'} for m, (t, n) in filas],
        'incluye': ' y '.join(fuentes),
        'nota': 'El POS de escritorio no informa el medio de pago, así que no está incluido.',
    }
