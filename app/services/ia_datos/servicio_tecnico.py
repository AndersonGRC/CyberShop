"""Servicio Técnico para el asistente del panel: el taller en preguntas.

Consultas de SOLO LECTURA sobre las tablas st_* del módulo. Reglas:
  - Nunca devuelven la clave de desbloqueo (ni cifrada) ni el token público.
  - Las que nombran clientes llevan extra nube=False al registrarse: esos
    datos personales no se redactan con el respaldo en la nube.
  - `taller_desempeno` solo da agregados (sin nombres): puede ir a la nube.
  - Si el negocio no tiene las tablas, responden con una conclusión clara.
"""

import calendar
import re
from datetime import date, timedelta

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import Rango, _existe, _label_periodo, _periodo, _sql_periodo

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
        con_motivo = 'motivo' in _columnas_de(cur, 'st_seguimientos')
        cur.execute(f"""
            SELECT s.tipo, s.fecha_programada, s.canal, o.numero, e.tipo AS equipo_tipo, e.marca, e.modelo,
                   {'s.motivo' if con_motivo else 'NULL'} AS motivo,
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
                       WHERE estado = 'pendiente' AND fecha_programada <= CURRENT_DATE""")
        total = int(cur.fetchone()['n'])
        cur.execute("""SELECT COUNT(*) AS n FROM st_seguimientos
                       WHERE estado = 'pendiente' AND fecha_programada BETWEEN CURRENT_DATE + 1 AND CURRENT_DATE + 7""")
        proximos = int(cur.fetchone()['n'])
    from services.servicio_tecnico_seguimiento import TIPOS
    if not filas:
        return {'seguimientos_para_hoy': 0, 'proximos_7_dias': proximos,
                'conclusion': 'No hay seguimientos del taller pendientes para hoy.'}
    lista = [{
        'que_hacer': ('Recordatorio interno' if f['tipo'] == 'recordatorio' and f['canal'] == 'interno'
                      else TIPOS.get(f['tipo'], (f['tipo'],))[0]),
        'motivo': f['motivo'] or None,
        'cliente': f['cliente'], 'orden': f['numero'],
        'equipo': _equipo({'tipo': f['equipo_tipo'], 'marca': f['marca'], 'modelo': f['modelo']}) if f['equipo_tipo'] else None,
        'valor_cotizado': _dinero(f['cotizacion_total']) if f['tipo'] == 'cotizacion_sin_respuesta' else None,
        'dias_de_atraso': int(f['dias_atraso'] or 0),
        'urgente': f['tipo'] == 'calificacion_baja',
    } for f in filas]
    urgentes = sum(1 for x in lista if x['urgente'])
    return {
        'seguimientos_para_hoy': total, 'mostrando': len(lista), 'proximos_7_dias': proximos, 'seguimientos': lista,
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
                         o.solucion, o.falla_categoria, o.solucion_categoria, o.resumen_caso,
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
                'solucion': f['solucion'], 'tipo_de_falla': _nombres_clasificacion()[0].get(f['falla_categoria']),
                'tipo_de_solucion': _nombres_clasificacion()[1].get(f['solucion_categoria']),
                'resumen_del_caso': f['resumen_caso'],
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
# Palabras que no ayudan a encontrar un equipo («¿qué equipos tiene registrados…?»).
_VACIAS_EQUIPO = set('de del la el los las a al mi mis su sus un una unos unas equipo equipos registrado '
                     'registrados registrada registradas tiene tienen tenemos que cual cuales cuando ficha hoja '
                     'vida historial caracteristicas datos con serial imei cliente clientes le les toca '
                     'mantenimiento mantenimientos piezas pieza cambiado cambiaron se han ha y o'.split())


def _columnas_de(cur, tabla):
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = %s""", (tabla,))
    return {r[0] for r in cur.fetchall()}


def _buscar_equipos(cur, texto, limite=8):
    """Equipos por IMEI o serial exactos, o por palabras: cliente, marca,
    modelo y tipo («el portátil de Laura Gómez», «Samsung de Carlos»). Cada
    palabra tiene que aparecer al comienzo de alguna palabra del equipo."""
    from services.servicio_tecnico_clasificador import normalizar
    texto = (texto or '').strip()
    base = """SELECT e.*, c.nombre AS cliente FROM st_equipos e
              LEFT JOIN crm_contactos c ON c.id = e.crm_contacto_id WHERE e.activo"""
    digitos = re.sub(r'\D', '', texto)
    if len(digitos) == 15:
        cur.execute(base + ' AND e.imei = %s ORDER BY e.actualizado_en DESC LIMIT %s', (digitos, limite))
        filas = cur.fetchall()
        if filas:
            return filas
    cur.execute(base + " AND lower(COALESCE(e.serial, '')) = lower(%s) ORDER BY e.actualizado_en DESC LIMIT %s",
                (texto, limite))
    filas = cur.fetchall()
    if filas:
        return filas
    palabras = [w for w in re.findall(r'[a-z0-9\-]{2,}', normalizar(texto)) if w not in _VACIAS_EQUIPO]
    tipos_buscados = set()
    for w in palabras:
        tipos_buscados.update(_TIPOS_PALABRA.get(w, ()))
    terminos = [w for w in palabras if w not in _TIPOS_PALABRA]
    if not terminos and not tipos_buscados:
        return []
    patrones = [re.compile(r'(?:^|[^a-z0-9])' + re.escape(t)) for t in terminos]
    cur.execute(base + ' ORDER BY e.actualizado_en DESC LIMIT 800')
    elegidos = []
    for f in cur.fetchall():
        if tipos_buscados and f['tipo'] not in tipos_buscados:
            continue
        datos = normalizar(' '.join(filter(None, (f['cliente'], f['marca'], f['modelo'], f['serial'], f['imei']))))
        if all(pt.search(datos) for pt in patrones):
            elegidos.append(f)
            if len(elegidos) >= limite:
                break
    return elegidos


def _asegurar_tablas_0020():
    """Fotos y mantenimientos (migración 0020). Se crean ANTES de abrir el
    cursor de la consulta (un ALTER con la consulta abierta se quedaría
    esperando) y solo en negocios que ya usan el módulo."""
    try:
        with get_db_cursor() as cur:
            if not _existe(cur, 'st_equipos'):
                return False
            if _existe(cur, 'st_mantenimientos'):
                return True
        from services.servicio_tecnico_service import asegurar_tablas
        return asegurar_tablas()
    except Exception:  # noqa: BLE001
        return False


def taller_equipo_historial(texto='', **_):
    """Hoja de vida de los equipos de UN cliente (por nombre), de un serial o
    IMEI, o descritos con palabras («el portátil de Laura»): características,
    plan y registro de mantenimientos, recordatorios, piezas cambiadas y
    reparaciones."""
    texto = (texto or '').strip()
    if not texto:
        return {'conclusion': 'Dime el nombre del cliente, el serial o el IMEI del equipo.'}
    completo = _asegurar_tablas_0020()
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'st_equipos'):
            return _SIN_MODULO
        equipos = _buscar_equipos(cur, texto, 8)
        if not equipos:
            return {'conclusion': f'No encontré equipos con «{texto}».'}
        salida = []
        for e in equipos:
            cur.execute("""SELECT numero, estado, falla_reportada, solucion, falla_categoria, fecha_recibido,
                                  valor_final
                           FROM st_ordenes WHERE equipo_id = %s ORDER BY id DESC LIMIT 10""", (e['id'],))
            ordenes = [{'orden': o['numero'], 'estado': _NOMBRE_ESTADO.get(o['estado'], o['estado']),
                        'falla': (o['falla_reportada'] or '')[:160], 'solucion': (o['solucion'] or '')[:200] or None,
                        'tipo_de_falla': _nombres_clasificacion()[0].get(o['falla_categoria']),
                        'recibido': o['fecha_recibido'].strftime('%d/%m/%Y'),
                        'cobrado': _dinero(o['valor_final'])} for o in cur.fetchall()]
            cur.execute("""SELECT componente, detalle, fecha, proxima_revision FROM st_cambios
                           WHERE equipo_id = %s ORDER BY fecha DESC LIMIT 10""", (e['id'],))
            piezas = [{'pieza': p['componente'], 'detalle': p['detalle'], 'fecha': str(p['fecha']),
                       'proxima_revision': str(p['proxima_revision']) if p['proxima_revision'] else None}
                      for p in cur.fetchall()]
            caracteristicas = {k: e[k] for k in ('procesador', 'ram', 'almacenamiento', 'sistema_operativo', 'pantalla')
                               if e.get(k)}
            caracteristicas.update({k: v for k, v in (e['extras'] or {}).items() if v})
            hoja = {
                'equipo': _equipo(e), 'cliente': e['cliente'], 'serial': e['serial'], 'imei': e['imei'],
                'caracteristicas': caracteristicas, 'resumen': e['resumen_ia'],
                'mejoras_sugeridas': [s.get('titulo') for s in (e['sugerencias_ia'] or []) if isinstance(s, dict)],
                'servicios': ordenes, 'piezas_cambiadas': piezas,
            }
            if completo:
                hoja['plan_de_mantenimiento'] = (
                    {'cada_meses': e.get('mant_cada_meses'),
                     'proximo': e['mant_proximo'].strftime('%d/%m/%Y') if e.get('mant_proximo') else None}
                    if e.get('mant_cada_meses') or e.get('mant_proximo') else 'Sin plan de mantenimiento')
                cur.execute("""SELECT tipo, fecha, descripcion, costo, proxima_fecha FROM st_mantenimientos
                               WHERE equipo_id = %s ORDER BY fecha DESC, id DESC LIMIT 8""", (e['id'],))
                hoja['mantenimientos'] = [{'tipo': m['tipo'], 'fecha': m['fecha'].strftime('%d/%m/%Y'),
                                           'que_se_hizo': (m['descripcion'] or '')[:200], 'costo': _dinero(m['costo'])}
                                          for m in cur.fetchall()]
                cur.execute("""SELECT tipo, fecha_programada, motivo, canal FROM st_seguimientos
                               WHERE equipo_id = %s AND estado = 'pendiente' ORDER BY fecha_programada LIMIT 8""",
                            (e['id'],))
                from services.servicio_tecnico_seguimiento import TIPOS
                hoja['recordatorios_pendientes'] = [
                    {'que': s['motivo'] or TIPOS.get(s['tipo'], (s['tipo'],))[0],
                     'fecha': s['fecha_programada'].strftime('%d/%m/%Y'),
                     'interno': s['canal'] == 'interno'} for s in cur.fetchall()]
                cur.execute('SELECT COUNT(*) AS n FROM st_fotos WHERE equipo_id = %s AND activo', (e['id'],))
                hoja['fotos'] = int(cur.fetchone()['n'])
            salida.append(hoja)
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


# ── 6. Casos: qué falla tuvo un equipo y cómo se solucionó ─────
_VACIAS = set('que cual cuales fue fueron como se le lo la las el los un una unos unas de del al a en con '
              'por para y o mi mis nuestro nuestra su sus tuvo tenia tiene paso pasaron novedad novedades falla '
              'fallas problema problemas solucion soluciono solucionamos solucionaron arreglo arreglamos caso '
              'casos atendimos atendido atendidos atendio ultimo ultima ultimos ultimas hizo hicimos hubo hay '
              'equipo equipos cliente esta este estos esa ese'.split())
_TIPOS_PALABRA = {
    'computador': ('computador', 'portatil'), 'computadores': ('computador', 'portatil'),
    'pc': ('computador', 'portatil'), 'escritorio': ('computador',), 'portatil': ('portatil',),
    'portatiles': ('portatil',), 'laptop': ('portatil',), 'celular': ('celular',), 'celulares': ('celular',),
    'telefono': ('celular',), 'movil': ('celular',), 'tablet': ('tablet',), 'tablets': ('tablet',),
    'televisor': ('televisor',), 'tv': ('televisor',), 'monitor': ('monitor',), 'impresora': ('impresora',),
    'ups': ('ups',), 'consola': ('consola',),
}


def _nombres_clasificacion():
    from services import servicio_tecnico_clasificador as c
    return c.NOMBRE_FALLA, c.NOMBRE_SOLUCION, c.NOMBRE_COMPONENTE


def taller_casos(texto='', limite=8, **_):
    """Casos atendidos que coinciden con lo que se pregunta (cliente, marca,
    modelo, tipo de equipo, falla o solución): qué falla tuvo y cómo se
    solucionó. Sin texto: los últimos casos atendidos."""
    from services.servicio_tecnico_clasificador import _REGLAS_FALLA, _aparece, normalizar
    limite = _limite(limite, 8, 20)
    pregunta = normalizar(texto)
    palabras = [p for p in re.findall(r'[a-z0-9\-]{2,}', pregunta) if p not in _VACIAS]
    tipos_buscados = set()
    for p in palabras:
        tipos_buscados.update(_TIPOS_PALABRA.get(p, ()))
    terminos = [p for p in palabras if p not in _TIPOS_PALABRA]
    categoria = None
    if pregunta:
        mejor = 0
        for codigo, claves in _REGLAS_FALLA:
            n = sum(1 for k in claves if _aparece(k, pregunta))
            if n > mejor:
                categoria, mejor = codigo, n
    nombre_falla, nombre_solucion, _ = _nombres_clasificacion()
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'st_ordenes'):
            return _SIN_MODULO
        cur.execute("""
            SELECT o.numero, o.estado, o.fecha_recibido, o.fecha_entregado, o.falla_reportada, o.diagnostico,
                   o.solucion, o.falla_categoria, o.solucion_categoria, o.resumen_caso, o.etiquetas,
                   e.tipo, e.marca, e.modelo, e.serial, c.nombre AS cliente
            FROM st_ordenes o JOIN st_equipos e ON e.id = o.equipo_id
            LEFT JOIN crm_contactos c ON c.id = o.crm_contacto_id
            ORDER BY o.id DESC LIMIT 600""")
        filas = cur.fetchall()
    puntuados = []
    for f in filas:
        if tipos_buscados and f['tipo'] not in tipos_buscados:
            continue
        cliente = normalizar(f['cliente'] or '')
        equipo_txt = normalizar(' '.join(filter(None, (f['marca'], f['modelo'], f['serial']))))
        caso_txt = normalizar(' '.join(filter(None, (f['falla_reportada'], f['diagnostico'], f['solucion'],
                                                      f['etiquetas'], f['resumen_caso']))))
        puntos = 0
        for t in terminos:
            if t in cliente:
                puntos += 3
            if t in equipo_txt:
                puntos += 3
            if t in caso_txt:
                puntos += 2
        if categoria and f['falla_categoria'] == categoria:
            puntos += 4
        if terminos and puntos == 0:
            continue
        puntuados.append((puntos, f))
    puntuados.sort(key=lambda x: (x[0], x[1]['fecha_recibido']), reverse=True)
    elegidos = [f for _, f in puntuados[:limite]]
    if not elegidos:
        return {'casos_encontrados': 0,
                'conclusion': f'No encontré casos atendidos con «{texto}».' if texto else 'Todavía no hay casos atendidos.'}
    casos = [{
        'orden': f['numero'], 'recibido': f['fecha_recibido'].strftime('%d/%m/%Y'),
        'entregado': f['fecha_entregado'].strftime('%d/%m/%Y') if f['fecha_entregado'] else None,
        'estado': _NOMBRE_ESTADO.get(f['estado'], f['estado']), 'cliente': f['cliente'], 'equipo': _equipo(f),
        'falla_reportada': f['falla_reportada'], 'diagnostico': f['diagnostico'],
        'solucion': f['solucion'] or ('(sin registrar)' if f['estado'] in ('entregado', 'garantia')
                                      else '(todavía en el taller)'),
        'tipo_de_falla': nombre_falla.get(f['falla_categoria']),
        'tipo_de_solucion': nombre_solucion.get(f['solucion_categoria']),
        'resumen': f['resumen_caso'],
    } for f in elegidos]
    salida = {'casos_encontrados': len(puntuados), 'mostrando': len(casos), 'casos': casos}
    if categoria:
        salida['tipo_de_falla_buscado'] = nombre_falla.get(categoria)
        conteo = {}
        for _, f in puntuados:
            if f['falla_categoria'] == categoria and f['solucion_categoria']:
                conteo[f['solucion_categoria']] = conteo.get(f['solucion_categoria'], 0) + 1
        if conteo:
            salida['como_se_ha_solucionado_esta_falla'] = {
                nombre_solucion.get(k, k): v for k, v in sorted(conteo.items(), key=lambda kv: kv[1], reverse=True)}
    return salida


# ── 7. Fallas más comunes (solo agregados) ──────────────────────
def taller_fallas_frecuentes(periodo='todo', **_):
    """Qué se daña más y cómo se soluciona: fallas, piezas y soluciones más
    comunes, por tipo de equipo y marca, y cuánto tardan."""
    p = _periodo(periodo)
    nombre_falla, nombre_solucion, nombre_componente = _nombres_clasificacion()
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'st_ordenes'):
            return _SIN_MODULO
        filtro = _sql_periodo(p, 'o.fecha_recibido')
        cur.execute(f"""SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE o.falla_categoria IS NULL) AS sin
                        FROM st_ordenes o WHERE {filtro}""")
        r = cur.fetchone()
        total, sin_clasificar = int(r['n']), int(r['sin'])

        def _top(col, nombres):
            cur.execute(f"""SELECT o.{col} AS c, COUNT(*) AS n FROM st_ordenes o
                            WHERE {filtro} AND o.{col} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8""")
            return {nombres.get(x['c'], x['c']): int(x['n']) for x in cur.fetchall()}
        fallas = _top('falla_categoria', nombre_falla)
        piezas = _top('componente', nombre_componente)
        soluciones = _top('solucion_categoria', nombre_solucion)
        cur.execute(f"""SELECT o.falla_categoria AS c,
                               AVG(EXTRACT(EPOCH FROM (o.fecha_entregado - o.fecha_recibido)) / 86400) AS dias
                        FROM st_ordenes o WHERE {filtro} AND o.fecha_entregado IS NOT NULL
                          AND o.falla_categoria IS NOT NULL GROUP BY 1""")
        dias = {nombre_falla.get(x['c'], x['c']): round(float(x['dias']), 1)
                for x in cur.fetchall() if x['dias'] is not None}
        cur.execute(f"""SELECT e.tipo, COALESCE(NULLIF(e.marca, ''), 'Sin marca') AS marca, COUNT(*) AS n
                        FROM st_ordenes o JOIN st_equipos e ON e.id = o.equipo_id
                        WHERE {filtro} GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 8""")
        marcas = [{'equipo': f"{_tipo(x['tipo'])} {x['marca']}", 'casos': int(x['n'])} for x in cur.fetchall()]
    if not total:
        return {'periodo': _label_periodo(p), 'conclusion': 'No hay órdenes en ese período.'}
    return {
        'periodo': _label_periodo(p), 'ordenes': total,
        'fallas_mas_comunes': fallas, 'piezas_mas_cambiadas_o_afectadas': piezas,
        'soluciones_mas_usadas': soluciones, 'dias_promedio_por_tipo_de_falla': dias,
        'equipos_y_marcas_con_mas_casos': marcas,
        'sin_clasificar': sin_clasificar,
        'confiabilidad': 'baja' if total < 10 else 'normal',
        'nota': (f'{sin_clasificar} orden(es) aún sin clasificar: se pueden clasificar en Servicio Técnico → '
                 'Configuración.' if sin_clasificar else None),
    }


# ── 8. Mantenimientos: agenda y lo hecho ────────────────────────
def _ventana(periodo):
    """(desde, hasta) del período completo, también hacia adelante («este mes» =
    del 1 al último día). Sin período: todo lo vencido y lo que viene (hasta=None)."""
    hoy = date.today()
    p = _periodo(periodo)
    if isinstance(p, Rango):
        return p.desde, p.hasta
    if p in ('hoy', 'ayer', 'anteayer'):
        d = hoy - timedelta(days={'hoy': 0, 'ayer': 1, 'anteayer': 2}[p])
        return d, d
    if p in ('semana', 'semana_anterior'):
        lunes = hoy - timedelta(days=hoy.weekday() + (7 if p == 'semana_anterior' else 0))
        return lunes, lunes + timedelta(days=6)
    if p in ('mes', 'mes_anterior'):
        base = hoy.replace(day=1)
        if p == 'mes_anterior':
            base = (base - timedelta(days=1)).replace(day=1)
        return base, base.replace(day=calendar.monthrange(base.year, base.month)[1])
    if p == 'anio':
        return date(hoy.year, 1, 1), date(hoy.year, 12, 31)
    return None, None


def _fecha_iso(valor):
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def taller_mantenimientos(periodo='todo', limite=20, **_):
    """Mantenimientos del taller: los que tocan (vencidos y del período, por el
    plan de cada equipo), los hechos en el período (preventivos y correctivos,
    con lo cobrado), revisiones de piezas, UPS con baterías viejas y equipos sin
    plan de mantenimiento."""
    limite = _limite(limite, 20, 50)
    if not _asegurar_tablas_0020():
        return _SIN_MODULO
    hoy = date.today()
    desde, hasta = _ventana(periodo)
    inicio, fin = desde or date(1900, 1, 1), hasta or date(9999, 12, 31)
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        # Lo que toca: el plan del equipo y los avisos de mantenimiento pendientes.
        cur.execute("""
            SELECT e.tipo, e.marca, e.modelo, e.serial, e.mant_cada_meses, c.nombre AS cliente,
                   LEAST(e.mant_proximo, s.fecha) AS fecha
            FROM st_equipos e
            LEFT JOIN crm_contactos c ON c.id = e.crm_contacto_id
            LEFT JOIN (SELECT equipo_id, MIN(fecha_programada) AS fecha FROM st_seguimientos
                       WHERE estado = 'pendiente' AND tipo = 'mantenimiento' AND equipo_id IS NOT NULL
                       GROUP BY equipo_id) s ON s.equipo_id = e.id
            WHERE e.activo AND COALESCE(e.mant_proximo, s.fecha) IS NOT NULL
              AND (LEAST(e.mant_proximo, s.fecha) < %s
                   OR LEAST(e.mant_proximo, s.fecha) BETWEEN %s AND %s)
            ORDER BY 7 LIMIT %s""", (hoy, inicio, fin, limite))
        filas_programados = cur.fetchall()
        cur.execute("""
            SELECT COUNT(*) AS n,
                   COUNT(*) FILTER (WHERE LEAST(e.mant_proximo, s.fecha) < %s) AS vencidos
            FROM st_equipos e
            LEFT JOIN (SELECT equipo_id, MIN(fecha_programada) AS fecha FROM st_seguimientos
                       WHERE estado = 'pendiente' AND tipo = 'mantenimiento' AND equipo_id IS NOT NULL
                       GROUP BY equipo_id) s ON s.equipo_id = e.id
            WHERE e.activo AND COALESCE(e.mant_proximo, s.fecha) IS NOT NULL
              AND (LEAST(e.mant_proximo, s.fecha) < %s
                   OR LEAST(e.mant_proximo, s.fecha) BETWEEN %s AND %s)""", (hoy, hoy, inicio, fin))
        conteo = cur.fetchone()
        total_por_hacer, vencidos = int(conteo['n']), int(conteo['vencidos'])
        programados = [{
            'equipo': _equipo(f), 'cliente': f['cliente'], 'serial': f['serial'],
            'fecha': f['fecha'].strftime('%d/%m/%Y'),
            'vencido': f['fecha'] < hoy, 'dias_de_atraso': (hoy - f['fecha']).days if f['fecha'] < hoy else 0,
            'cada_meses': f['mant_cada_meses'],
        } for f in filas_programados]

        filtro = _sql_periodo(p, 'm.fecha')
        cur.execute(f"""SELECT m.tipo, COUNT(*) AS n, COALESCE(SUM(m.costo), 0) AS total
                        FROM st_mantenimientos m WHERE {filtro} GROUP BY m.tipo""")
        resumen = {r['tipo']: (int(r['n']), float(r['total'])) for r in cur.fetchall()}
        cur.execute(f"""SELECT m.tipo, m.fecha, m.descripcion, m.costo, e.tipo AS equipo_tipo, e.marca, e.modelo,
                               c.nombre AS cliente
                        FROM st_mantenimientos m JOIN st_equipos e ON e.id = m.equipo_id
                        LEFT JOIN crm_contactos c ON c.id = e.crm_contacto_id
                        WHERE {filtro} ORDER BY m.fecha DESC, m.id DESC LIMIT %s""", (limite,))
        hechos = [{
            'tipo': f['tipo'], 'fecha': f['fecha'].strftime('%d/%m/%Y'), 'cliente': f['cliente'],
            'equipo': _equipo({'tipo': f['equipo_tipo'], 'marca': f['marca'], 'modelo': f['modelo']}),
            'que_se_hizo': (f['descripcion'] or '')[:160], 'costo': _dinero(f['costo']),
        } for f in cur.fetchall()]

        cur.execute("""SELECT cb.componente, cb.proxima_revision, e.tipo, e.marca, e.modelo, c.nombre AS cliente
                       FROM st_cambios cb JOIN st_equipos e ON e.id = cb.equipo_id
                       LEFT JOIN crm_contactos c ON c.id = e.crm_contacto_id
                       WHERE e.activo AND cb.proxima_revision IS NOT NULL
                         AND (cb.proxima_revision < %s OR cb.proxima_revision BETWEEN %s AND %s)
                       ORDER BY cb.proxima_revision LIMIT %s""", (hoy, inicio, fin, limite))
        piezas = [{'pieza': f['componente'], 'equipo': _equipo(f), 'cliente': f['cliente'],
                   'revisar': f['proxima_revision'].strftime('%d/%m/%Y'), 'vencida': f['proxima_revision'] < hoy}
                  for f in cur.fetchall()]

        cur.execute("""SELECT e.tipo, e.marca, e.modelo, e.extras->>'baterias_ultimo_cambio' AS ultimo,
                              c.nombre AS cliente
                       FROM st_equipos e LEFT JOIN crm_contactos c ON c.id = e.crm_contacto_id
                       WHERE e.activo AND e.tipo IN ('ups', 'bateria')
                         AND COALESCE(e.extras->>'baterias_ultimo_cambio', '') <> ''
                       LIMIT 300""")
        baterias = []
        for f in cur.fetchall():
            ultimo = _fecha_iso(f['ultimo'])
            if ultimo and (hoy - ultimo).days > 730:
                baterias.append({'equipo': _equipo(f), 'cliente': f['cliente'],
                                 'ultimo_cambio_de_baterias': ultimo.strftime('%d/%m/%Y'),
                                 'anios': round((hoy - ultimo).days / 365, 1)})
        baterias.sort(key=lambda b: -b['anios'])

        sin_plan_sql = """FROM st_equipos e LEFT JOIN crm_contactos c ON c.id = e.crm_contacto_id
                          WHERE e.activo AND e.mant_cada_meses IS NULL AND e.mant_proximo IS NULL
                            AND NOT EXISTS (SELECT 1 FROM st_seguimientos s WHERE s.equipo_id = e.id
                                            AND s.estado = 'pendiente' AND s.tipo = 'mantenimiento')"""
        cur.execute('SELECT COUNT(*) AS n ' + sin_plan_sql)
        sin_plan_total = int(cur.fetchone()['n'])
        cur.execute('SELECT e.tipo, e.marca, e.modelo, c.nombre AS cliente ' + sin_plan_sql +
                    ' ORDER BY e.actualizado_en DESC LIMIT %s', (limite,))
        sin_plan = [{'equipo': _equipo(f), 'cliente': f['cliente']} for f in cur.fetchall()]

    preventivos, correctivos = resumen.get('preventivo', (0, 0.0)), resumen.get('correctivo', (0, 0.0))
    if not (programados or hechos or piezas or baterias or sin_plan_total):
        return {'periodo': _label_periodo(p),
                'conclusion': 'No hay equipos registrados con mantenimientos todavía. Se programan en la ficha de '
                              'cada equipo (Soporte → Equipos → pestaña Mantenimientos).'}
    agenda = (f"del {desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}" if desde
              else 'vencidos y próximos, en orden de fecha')
    return {
        'periodo': _label_periodo(p),
        'agenda': agenda,
        'por_hacer': programados,
        'total_por_hacer': total_por_hacer,
        'vencidos': vencidos,
        'hechos_en_el_periodo': {'preventivos': preventivos[0], 'correctivos': correctivos[0],
                                 'cobrado': formatear_moneda(preventivos[1] + correctivos[1])},
        'ultimos_hechos': hechos,
        'revisiones_de_piezas': piezas,
        'ups_con_baterias_de_mas_de_2_anios': baterias,
        'equipos_sin_plan_de_mantenimiento': sin_plan_total,
        'sin_plan': sin_plan,
        'nota': (f'{vencidos} mantenimiento(s) vencido(s): aparecen en Soporte → Seguimientos hoy con el mensaje '
                 'listo para el cliente.' if vencidos else None),
    }
