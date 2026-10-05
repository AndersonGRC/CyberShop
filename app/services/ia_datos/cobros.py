"""Cotizaciones y cuentas de cobro UNA por UNA, y lo cobrado en un período.

Complementa a comercial.py (agregados del período y cartera): aquí se responde
«¿qué le cotizamos a Juan?», «¿ya pagaron la CC-0007?» y «¿cuánto cobré este
mes?». Solo lectura. Del cliente: nombre y lo que se le cotizó o cobró; nunca
documento, teléfono, correo ni dirección.
"""

import re

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import _columnas, _existe, _label_periodo, _periodo, _sql_periodo

_PLAZO_DIAS = 30           # mismo criterio que la cartera: sin vencimiento propio, 30 días
_ESTADO_COT = {'pendiente': 'Pendiente (sin respuesta del cliente)', 'aprobada': 'Aprobada',
               'rechazada': 'Rechazada'}
_ESTADO_PAGO = {'pendiente': 'Pendiente de pago', 'pagada': 'Pagada', None: 'Sin revisar (nadie ha marcado el cobro)'}


def _dinero(v):
    return formatear_moneda(float(v or 0))


def _fecha(v):
    return v.strftime('%d/%m/%Y') if hasattr(v, 'strftime') else (str(v) if v else None)


def _numero_de(texto):
    """«COT 0000000012» / «cotización 15» / «#15» / «CC-0007» → 15 / 7. None si
    el texto no es un número de documento (entonces es el nombre del cliente)."""
    t = (texto or '').strip()
    m = re.fullmatch(r'(?:cot|cc|cuenta|n[uú]mero|no\.?|n[°º]|#)?[\s\-#:]*0*(\d{1,10})', t, re.I)
    return int(m.group(1)) if m else None


def _cobro(r, cols):
    """Estado de cobro de un documento (si el negocio lo lleva)."""
    if 'estado_pago' not in cols:
        return {}
    estado = r.get('estado_pago')
    salida = {'cobro': _ESTADO_PAGO.get(estado, estado)}
    if estado == 'pagada' and r.get('fecha_pago'):
        salida['pagada_el'] = _fecha(r['fecha_pago'])
    if estado == 'pendiente' and r.get('dias_mora') is not None and r['dias_mora'] > 0:
        salida['dias_de_mora'] = int(r['dias_mora'])
    if r.get('vence'):
        salida['vence'] = _fecha(r['vence'])
    return salida


# ── Una cotización ──────────────────────────────────────────────
def cotizacion_detalle(texto='', **_):
    """UNA cotización por su número, o las últimas cotizaciones de un cliente:
    cuánto, qué incluye, si la aprobaron y si ya la pagaron."""
    texto = (texto or '').strip()
    if not texto:
        return {'conclusion': 'Dime el número de la cotización (por ejemplo COT 0000000012) o el nombre del cliente.'}
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'cotizaciones'):
            return {'confiabilidad': 'insuficiente', 'conclusion': 'Este negocio no usa el módulo de cotizaciones.'}
        cols = _columnas(cur, 'cotizaciones')
        extra = []
        if 'estado_pago' in cols:
            extra += ['estado_pago', 'fecha_pago',
                      f"COALESCE(fecha_vencimiento, (fecha + INTERVAL '{_PLAZO_DIAS} days'))::date AS vence",
                      f"(CURRENT_DATE - COALESCE(fecha_vencimiento, (fecha + INTERVAL '{_PLAZO_DIAS} days'))::date) AS dias_mora"]
        estado_sql = "COALESCE(NULLIF(TRIM(estado), ''), 'pendiente')" if 'estado' in cols else "'pendiente'"
        sel = (f"SELECT id, fecha, cliente_nombre, total, {estado_sql} AS estado, "
               f"(CURRENT_DATE - fecha::date) AS dias{''.join(', ' + e for e in extra)} FROM cotizaciones")
        numero = _numero_de(texto)
        filas = []
        if numero is not None:
            cur.execute(sel + ' WHERE id = %s', (numero,))
            filas = cur.fetchall()
        if not filas:
            cur.execute(sel + ' WHERE lower(cliente_nombre) LIKE %s ORDER BY fecha DESC LIMIT 5',
                        (f'%{texto.lower()}%',))
            filas = cur.fetchall()
        if not filas:
            return {'conclusion': f'No encontré cotizaciones con «{texto}».'}
        detalle_ok = _existe(cur, 'detalle_cotizacion')
        orden_ok = _existe(cur, 'st_ordenes')
        salida = []
        for r in filas:
            items = []
            if detalle_ok:
                cur.execute("""SELECT descripcion, cantidad, subtotal FROM detalle_cotizacion
                               WHERE cotizacion_id = %s ORDER BY id LIMIT 10""", (r['id'],))
                items = [{'que': i['descripcion'], 'cantidad': i['cantidad'], 'subtotal': _dinero(i['subtotal'])}
                         for i in cur.fetchall()]
            doc = {
                'numero': f"COT {r['id']:010d}", 'fecha': _fecha(r['fecha']), 'cliente': r['cliente_nombre'],
                'total': _dinero(r['total']), 'estado': _ESTADO_COT.get(r['estado'], r['estado'].capitalize()),
                'items': items,
            }
            if r['estado'] == 'pendiente':
                doc['dias_sin_respuesta'] = int(r['dias'] or 0)
            if r['estado'] == 'aprobada':
                doc.update(_cobro(r, cols))
            if orden_ok:
                cur.execute('SELECT numero FROM st_ordenes WHERE cotizacion_id = %s LIMIT 1', (r['id'],))
                o = cur.fetchone()
                if o:
                    doc['orden_de_servicio'] = o['numero']
            salida.append(doc)
    return {'cotizaciones_encontradas': len(salida), 'cotizaciones': salida,
            'nota': 'Solo las aprobadas tienen seguimiento de cobro.' if any(
                d['estado'].startswith('Pendiente') for d in salida) else None}


# ── Una cuenta de cobro ─────────────────────────────────────────
def cuenta_cobro_detalle(texto='', **_):
    """UNA cuenta de cobro por su número (CC-0007) o las últimas de un cliente:
    cuánto, por qué labores y si ya la pagaron o está en mora."""
    texto = (texto or '').strip()
    if not texto:
        return {'conclusion': 'Dime el número de la cuenta de cobro (por ejemplo CC-0007) o el nombre del cliente.'}
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'cuentas_cobro'):
            return {'confiabilidad': 'insuficiente', 'conclusion': 'Este negocio no usa el módulo de cuentas de cobro.'}
        cols = _columnas(cur, 'cuentas_cobro')
        extra = []
        if 'estado_pago' in cols:
            extra += ['estado_pago', 'fecha_pago',
                      f"COALESCE(fecha_vencimiento, (fecha + INTERVAL '{_PLAZO_DIAS} days'))::date AS vence",
                      f"(CURRENT_DATE - COALESCE(fecha_vencimiento, (fecha + INTERVAL '{_PLAZO_DIAS} days'))::date) AS dias_mora"]
        consecutivo = "COALESCE(consecutivo, 'CC-' || id::text)" if 'consecutivo' in cols else "'CC-' || id::text"
        sel = (f"SELECT id, {consecutivo} AS numero, fecha, cliente_nombre, total"
               f"{''.join(', ' + e for e in extra)} FROM cuentas_cobro")
        numero = _numero_de(texto)
        filas = []
        if numero is not None:
            cond = "id = %s"
            params = [numero]
            if 'consecutivo' in cols:
                cond = "(NULLIF(regexp_replace(COALESCE(consecutivo, ''), '\\D', '', 'g'), '')::bigint = %s OR (consecutivo IS NULL AND id = %s))"
                params = [numero, numero]
            cur.execute(sel + f' WHERE {cond} ORDER BY fecha DESC LIMIT 3', params)
            filas = cur.fetchall()
        if not filas:
            cur.execute(sel + ' WHERE lower(cliente_nombre) LIKE %s ORDER BY fecha DESC LIMIT 5',
                        (f'%{texto.lower()}%',))
            filas = cur.fetchall()
        if not filas:
            return {'conclusion': f'No encontré cuentas de cobro con «{texto}».'}
        detalle_ok = _existe(cur, 'detalle_cuenta_cobro')
        salida = []
        for r in filas:
            labores = []
            if detalle_ok:
                cur.execute("""SELECT fecha_labor, descripcion, valor FROM detalle_cuenta_cobro
                               WHERE cuenta_id = %s ORDER BY id LIMIT 10""", (r['id'],))
                labores = [{'fecha': _fecha(x['fecha_labor']), 'que': x['descripcion'], 'valor': _dinero(x['valor'])}
                           for x in cur.fetchall()]
            salida.append({'numero': r['numero'], 'fecha': _fecha(r['fecha']), 'cliente': r['cliente_nombre'],
                           'total': _dinero(r['total']), 'labores': labores, **_cobro(r, cols)})
    salida_final = {'cuentas_encontradas': len(salida), 'cuentas_de_cobro': salida}
    if 'estado_pago' not in cols:
        salida_final['nota'] = 'Este negocio todavía no marca el cobro de sus cuentas: no sé si están pagadas.'
    return salida_final


# ── Lo cobrado en un período ────────────────────────────────────
def cobros_recibidos(periodo='mes', **_):
    """Lo que de verdad le pagaron en el período: cotizaciones aprobadas y
    cuentas de cobro marcadas como pagadas, por fecha de pago."""
    p = _periodo(periodo)
    fuentes = (('cotizaciones', 'Cotización', "'COT ' || LPAD(id::text, 10, '0')"),
               ('cuentas_cobro', 'Cuenta de cobro', "COALESCE(consecutivo, 'CC-' || id::text)"))
    total, n, sin_fecha = 0.0, 0, 0
    por_documento, por_cliente, ultimos = [], {}, []
    with get_db_cursor(dict_cursor=True) as cur:
        disponibles = [f for f in fuentes
                       if _existe(cur, f[0]) and {'estado_pago', 'fecha_pago'} <= _columnas(cur, f[0])]
        if not disponibles:
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio todavía no marca cuándo le pagan sus cotizaciones y cuentas de cobro.'}
        for tabla, etiqueta, numero in disponibles:
            filtro = f"estado_pago = 'pagada' AND fecha_pago IS NOT NULL AND {_sql_periodo(p, 'fecha_pago')}"
            cur.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS t FROM {tabla} WHERE {filtro}")
            r = cur.fetchone()
            n += int(r['n'])
            total += float(r['t'])
            por_documento.append({'documento': etiqueta, 'pagos': int(r['n']), 'monto': _dinero(r['t'])})
            cur.execute(f"""SELECT COALESCE(cliente_nombre, 'Sin nombre') AS cliente, COUNT(*) AS n,
                                   COALESCE(SUM(total), 0) AS t
                            FROM {tabla} WHERE {filtro} GROUP BY 1""")
            for x in cur.fetchall():
                c = por_cliente.setdefault(x['cliente'], [0, 0.0])
                c[0] += int(x['n'])
                c[1] += float(x['t'])
            cur.execute(f"""SELECT {numero} AS numero, cliente_nombre, total, fecha_pago FROM {tabla}
                            WHERE {filtro} ORDER BY fecha_pago DESC LIMIT 10""")
            ultimos += [{'documento': etiqueta, 'numero': x['numero'], 'cliente': x['cliente_nombre'],
                         'monto': _dinero(x['total']), 'pagado_el': _fecha(x['fecha_pago']),
                         '_orden': x['fecha_pago']} for x in cur.fetchall()]
            cur.execute(f"SELECT COUNT(*) AS n FROM {tabla} WHERE estado_pago = 'pagada' AND fecha_pago IS NULL")
            sin_fecha += int(cur.fetchone()['n'])
    ultimos.sort(key=lambda x: str(x['_orden']), reverse=True)
    for u in ultimos:
        u.pop('_orden', None)
    if not n:
        salida = {'periodo': _label_periodo(p), 'pagos_recibidos': 0,
                  'conclusion': 'No hay pagos marcados en ese período.'}
    else:
        salida = {
            'periodo': _label_periodo(p), 'pagos_recibidos': n, 'monto_cobrado': formatear_moneda(total),
            'por_tipo_de_documento': por_documento,
            'quien_pago_mas': [{'cliente': c, 'pagos': v[0], 'monto': formatear_moneda(v[1])}
                               for c, v in sorted(por_cliente.items(), key=lambda kv: kv[1][1], reverse=True)[:10]],
            'ultimos_pagos': ultimos[:10],
        }
    salida['nota'] = ('Cuenta lo marcado como pagado en cotizaciones y cuentas de cobro (por fecha de pago); '
                      'las ventas de la tienda y del punto de venta van aparte.'
                      + (f' Hay {sin_fecha} documento(s) pagados sin fecha de pago: no entran.' if sin_fecha else ''))
    return salida
