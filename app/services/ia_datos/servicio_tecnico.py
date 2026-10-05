"""Servicio Técnico para el asistente del panel: el taller en preguntas.

Consultas de SOLO LECTURA sobre las tablas st_* del módulo. Reglas:
  - Nunca devuelven la clave de desbloqueo (ni cifrada) ni el token público.
  - Las que nombran clientes llevan extra nube=False al registrarse: esos
    datos personales no se redactan con el respaldo en la nube.
  - `taller_desempeno` solo da agregados (sin nombres): puede ir a la nube.
  - Si el negocio no tiene las tablas, responden con una conclusión clara.
"""

import re
from datetime import date

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import _existe, _label_periodo, _periodo, _sql_periodo

_NOMBRE_ESTADO = {
    'recibido': 'Recibido', 'diagnostico': 'En diagnóstico', 'cotizado': 'Cotizado (esperando respuesta)',
    'aprobado': 'Aprobado', 'reparacion': 'En reparación', 'listo': 'Listo para entregar',
    'entregado': 'Entregado', 'garantia': 'En garantía', 'cancelado': 'Cancelado',
}
_ABIERTOS = ['recibido', 'diagnostico', 'cotizado', 'aprobado', 'reparacion', 'listo', 'garantia']
_SIN_MODULO = {'confiabilidad': 'insuficiente',
               'conclusion': 'Este negocio todavía no usa el módulo de Servicio Técnico.'}


def _tipo(codigo):
    from services.servicio_tecnico_tipos import nombre
    return nombre(codigo)


def _equipo(r):
    return ' '.join(p for p in (_tipo(r.get('tipo')), r.get('marca'), r.get('modelo')) if p)


def _dinero(v):
    return formatear_moneda(float(v)) if v is not None else None


def _limite(limite, defecto, tope):
    try:
        return max(1, min(int(limite or defecto), tope))
    except (TypeError, ValueError):
        return defecto


# ── 1. ¿Cómo está el taller? ────────────────────────────────────
def taller_estado(limite=15, **_):
    """Equipos en el taller ahora: por estado, listos sin entregar, entregas
    prometidas vencidas, sin técnico y carga por técnico."""
    limite = _limite(limite, 15, 40)
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'st_ordenes'):
            return _SIN_MODULO
        cur.execute("SELECT estado, COUNT(*) AS n FROM st_ordenes WHERE estado = ANY(%s) GROUP BY estado",
                    (_ABIERTOS,))
        por_estado = {r['estado']: int(r['n']) for r in cur.fetchall()}
        cur.execute("""
            SELECT o.numero, o.estado, o.fecha_recibido, o.fecha_promesa, o.fecha_listo, o.valor_estimado,
                   e.tipo, e.marca, e.modelo, c.nombre AS cliente, u.nombre AS tecnico,
                   (CURRENT_DATE - o.fecha_recibido::date) AS dias_en_taller,
                   (CURRENT_DATE - o.fecha_listo::date) AS dias_listo
            FROM st_ordenes o
            JOIN st_equipos e ON e.id = o.equipo_id
            LEFT JOIN crm_contactos c ON c.id = o.crm_contacto_id
            LEFT JOIN usuarios u ON u.id = o.tecnico_id
            WHERE o.estado = ANY(%s)
            ORDER BY (o.estado = 'listo') DESC, o.fecha_promesa NULLS LAST, o.fecha_recibido
            LIMIT %s""", (_ABIERTOS, limite))
        filas = cur.fetchall()
        cur.execute("""SELECT COALESCE(u.nombre, 'Sin asignar') AS tecnico, COUNT(*) AS n
                       FROM st_ordenes o LEFT JOIN usuarios u ON u.id = o.tecnico_id
                       WHERE o.estado = ANY(%s) AND o.estado <> 'listo' GROUP BY 1 ORDER BY 2 DESC""",
                    (_ABIERTOS,))
        carga = {r['tecnico']: int(r['n']) for r in cur.fetchall()}
    total = sum(por_estado.values())
    if not total:
        return {'equipos_en_taller': 0, 'conclusion': 'No hay equipos en el taller en este momento.'}
    hoy = date.today()
    ordenes = [{
        'orden': f['numero'], 'estado': _NOMBRE_ESTADO.get(f['estado'], f['estado']),
        'equipo': _equipo(f), 'cliente': f['cliente'], 'tecnico': f['tecnico'] or 'Sin asignar',
        'dias_en_taller': int(f['dias_en_taller'] or 0),
        'prometido_para': str(f['fecha_promesa']) if f['fecha_promesa'] else None,
        'promesa_vencida': bool(f['fecha_promesa'] and f['fecha_promesa'] < hoy and f['estado'] != 'listo'),
        'dias_listo_sin_recoger': int(f['dias_listo']) if f['estado'] == 'listo' and f['dias_listo'] is not None else None,
    } for f in filas]
    vencidas = [o['orden'] for o in ordenes if o['promesa_vencida']]
    listos = por_estado.get('listo', 0)
    return {
        'equipos_en_taller': total,
        'por_estado': {_NOMBRE_ESTADO[k]: v for k, v in por_estado.items()},
        'listos_para_entregar': listos,
        'esperando_respuesta_de_cotizacion': por_estado.get('cotizado', 0),
        'promesas_vencidas': vencidas,
        'carga_por_tecnico': carga,
        'ordenes': ordenes,
        'nota': (f'{len(vencidas)} orden(es) pasaron la fecha prometida al cliente.' if vencidas else None),
    }


# ── 2. ¿A quién hay que contactar? ──────────────────────────────
def taller_seguimientos(limite=20, **_):
    """Seguimientos del taller para hoy o atrasados (la bandeja «Hoy»):
    cotizaciones sin respuesta, equipos listos sin recoger, preguntar cómo le
    fue, garantías, mantenimientos y calificaciones bajas."""
    limite = _limite(limite, 20, 50)
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'st_seguimientos'):
            return _SIN_MODULO
        cur.execute("""
            SELECT s.tipo, s.fecha_programada, o.numero, e.tipo AS equipo_tipo, e.marca, e.modelo,
                   COALESCE(c.nombre, ct.cliente_nombre) AS cliente, ct.total AS cotizacion_total,
                   (CURRENT_DATE - s.fecha_programada) AS dias_atraso
            FROM st_seguimientos s
            LEFT JOIN st_ordenes o ON o.id = s.orden_id
            LEFT JOIN st_equipos e ON e.id = COALESCE(s.equipo_id, o.equipo_id)
            LEFT JOIN crm_contactos c ON c.id = COALESCE(s.crm_contacto_id, o.crm_contacto_id)
            LEFT JOIN cotizaciones ct ON ct.id = s.cotizacion_id
            WHERE s.estado = 'pendiente' AND s.fecha_programada <= CURRENT_DATE
            ORDER BY (s.tipo = 'calificacion_baja') DESC, s.fecha_programada
            LIMIT %s""", (limite,))
        filas = cur.fetchall()
        cur.execute("""SELECT COUNT(*) AS n FROM st_seguimientos
                       WHERE estado = 'pendiente' AND fecha_programada BETWEEN CURRENT_DATE + 1 AND CURRENT_DATE + 7""")
        proximos = int(cur.fetchone()['n'])
    from services.servicio_tecnico_seguimiento import TIPOS
    if not filas:
        return {'seguimientos_para_hoy': 0, 'proximos_7_dias': proximos,
                'conclusion': 'No hay seguimientos del taller pendientes para hoy.'}
    lista = [{
        'que_hacer': TIPOS.get(f['tipo'], (f['tipo'],))[0],
        'cliente': f['cliente'], 'orden': f['numero'],
        'equipo': _equipo({'tipo': f['equipo_tipo'], 'marca': f['marca'], 'modelo': f['modelo']}) if f['equipo_tipo'] else None,
        'valor_cotizado': _dinero(f['cotizacion_total']) if f['tipo'] == 'cotizacion_sin_respuesta' else None,
        'dias_de_atraso': int(f['dias_atraso'] or 0),
        'urgente': f['tipo'] == 'calificacion_baja',
    } for f in filas]
    urgentes = sum(1 for x in lista if x['urgente'])
    return {
        'seguimientos_para_hoy': len(lista), 'proximos_7_dias': proximos, 'seguimientos': lista,
        'nota': (f'{urgentes} cliente(s) calificaron mal el servicio: conviene llamarlos primero.' if urgentes else
                 'Se atienden desde Servicio Técnico → Hoy (WhatsApp con el mensaje listo, correo o llamada).'),
    }


# ── 3. Una orden ────────────────────────────────────────────────
def taller_orden(texto='', **_):
    """Detalle de UNA orden por su número (OS-000012 o 12) o, si no, las
    órdenes más recientes de ese cliente."""
    texto = (texto or '').strip()
    if not texto:
        return {'conclusion': 'Dime el número de la orden (por ejemplo OS-000012) o el nombre del cliente.'}
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'st_ordenes'):
            return _SIN_MODULO
        base = """SELECT o.id, o.numero, o.estado, o.falla_reportada, o.diagnostico, o.estado_fisico, o.accesorios,
                         o.valor_estimado, o.valor_final, o.fecha_recibido, o.fecha_promesa, o.fecha_listo,
                         o.fecha_entregado, o.garantia_hasta, o.cotizacion_id,
                         e.tipo, e.marca, e.modelo, e.serial, c.nombre AS cliente, u.nombre AS tecnico
                  FROM st_ordenes o JOIN st_equipos e ON e.id = o.equipo_id
                  LEFT JOIN crm_contactos c ON c.id = o.crm_contacto_id
                  LEFT JOIN usuarios u ON u.id = o.tecnico_id"""
        m = re.search(r'(?:os[\s-]*)?0*(\d{1,7})\b', texto, re.I)
        filas = []
        if m and (texto.upper().startswith('OS') or texto.strip('#nº° ').isdigit()):
            cur.execute(base + ' WHERE o.id = %s', (int(m.group(1)),))
            filas = cur.fetchall()
        if not filas:
            cur.execute(base + ' WHERE lower(c.nombre) LIKE %s ORDER BY o.id DESC LIMIT 5',
                        (f'%{texto.lower()}%',))
            filas = cur.fetchall()
        if not filas:
            return {'conclusion': f'No encontré órdenes con «{texto}».'}
        detalle = []
        for f in filas:
            cur.execute("""SELECT tipo, detalle, creado_en FROM st_eventos
                           WHERE orden_id = %s AND tipo <> 'clave' ORDER BY creado_en DESC LIMIT 5""", (f['id'],))
            bitacora = [{'cuando': e['creado_en'].strftime('%d/%m/%Y %H:%M'), 'que': e['detalle']}
                        for e in cur.fetchall()]
            detalle.append({
                'orden': f['numero'], 'estado': _NOMBRE_ESTADO.get(f['estado'], f['estado']),
                'cliente': f['cliente'], 'equipo': _equipo(f), 'serial': f['serial'],
                'falla_reportada': f['falla_reportada'], 'diagnostico': f['diagnostico'],
                'estado_fisico': f['estado_fisico'], 'accesorios': f['accesorios'],
                'tecnico': f['tecnico'] or 'Sin asignar',
                'valor_estimado': _dinero(f['valor_estimado']), 'valor_cobrado': _dinero(f['valor_final']),
                'recibido': f['fecha_recibido'].strftime('%d/%m/%Y'),
                'prometido': str(f['fecha_promesa']) if f['fecha_promesa'] else None,
                'entregado': f['fecha_entregado'].strftime('%d/%m/%Y') if f['fecha_entregado'] else None,
                'garantia_hasta': str(f['garantia_hasta']) if f['garantia_hasta'] else None,
                'tiene_cotizacion': bool(f['cotizacion_id']),
                'ultimos_movimientos': bitacora,
            })
    return {'ordenes_encontradas': len(detalle), 'ordenes': detalle}


# ── 4. Equipos de un cliente / por serial o IMEI ────────────────
def taller_equipo_historial(texto='', **_):
    """Equipos de UN cliente (por nombre) o el equipo con ese serial o IMEI:
    características, piezas cambiadas, próximas revisiones e historial de servicios."""
    texto = (texto or '').strip()
    if not texto:
        return {'conclusion': 'Dime el nombre del cliente, el serial o el IMEI del equipo.'}
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'st_equipos'):
            return _SIN_MODULO
        digitos = re.sub(r'\D', '', texto)
        cur.execute("""
            SELECT e.id, e.tipo, e.marca, e.modelo, e.serial, e.imei, e.procesador, e.ram, e.almacenamiento,
                   e.sistema_operativo, e.extras, e.resumen_ia, e.sugerencias_ia, c.nombre AS cliente
            FROM st_equipos e LEFT JOIN crm_contactos c ON c.id = e.crm_contacto_id
            WHERE e.activo AND (lower(COALESCE(e.serial, '')) = lower(%s)
                                OR (%s <> '' AND e.imei = %s)
                                OR lower(COALESCE(c.nombre, '')) LIKE %s)
            ORDER BY e.actualizado_en DESC LIMIT 8""",
                    (texto, digitos if len(digitos) == 15 else '', digitos, f'%{texto.lower()}%'))
        equipos = cur.fetchall()
        if not equipos:
            return {'conclusion': f'No encontré equipos con «{texto}».'}
        salida = []
        for e in equipos:
            cur.execute("""SELECT numero, estado, falla_reportada, fecha_recibido, valor_final
                           FROM st_ordenes WHERE equipo_id = %s ORDER BY id DESC LIMIT 10""", (e['id'],))
            ordenes = [{'orden': o['numero'], 'estado': _NOMBRE_ESTADO.get(o['estado'], o['estado']),
                        'falla': (o['falla_reportada'] or '')[:160], 'recibido': o['fecha_recibido'].strftime('%d/%m/%Y'),
                        'cobrado': _dinero(o['valor_final'])} for o in cur.fetchall()]
            cur.execute("""SELECT componente, detalle, fecha, proxima_revision FROM st_cambios
                           WHERE equipo_id = %s ORDER BY fecha DESC LIMIT 10""", (e['id'],))
            piezas = [{'pieza': p['componente'], 'detalle': p['detalle'], 'fecha': str(p['fecha']),
                       'proxima_revision': str(p['proxima_revision']) if p['proxima_revision'] else None}
                      for p in cur.fetchall()]
            caracteristicas = {k: e[k] for k in ('procesador', 'ram', 'almacenamiento', 'sistema_operativo') if e[k]}
            caracteristicas.update({k: v for k, v in (e['extras'] or {}).items() if v})
            salida.append({
                'equipo': _equipo(e), 'cliente': e['cliente'], 'serial': e['serial'], 'imei': e['imei'],
                'caracteristicas': caracteristicas, 'resumen': e['resumen_ia'],
                'mejoras_sugeridas': [s.get('titulo') for s in (e['sugerencias_ia'] or []) if isinstance(s, dict)],
                'servicios': ordenes, 'piezas_cambiadas': piezas,
            })
    return {'equipos_encontrados': len(salida), 'equipos': salida}


# ── 5. Desempeño del taller (solo agregados) ────────────────────
def taller_desempeno(periodo='mes', **_):
    """Cómo le fue al taller en un período: órdenes recibidas y entregadas,
    tiempo de reparación, lo cobrado, equipos más atendidos, aprobación de
    cotizaciones y satisfacción de los clientes."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'st_ordenes'):
            return _SIN_MODULO
        recibidas_sql = _sql_periodo(p, 'o.fecha_recibido')
        entregadas_sql = _sql_periodo(p, 'o.fecha_entregado')
        cur.execute(f"SELECT COUNT(*) AS n FROM st_ordenes o WHERE {recibidas_sql}")
        recibidas = int(cur.fetchone()['n'])
        cur.execute(f"""SELECT COUNT(*) AS n, COALESCE(SUM(o.valor_final), 0) AS cobrado,
                               AVG(EXTRACT(EPOCH FROM (o.fecha_entregado - o.fecha_recibido)) / 86400) AS dias
                        FROM st_ordenes o WHERE o.estado IN ('entregado', 'garantia')
                          AND o.fecha_entregado IS NOT NULL AND {entregadas_sql}""")
        r = cur.fetchone()
        entregadas, cobrado, dias = int(r['n']), float(r['cobrado'] or 0), r['dias']
        cur.execute(f"""SELECT e.tipo, COUNT(*) AS n FROM st_ordenes o JOIN st_equipos e ON e.id = o.equipo_id
                        WHERE {recibidas_sql} GROUP BY e.tipo ORDER BY 2 DESC LIMIT 5""")
        por_tipo = {_tipo(x['tipo']): int(x['n']) for x in cur.fetchall()}
        cur.execute(f"""SELECT COUNT(*) FILTER (WHERE o.cotizacion_id IS NOT NULL) AS cotizadas,
                               COUNT(*) FILTER (WHERE o.cotizacion_id IS NOT NULL
                                                AND o.estado IN ('aprobado','reparacion','listo','entregado','garantia')) AS aprobadas,
                               COUNT(*) FILTER (WHERE o.estado = 'cancelado') AS canceladas,
                               COUNT(*) FILTER (WHERE o.estado = 'garantia') AS en_garantia
                        FROM st_ordenes o WHERE {recibidas_sql}""")
        q = cur.fetchone()
        calif = {'respuestas': 0}
        if _existe(cur, 'st_seguimientos'):
            cur.execute(f"""SELECT COUNT(*) AS n, AVG(s.calificacion) AS prom,
                                   COUNT(*) FILTER (WHERE s.calificacion <= 3) AS bajas
                            FROM st_seguimientos s
                            WHERE s.tipo = 'satisfaccion' AND s.calificacion IS NOT NULL
                              AND {_sql_periodo(p, 's.hecho_en')}""")
            c = cur.fetchone()
            calif = {'respuestas': int(c['n']), 'promedio_estrellas': round(float(c['prom']), 1) if c['prom'] else None,
                     'calificaciones_bajas': int(c['bajas'])}
    cotizadas, aprobadas = int(q['cotizadas']), int(q['aprobadas'])
    pocos = recibidas + entregadas < 5
    return {
        'periodo': _label_periodo(p),
        'ordenes_recibidas': recibidas, 'equipos_entregados': entregadas,
        'cobrado_en_entregas': formatear_moneda(cobrado),
        'ticket_promedio_por_equipo': formatear_moneda(cobrado / entregadas) if entregadas else None,
        'dias_promedio_de_reparacion': round(float(dias), 1) if dias is not None else None,
        'equipos_mas_atendidos': por_tipo,
        'cotizaciones_del_taller': cotizadas,
        'tasa_aprobacion_cotizaciones': f'{aprobadas / cotizadas * 100:.0f}%' if cotizadas else None,
        'ordenes_canceladas': int(q['canceladas']), 'reingresos_por_garantia': int(q['en_garantia']),
        'satisfaccion': calif,
        'confiabilidad': 'baja' if pocos else 'normal',
        'nota': 'Hay pocas órdenes en el período: las cifras sirven de referencia, no de tendencia.' if pocos else None,
    }
