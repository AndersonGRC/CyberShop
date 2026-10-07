"""Servicio Técnico F2: seguimientos, alertas y avisos al cliente.

Un seguimiento (`st_seguimientos`) es algo que hay que hacer en una fecha:
recordar una cotización, avisar que el equipo sigue listo, preguntar cómo le
fue, avisar la garantía, ofrecer mantenimiento, revisar una pieza. Se crean
solos al cambiar el estado de la orden (`al_cambiar_estado`, dentro de la misma
transacción) y aparecen en la bandeja «Hoy».

Canales:
  - WhatsApp: botón `wa.me` con el mensaje escrito; quien atiende lo envía.
  - Correo: sale automático en los cambios de estado y en los recordatorios
    vencidos (cron), si el contacto tiene correo y la opción está encendida.

Nada aquí manda datos a la IA ni a terceros fuera del correo del propio negocio.
"""

import threading
from datetime import date, timedelta
from urllib.parse import quote

from flask import current_app, has_request_context, request, url_for

from database import get_db_cursor
from services import servicio_tecnico_mensajes as msj

# tipo → (nombre, ícono, quién lo atiende)
TIPOS = {
    'cotizacion_sin_respuesta': ('Cotización sin respuesta', 'file-invoice-dollar', 'cliente'),
    'listo_sin_recoger': ('Listo sin recoger', 'box-open', 'cliente'),
    'satisfaccion': ('¿Cómo le fue?', 'smile', 'cliente'),
    'garantia_por_vencer': ('Garantía por vencer', 'shield-alt', 'cliente'),
    'mantenimiento': ('Mantenimiento preventivo', 'tools', 'cliente'),
    'revision_pieza': ('Revisión de pieza', 'microchip', 'cliente'),
    'calificacion_baja': ('Calificación baja: llamar', 'exclamation-triangle', 'urgente'),
    'recordatorio': ('Recordatorio', 'bell', 'cliente'),
}
# Canales de un recordatorio programado a mano («interno» = solo para el equipo de trabajo).
CANALES_RECORDATORIO = [('whatsapp', 'WhatsApp'), ('correo', 'Correo'), ('llamada', 'Llamada'),
                        ('interno', 'Solo para nosotros')]
# Los que el cron puede mandar solos por correo.
AUTO_CORREO = ('listo_sin_recoger', 'satisfaccion', 'garantia_por_vencer', 'mantenimiento', 'revision_pieza')
CLAVE_URL_BASE = 'st_url_base'


# ── Enlace público (también fuera de una petición: cron) ────────
def recordar_url_base():
    """Guarda la URL del sitio la primera vez que alguien usa el módulo, para
    que el cron arme los enlaces de los correos."""
    if not has_request_context():
        return
    base = request.url_root.rstrip('/') + '/'
    cache = current_app.extensions.setdefault('st_url_base', {})
    from database import _current_db_name
    db = _current_db_name()
    if cache.get(db) == base:
        return
    try:
        from services.config_tenant import set_cliente_config
        with get_db_cursor() as cur:
            set_cliente_config(cur, CLAVE_URL_BASE, base, grupo='servicio_tecnico',
                               descripcion='URL del sitio para los enlaces de los correos')
        cache[db] = base
    except Exception:  # noqa: BLE001
        pass


def enlace_publico(token):
    if not token:
        return ''
    if has_request_context():
        return url_for('servicio_tecnico.publico', token=token, _external=True)
    try:
        with get_db_cursor() as cur:
            cur.execute('SELECT valor FROM cliente_config WHERE clave = %s LIMIT 1', (CLAVE_URL_BASE,))
            fila = cur.fetchone()
        base = (fila[0] if fila else '') or ''
    except Exception:  # noqa: BLE001
        base = ''
    return (base.rstrip('/') + '/servicio/' + token) if base else ''


def whatsapp_url(telefono, texto=''):
    """wa.me con el número en formato internacional (Colombia por defecto)."""
    digitos = ''.join(ch for ch in str(telefono or '') if ch.isdigit())
    if len(digitos) == 10 and digitos.startswith('3'):
        digitos = '57' + digitos
    if len(digitos) < 11:
        return None
    return f'https://wa.me/{digitos}' + (f'?text={quote(texto)}' if texto else '')


def _uno(fila):
    """Primer valor de una fila, venga de un cursor normal o de uno dict."""
    if fila is None:
        return None
    return next(iter(fila.values())) if isinstance(fila, dict) else fila[0]


def _sumar_meses(d, meses):
    mes = d.month - 1 + meses
    anio = d.year + mes // 12
    mes = mes % 12 + 1
    import calendar
    return date(anio, mes, min(d.day, calendar.monthrange(anio, mes)[1]))


# ── Programar y cerrar ──────────────────────────────────────────
def programar(cur, tipo, fecha, *, orden_id=None, equipo_id=None, cambio_id=None,
              cotizacion_id=None, contacto_id=None, canal='whatsapp'):
    """Crea el seguimiento si no hay ya uno pendiente igual. Devuelve su id o None."""
    cur.execute("""SELECT id FROM st_seguimientos
                   WHERE tipo = %s AND estado = 'pendiente'
                     AND orden_id IS NOT DISTINCT FROM %s AND cambio_id IS NOT DISTINCT FROM %s
                     AND cotizacion_id IS NOT DISTINCT FROM %s AND equipo_id IS NOT DISTINCT FROM %s LIMIT 1""",
                (tipo, orden_id, cambio_id, cotizacion_id, equipo_id))
    if cur.fetchone():
        return None
    cur.execute("""INSERT INTO st_seguimientos (orden_id, equipo_id, cambio_id, cotizacion_id, crm_contacto_id,
                                                tipo, fecha_programada, canal)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (orden_id, equipo_id, cambio_id, cotizacion_id, contacto_id, tipo, fecha, canal))
    return _uno(cur.fetchone())


def cerrar_pendientes(cur, orden_id, tipos=None, estado='omitido', comentario=None):
    sql = "UPDATE st_seguimientos SET estado = %s, hecho_en = NOW(), comentario = COALESCE(comentario, %s) " \
          "WHERE orden_id = %s AND estado = 'pendiente'"
    params = [estado, comentario, orden_id]
    if tipos:
        sql += ' AND tipo = ANY(%s)'
        params.append(list(tipos))
    cur.execute(sql, params)


def cerrar_de_equipo(cur, equipo_id, tipos, comentario, estado='omitido', solo_sin_orden=False):
    """Cierra los seguimientos pendientes del equipo de esos tipos (los de sus
    órdenes también, salvo `solo_sin_orden`)."""
    sql = ("UPDATE st_seguimientos SET estado = %s, hecho_en = NOW(), comentario = COALESCE(comentario, %s) "
           "WHERE equipo_id = %s AND estado = 'pendiente' AND tipo = ANY(%s)")
    if solo_sin_orden:
        sql += ' AND orden_id IS NULL'
    cur.execute(sql, (estado, comentario, equipo_id, list(tipos)))


def programar_recordatorio(equipo_id, fecha, motivo, canal='whatsapp', usuario_id=None):
    """Recordatorio puesto a mano en la ficha del equipo (llamar, revisar, ofrecer…)."""
    from services.servicio_tecnico_service import ErrorServicio, _evento, _fecha, _texto
    fecha = _fecha(fecha)
    if not fecha:
        raise ErrorServicio('Escoge la fecha del recordatorio.')
    if fecha < date.today():
        raise ErrorServicio('La fecha del recordatorio ya pasó.')
    motivo = _texto(motivo, 300)
    if not motivo:
        raise ErrorServicio('Escribe para qué es el recordatorio.')
    if canal not in dict(CANALES_RECORDATORIO):
        canal = 'whatsapp'
    with get_db_cursor() as cur:
        cur.execute('SELECT crm_contacto_id FROM st_equipos WHERE id = %s', (equipo_id,))
        fila = cur.fetchone()
        if not fila:
            raise ErrorServicio('El equipo no existe.')
        cur.execute("""INSERT INTO st_seguimientos (equipo_id, crm_contacto_id, tipo, fecha_programada, canal, motivo)
                       VALUES (%s, %s, 'recordatorio', %s, %s, %s) RETURNING id""",
                    (equipo_id, _uno(fila), fecha, canal, motivo))
        seg_id = _uno(cur.fetchone())
        _evento(cur, None, equipo_id, 'nota', f"Recordatorio para el {fecha.strftime('%d/%m/%Y')}: {motivo}", usuario_id)
    return seg_id


def de_equipo(equipo_id, hechos=10):
    """Seguimientos del equipo (de sus órdenes y propios): pendientes con el
    mensaje listo y los últimos ya atendidos."""
    cfg = msj.config()
    negocio = msj.datos_negocio()
    hoy = date.today()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(_SQL_SEGUIMIENTO + """
            WHERE COALESCE(s.equipo_id, o.equipo_id) = %s AND s.estado = 'pendiente'
            ORDER BY s.fecha_programada, s.id""", (equipo_id,))
        pendientes = [_enriquecer(f, negocio, cfg) for f in cur.fetchall()]
        cur.execute(_SQL_SEGUIMIENTO + """
            WHERE COALESCE(s.equipo_id, o.equipo_id) = %s AND s.estado <> 'pendiente'
            ORDER BY s.hecho_en DESC NULLS LAST, s.id DESC LIMIT %s""", (equipo_id, hechos))
        atendidos = [_enriquecer(f, negocio, cfg) for f in cur.fetchall()]
    for f in pendientes:
        f['dias'] = (hoy - f['fecha_programada']).days
    return pendientes, atendidos


def al_cambiar_estado(cur, orden, nuevo, garantia_hasta=None, cfg=None):
    """Seguimientos que nacen o se cierran con el cambio de estado (misma transacción)."""
    cfg = cfg or msj.config()
    hoy = date.today()
    base = dict(orden_id=orden['id'], equipo_id=orden['equipo_id'], contacto_id=orden['crm_contacto_id'])
    if nuevo in ('aprobado', 'reparacion', 'listo', 'cancelado', 'entregado'):
        cerrar_pendientes(cur, orden['id'], ['cotizacion_sin_respuesta'], comentario='La orden avanzó')
    if nuevo == 'listo':
        programar(cur, 'listo_sin_recoger', hoy + timedelta(days=cfg['st_dias_listo']), **base)
    elif nuevo == 'reparacion':
        cerrar_pendientes(cur, orden['id'], ['listo_sin_recoger'], comentario='Volvió a reparación')
    elif nuevo == 'entregado':
        cerrar_pendientes(cur, orden['id'], ['listo_sin_recoger'], comentario='Entregado')
        programar(cur, 'satisfaccion', hoy + timedelta(days=cfg['st_dias_satisfaccion']), **base)
        if garantia_hasta:
            aviso = garantia_hasta - timedelta(days=cfg['st_dias_garantia'])
            if aviso > hoy:
                programar(cur, 'garantia_por_vencer', aviso, **base)
        if cfg['st_meses_mantenimiento'] > 0 and not _tiene_plan(cur, orden['equipo_id']):
            programar(cur, 'mantenimiento', _sumar_meses(hoy, cfg['st_meses_mantenimiento']), **base)
    elif nuevo == 'cancelado':
        cerrar_pendientes(cur, orden['id'], comentario='Orden cancelada')


def _tiene_plan(cur, equipo_id):
    """El equipo tiene su propio plan de mantenimiento (entonces sobra el aviso
    general de «N meses después de entregar»)."""
    cur.execute('SELECT mant_cada_meses, mant_proximo FROM st_equipos WHERE id = %s', (equipo_id,))
    fila = cur.fetchone()
    if not fila:
        return False
    valores = list(fila.values()) if isinstance(fila, dict) else list(fila)
    return bool(valores[0] or valores[1])


def al_registrar_cambio(cur, cambio_id, equipo_id, proxima_revision, orden_id=None):
    if not proxima_revision:
        return
    cur.execute('SELECT crm_contacto_id FROM st_equipos WHERE id = %s', (equipo_id,))
    fila = cur.fetchone()
    programar(cur, 'revision_pieza', proxima_revision, orden_id=orden_id, equipo_id=equipo_id,
              cambio_id=cambio_id, contacto_id=_uno(fila))


def sincronizar_cotizaciones(cfg=None):
    """Cotizaciones pendientes con más de N días → seguimiento; las que ya se
    aprobaron o rechazaron cierran el suyo. Aplica a TODAS las cotizaciones del
    negocio (no solo las de servicio técnico)."""
    cfg = cfg or msj.config()
    dias = cfg['st_dias_cotizacion']
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            UPDATE st_seguimientos s SET estado = 'hecho', hecho_en = NOW(),
                   comentario = COALESCE(s.comentario, 'Cotización ' || c.estado)
            FROM cotizaciones c
            WHERE s.cotizacion_id = c.id AND s.estado = 'pendiente' AND s.tipo = 'cotizacion_sin_respuesta'
              AND COALESCE(c.estado, 'pendiente') <> 'pendiente'
        """)
        cur.execute("""
            SELECT c.id, c.crm_contacto_id, c.fecha,
                   (SELECT o.id FROM st_ordenes o WHERE o.cotizacion_id = c.id ORDER BY o.id DESC LIMIT 1) AS orden_id,
                   (SELECT o.equipo_id FROM st_ordenes o WHERE o.cotizacion_id = c.id ORDER BY o.id DESC LIMIT 1) AS equipo_id
            FROM cotizaciones c
            WHERE COALESCE(c.estado, 'pendiente') = 'pendiente'
              AND c.fecha IS NOT NULL AND c.fecha::date <= CURRENT_DATE - %s
              AND c.fecha::date >= CURRENT_DATE - 90
              AND NOT EXISTS (SELECT 1 FROM st_seguimientos s
                              WHERE s.cotizacion_id = c.id AND s.tipo = 'cotizacion_sin_respuesta')
        """, (dias,))
        for c in cur.fetchall():
            programar(cur, 'cotizacion_sin_respuesta', c['fecha'].date() + timedelta(days=dias),
                      orden_id=c['orden_id'], equipo_id=c['equipo_id'], cotizacion_id=c['id'],
                      contacto_id=c['crm_contacto_id'])


# ── Bandeja ─────────────────────────────────────────────────────
def _datos_mensaje(fila, negocio):
    from services import servicio_tecnico_tipos as tipos
    equipo = ''
    if fila.get('equipo_tipo'):
        equipo = ' '.join(p for p in (tipos.nombre(fila['equipo_tipo']).lower(), fila.get('marca'), fila.get('modelo')) if p)
    valor = fila.get('cot_total') if fila.get('cot_total') is not None else (
        fila.get('valor_final') if fila.get('valor_final') is not None else fila.get('valor_estimado'))
    nombre = (fila.get('cliente_nombre') or fila.get('cot_cliente') or '').strip()
    return {
        'cliente': nombre.split(' ')[0] if nombre else '',
        'negocio': negocio['negocio'], 'telefono': negocio['telefono'],
        'numero': fila.get('numero') or '', 'equipo': equipo or 'equipo',
        'enlace': enlace_publico(fila.get('token_publico')),
        'valor': ('$' + '{:,.0f}'.format(float(valor)).replace(',', '.')) if valor is not None else '',
        'garantia': fila['garantia_hasta'].strftime('%d/%m/%Y') if fila.get('garantia_hasta') else '',
        'pieza': (fila.get('componente') or 'la pieza').lower(),
        'motivo': (fila.get('motivo') or '').strip().rstrip('.'),
    }


_SQL_SEGUIMIENTO = """
    SELECT s.*, o.numero, o.token_publico, o.valor_estimado, o.valor_final, o.garantia_hasta, o.estado AS orden_estado,
           e.tipo AS equipo_tipo, e.marca, e.modelo,
           c.nombre AS cliente_nombre, c.email AS cliente_email,
           COALESCE(NULLIF(c.whatsapp, ''), c.telefono) AS cliente_whatsapp,
           ct.total AS cot_total, ct.cliente_nombre AS cot_cliente, ct.cliente_telefono AS cot_telefono,
           cb.componente
    FROM st_seguimientos s
    LEFT JOIN st_ordenes o ON o.id = s.orden_id
    LEFT JOIN st_equipos e ON e.id = COALESCE(s.equipo_id, o.equipo_id)
    LEFT JOIN crm_contactos c ON c.id = COALESCE(s.crm_contacto_id, o.crm_contacto_id)
    LEFT JOIN cotizaciones ct ON ct.id = s.cotizacion_id
    LEFT JOIN st_cambios cb ON cb.id = s.cambio_id
"""


def _enriquecer(fila, negocio, cfg):
    fila = dict(fila)
    nombre, icono, quien = TIPOS.get(fila['tipo'], (fila['tipo'], 'bell', 'cliente'))
    fila.update(tipo_nombre=nombre, tipo_icono=icono, urgente=(quien == 'urgente'))
    asunto, texto = msj.armar(fila['tipo'], _datos_mensaje(fila, negocio), cfg)
    telefono = fila.get('cliente_whatsapp') or fila.get('cot_telefono')
    interno = fila['tipo'] == 'recordatorio' and fila.get('canal') == 'interno'
    if interno:
        # Recordatorio para el equipo de trabajo: no se le escribe al cliente.
        fila.update(tipo_nombre='Recordatorio interno', tipo_icono='clipboard-check')
        texto = fila.get('motivo') or texto
    fila.update(asunto=asunto, mensaje=texto, wa_url=None if interno else whatsapp_url(telefono, texto),
                telefono=telefono, tiene_correo=bool(fila.get('cliente_email')) and not interno,
                interno=interno,
                nombre_cliente=fila.get('cliente_nombre') or fila.get('cot_cliente') or 'Cliente')
    return fila


def bandeja(horizonte=7):
    """{'atrasados': [...], 'hoy': [...], 'proximos': [...]} con el mensaje listo."""
    cfg = msj.config()
    try:
        sincronizar_cotizaciones(cfg)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'servicio_tecnico: no se pudieron revisar las cotizaciones: {exc}')
    negocio = msj.datos_negocio()
    hoy = date.today()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(_SQL_SEGUIMIENTO + """
            WHERE s.estado = 'pendiente' AND s.fecha_programada <= %s
            ORDER BY (s.tipo = 'calificacion_baja') DESC, s.fecha_programada, s.id
        """, (hoy + timedelta(days=horizonte),))
        filas = [_enriquecer(f, negocio, cfg) for f in cur.fetchall()]
    grupos = {'atrasados': [], 'hoy': [], 'proximos': []}
    for f in filas:
        clave = 'atrasados' if f['fecha_programada'] < hoy else ('hoy' if f['fecha_programada'] == hoy else 'proximos')
        f['dias'] = (hoy - f['fecha_programada']).days
        grupos[clave].append(f)
    return grupos


def contar_pendientes():
    """Seguimientos para hoy o atrasados (para el menú y el panel)."""
    try:
        with get_db_cursor() as cur:
            cur.execute("SELECT to_regclass('public.st_seguimientos')")
            if not cur.fetchone()[0]:
                return 0
            cur.execute("SELECT COUNT(*) FROM st_seguimientos WHERE estado = 'pendiente' AND fecha_programada <= CURRENT_DATE")
            return cur.fetchone()[0]
    except Exception:  # noqa: BLE001
        return 0


def obtener(seg_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(_SQL_SEGUIMIENTO + ' WHERE s.id = %s', (seg_id,))
        fila = cur.fetchone()
    return _enriquecer(fila, msj.datos_negocio(), msj.config()) if fila else None


def completar(seg_id, estado='hecho', canal=None, comentario=None, usuario_id=None):
    """Marca hecho u omitido y lo deja en la bitácora de la orden y en el CRM."""
    if estado not in ('hecho', 'omitido'):
        raise ValueError('Estado no válido')
    seg = obtener(seg_id)
    if not seg or seg['estado'] != 'pendiente':
        return None
    from services.servicio_tecnico_service import _actividad_crm, _evento
    detalle = f"{seg['tipo_nombre']}: {'hecho' if estado == 'hecho' else 'omitido'}"
    if canal:
        detalle += f' por {canal}'
    if comentario:
        detalle += f'. {comentario[:500]}'
    with get_db_cursor() as cur:
        cur.execute("""UPDATE st_seguimientos SET estado = %s, canal = COALESCE(%s, canal), hecho_por = %s,
                              hecho_en = NOW(), comentario = COALESCE(%s, comentario)
                       WHERE id = %s AND estado = 'pendiente'""",
                    (estado, canal, usuario_id, (comentario or None) and comentario[:1000], seg_id))
        if not cur.rowcount:
            return None
        if seg.get('orden_id') or seg.get('equipo_id'):
            _evento(cur, seg.get('orden_id'), seg.get('equipo_id'),
                    {'whatsapp': 'whatsapp', 'correo': 'correo', 'llamada': 'llamada'}.get(canal, 'nota'),
                    detalle, usuario_id)
        if estado == 'hecho' and seg.get('crm_contacto_id'):
            _actividad_crm(cur, seg['crm_contacto_id'],
                           {'whatsapp': 'whatsapp', 'correo': 'email', 'llamada': 'llamada'}.get(canal, 'nota'),
                           f"Seguimiento: {seg['tipo_nombre']}", detalle, usuario_id)
    return seg


def enviar_correo_seguimiento(seg_id, usuario_id=None):
    """Envía el mensaje del seguimiento por correo y lo marca hecho."""
    seg = obtener(seg_id)
    if not seg or seg['estado'] != 'pendiente':
        return False, 'El seguimiento ya no está pendiente.'
    if not seg.get('cliente_email'):
        return False, 'El cliente no tiene correo registrado.'
    negocio = msj.datos_negocio()['negocio']
    enlace = enlace_publico(seg.get('token_publico'))
    boton = 'Calificar el servicio' if seg['tipo'] == 'satisfaccion' else 'Ver mi orden'
    ok = _enviar(seg['cliente_email'], seg['asunto'], seg['mensaje'],
                 msj.html_correo(seg['asunto'], seg['mensaje'], negocio, enlace or None, boton))
    if not ok:
        return False, 'No se pudo enviar el correo. Intenta de nuevo o usa WhatsApp.'
    completar(seg_id, 'hecho', 'correo', 'Correo enviado', usuario_id)
    return True, None


def _enviar(destino, asunto, texto, html):
    try:
        from helpers_gmail import enviar_email_gmail
        return bool(enviar_email_gmail(destino, asunto, texto, html=html))
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'servicio_tecnico: correo a {destino} falló: {exc}')
        return False


# ── Correos automáticos por cambio de estado ────────────────────
ESTADOS_CON_CORREO = ('recibido', 'cotizado', 'listo', 'entregado')


def _datos_orden(orden, estado):
    from services import servicio_tecnico_tipos as tipos
    valor = orden.get('valor_estimado')
    if estado == 'cotizado' and orden.get('cotizacion_id'):
        with get_db_cursor() as cur:
            cur.execute('SELECT total FROM cotizaciones WHERE id = %s', (orden['cotizacion_id'],))
            fila = cur.fetchone()
            valor = fila[0] if fila else valor
    if orden.get('valor_final') is not None:
        valor = orden['valor_final']
    return {
        'cliente': (orden.get('cliente_nombre') or '').split(' ')[0],
        **msj.datos_negocio(),
        'numero': orden['numero'],
        'equipo': ' '.join(p for p in (tipos.nombre(orden['tipo']).lower(), orden.get('marca'), orden.get('modelo')) if p),
        'enlace': enlace_publico(orden['token_publico']),
        'valor': ('$' + '{:,.0f}'.format(float(valor)).replace(',', '.')) if valor is not None else 'por confirmar',
        'garantia': orden['garantia_hasta'].strftime('%d/%m/%Y') if orden.get('garantia_hasta') else '',
    }


def aviso_estado(orden):
    """Mensaje para avisar al cliente del estado actual (botón de WhatsApp en la
    orden). None si el estado no tiene aviso."""
    estado = orden['estado']
    if estado not in ESTADOS_CON_CORREO:
        return None
    asunto, texto = msj.armar(estado, _datos_orden(orden, estado))
    with get_db_cursor() as cur:
        cur.execute("SELECT 1 FROM st_eventos WHERE orden_id = %s AND tipo = 'correo' AND detalle LIKE %s LIMIT 1",
                    (orden['id'], f'correo:{estado}%'))
        correo_enviado = cur.fetchone() is not None
    telefono = orden.get('cliente_whatsapp') or orden.get('cliente_telefono')
    return {'estado': estado, 'asunto': asunto, 'texto': texto, 'wa_url': whatsapp_url(telefono, texto),
            'correo': orden.get('cliente_email'), 'correo_enviado': correo_enviado}


def correo_estado(orden_id, estado, en_hilo=True, forzar=False):
    """Avisa al cliente por correo del nuevo estado, una sola vez por estado.
    Por defecto en un hilo: la página no espera al servidor de correo."""
    if estado not in ESTADOS_CON_CORREO:
        return False
    cfg = msj.config()
    if not cfg.get(f'st_correo_{estado}') and not forzar:
        return False
    from services.servicio_tecnico_service import obtener_orden
    orden = obtener_orden(orden_id)
    if not orden or not orden.get('cliente_email'):
        return False
    marca = f'correo:{estado}'
    with get_db_cursor() as cur:
        cur.execute("SELECT 1 FROM st_eventos WHERE orden_id = %s AND tipo = 'correo' AND detalle LIKE %s LIMIT 1",
                    (orden_id, marca + '%'))
        if cur.fetchone() and not forzar:
            return False
    datos = _datos_orden(orden, estado)
    asunto, texto = msj.armar(estado, datos, cfg)
    html = msj.html_correo(asunto, texto, datos['negocio'], datos['enlace'] or None)

    # Se marca ANTES de enviar: dos clics seguidos no mandan dos correos.
    from services.servicio_tecnico_service import _evento
    with get_db_cursor() as cur:
        _evento(cur, orden_id, orden['equipo_id'], 'correo', f'{marca} · Correo «{asunto}» a {orden["cliente_email"]}')

    def _mandar(app):
        with app.app_context():
            if not _enviar(orden['cliente_email'], asunto, texto, html):
                with get_db_cursor() as cur:
                    _evento(cur, orden_id, orden['equipo_id'], 'nota', f'No se pudo enviar el correo «{asunto}»')

    app = current_app._get_current_object()
    if en_hilo:
        threading.Thread(target=_mandar, args=(app,), daemon=True).start()
    else:
        _mandar(app)
    return True


# ── Encuesta de satisfacción (página pública) ───────────────────
def encuesta_respondida(orden_id):
    with get_db_cursor() as cur:
        cur.execute("""SELECT calificacion FROM st_seguimientos
                       WHERE orden_id = %s AND tipo = 'satisfaccion' AND calificacion IS NOT NULL LIMIT 1""",
                    (orden_id,))
        fila = cur.fetchone()
    return fila[0] if fila else None


def registrar_encuesta(orden, calificacion, comentario=''):
    """Guarda la calificación (1 a 5). Una calificación de 3 o menos crea una
    alerta urgente para el dueño. Devuelve False si ya había respondido."""
    try:
        calificacion = int(calificacion)
    except (TypeError, ValueError):
        raise ValueError('Escoge de 1 a 5 estrellas.')
    if not 1 <= calificacion <= 5:
        raise ValueError('Escoge de 1 a 5 estrellas.')
    comentario = (comentario or '').strip()[:1000] or None
    from services.servicio_tecnico_service import _evento
    with get_db_cursor() as cur:
        cur.execute('SELECT id FROM st_ordenes WHERE id = %s FOR UPDATE', (orden['id'],))
        cur.execute("""SELECT id, estado, calificacion FROM st_seguimientos
                       WHERE orden_id = %s AND tipo = 'satisfaccion' ORDER BY id LIMIT 1""", (orden['id'],))
        seg = cur.fetchone()
        if seg and seg[2] is not None:
            return False
        if seg:
            cur.execute("""UPDATE st_seguimientos SET calificacion = %s, comentario = %s, estado = 'hecho',
                                  canal = COALESCE(canal, 'encuesta'), hecho_en = COALESCE(hecho_en, NOW())
                           WHERE id = %s""", (calificacion, comentario, seg[0]))
        else:
            cur.execute("""INSERT INTO st_seguimientos (orden_id, equipo_id, crm_contacto_id, tipo, fecha_programada,
                                                        canal, estado, calificacion, comentario, hecho_en)
                           VALUES (%s, %s, %s, 'satisfaccion', CURRENT_DATE, 'encuesta', 'hecho', %s, %s, NOW())""",
                        (orden['id'], orden['equipo_id'], orden['crm_contacto_id'], calificacion, comentario))
        _evento(cur, orden['id'], orden['equipo_id'], 'nota',
                f"El cliente calificó el servicio: {'★' * calificacion}{'☆' * (5 - calificacion)}"
                + (f' — «{comentario}»' if comentario else ''))
        if calificacion <= 3:
            programar(cur, 'calificacion_baja', date.today(), orden_id=orden['id'], equipo_id=orden['equipo_id'],
                      contacto_id=orden['crm_contacto_id'], canal='llamada')
    return True


# ── Recordatorios automáticos por correo (cron) ─────────────────
def enviar_vencidos_por_correo(limite=50):
    """Manda por correo los recordatorios vencidos de clientes con correo.
    Los demás quedan en la bandeja para WhatsApp. Devuelve cuántos salieron."""
    cfg = msj.config()
    if not cfg.get('st_correo_seguimientos'):
        return 0
    with get_db_cursor() as cur:
        cur.execute("""SELECT s.id FROM st_seguimientos s
                       LEFT JOIN st_ordenes o ON o.id = s.orden_id
                       LEFT JOIN crm_contactos c ON c.id = COALESCE(s.crm_contacto_id, o.crm_contacto_id)
                       WHERE s.estado = 'pendiente' AND s.fecha_programada <= CURRENT_DATE
                         AND s.tipo = ANY(%s) AND COALESCE(c.email, '') LIKE '%%@%%'
                       ORDER BY s.fecha_programada LIMIT %s""", (list(AUTO_CORREO), limite))
        ids = [r[0] for r in cur.fetchall()]
    enviados = 0
    for seg_id in ids:
        ok, _ = enviar_correo_seguimiento(seg_id)
        enviados += 1 if ok else 0
    return enviados


# ── Resumen diario para el dueño ────────────────────────────────
def _destinatarios(cfg):
    if cfg['resumen_destinos']:
        return cfg['resumen_destinos']
    with get_db_cursor() as cur:
        cur.execute("""SELECT email FROM usuarios WHERE rol_id IN (1, 2) AND estado = 'habilitado'
                       AND email LIKE '%%@%%' ORDER BY rol_id DESC, id LIMIT 3""")
        return [r[0] for r in cur.fetchall()]


def datos_resumen():
    grupos = bandeja(horizonte=0)
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT estado, COUNT(*) AS n FROM st_ordenes
                       WHERE estado = ANY(%s) GROUP BY estado""",
                    (['recibido', 'diagnostico', 'cotizado', 'aprobado', 'reparacion', 'listo', 'garantia'],))
        taller = {r['estado']: r['n'] for r in cur.fetchall()}
        cur.execute("""SELECT o.numero, o.fecha_promesa, c.nombre FROM st_ordenes o
                       LEFT JOIN crm_contactos c ON c.id = o.crm_contacto_id
                       WHERE o.estado = ANY(%s) AND o.fecha_promesa IS NOT NULL AND o.fecha_promesa <= CURRENT_DATE
                       ORDER BY o.fecha_promesa LIMIT 20""",
                    (['recibido', 'diagnostico', 'cotizado', 'aprobado', 'reparacion'],))
        vencidas = [dict(r) for r in cur.fetchall()]
    return {'pendientes': grupos['atrasados'] + grupos['hoy'], 'taller': taller, 'promesas_vencidas': vencidas}


def enviar_resumen(forzar=False, prueba=False):
    """Correo de la mañana con lo que hay que atender hoy."""
    cfg = msj.config()
    hoy = date.today().isoformat()
    if not forzar and not prueba:
        if not cfg['resumen_activo']:
            return {'enviado': False, 'motivo': 'resumen apagado'}
        if cfg['resumen_ultimo'] == hoy:
            return {'enviado': False, 'motivo': 'ya se envió hoy'}
    d = datos_resumen()
    negocio = msj.datos_negocio()['negocio']
    asunto = f"Servicio técnico hoy: {len(d['pendientes'])} seguimientos · {negocio}"
    lineas = [f"Buenos días. Esto es lo que hay que atender hoy en {negocio}:", '']
    if d['pendientes']:
        lineas.append('SEGUIMIENTOS')
        for p in d['pendientes']:
            atraso = f" (atrasado {p['dias']} d)" if p['dias'] > 0 else ''
            lineas.append(f"- {p['tipo_nombre']}: {p['nombre_cliente']} {p.get('numero') or ''}{atraso}")
        lineas.append('')
    else:
        lineas += ['No hay seguimientos para hoy.', '']
    if d['promesas_vencidas']:
        lineas.append('ENTREGAS PROMETIDAS PARA HOY O ANTES')
        for o in d['promesas_vencidas']:
            lineas.append(f"- {o['numero']} · {o['nombre'] or ''} · prometido {o['fecha_promesa'].strftime('%d/%m')}")
        lineas.append('')
    en_taller = sum(d['taller'].values())
    lineas.append(f"Equipos en el taller: {en_taller} (listos para entregar: {d['taller'].get('listo', 0)}, "
                  f"esperando cotización: {d['taller'].get('cotizado', 0)}).")
    texto = '\n'.join(lineas)
    destinos = _destinatarios(cfg)
    if prueba:
        return {'enviado': False, 'prueba': True, 'asunto': asunto, 'texto': texto, 'destinos': destinos}
    if not destinos:
        return {'enviado': False, 'motivo': 'sin destinatarios'}
    import html as _h
    html = ('<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;color:#1f2937">'
            + ''.join(f'<p style="margin:4px 0">{_h.escape(l)}</p>' if l else '<br>' for l in lineas) + '</div>')
    ok = [dst for dst in destinos if _enviar(dst, asunto, texto, html)]
    if ok:
        msj.marcar_resumen_enviado(hoy)
    return {'enviado': bool(ok), 'destinos': ok, 'fallidos': [x for x in destinos if x not in ok], 'asunto': asunto}


# ── Consultas para la orden y la página pública ─────────────────
def de_orden(orden_id):
    """Seguimientos de una orden (pendientes primero) para mostrarlos en ella."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT id, tipo, fecha_programada, estado, canal, calificacion, comentario, hecho_en
                       FROM st_seguimientos WHERE orden_id = %s
                       ORDER BY (estado = 'pendiente') DESC, fecha_programada""", (orden_id,))
        filas = [dict(r) for r in cur.fetchall()]
    for f in filas:
        f['tipo_nombre'], f['tipo_icono'], _ = TIPOS.get(f['tipo'], (f['tipo'], 'bell', ''))
    return filas


def total_cotizacion(cotizacion_id):
    with get_db_cursor() as cur:
        cur.execute('SELECT total FROM cotizaciones WHERE id = %s', (cotizacion_id,))
        fila = cur.fetchone()
    return fila[0] if fila else None


_CONTEO = {}


def contar_pendientes_cache(segundos=60):
    """contar_pendientes con caché corta por base (se pinta en cada página del panel)."""
    import time
    from database import _current_db_name
    db = _current_db_name()
    ahora = time.time()
    valor = _CONTEO.get(db)
    if valor and ahora - valor[0] < segundos:
        return valor[1]
    n = contar_pendientes()
    _CONTEO[db] = (ahora, n)
    return n
