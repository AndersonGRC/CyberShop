"""Comercial: CRM (oportunidades y seguimiento), cotizaciones, cuentas de cobro,
historial de un cliente y reseñas.

Todo es de solo lectura y agregado. Del cliente se devuelve su nombre y lo que
compró; nunca documento, teléfono, correo ni dirección.
"""

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import (
    _PEDIDO_PAGADO, _columnas, _existe, _label_periodo, _periodo, _sql_periodo,
)

# Espejo de routes/crm.py: las claves internas no cambian, las etiquetas son las comerciales.
ETAPAS = {'prospecto': 'Nuevo', 'calificado': 'Contactado', 'propuesta': 'Cotización',
          'negociacion': 'Negociación', 'ganada': 'Ganado', 'perdida': 'Perdida'}
ETAPAS_ABIERTAS = ('prospecto', 'calificado', 'propuesta', 'negociacion')


def crm_pipeline(**_):
    """Negocios en curso: cuánto hay por etapa, cuánto se espera cerrar
    (monto por probabilidad), qué se ganó o perdió y qué cierra pronto."""
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'crm_oportunidades'):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio todavía no usa el tablero de oportunidades del CRM.'}
        cur.execute("""SELECT etapa, COUNT(*) AS n, COALESCE(SUM(monto_estimado), 0) AS total,
                              COALESCE(SUM(monto_estimado * probabilidad / 100.0), 0) AS ponderado
                       FROM crm_oportunidades GROUP BY etapa""")
        por_etapa, abierto, ponderado = [], 0.0, 0.0
        ganadas = perdidas = 0
        monto_ganado = 0.0
        for r in cur.fetchall():
            etapa = r['etapa']
            fila = {'etapa': ETAPAS.get(etapa, etapa), 'negocios': int(r['n']),
                    'monto': formatear_moneda(float(r['total']))}
            if etapa in ETAPAS_ABIERTAS:
                abierto += float(r['total'])
                ponderado += float(r['ponderado'])
                fila['esperado_por_probabilidad'] = formatear_moneda(float(r['ponderado']))
            elif etapa == 'ganada':
                ganadas, monto_ganado = int(r['n']), float(r['total'])
            elif etapa == 'perdida':
                perdidas = int(r['n'])
            por_etapa.append(fila)

        cur.execute("""SELECT o.titulo, o.monto_estimado, o.probabilidad, o.fecha_cierre_est,
                              c.nombre AS contacto
                       FROM crm_oportunidades o LEFT JOIN crm_contactos c ON c.id = o.contacto_id
                       WHERE o.etapa = ANY(%s) AND o.fecha_cierre_est IS NOT NULL
                         AND o.fecha_cierre_est <= CURRENT_DATE + 30
                       ORDER BY o.fecha_cierre_est LIMIT 10""", (list(ETAPAS_ABIERTAS),))
        proximas = [{'negocio': r['titulo'], 'cliente': r['contacto'],
                     'monto': formatear_moneda(float(r['monto_estimado'] or 0)),
                     'probabilidad': f"{int(r['probabilidad'] or 0)}%",
                     'cierra': r['fecha_cierre_est'].isoformat(),
                     'vencida': r['fecha_cierre_est'] < _hoy(cur)} for r in cur.fetchall()]

        cur.execute("""SELECT COUNT(*) AS n FROM crm_oportunidades
                       WHERE etapa = ANY(%s) AND updated_at < NOW() - INTERVAL '7 days'""",
                    (list(ETAPAS_ABIERTAS),))
        estancadas = int(cur.fetchone()['n'] or 0)

    cerradas = ganadas + perdidas
    return {
        'negocios_abiertos': sum(f['negocios'] for f in por_etapa if f['etapa'] not in ('Ganado', 'Perdida')),
        'monto_en_juego': formatear_moneda(abierto),
        'esperado_por_probabilidad': formatear_moneda(ponderado),
        'por_etapa': por_etapa,
        'ganados': ganadas, 'perdidos': perdidas,
        'monto_ganado': formatear_moneda(monto_ganado),
        'tasa_de_cierre': f'{ganadas / cerradas * 100:.0f}%' if cerradas else None,
        'cierres_proximos_30_dias': proximas,
        'sin_movimiento_hace_una_semana': estancadas,
        'nota': ('"Esperado por probabilidad" pondera cada negocio por su probabilidad de cierre; '
                 'no es dinero seguro.'),
    }


def _hoy(cur):
    cur.execute("SELECT CURRENT_DATE AS hoy")
    return cur.fetchone()['hoy']


def crm_seguimiento(**_):
    """A quién hay que atender: tareas vencidas o de hoy, por responsable, y
    contactos sin movimiento hace más de un mes."""
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'crm_tareas'):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio todavía no usa las tareas del CRM.'}
        cur.execute("""SELECT COUNT(*) FILTER (WHERE fecha_limite < CURRENT_DATE) AS vencidas,
                              COUNT(*) FILTER (WHERE fecha_limite = CURRENT_DATE) AS hoy,
                              COUNT(*) FILTER (WHERE fecha_limite > CURRENT_DATE) AS proximas,
                              COUNT(*) AS pendientes
                       FROM crm_tareas WHERE estado = 'pendiente'""")
        t = cur.fetchone()
        cur.execute("""SELECT COALESCE(u.nombre, 'Sin responsable') AS responsable,
                              COUNT(*) FILTER (WHERE t.fecha_limite < CURRENT_DATE) AS vencidas,
                              COUNT(*) AS pendientes
                       FROM crm_tareas t LEFT JOIN usuarios u ON u.id = t.asignado_a
                       WHERE t.estado = 'pendiente' GROUP BY 1 ORDER BY vencidas DESC, pendientes DESC LIMIT 10""")
        por_responsable = [{'responsable': r['responsable'], 'vencidas': int(r['vencidas']),
                            'pendientes': int(r['pendientes'])} for r in cur.fetchall()]
        cur.execute("""SELECT t.titulo, t.prioridad, t.fecha_limite, c.nombre AS contacto,
                              COALESCE(u.nombre, 'Sin responsable') AS responsable
                       FROM crm_tareas t
                       LEFT JOIN crm_contactos c ON c.id = t.contacto_id
                       LEFT JOIN usuarios u ON u.id = t.asignado_a
                       WHERE t.estado = 'pendiente' AND t.fecha_limite <= CURRENT_DATE
                       ORDER BY t.fecha_limite LIMIT 10""")
        urgentes = [{'tarea': r['titulo'], 'prioridad': r['prioridad'], 'cliente': r['contacto'],
                     'responsable': r['responsable'],
                     'vence': r['fecha_limite'].isoformat() if r['fecha_limite'] else None}
                    for r in cur.fetchall()]

        dormidos = []
        if _existe(cur, 'crm_contactos') and _existe(cur, 'crm_actividades'):
            cur.execute("""SELECT c.nombre, c.empresa, MAX(a.fecha_actividad) AS ultima
                           FROM crm_contactos c LEFT JOIN crm_actividades a ON a.contacto_id = c.id
                           WHERE COALESCE(c.activo, TRUE)
                           GROUP BY c.id, c.nombre, c.empresa
                           HAVING MAX(a.fecha_actividad) IS NULL
                               OR MAX(a.fecha_actividad) < NOW() - INTERVAL '30 days'
                           ORDER BY ultima NULLS FIRST LIMIT 10""")
            dormidos = [{'cliente': r['nombre'], 'empresa': r['empresa'],
                         'ultimo_contacto': r['ultima'].date().isoformat() if r['ultima'] else 'nunca'}
                        for r in cur.fetchall()]
    return {
        'tareas_pendientes': int(t['pendientes']), 'tareas_vencidas': int(t['vencidas']),
        'tareas_para_hoy': int(t['hoy']), 'tareas_proximas': int(t['proximas']),
        'por_responsable': por_responsable,
        'lo_mas_urgente': urgentes,
        'clientes_sin_contacto_hace_un_mes': dormidos,
    }


def cotizaciones_estado(periodo='mes', **_):
    """Cotizaciones del período: cuántas, por cuánto, cuántas se aprobaron y
    cuáles llevan mucho sin respuesta."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'cotizaciones'):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio no usa el módulo de cotizaciones.'}
        tiene_estado = 'estado' in _columnas(cur, 'cotizaciones')
        estado_sql = "COALESCE(NULLIF(TRIM(estado), ''), 'pendiente')" if tiene_estado else "'pendiente'"
        cur.execute(f"""SELECT {estado_sql} AS estado, COUNT(*) AS n, COALESCE(SUM(total), 0) AS total
                        FROM cotizaciones WHERE {_sql_periodo(p, 'fecha')}
                        GROUP BY 1 ORDER BY n DESC""")
        por_estado, totales = [], {}
        for r in cur.fetchall():
            totales[r['estado']] = (int(r['n']), float(r['total']))
            por_estado.append({'estado': r['estado'].capitalize(), 'cotizaciones': int(r['n']),
                               'monto': formatear_moneda(float(r['total']))})
        cur.execute(f"""SELECT cliente_nombre, total, fecha FROM cotizaciones
                        WHERE {estado_sql} = 'pendiente' AND fecha < CURRENT_DATE - 15
                        ORDER BY fecha LIMIT 10""")
        viejas = [{'cliente': r['cliente_nombre'], 'monto': formatear_moneda(float(r['total'] or 0)),
                   'fecha': r['fecha'].isoformat() if hasattr(r['fecha'], 'isoformat') else str(r['fecha'])}
                  for r in cur.fetchall()]
    n_total = sum(n for n, _ in totales.values())
    monto_total = sum(t for _, t in totales.values())
    aprobadas = totales.get('aprobada', (0, 0.0))
    if not n_total:
        return {'periodo': _label_periodo(p), 'confiabilidad': 'insuficiente',
                'conclusion': 'No se hicieron cotizaciones en ese período.'}
    return {
        'periodo': _label_periodo(p), 'cotizaciones': n_total,
        'monto_cotizado': formatear_moneda(monto_total),
        'por_estado': por_estado,
        'aprobadas': aprobadas[0], 'monto_aprobado': formatear_moneda(aprobadas[1]),
        'tasa_de_aprobacion': f'{aprobadas[0] / n_total * 100:.0f}%',
        'pendientes_hace_mas_de_15_dias': viejas,
    }


def cuentas_cobro_periodo(periodo='mes', **_):
    """Cuentas de cobro emitidas en el período y a quién."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'cuentas_cobro'):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio no usa el módulo de cuentas de cobro.'}
        cur.execute(f"""SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS total
                        FROM cuentas_cobro WHERE {_sql_periodo(p, 'fecha')}""")
        r = cur.fetchone()
        cur.execute(f"""SELECT cliente_nombre, COUNT(*) AS n, COALESCE(SUM(total), 0) AS total
                        FROM cuentas_cobro WHERE {_sql_periodo(p, 'fecha')}
                        GROUP BY 1 ORDER BY total DESC LIMIT 10""")
        clientes = [{'cliente': x['cliente_nombre'], 'cuentas': int(x['n']),
                     'monto': formatear_moneda(float(x['total']))} for x in cur.fetchall()]
    n = int(r['n'] or 0)
    if not n:
        return {'periodo': _label_periodo(p), 'confiabilidad': 'insuficiente',
                'conclusion': 'No se emitieron cuentas de cobro en ese período.'}
    return {
        'periodo': _label_periodo(p), 'cuentas_emitidas': n,
        'monto_emitido': formatear_moneda(float(r['total'])),
        'por_cliente': clientes,
        'nota': ('El sistema no registra si cada cuenta de cobro ya fue pagada, así que no puedo '
                 'decir cuánto está pendiente por cobrar.'),
    }


def cliente_historial(cliente='', **_):
    """Todo lo que ha comprado un cliente: cuántas veces, cuánto, cuándo fue la
    última y qué se lleva siempre. Sin datos de contacto."""
    nombre = (cliente or '').strip()
    if len(nombre) < 3:
        return {'confiabilidad': 'insuficiente',
                'conclusion': 'Dime el nombre del cliente (al menos 3 letras) para buscar su historial.'}
    patron = f'%{nombre.lower()}%'
    with get_db_cursor(dict_cursor=True) as cur:
        partes = [(f"SELECT cliente_nombre AS nombre, monto_total AS monto, fecha_creacion AS fecha, "
                   f"'Tienda web' AS canal FROM pedidos WHERE {_PEDIDO_PAGADO} AND LOWER(cliente_nombre) LIKE %s")]
        params = [patron]
        if _existe(cur, 'ventas_pos'):
            partes.append("SELECT cliente_nombre, total, fecha, "
                          "CASE WHEN numero_venta LIKE 'MESA-%%' THEN 'Mesas' ELSE 'Mostrador' END "
                          "FROM ventas_pos WHERE COALESCE(estado,'completada') <> 'anulada' "
                          "AND LOWER(cliente_nombre) LIKE %s")
            params.append(patron)
        union = ' UNION ALL '.join(partes)
        cur.execute(f"""SELECT nombre, COUNT(*) AS compras, COALESCE(SUM(monto), 0) AS total,
                               MAX(fecha) AS ultima, MIN(fecha) AS primera
                        FROM ({union}) x GROUP BY nombre ORDER BY total DESC LIMIT 5""", params)
        coincidencias = cur.fetchall()
        if not coincidencias:
            return {'cliente_buscado': nombre, 'confiabilidad': 'insuficiente',
                    'conclusion': f'No encontré compras a nombre de «{nombre}».'}
        if len(coincidencias) > 1:
            return {'cliente_buscado': nombre,
                    'varios_clientes_coinciden': [{'cliente': c['nombre'], 'compras': int(c['compras']),
                                                   'total': formatear_moneda(float(c['total']))}
                                                  for c in coincidencias],
                    'conclusion': 'Hay varios clientes con ese nombre: pregunta a cuál se refiere.'}
        c = coincidencias[0]
        exacto = c['nombre']
        favoritos = []
        if _existe(cur, 'detalle_venta_pos'):
            cur.execute("""SELECT dv.descripcion AS nombre, SUM(dv.cantidad) AS unidades
                           FROM detalle_venta_pos dv JOIN ventas_pos v ON v.id = dv.venta_id
                           WHERE COALESCE(v.estado,'completada') <> 'anulada' AND v.cliente_nombre = %s
                           GROUP BY 1 ORDER BY unidades DESC LIMIT 5""", (exacto,))
            favoritos = [{'producto': x['nombre'], 'unidades': int(x['unidades'])} for x in cur.fetchall()]
        cur.execute(f"""SELECT canal, COUNT(*) AS n, COALESCE(SUM(monto), 0) AS total
                        FROM ({union}) x WHERE nombre = %s GROUP BY canal ORDER BY total DESC""",
                    params + [exacto])
        canales = [{'canal': x['canal'], 'compras': int(x['n']),
                    'monto': formatear_moneda(float(x['total']))} for x in cur.fetchall()]
        hoy = _hoy(cur)
    compras = int(c['compras'])
    total = float(c['total'])
    ultima = c['ultima'].date() if hasattr(c['ultima'], 'date') else c['ultima']
    return {
        'cliente': exacto, 'compras': compras, 'total_comprado': formatear_moneda(total),
        'ticket_promedio': formatear_moneda(total / compras),
        'primera_compra': (c['primera'].date() if hasattr(c['primera'], 'date') else c['primera']).isoformat(),
        'ultima_compra': ultima.isoformat(),
        'dias_desde_la_ultima_compra': (hoy - ultima).days,
        'productos_favoritos': favoritos, 'por_canal': canales,
        'nota': 'No incluyo datos de contacto del cliente.',
    }


def resenas_estado(**_):
    """Cómo califican los clientes: promedio, distribución, reseñas sin
    responder o sin aprobar y los productos peor calificados."""
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'producto_comentarios'):
            return {'confiabilidad': 'insuficiente', 'conclusion': 'Todavía no hay reseñas de clientes.'}
        cols = _columnas(cur, 'producto_comentarios')
        cur.execute("""SELECT COUNT(*) AS n, AVG(calificacion) AS promedio,
                              COUNT(*) FILTER (WHERE NOT COALESCE(aprobado, FALSE)) AS sin_aprobar
                       FROM producto_comentarios""")
        r = cur.fetchone()
        if not int(r['n'] or 0):
            return {'confiabilidad': 'insuficiente', 'conclusion': 'Todavía no hay reseñas de clientes.'}
        cur.execute("""SELECT calificacion, COUNT(*) AS n FROM producto_comentarios
                       GROUP BY 1 ORDER BY 1 DESC""")
        distribucion = [{'estrellas': int(x['calificacion'] or 0), 'reseñas': int(x['n'])} for x in cur.fetchall()]
        sin_responder = 0
        if 'respuesta' in cols:
            cur.execute("""SELECT COUNT(*) AS n FROM producto_comentarios
                           WHERE COALESCE(aprobado, FALSE) AND (respuesta IS NULL OR TRIM(respuesta) = '')""")
            sin_responder = int(cur.fetchone()['n'] or 0)
        cur.execute("""SELECT p.nombre, AVG(c.calificacion) AS promedio, COUNT(*) AS n
                       FROM producto_comentarios c JOIN productos p ON p.id = c.producto_id
                       GROUP BY p.id, p.nombre HAVING COUNT(*) >= 2
                       ORDER BY promedio ASC LIMIT 5""")
        peores = [{'producto': x['nombre'], 'promedio': round(float(x['promedio']), 1),
                   'reseñas': int(x['n'])} for x in cur.fetchall()]
    return {
        'reseñas': int(r['n']), 'promedio': round(float(r['promedio'] or 0), 1),
        'distribucion': distribucion,
        'sin_aprobar': int(r['sin_aprobar'] or 0),
        'aprobadas_sin_responder': sin_responder,
        'productos_peor_calificados': peores,
        'nota': 'Responder las reseñas ayuda al posicionamiento en buscadores.',
    }
