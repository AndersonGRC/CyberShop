"""Restaurante: qué pasa ahora en el salón y cómo le fue en un período.

Consultas de solo lectura sobre las mismas tablas del módulo de mesas. No se
reutiliza restaurant_tables_service.list_restaurant_reports porque ese camino
crea/ajusta el esquema y estas herramientas nunca deben escribir.
"""

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import _columnas, _existe, _label_periodo, _periodo, _sql_periodo

_ESTADO_MESA = {'disponible': 'Disponible', 'ocupada': 'Ocupada', 'reservada': 'Reservada',
                'cuenta_solicitada': 'Cuenta solicitada'}
_HORAS_ALERTA = 3   # una cuenta abierta más de 3 h suele ser un olvido


def _sin_modulo(cur):
    return not (_existe(cur, 'restaurant_table_orders') and _existe(cur, 'restaurant_tables'))


def restaurante_ahora(**_):
    """Estado del salón en este momento: mesas ocupadas, hace cuánto y cuánto
    llevan consumido las cuentas abiertas."""
    with get_db_cursor(dict_cursor=True) as cur:
        if _sin_modulo(cur):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio no tiene el módulo de mesas en uso.'}
        cur.execute("""SELECT COALESCE(estado, 'disponible') AS estado, COUNT(*) AS n
                       FROM restaurant_tables GROUP BY 1""")
        por_estado = {r['estado']: int(r['n']) for r in cur.fetchall()}
        cur.execute("""
            SELECT t.codigo, t.nombre, o.comensales, o.cliente_nombre, o.opened_at,
                   COALESCE(o.total_acumulado, 0) AS total,
                   EXTRACT(EPOCH FROM (NOW() - o.opened_at)) / 60 AS minutos
            FROM restaurant_table_orders o
            JOIN restaurant_tables t ON t.id = o.table_id
            WHERE o.estado = 'abierta' ORDER BY o.opened_at""")
        abiertas, total_abierto = [], 0.0
        for r in cur.fetchall():
            minutos = int(r['minutos'] or 0)
            total_abierto += float(r['total'] or 0)
            abiertas.append({
                'mesa': r['nombre'] or r['codigo'], 'comensales': r['comensales'],
                'cliente': r['cliente_nombre'], 'abierta_hace_minutos': minutos,
                'lleva_consumido': formatear_moneda(float(r['total'] or 0)),
                'demorada': minutos >= _HORAS_ALERTA * 60,
            })
    demoradas = [a for a in abiertas if a['demorada']]
    return {
        'mesas_por_estado': {_ESTADO_MESA.get(k, k): v for k, v in por_estado.items()},
        'mesas_totales': sum(por_estado.values()),
        'cuentas_abiertas': len(abiertas),
        'detalle_cuentas_abiertas': abiertas,
        'dinero_en_cuentas_abiertas': formatear_moneda(total_abierto),
        'cuentas_demoradas': len(demoradas),
        'nota': (f'{len(demoradas)} cuenta(s) llevan más de {_HORAS_ALERTA} horas abiertas: '
                 'convendría revisarlas.') if demoradas else None,
    }


def restaurante_desempeno(periodo='mes', **_):
    """Cómo le fue al salón en el período: ventas cerradas, ticket por mesa y
    por persona, cuánto duran las mesas, horas pico, platos más pedidos y
    anulaciones."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        if _sin_modulo(cur):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio no tiene el módulo de mesas en uso.'}
        cerradas = _sql_periodo(p, 'o.closed_at')
        cur.execute(f"""
            SELECT COUNT(*) AS n, COALESCE(SUM(o.total_acumulado), 0) AS total,
                   COALESCE(SUM(o.comensales), 0) AS comensales,
                   AVG(EXTRACT(EPOCH FROM (o.closed_at - o.opened_at)) / 60) AS minutos
            FROM restaurant_table_orders o
            WHERE o.estado = 'cerrada' AND o.closed_at IS NOT NULL AND {cerradas}""")
        r = cur.fetchone()
        n, total = int(r['n'] or 0), float(r['total'] or 0)
        comensales = int(r['comensales'] or 0)
        minutos = float(r['minutos'] or 0)
        if not n:
            return {'periodo': _label_periodo(p), 'confiabilidad': 'insuficiente',
                    'conclusion': 'No hubo mesas cerradas en ese período.'}

        cur.execute(f"""SELECT EXTRACT(HOUR FROM o.opened_at)::int AS hora, COUNT(*) AS n,
                               COALESCE(SUM(o.total_acumulado), 0) AS total
                        FROM restaurant_table_orders o
                        WHERE o.estado = 'cerrada' AND o.closed_at IS NOT NULL AND {cerradas}
                        GROUP BY 1 ORDER BY total DESC LIMIT 3""")
        picos = [{'hora': f"{x['hora']:02d}:00", 'mesas': int(x['n']),
                  'ventas': formatear_moneda(float(x['total']))} for x in cur.fetchall()]

        cur.execute(f"""SELECT t.nombre, t.codigo, COUNT(*) AS n,
                               COALESCE(SUM(o.total_acumulado), 0) AS total
                        FROM restaurant_table_orders o JOIN restaurant_tables t ON t.id = o.table_id
                        WHERE o.estado = 'cerrada' AND o.closed_at IS NOT NULL AND {cerradas}
                        GROUP BY 1, 2 ORDER BY total DESC LIMIT 5""")
        mesas = [{'mesa': x['nombre'] or x['codigo'], 'veces_usada': int(x['n']),
                  'ventas': formatear_moneda(float(x['total']))} for x in cur.fetchall()]

        platos = []
        if _existe(cur, 'restaurant_table_consumptions'):
            cur.execute(f"""SELECT c.descripcion, SUM(c.cantidad) AS unidades,
                                   COALESCE(SUM(c.subtotal), 0) AS total
                            FROM restaurant_table_consumptions c
                            JOIN restaurant_table_orders o ON o.id = c.order_id
                            WHERE o.estado = 'cerrada' AND o.closed_at IS NOT NULL AND {cerradas}
                            GROUP BY 1 ORDER BY unidades DESC LIMIT 5""")
            platos = [{'plato': x['descripcion'], 'unidades': int(x['unidades'] or 0),
                       'vendido': formatear_moneda(float(x['total']))} for x in cur.fetchall()]

        pagos = []
        if 'payment_method' in _columnas(cur, 'restaurant_table_orders'):
            cur.execute(f"""SELECT COALESCE(NULLIF(TRIM(o.payment_method), ''), 'sin_dato') AS metodo,
                                   COUNT(*) AS n, COALESCE(SUM(o.total_acumulado), 0) AS total
                            FROM restaurant_table_orders o
                            WHERE o.estado = 'cerrada' AND o.closed_at IS NOT NULL AND {cerradas}
                            GROUP BY 1 ORDER BY total DESC""")
            pagos = [{'metodo': (x['metodo'] or '').replace('_', ' ').capitalize(), 'mesas': int(x['n']),
                      'monto': formatear_moneda(float(x['total']))} for x in cur.fetchall()]

        anuladas, motivos = 0, []
        cols = _columnas(cur, 'restaurant_table_orders')
        if 'cancelled_at' in cols:
            cur.execute(f"""SELECT COUNT(*) AS n FROM restaurant_table_orders o
                            WHERE o.estado = 'cancelada' AND {_sql_periodo(p, 'o.cancelled_at')}""")
            anuladas = int(cur.fetchone()['n'] or 0)
            if anuladas and 'cancel_reason' in cols:
                cur.execute(f"""SELECT COALESCE(NULLIF(TRIM(o.cancel_reason), ''), 'sin motivo') AS motivo,
                                       COUNT(*) AS n
                                FROM restaurant_table_orders o
                                WHERE o.estado = 'cancelada' AND {_sql_periodo(p, 'o.cancelled_at')}
                                GROUP BY 1 ORDER BY n DESC LIMIT 5""")
                motivos = [{'motivo': x['motivo'], 'veces': int(x['n'])} for x in cur.fetchall()]

    return {
        'periodo': _label_periodo(p),
        'mesas_atendidas': n, 'ventas': formatear_moneda(total),
        'ticket_promedio_por_mesa': formatear_moneda(total / n),
        'comensales': comensales or None,
        'ticket_promedio_por_persona': formatear_moneda(total / comensales) if comensales else None,
        'duracion_promedio_minutos': round(minutos, 1) if minutos else None,
        'horas_de_mayor_venta': picos,
        'mesas_mas_productivas': mesas,
        'platos_mas_pedidos': platos,
        'medios_de_pago': pagos,
        'mesas_anuladas': anuladas, 'motivos_de_anulacion': motivos,
        'nota': 'Las cuentas abiertas ahora no entran: solo cuentan las mesas ya cobradas.',
    }
