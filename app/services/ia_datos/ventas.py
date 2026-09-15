"""Ventas, clientes y pedidos.

Las "ventas" combinan pedidos web aprobados (`pedidos`) + ventas de mostrador
(`ventas_pos`) + POS de escritorio (`pos_desktop_sales`).
"""

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import (
    _PEDIDO_PAGADO, _columnas, _existe, _label_periodo, _periodo, _sql_periodo, _suma,
)


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


def _escritorio_sincronizado_hasta(cur):
    """Hora de la última venta del POS de escritorio que llegó al servidor. El
    escritorio vende sin conexión y sube las ventas al sincronizar: sin este dato
    la IA daría por completas unas cifras a las que les faltan ventas en camino."""
    if not _existe(cur, 'pos_desktop_sales') or 'received_at' not in _columnas(cur, 'pos_desktop_sales'):
        return None
    cur.execute("SELECT MAX(received_at) AS u FROM pos_desktop_sales")
    u = cur.fetchone()['u']
    return u.isoformat(sep=' ', timespec='minutes') if u else None


def ventas_periodo(periodo='hoy', **_):
    """Ventas del período (web pagados + POS mostrador + POS escritorio).
    Incluye SIEMPRE el total histórico para no confundir cuando el período
    pedido da 0 (p. ej. preguntan 'este mes' pero las ventas fueron antes)."""
    p = _periodo(periodo)
    fweb = _sql_periodo(p, 'fecha_creacion')
    fpos = _sql_periodo(p, 'fecha')
    fdesk = _sql_periodo(p, 'created_at_local')
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
        escritorio = _escritorio_sincronizado_hasta(cur)
    res = {
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
    if escritorio:
        res['ventas_escritorio_recibidas_hasta'] = escritorio
    return res


def top_productos(periodo='todo', limite=5, **_):
    """Productos más vendidos (web + POS) por unidades. Por defecto histórico."""
    p = _periodo(periodo)
    lim = max(1, min(int(limite or 5), 20))
    fweb = _sql_periodo(p, 'p.fecha_creacion')
    fpos = _sql_periodo(p, 'v.fecha')
    fdesk = _sql_periodo(p, 's.created_at_local')
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
    # Si el período pedido no tiene ventas, cae al histórico (más útil que "vacío").
    if not filas and p != 'todo':
        res = top_productos('todo', limite)
        res['nota'] = f"No hubo ventas {_label_periodo(p)}; muestro el histórico."
        return res
    return {'periodo': _label_periodo(p),
            'productos': [{'nombre': r['nombre'], 'unidades': int(r['unidades'])} for r in filas]}


def kpis_dashboard():
    """KPIs puros para el dashboard admin (consultas directas, SIN LLM):
    ventas de hoy y de la semana (3 canales), pedidos por despachar y
    productos con stock bajo. No es herramienta del chat: lo usa la vista."""
    with get_db_cursor(dict_cursor=True) as cur:
        hoy_n, hoy_t, _d = _ventas_en(
            cur, _sql_periodo('hoy', 'fecha_creacion'),
            _sql_periodo('hoy', 'fecha'),
            _sql_periodo('hoy', 'created_at_local'))
        sem_n, sem_t, _d = _ventas_en(
            cur, _sql_periodo('semana', 'fecha_creacion'),
            _sql_periodo('semana', 'fecha'),
            _sql_periodo('semana', 'created_at_local'))
        cur.execute("""SELECT COUNT(*) n FROM pedidos WHERE estado_pago='APROBADO'
                       AND estado_envio IN ('POR_DESPACHAR','PENDIENTE')""")
        despachar = cur.fetchone()['n']
        cur.execute("SELECT COUNT(*) n FROM productos WHERE stock <= 5")
        stock_bajo = cur.fetchone()['n']
    return {
        'ventas_hoy_n': hoy_n, 'ventas_hoy': formatear_moneda(hoy_t),
        'ventas_semana_n': sem_n, 'ventas_semana': formatear_moneda(sem_t),
        'por_despachar': int(despachar), 'stock_bajo': int(stock_bajo),
    }


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


# ── Análisis estadístico (tendencias y segmentos) ──────────────
# Las cifras las calcula services/estadistica.py (Python determinista); la IA
# solo las explica. Cada resultado trae 'confiabilidad' para que la respuesta
# no afirme más de lo que los datos sostienen.
_DIAS_SEMANA = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']


def _analizar_tendencia(por_dia, hoy, dias):
    """Análisis puro (sin BD) de la serie diaria de ventas. `por_dia` =
    {fecha: total}. Separado de la consulta para poder probarlo."""
    from datetime import timedelta
    from services import estadistica as est

    if not por_dia:
        return {'confiabilidad': 'insuficiente',
                'conclusion': f'No hay ventas registradas en los últimos {dias} días.'}
    # La serie empieza en la primera venta del período: si el negocio arrancó
    # hace poco, los ceros de antes inventarían una tendencia al alza.
    inicio = max(min(por_dia), hoy - timedelta(days=dias))
    fechas = [inicio + timedelta(days=i) for i in range((hoy - inicio).days)]
    ys = [float(por_dia.get(f, 0.0)) for f in fechas]
    dias_con_ventas = sum(1 for y in ys if y > 0)
    base = {'dias_analizados': len(ys), 'dias_con_ventas': dias_con_ventas,
            'desde': fechas[0].isoformat() if fechas else None}
    if len(ys) < 14 or dias_con_ventas < 7:
        return {**base, 'confiabilidad': 'insuficiente',
                'conclusion': ('Aún no hay suficientes días con ventas para medir una tendencia '
                               '(se necesitan al menos 14 días y 7 con ventas).')}

    reg = est.regresion_lineal(list(range(len(ys))), ys)
    promedio = sum(ys) / len(ys)
    r2 = reg['r2']
    cambio_semanal = reg['pendiente'] * 7
    pct_semanal = (cambio_semanal / promedio * 100) if promedio > 0 else 0.0
    direccion = 'estable' if abs(pct_semanal) < 2 else ('al alza' if pct_semanal > 0 else 'a la baja')

    if r2 >= 0.5:
        confiabilidad = 'alta'
        conclusion = (f'Tendencia confiable {direccion}: la recta explica el {r2:.0%} de la '
                      f'variación de las ventas diarias (R² = {r2:.2f}).')
    elif r2 >= 0.25:
        confiabilidad = 'media'
        conclusion = (f'Hay una tendencia {direccion} pero débil (R² = {r2:.2f}): las ventas '
                      f'varían mucho de un día a otro; tómala con cautela.')
    else:
        confiabilidad = 'baja'
        conclusion = (f'No hay una tendencia clara (R² = {r2:.2f}): las ventas suben y bajan '
                      f'sin una dirección definida. No conviene proyectar.')

    proyeccion = None
    if confiabilidad == 'alta':
        n = len(ys)
        proyeccion = formatear_moneda(sum(max(0.0, reg['intercepto'] + reg['pendiente'] * (n + i))
                                          for i in range(7)))

    # Día de la semana (promedio, incluye días sin venta): patrón descriptivo.
    por_dia_semana = {}
    for f, y in zip(fechas, ys):
        por_dia_semana.setdefault(f.weekday(), []).append(y)
    promedios = {d: sum(v) / len(v) for d, v in por_dia_semana.items() if len(v) >= 2}
    mejor = max(promedios, key=promedios.get) if promedios else None
    peor = min(promedios, key=promedios.get) if promedios else None

    ultimos7, previos7 = sum(ys[-7:]), sum(ys[-14:-7])
    return {
        **base,
        'promedio_diario': formatear_moneda(promedio),
        'direccion': direccion,
        'cambio_semanal_del_promedio_diario': f'{pct_semanal:+.1f}%',
        'r2': round(r2, 2),
        'confiabilidad': confiabilidad,
        'conclusion': conclusion,
        'proyeccion_7_dias': proyeccion,
        'nota_proyeccion': (None if proyeccion else
                            'Sin proyección: solo se proyecta cuando la tendencia es confiable (R² ≥ 0.5).'),
        'mejor_dia_semana': _DIAS_SEMANA[mejor] if mejor is not None else None,
        'peor_dia_semana': _DIAS_SEMANA[peor] if peor is not None else None,
        'ultimos_7_dias': formatear_moneda(ultimos7),
        '7_dias_anteriores': formatear_moneda(previos7),
        'metodo': 'Regresión lineal sobre las ventas diarias de los 3 canales (web, POS y escritorio).',
    }


def tendencia_ventas(dias=90, **_):
    """Tendencia de las ventas diarias (3 canales) con R² y proyección solo si
    es confiable. Consulta SOLO la BD del tenant actual."""
    d = max(28, min(int(dias or 90), 365))
    with get_db_cursor(dict_cursor=True) as cur:
        partes = [f"""SELECT DATE(fecha_creacion) d, monto_total t FROM pedidos
                      WHERE {_PEDIDO_PAGADO} AND fecha_creacion >= CURRENT_DATE - INTERVAL '{d} days'"""]
        if _existe(cur, 'ventas_pos'):
            partes.append(f"""SELECT DATE(fecha) d, total t FROM ventas_pos
                WHERE COALESCE(estado,'completada') <> 'anulada'
                  AND fecha >= CURRENT_DATE - INTERVAL '{d} days'""")
        if _existe(cur, 'pos_desktop_sales'):
            partes.append(f"""SELECT DATE(created_at_local) d, total t FROM pos_desktop_sales
                WHERE created_at_local >= CURRENT_DATE - INTERVAL '{d} days'""")
        # El día en curso va incompleto: excluirlo evita una falsa caída al final.
        cur.execute("SELECT d, SUM(t) total FROM (" + " UNION ALL ".join(partes) +
                    ") x WHERE d < CURRENT_DATE GROUP BY d")
        por_dia = {r['d']: float(r['total'] or 0) for r in cur.fetchall()}
        cur.execute("SELECT CURRENT_DATE AS hoy")
        hoy = cur.fetchone()['hoy']
    return _analizar_tendencia(por_dia, hoy, d)


def patron_horario(periodo='mes', **_):
    """A qué horas y qué días vende más (los 3 canales). Sirve para decidir
    turnos, promociones en horas flojas y horarios de atención."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        partes = [f"""SELECT fecha_creacion AS f, monto_total AS t FROM pedidos
                      WHERE {_PEDIDO_PAGADO} AND {_sql_periodo(p, 'fecha_creacion')}"""]
        if _existe(cur, 'ventas_pos'):
            partes.append(f"""SELECT fecha AS f, total AS t FROM ventas_pos
                WHERE COALESCE(estado,'completada') <> 'anulada' AND {_sql_periodo(p, 'fecha')}""")
        if _existe(cur, 'pos_desktop_sales'):
            partes.append(f"""SELECT created_at_local AS f, total AS t FROM pos_desktop_sales
                WHERE {_sql_periodo(p, 'created_at_local')}""")
        union = " UNION ALL ".join(partes)
        cur.execute("SELECT EXTRACT(HOUR FROM f)::int AS hora, COUNT(*) n, COALESCE(SUM(t),0) total "
                    f"FROM ({union}) x GROUP BY 1 ORDER BY 1")
        horas = [{'hora': f"{r['hora']:02d}:00", 'ventas': int(r['n']),
                  'monto': formatear_moneda(float(r['total'])), '_t': float(r['total'])}
                 for r in cur.fetchall()]
        cur.execute("SELECT EXTRACT(ISODOW FROM f)::int AS dia, COUNT(*) n, COALESCE(SUM(t),0) total "
                    f"FROM ({union}) x GROUP BY 1 ORDER BY 1")
        dias = [{'dia': _DIAS_SEMANA[r['dia'] - 1], 'ventas': int(r['n']),
                 'monto': formatear_moneda(float(r['total'])), '_t': float(r['total'])}
                for r in cur.fetchall()]
    if not horas:
        return {'periodo': _label_periodo(p), 'confiabilidad': 'insuficiente',
                'conclusion': 'No hubo ventas en ese período.'}
    mejores = sorted(horas, key=lambda h: -h['_t'])[:3]
    mejor_dia = max(dias, key=lambda d: d['_t'])
    peor_dia = min(dias, key=lambda d: d['_t'])
    limpiar = [{k: v for k, v in x.items() if k != '_t'} for x in horas]
    return {
        'periodo': _label_periodo(p),
        'por_hora': limpiar,
        'horas_de_mayor_venta': [{k: v for k, v in h.items() if k != '_t'} for h in mejores],
        'por_dia_de_la_semana': [{k: v for k, v in d.items() if k != '_t'} for d in dias],
        'mejor_dia': mejor_dia['dia'], 'peor_dia': peor_dia['dia'],
        'nota': 'Se usa la hora de la venta en los 3 canales (web, mostrador y escritorio).',
    }


_CLAVES_ANONIMAS = {'mostrador', 'consumidor final', 'sin nombre', 'cliente', 'cliente mostrador',
                    'general', 'varios', '222222222222', '0'}


def _analizar_segmentos(clientes, hoy):
    """Análisis puro (sin BD). `clientes` = [(ultima_fecha, compras, total)].
    Segmenta por RFM (recencia, frecuencia, monto) con k-means; k por el método
    del codo. Devuelve SOLO agregados: ningún dato personal."""
    import math
    from services import estadistica as est

    n = len(clientes)
    if n < 12:
        return {'clientes_identificados': n, 'confiabilidad': 'insuficiente',
                'conclusion': ('Se necesitan al menos 12 clientes identificados (con documento, correo '
                               f'o nombre en sus compras) para agruparlos con confianza; hay {n}.')}

    recencia = [max(0, (hoy - (u.date() if hasattr(u, 'date') else u)).days) for u, _, _ in clientes]
    compras = [int(c) for _, c, _ in clientes]
    montos = [float(m) for _, _, m in clientes]
    # log1p: frecuencia y monto tienen colas largas (pocos clientes muy grandes)
    puntos = est.estandarizar([[r, math.log1p(c), math.log1p(m)]
                               for r, c, m in zip(recencia, compras, montos)])

    k_max = max(3, min(6, n // 4))
    modelos = {k: est.kmeans(puntos, k) for k in range(1, k_max + 1)}
    inercias = {k: m['inercia'] for k, m in modelos.items()}
    k_codo = max(2, est.elegir_k_codo(inercias))
    # El codo solo tiende a quedarse corto cuando la primera caída de la inercia
    # es muy grande (aplana el resto de la curva). Se valida con la silueta entre
    # sus vecinos y se elige el k que mejor separa; empate → el menor.
    siluetas = {}
    if n <= 2000:
        for kk in sorted({k_codo - 1, k_codo, k_codo + 1}):
            if 2 <= kk <= k_max:
                siluetas[kk] = est.silueta(puntos, modelos[kk]['etiquetas'])
    validas = {kk: s for kk, s in siluetas.items() if s is not None}
    k = max(validas, key=lambda kk: (round(validas[kk], 3), -kk)) if validas else k_codo
    etiquetas = modelos[k]['etiquetas']
    sil = validas.get(k)

    # Umbrales para nombrar los grupos. No se usa la mediana de compras: si la
    # mayoría compró una sola vez da 1 y "frecuente" sería verdadero para todos.
    med_r = est.mediana(recencia)
    media_c = sum(compras) / n
    media_m = sum(montos) / n
    umbral_reciente = max(med_r, 30)          # ≤ 30 días siempre cuenta como reciente
    umbral_frecuente = max(2.0, media_c)      # más de una compra y sobre el promedio
    total_ventas = sum(montos) or 1.0
    segmentos, usados = [], {}
    for g in range(k):
        idx = [i for i, e in enumerate(etiquetas) if e == g]
        if not idx:
            continue
        r_g = est.mediana([recencia[i] for i in idx])
        c_g = sum(compras[i] for i in idx) / len(idx)
        m_g = est.mediana([montos[i] for i in idx])
        reciente, frecuente, alto = r_g <= umbral_reciente, c_g >= umbral_frecuente, m_g >= media_m
        if reciente and frecuente and alto:
            nombre, accion = 'Clientes fieles (VIP)', 'Cuídalos: atención preferente, beneficios o preventas.'
        elif reciente and not frecuente:
            nombre, accion = 'Nuevos o recientes', 'Invítalos a una segunda compra con un incentivo.'
        elif not reciente and (frecuente or alto):
            nombre, accion = 'En riesgo (compraban y dejaron de venir)', 'Contáctalos con una oferta de regreso.'
        elif not reciente:
            nombre, accion = 'Ocasionales o inactivos', 'Campañas masivas de bajo costo.'
        else:
            nombre, accion = 'Regulares', 'Mantén el contacto y ofrece novedades.'
        usados[nombre] = usados.get(nombre, 0) + 1
        if usados[nombre] > 1:
            nombre = f'{nombre} (grupo {usados[nombre]})'
        ventas_g = sum(montos[i] for i in idx)
        segmentos.append({
            'segmento': nombre,
            'clientes': len(idx),
            'porcentaje_clientes': f'{len(idx) / n:.0%}',
            'porcentaje_ventas': f'{ventas_g / total_ventas:.0%}',
            'compras_promedio': round(c_g, 1),
            'ticket_promedio': formatear_moneda(ventas_g / max(1, sum(compras[i] for i in idx))),
            'dias_desde_ultima_compra_mediana': int(r_g),
            'accion_sugerida': accion,
        })
    segmentos.sort(key=lambda s: -int(s['porcentaje_ventas'].rstrip('%')))

    if sil is None:
        confiabilidad, conclusion = 'media', 'Segmentación calculada (demasiados clientes para medir la separación).'
    elif sil >= 0.5:
        confiabilidad, conclusion = 'alta', f'Los grupos están bien diferenciados (silueta = {sil:.2f}).'
    elif sil >= 0.25:
        confiabilidad, conclusion = 'media', f'Los grupos se distinguen, con algo de solapamiento (silueta = {sil:.2f}).'
    else:
        confiabilidad, conclusion = 'baja', (f'Los clientes se parecen mucho entre sí (silueta = {sil:.2f}): '
                                             'los grupos son orientativos.')
    return {
        'clientes_identificados': n,
        'segmentos': segmentos,
        'confiabilidad': confiabilidad,
        'conclusion': conclusion,
        'metodo': {
            'algoritmo': 'k-means sobre recencia, frecuencia y monto (RFM) estandarizados',
            'k_elegido': k,
            'criterio_k': 'método del codo sobre la inercia, validado con la silueta',
            'k_por_codo': k_codo,
            'inercia_por_k': {str(kk): round(v, 1) for kk, v in inercias.items()},
            'silueta_por_k': {str(kk): round(v, 2) for kk, v in validas.items()},
            'silueta': round(sil, 2) if sil is not None else None,
            'nota': 'Clientes identificados por documento, correo o nombre en sus compras; no se exponen datos personales.',
        },
    }


def segmentos_clientes(**_):
    """Segmentación de clientes (RFM + k-means + codo). SOLO BD del tenant."""
    fuentes = [('pedidos', 'fecha_creacion', 'monto_total', _PEDIDO_PAGADO)]
    with get_db_cursor(dict_cursor=True) as cur:
        if _existe(cur, 'ventas_pos'):
            fuentes.append(('ventas_pos', 'fecha', 'total', "COALESCE(estado,'completada') <> 'anulada'"))
        partes = []
        for tabla, col_fecha, col_monto, filtro in fuentes:
            cols = _columnas(cur, tabla)
            claves = []
            if 'cliente_documento' in cols:
                claves.append(r"NULLIF(REGEXP_REPLACE(cliente_documento, '\D', '', 'g'), '')")
            if 'cliente_email' in cols:
                claves.append("NULLIF(LOWER(TRIM(cliente_email)), '')")
            if 'cliente_nombre' in cols:
                claves.append("NULLIF(LOWER(TRIM(cliente_nombre)), '')")
            if claves:
                partes.append(f"SELECT COALESCE({', '.join(claves)}) clave, {col_fecha} fecha, "
                              f"{col_monto} monto FROM {tabla} WHERE {filtro}")
        if not partes:
            return _analizar_segmentos([], None)
        anonimas = ", ".join("'" + c + "'" for c in sorted(_CLAVES_ANONIMAS))
        cur.execute("SELECT MAX(fecha) ultima, COUNT(*) compras, SUM(monto) total FROM (" +
                    " UNION ALL ".join(partes) + f") x WHERE clave IS NOT NULL AND clave NOT IN ({anonimas}) "
                    "AND monto > 0 GROUP BY clave")
        clientes = [(r['ultima'], r['compras'], float(r['total'] or 0)) for r in cur.fetchall()]
        cur.execute("SELECT CURRENT_DATE AS hoy")
        hoy = cur.fetchone()['hoy']
    return _analizar_segmentos(clientes, hoy)
