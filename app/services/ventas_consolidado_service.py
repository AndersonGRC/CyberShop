"""Consolidado de ventas de todos los canales, desde el libro contable.

Cada venta es UN movimiento de ingreso en `contabilidad_movimientos`, etiquetado
por canal. `ventas_pos` y las órdenes de mesa son espejos operativos: no se
suman. Por eso el consolidado (total) y el diferencial (por canal) salen SOLO de
aquí, sin duplicar. Lo usan el reporte /admin/contabilidad/ventas y el script de
reconciliación de la IA (tools/ia_reconciliar_ventas.py).
"""

from flask import current_app

from database import get_db_cursor

VENTA_CATEGORIAS = ['venta_pos', 'venta_restaurante', 'pedido_online', 'cuenta_cobro']
CANAL_LABEL = {
    'venta_pos': 'POS',
    'venta_restaurante': 'Mesas',
    'pedido_online': 'Tienda online',
    'cuenta_cobro': 'Cuentas de cobro',
}


def ventas_consolidado_data(agrup, date_from, date_to):
    """(por_canal, serie, total_general, total_cnt, ticket) entre dos fechas
    (inclusive), agrupado por 'dia', 'semana' o 'mes'."""
    trunc = {'dia': 'day', 'semana': 'week', 'mes': 'month'}[agrup]
    por_canal, serie = [], []
    total_general, total_cnt = 0.0, 0
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT categoria, COALESCE(SUM(monto),0) AS total, COUNT(*) AS cnt
                FROM contabilidad_movimientos
                WHERE tipo='ingreso' AND categoria = ANY(%s)
                  AND fecha BETWEEN %s AND %s
                GROUP BY categoria ORDER BY total DESC
            """, (VENTA_CATEGORIAS, date_from, date_to))
            for r in cur.fetchall():
                t = float(r['total'])
                por_canal.append({'categoria': r['categoria'],
                                  'label': CANAL_LABEL.get(r['categoria'], r['categoria']),
                                  'total': t, 'cnt': int(r['cnt'])})
                total_general += t
                total_cnt += int(r['cnt'])

            cur.execute("""
                SELECT DATE_TRUNC(%s, fecha)::date AS periodo, categoria,
                       COALESCE(SUM(monto),0) AS total, COUNT(*) AS cnt
                FROM contabilidad_movimientos
                WHERE tipo='ingreso' AND categoria = ANY(%s)
                  AND fecha BETWEEN %s AND %s
                GROUP BY periodo, categoria ORDER BY periodo
            """, (trunc, VENTA_CATEGORIAS, date_from, date_to))
            buckets = {}
            for r in cur.fetchall():
                p = r['periodo'].isoformat()
                b = buckets.setdefault(p, {'periodo': p, 'total': 0.0, 'cnt': 0})
                b[r['categoria']] = float(r['total'])
                b['total'] += float(r['total'])
                b['cnt'] += int(r['cnt'])
            serie = [buckets[k] for k in sorted(buckets)]
    except Exception as e:
        current_app.logger.error(f"ventas_consolidado: {e}")
    ticket = round(total_general / total_cnt, 2) if total_cnt else 0
    return por_canal, serie, total_general, total_cnt, ticket
