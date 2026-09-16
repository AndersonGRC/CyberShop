"""Resumen diario del negocio por correo.

Contenido: las ventas de ayer y las alertas, calculadas con consultas (no con el
modelo de IA). Si el servidor de IA responde a tiempo se agrega un párrafo
redactado por la IA; si está apagado, el correo sale igual.

Nunca incluye nómina ni datos personales de clientes.

Configuración por cliente, en cliente_config:
  ia_resumen_correo_activo    'true' | 'false'   (apagado por defecto)
  ia_resumen_correo_destinos  correos separados por coma (vacío = dueños del negocio)
  ia_resumen_correo_ultimo    fecha del último envío (evita duplicados)
"""

import json
from datetime import date

from flask import current_app

from database import get_db_cursor

CLAVE_ACTIVO = 'ia_resumen_correo_activo'
CLAVE_DESTINOS = 'ia_resumen_correo_destinos'
CLAVE_ULTIMO = 'ia_resumen_correo_ultimo'
_COLOR = {'alta': '#dc3545', 'media': '#e0a800', 'info': '#0d6efd'}


def leer_config():
    valores = {}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT clave, valor FROM cliente_config WHERE clave = ANY(%s)",
                        ([CLAVE_ACTIVO, CLAVE_DESTINOS, CLAVE_ULTIMO],))
            valores = {r['clave']: r['valor'] for r in cur.fetchall()}
    except Exception:
        pass
    return {
        'activo': str(valores.get(CLAVE_ACTIVO, 'false')).strip().lower() in ('1', 'true', 'si', 'sí'),
        'destinos': [c.strip() for c in (valores.get(CLAVE_DESTINOS) or '').split(',') if c.strip()],
        'ultimo_envio': valores.get(CLAVE_ULTIMO) or None,
    }


def guardar_config(activo=None, destinos=None):
    """Guarda el interruptor y los destinatarios (lo usa el panel del dueño)."""
    cambios = {}
    if activo is not None:
        cambios[CLAVE_ACTIVO] = 'true' if activo else 'false'
    if destinos is not None:
        limpios = [c.strip() for c in destinos if c and '@' in c]
        cambios[CLAVE_DESTINOS] = ', '.join(limpios[:5])
    with get_db_cursor() as cur:
        for clave, valor in cambios.items():
            cur.execute("""INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion)
                           VALUES (%s, %s, 'texto', 'sistema', 'Resumen diario del negocio por correo')
                           ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor""", (clave, valor))
    return leer_config()


def _marcar_enviado(hoy):
    try:
        with get_db_cursor() as cur:
            cur.execute("""INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion)
                           VALUES (%s, %s, 'texto', 'sistema', 'Último envío del resumen diario')
                           ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor""",
                        (CLAVE_ULTIMO, hoy.isoformat()))
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'resumen diario: no se pudo marcar el envío: {exc}')


def _destinatarios(config):
    if config['destinos']:
        return config['destinos']
    # Sin destinatarios configurados: los dueños del negocio con correo.
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""SELECT email FROM usuarios
                           WHERE rol_id IN (1, 2) AND email IS NOT NULL AND TRIM(email) <> ''
                           ORDER BY rol_id LIMIT 3""")
            return [r['email'] for r in cur.fetchall()]
    except Exception:
        return []


def _parrafo_ia(datos):
    """Párrafo de la IA, si el motor responde pronto. Nunca bloquea el correo."""
    try:
        import services.ai_service as ai
        if not ai.ia_disponible():
            return None
        user = ('Con estos datos REALES del negocio de AYER (JSON), escribe 2 o 3 frases para el dueño: '
                'qué pasó y qué conviene atender hoy. Sin saludos, sin inventar cifras.\n\n'
                + json.dumps(datos, ensure_ascii=False, default=str))
        texto, err = ai._chat(ai._contexto_tenant(), user, max_tokens=220, temperature=0.4,
                              espera_frio=60)
        return None if err else texto
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'resumen diario: sin párrafo de IA ({exc})')
        return None


def construir(con_ia=True):
    """Arma el resumen: (asunto, texto_plano, html, datos)."""
    from services.ia_datos.acceso import Contexto
    from services.ia_datos.alertas import alertas_para_correo
    import services.ai_tools as tools

    sistema = Contexto(canal='sistema')
    ventas = tools.ejecutar('ventas_periodo', {'periodo': 'ayer'}, sistema) or {}
    pendientes = tools.ejecutar('pedidos_por_despachar', {}, sistema) or {}
    alertas = alertas_para_correo()
    datos = {'ventas_de_ayer': ventas, 'pedidos_por_despachar': pendientes.get('cantidad'),
             'alertas': [{'nivel': a['nivel'], 'titulo': a['titulo']} for a in alertas['alertas']]}
    parrafo = _parrafo_ia(datos) if con_ia else None

    negocio = 'tu negocio'
    try:
        from services.public_site_service import get_brand_config
        negocio = (get_brand_config() or {}).get('empresa_nombre') or negocio
    except Exception:
        pass

    urgentes = alertas['urgentes']
    asunto = f"Resumen de {negocio}: {ventas.get('total_en_periodo', 'sin ventas')} ayer"
    if urgentes:
        asunto += f" · {urgentes} urgente(s)"

    lineas = [f"Resumen de {negocio}", '',
              f"Ventas de ayer: {ventas.get('total_en_periodo', '$ 0')} "
              f"({ventas.get('ventas_en_periodo', 0)} ventas)"]
    desglose = ventas.get('desglose_periodo') or {}
    for clave, etiqueta in (('web', 'Tienda web'), ('pos_mostrador', 'Mostrador y mesas'),
                            ('pos_escritorio', 'POS de escritorio')):
        d = desglose.get(clave) or {}
        if d.get('n'):
            lineas.append(f"  - {etiqueta}: {d['monto']} ({d['n']})")
    if pendientes.get('cantidad'):
        lineas.append(f"Pedidos por despachar: {pendientes['cantidad']}")
    lineas.append('')
    if alertas['cantidad']:
        lineas.append('Qué atender hoy:')
        lineas += [f"  - [{a['nivel']}] {a['titulo']}: {a['detalle']}" for a in alertas['alertas']]
    else:
        lineas.append('No hay alertas pendientes.')
    if parrafo:
        lineas += ['', parrafo]
    texto = '\n'.join(lineas)

    filas_alertas = ''.join(
        f"<tr><td style='padding:8px 12px;border-bottom:1px solid #eee;color:{_COLOR.get(a['nivel'], '#666')};"
        f"font-weight:700;white-space:nowrap;'>{a['nivel'].upper()}</td>"
        f"<td style='padding:8px 12px;border-bottom:1px solid #eee;'><strong>{a['titulo']}</strong><br>"
        f"<span style='color:#666;font-size:0.92em;'>{a['detalle']}</span></td></tr>"
        for a in alertas['alertas'])
    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:620px;margin:0 auto;border:1px solid #e0e0e0;border-radius:12px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#122C94,#29A9E2);padding:22px 28px;">
        <h2 style="color:#fff;margin:0;font-size:19px;">Resumen de {negocio}</h2>
        <div style="color:#dbe7ff;font-size:13px;margin-top:4px;">Ventas de ayer y qué atender hoy</div>
      </div>
      <div style="padding:24px 28px;background:#fff;">
        <div style="font-size:28px;font-weight:800;color:#122C94;">{ventas.get('total_en_periodo', '$ 0')}</div>
        <div style="color:#666;font-size:13px;margin-bottom:14px;">{ventas.get('ventas_en_periodo', 0)} ventas ayer
          {'· ' + str(pendientes['cantidad']) + ' pedido(s) por despachar' if pendientes.get('cantidad') else ''}</div>
        {'<p style="background:#f4f6fb;border-left:3px solid #7c3aed;padding:12px 16px;border-radius:0 8px 8px 0;color:#333;line-height:1.6;">' + parrafo + '</p>' if parrafo else ''}
        {'<table style="width:100%;border-collapse:collapse;font-size:14px;margin-top:8px;">' + filas_alertas + '</table>' if filas_alertas else '<p style="color:#1a7a3f;">No hay alertas pendientes: todo en orden.</p>'}
      </div>
      <div style="background:#f4f6fb;padding:12px 28px;text-align:center;font-size:12px;color:#999;">
        Resumen automático de CyberShop · puedes desactivarlo desde el panel del Asistente IA
      </div>
    </div>"""
    return asunto, texto, html, datos


def enviar_diario(forzar=False, prueba=False):
    """Envía el resumen si está activo y no se ha enviado hoy.
    prueba=True arma el correo y lo devuelve sin enviarlo."""
    config = leer_config()
    hoy = date.today()
    if not config['activo'] and not (forzar or prueba):
        return {'enviado': False, 'motivo': 'El resumen diario está desactivado para este negocio.'}
    if config['ultimo_envio'] == hoy.isoformat() and not (forzar or prueba):
        return {'enviado': False, 'motivo': 'Ya se envió hoy.'}
    destinos = _destinatarios(config)
    if not destinos and not prueba:
        return {'enviado': False, 'motivo': 'No hay a quién enviarlo: configura un correo.'}

    asunto, texto, html, datos = construir()
    if prueba:
        return {'enviado': False, 'prueba': True, 'destinos': destinos, 'asunto': asunto,
                'texto': texto, 'html': html}

    from helpers_gmail import enviar_email_gmail
    enviados, fallidos = [], []
    for correo in destinos:
        try:
            (enviados if enviar_email_gmail(correo, asunto, texto, html=html) else fallidos).append(correo)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.warning(f'resumen diario: falló el envío a {correo}: {exc}')
            fallidos.append(correo)
    if enviados:
        _marcar_enviado(hoy)
    return {'enviado': bool(enviados), 'destinos': enviados, 'fallidos': fallidos, 'asunto': asunto}
