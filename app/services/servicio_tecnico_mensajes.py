"""Servicio Técnico: configuración y plantillas de los mensajes al cliente.

Los mensajes funcionan SIN IA: plantillas fijas con los datos de la orden. El
dueño puede cambiarlas en Configuración (se guardan en `cliente_config` con la
clave `st_msg_<tipo>`). Variables disponibles en las plantillas:

  {cliente}  primer nombre del cliente      {negocio}   nombre del negocio
  {numero}   número de la orden (OS-…)      {equipo}    tipo, marca y modelo
  {enlace}   página de estado / encuesta    {valor}     valor (cotizado o cobrado)
  {garantia} fecha fin de garantía          {pieza}     pieza a revisar
  {telefono} teléfono / WhatsApp del negocio

Una variable mal escrita no rompe el mensaje: queda vacía.
"""

from database import get_db_cursor

# ── Configuración (clave, valor por defecto, etiqueta) ──────────
DIAS = [
    ('st_dias_cotizacion', 2, 'Días para recordar una cotización sin respuesta'),
    ('st_dias_listo', 3, 'Días con el equipo listo sin recoger antes de recordar'),
    ('st_dias_satisfaccion', 7, 'Días después de entregar para preguntar cómo le fue'),
    ('st_dias_garantia', 5, 'Días antes de vencer la garantía para avisar'),
    ('st_meses_mantenimiento', 6, 'Meses después de entregar para ofrecer mantenimiento (0 = no)'),
]

# Correos automáticos al cliente (solo si el contacto tiene correo).
CORREOS = [
    ('st_correo_recibido', True, 'Equipo recibido (con el enlace de estado)'),
    ('st_correo_cotizado', True, 'Cotización lista'),
    ('st_correo_listo', True, 'Equipo listo para recoger'),
    ('st_correo_entregado', True, 'Equipo entregado (con la garantía)'),
    ('st_correo_seguimientos', True, 'Recordatorios programados por correo (encuesta, garantía, mantenimiento, listo sin recoger)'),
]

CLAVE_RESUMEN = 'st_resumen_activo'
CLAVE_DESTINOS = 'st_resumen_destinos'
CLAVE_ULTIMO_RESUMEN = 'st_resumen_ultimo'

# ── Plantillas por tipo de mensaje ──────────────────────────────
# (tipo, nombre visible, asunto del correo, texto)
PLANTILLAS = [
    ('recibido', 'Equipo recibido', 'Recibimos tu equipo · {numero}',
     'Hola {cliente}, recibimos tu {equipo} en {negocio}. Tu orden es la {numero}. '
     'Puedes ver cómo va aquí: {enlace}'),
    ('cotizado', 'Cotización lista', 'Tu cotización está lista · {numero}',
     'Hola {cliente}, ya revisamos tu {equipo} (orden {numero}). La cotización es de {valor}. '
     '¿Nos confirmas si seguimos con la reparación? Detalle: {enlace}'),
    ('listo', 'Listo para recoger', 'Tu equipo está listo · {numero}',
     'Hola {cliente}, tu {equipo} ya está listo para recoger en {negocio} (orden {numero}). ¡Te esperamos!'),
    ('entregado', 'Entregado', 'Gracias por confiar en {negocio} · {numero}',
     'Hola {cliente}, gracias por traer tu {equipo} a {negocio}. Tu garantía va hasta el {garantia}. '
     'Si algo falla, escríbenos citando la orden {numero}.'),
    ('cotizacion_sin_respuesta', 'Cotización sin respuesta', 'Seguimos atentos a tu cotización',
     'Hola {cliente}, te escribimos de {negocio} por la cotización de {valor} que te enviamos. '
     '¿Tienes alguna duda o la revisamos juntos?'),
    ('listo_sin_recoger', 'Listo sin recoger', 'Tu equipo te está esperando · {numero}',
     'Hola {cliente}, te recordamos que tu {equipo} está listo en {negocio} desde hace unos días '
     '(orden {numero}). ¿Cuándo pasas por él?'),
    ('satisfaccion', '¿Cómo le fue?', '¿Cómo te ha ido con tu equipo?',
     'Hola {cliente}, ¿cómo te ha ido con tu {equipo} después del servicio en {negocio}? '
     'Nos ayudas mucho calificándonos aquí (1 minuto): {enlace}'),
    ('garantia_por_vencer', 'Garantía por vencer', 'Tu garantía vence pronto · {numero}',
     'Hola {cliente}, la garantía del servicio de tu {equipo} vence el {garantia}. '
     'Si notas cualquier falla, tráelo antes de esa fecha (orden {numero}).'),
    ('mantenimiento', 'Mantenimiento preventivo', 'Es buen momento para un mantenimiento',
     'Hola {cliente}, hace unos meses revisamos tu {equipo} en {negocio}. '
     'Un mantenimiento preventivo lo mantiene rápido y evita daños mayores. ¿Te agendamos?'),
    ('revision_pieza', 'Revisión de pieza', 'Revisión programada de tu equipo',
     'Hola {cliente}, se cumple la fecha de revisión de {pieza} de tu {equipo}. '
     '¿Quieres que lo revisemos? Escríbenos y te damos un espacio.'),
    ('calificacion_baja', 'Calificación baja', 'Un cliente quedó inconforme',
     'Hola {cliente}, vimos tu calificación del servicio de tu {equipo}. Queremos entender qué pasó '
     'y solucionarlo. ¿Podemos llamarte?'),
]
PLANTILLA_POR_TIPO = {p[0]: p for p in PLANTILLAS}


class _Seguro(dict):
    def __missing__(self, clave):
        return ''


def _leer(claves):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT clave, valor FROM cliente_config WHERE clave = ANY(%s)', (list(claves),))
            return {r['clave']: r['valor'] for r in cur.fetchall()}
    except Exception:  # noqa: BLE001
        return {}


def _bool(valor, defecto):
    if valor is None or str(valor).strip() == '':
        return defecto
    return str(valor).strip().lower() in ('1', 'true', 'si', 'sí', 'on')


def _entero(valor, defecto, minimo=0, maximo=3650):
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        return defecto
    return max(minimo, min(maximo, n))


def config():
    """Configuración efectiva (con valores por defecto)."""
    claves = ([c[0] for c in DIAS] + [c[0] for c in CORREOS] + [CLAVE_RESUMEN, CLAVE_DESTINOS, CLAVE_ULTIMO_RESUMEN]
              + ['st_msg_' + p[0] for p in PLANTILLAS])
    v = _leer(claves)
    cfg = {c[0]: _entero(v.get(c[0]), c[1]) for c in DIAS}
    cfg.update({c[0]: _bool(v.get(c[0]), c[1]) for c in CORREOS})
    cfg['resumen_activo'] = _bool(v.get(CLAVE_RESUMEN), False)
    cfg['resumen_destinos'] = [d.strip() for d in (v.get(CLAVE_DESTINOS) or '').split(',') if '@' in d]
    cfg['resumen_ultimo'] = v.get(CLAVE_ULTIMO_RESUMEN) or None
    cfg['plantillas'] = {p[0]: (v.get('st_msg_' + p[0]) or '').strip() or p[3] for p in PLANTILLAS}
    cfg['plantillas_editadas'] = {p[0] for p in PLANTILLAS if (v.get('st_msg_' + p[0]) or '').strip()}
    return cfg


def guardar_config(form):
    """Guarda lo que llega del formulario de Configuración."""
    from services.config_tenant import set_cliente_config
    with get_db_cursor() as cur:
        for clave, defecto, etiqueta in DIAS:
            if clave in form:
                set_cliente_config(cur, clave, str(_entero(form.get(clave), defecto)), tipo='numero',
                                   grupo='servicio_tecnico', descripcion=etiqueta)
        for clave, _d, etiqueta in CORREOS:
            set_cliente_config(cur, clave, 'true' if form.get(clave) else 'false', tipo='boolean',
                               grupo='servicio_tecnico', descripcion=etiqueta)
        set_cliente_config(cur, CLAVE_RESUMEN, 'true' if form.get(CLAVE_RESUMEN) else 'false',
                           tipo='boolean', grupo='servicio_tecnico', descripcion='Resumen diario al dueño')
        destinos = ','.join(d.strip() for d in (form.get(CLAVE_DESTINOS) or '').split(',') if '@' in d)[:500]
        set_cliente_config(cur, CLAVE_DESTINOS, destinos, grupo='servicio_tecnico',
                           descripcion='Correos del resumen diario')
        for tipo, _n, _a, original in PLANTILLAS:
            clave = 'st_msg_' + tipo
            if clave in form:
                texto = (form.get(clave) or '').strip()[:1000]
                # Igual a la original = sin personalizar (así le llegan mejoras futuras).
                set_cliente_config(cur, clave, '' if texto == original else texto,
                                   grupo='servicio_tecnico', descripcion=f'Mensaje: {tipo}')


def marcar_resumen_enviado(fecha_iso):
    from services.config_tenant import set_cliente_config
    with get_db_cursor() as cur:
        set_cliente_config(cur, CLAVE_ULTIMO_RESUMEN, fecha_iso, grupo='servicio_tecnico',
                           descripcion='Último resumen diario enviado')


def datos_negocio():
    try:
        from services.public_site_service import get_brand_config
        marca = get_brand_config() or {}
    except Exception:  # noqa: BLE001
        marca = {}
    return {'negocio': marca.get('empresa_nombre') or 'nuestro taller',
            'telefono': marca.get('empresa_whatsapp') or marca.get('empresa_telefono') or ''}


def armar(tipo, datos, cfg=None):
    """(asunto, texto) del mensaje `tipo` con los datos de la orden."""
    cfg = cfg or config()
    plantilla = PLANTILLA_POR_TIPO.get(tipo)
    if not plantilla:
        return '', ''
    valores = _Seguro({k: ('' if v is None else str(v)) for k, v in datos.items()})
    texto = cfg['plantillas'].get(tipo, plantilla[3])
    try:
        texto = texto.format_map(valores)
    except (ValueError, IndexError, AttributeError):
        texto = plantilla[3].format_map(valores)
    try:
        asunto = plantilla[2].format_map(valores)
    except (ValueError, IndexError):
        asunto = plantilla[1]
    return asunto, ' '.join(texto.split())


def html_correo(asunto, texto, negocio, enlace=None, boton='Ver mi orden'):
    """Correo sencillo con la marca (los colores fijos aquí son del correo:
    los clientes de correo no leen variables CSS)."""
    import html as _h
    try:
        from services.public_site_service import get_brand_config
        color = (get_brand_config() or {}).get('color_primario') or '#1e3a8a'
    except Exception:  # noqa: BLE001
        color = '#1e3a8a'
    boton_html = ''
    if enlace:
        boton_html = (f'<p style="margin:26px 0"><a href="{_h.escape(enlace)}" style="background:{_h.escape(color)};'
                      f'color:#ffffff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:bold">'
                      f'{_h.escape(boton)}</a></p>')
    return (f'<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#1f2937">'
            f'<h2 style="color:{_h.escape(color)};margin-bottom:6px">{_h.escape(negocio)}</h2>'
            f'<p style="font-size:15px;line-height:1.55">{_h.escape(texto)}</p>{boton_html}'
            f'<p style="font-size:12px;color:#6b7280">{_h.escape(asunto)}</p></div>')


def rellenar(texto, datos):
    """Rellena una plantilla con los datos (variables desconocidas quedan vacías)."""
    try:
        texto = texto.format_map(_Seguro({k: ('' if v is None else str(v)) for k, v in datos.items()}))
    except (ValueError, IndexError, AttributeError):
        pass
    return ' '.join(texto.split())
