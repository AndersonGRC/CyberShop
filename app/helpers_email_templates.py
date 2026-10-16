"""
helpers_email_templates.py — Templates HTML para emails del sistema.

Genera cuerpos HTML con branding dinamico usando Config.BRAND_COLORS
y datos de cliente_config (empresa_nombre, empresa_email).
"""

from database import get_db_cursor
from helpers import formatear_moneda


def _get_empresa_info():
    """Obtiene nombre, email, telefono, WhatsApp y URL de la empresa desde cliente_config."""
    info = {'nombre': 'CyberShop', 'email': '', 'telefono': '', 'url': '', 'whatsapp': '', 'website': ''}
    campos = {'empresa_nombre': 'nombre', 'empresa_email': 'email', 'empresa_telefono': 'telefono',
              'empresa_url': 'url', 'empresa_whatsapp': 'whatsapp', 'empresa_website': 'website'}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT clave, valor FROM cliente_config WHERE clave = ANY(%s)", (list(campos),))
            for row in cur.fetchall():
                if row['valor']:
                    info[campos[row['clave']]] = row['valor']
        # Nunca el WhatsApp o el celular de CyberShop en los correos de la tienda de un
        # cliente (quedaban guardados al grabar el formulario con el valor por defecto).
        from services.public_site_service import es_contacto_de_cybershop
        for campo in ('whatsapp', 'telefono'):
            if es_contacto_de_cybershop(info[campo]):
                info[campo] = ''
    except Exception:
        pass
    return info


def _esc(valor):
    """Texto que escribió el cliente (nombre, negocio): nunca HTML en el correo."""
    from html import escape
    return escape(str(valor or ''))


def _whatsapp_link(numero, texto=''):
    """Enlace wa.me con el número (solo dígitos; 10 dígitos → +57)."""
    import re
    from urllib.parse import quote
    digitos = re.sub(r'\D', '', str(numero or ''))
    if len(digitos) == 10:
        digitos = '57' + digitos
    if not digitos:
        return ''
    return f"https://wa.me/{digitos}" + (f"?text={quote(texto)}" if texto else '')


def _fecha(valor):
    """dd/mm/aaaa de una fecha (date o texto ISO); '' si no hay."""
    if not valor:
        return ''
    if hasattr(valor, 'strftime'):
        return valor.strftime('%d/%m/%Y')
    try:
        from datetime import date
        return date.fromisoformat(str(valor)[:10]).strftime('%d/%m/%Y')
    except ValueError:
        return str(valor)


def _ayuda_html(empresa, colores, texto_wa=''):
    """«¿Necesitas ayuda?» con el WhatsApp del negocio como enlace (o su teléfono)."""
    link = _whatsapp_link(empresa.get('whatsapp') or empresa.get('telefono'), texto_wa)
    if link:
        return (f'<p style="font-size:14px;color:#333;line-height:1.6;margin-top:18px;">¿Necesitas ayuda? '
                f'<a href="{link}" style="color:{colores["primario"]};font-weight:bold;">Escríbenos por WhatsApp</a></p>')
    if empresa.get('email'):
        return (f'<p style="font-size:14px;color:#333;line-height:1.6;margin-top:18px;">¿Necesitas ayuda? '
                f'Escríbenos a {_esc(empresa["email"])}</p>')
    return ''


def _get_colores():
    """Obtiene colores de marca desde Config."""
    from config import Config
    return Config.BRAND_COLORS


def _base_html(contenido, empresa):
    """Envuelve contenido en layout base de email."""
    colores = _get_colores()
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;background:#f4f4f7;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
  <!-- Header -->
  <tr>
    <td style="background:{colores['primario']};padding:24px 32px;text-align:center;">
      <h1 style="margin:0;color:#ffffff;font-size:24px;">{empresa['nombre']}</h1>
    </td>
  </tr>
  <!-- Body -->
  <tr>
    <td style="padding:32px;">
      {contenido}
    </td>
  </tr>
  <!-- Footer -->
  <tr>
    <td style="background:{colores['fondo_claro']};padding:16px 32px;text-align:center;border-top:1px solid #eee;">
      <p style="margin:0;font-size:12px;color:{colores['texto_claro']};">
        {empresa['nombre']}
        {(' | ' + empresa['email']) if empresa['email'] else ''}
        {(' | ' + empresa['telefono']) if empresa['telefono'] else ''}
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def _config_habilitada(clave):
    """Verifica si una config booleana esta habilitada."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = %s", (clave,))
            row = cur.fetchone()
            if row and row['valor'] == 'false':
                return False
    except Exception:
        pass
    return True


def generar_email_confirmacion_pedido(pedido, detalles=None):
    """Genera HTML de confirmacion de pedido aprobado.

    Args:
        pedido: dict con referencia_pedido, cliente_nombre, monto_total, metodo_pago, fecha_creacion
        detalles: lista de dicts con producto_nombre, cantidad, precio_unitario, subtotal

    Returns:
        tuple (asunto, texto_plano, html) o None si notificaciones desactivadas
    """
    if not _config_habilitada('notif_email_pedido'):
        return None

    empresa = _get_empresa_info()
    colores = _get_colores()
    ref = pedido.get('referencia_pedido', '')
    nombre = pedido.get('cliente_nombre', 'Cliente')
    total = formatear_moneda(pedido.get('monto_total', 0))
    metodo = pedido.get('metodo_pago', 'N/A')
    descuento = pedido.get('descuento_total', 0)

    # Tabla de detalles
    filas_html = ''
    if detalles:
        for d in detalles:
            filas_html += f"""<tr>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;">{d.get('producto_nombre','')}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:center;">{d.get('cantidad',0)}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{formatear_moneda(d.get('precio_unitario',0))}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{formatear_moneda(d.get('subtotal',0))}</td>
            </tr>"""

    tabla_detalles = ''
    if filas_html:
        tabla_detalles = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0;border:1px solid #eee;border-radius:6px;overflow:hidden;">
          <tr style="background:{colores['fondo_claro']};">
            <th style="padding:10px 12px;text-align:left;font-size:13px;">Producto</th>
            <th style="padding:10px 12px;text-align:center;font-size:13px;">Cant.</th>
            <th style="padding:10px 12px;text-align:right;font-size:13px;">Precio</th>
            <th style="padding:10px 12px;text-align:right;font-size:13px;">Subtotal</th>
          </tr>
          {filas_html}
        </table>"""

    descuento_html = ''
    if descuento and float(descuento) > 0:
        descuento_html = f"""
        <p style="margin:4px 0;font-size:14px;color:{colores['exito']};">
          Descuento aplicado: -{formatear_moneda(descuento)}
        </p>"""

    contenido = f"""
    <h2 style="margin:0 0 16px;color:{colores['primario']};font-size:20px;">
      ¡Pedido confirmado!
    </h2>
    <p style="margin:0 0 8px;font-size:15px;color:{colores['texto']};">
      Hola <strong>{nombre}</strong>, tu pago ha sido aprobado.
    </p>
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0;background:{colores['fondo_claro']};border-radius:6px;padding:16px;">
      <tr><td style="padding:6px 16px;">
        <strong>Referencia:</strong> {ref}
      </td></tr>
      <tr><td style="padding:6px 16px;">
        <strong>Método de pago:</strong> {metodo}
      </td></tr>
      <tr><td style="padding:6px 16px;">
        <strong>Total:</strong> <span style="font-size:18px;color:{colores['primario']};font-weight:bold;">{total}</span>
      </td></tr>
    </table>
    {descuento_html}
    {tabla_detalles}
    <p style="margin:16px 0 0;font-size:14px;color:{colores['texto_claro']};">
      Recibirás una notificación cuando tu pedido cambie de estado.
    </p>"""

    html = _base_html(contenido, empresa)
    texto = f"Hola {nombre}, tu pedido {ref} ha sido confirmado. Total: {total}. Método: {metodo}."
    asunto = f"Pedido confirmado - {ref}"

    return asunto, texto, html


def generar_email_bienvenida(nombre, email):
    """Genera HTML de bienvenida para nuevo cliente.

    Returns:
        tuple (asunto, texto_plano, html) o None si desactivado
    """
    if not _config_habilitada('notif_email_bienvenida'):
        return None

    empresa = _get_empresa_info()
    colores = _get_colores()

    contenido = f"""
    <h2 style="margin:0 0 16px;color:{colores['primario']};font-size:20px;">
      ¡Bienvenido/a a {empresa['nombre']}!
    </h2>
    <p style="margin:0 0 12px;font-size:15px;color:{colores['texto']};">
      Hola <strong>{nombre}</strong>, gracias por registrarte en nuestra tienda.
    </p>
    <p style="margin:0 0 12px;font-size:14px;color:{colores['texto']};">
      Tu cuenta ha sido creada exitosamente con el correo <strong>{email}</strong>.
      Ya puedes iniciar sesión y explorar nuestro catálogo.
    </p>
    {(f'<p style="margin:16px 0 0;text-align:center;"><a href="{empresa["url"]}" style="display:inline-block;padding:12px 32px;background:{colores["primario"]};color:#ffffff;text-decoration:none;border-radius:6px;font-weight:bold;">Ir a la tienda</a></p>') if empresa.get('url') else ''}"""

    html = _base_html(contenido, empresa)
    texto = f"Hola {nombre}, bienvenido/a a {empresa['nombre']}. Tu cuenta con el correo {email} ha sido creada."
    asunto = f"Bienvenido/a a {empresa['nombre']}"

    return asunto, texto, html


def generar_email_estado_envio(pedido, nuevo_estado):
    """Genera HTML de notificacion de cambio de estado de envio.

    Args:
        pedido: dict con referencia_pedido, cliente_nombre, monto_total
        nuevo_estado: string del nuevo estado de envio

    Returns:
        tuple (asunto, texto_plano, html) o None si desactivado
    """
    if not _config_habilitada('notif_email_envio'):
        return None

    empresa = _get_empresa_info()
    colores = _get_colores()
    ref = pedido.get('referencia_pedido', '')
    nombre = pedido.get('cliente_nombre', 'Cliente')

    estados_texto = {
        'POR_DESPACHAR': 'Por despachar',
        'ENVIADO': 'Enviado',
        'ENTREGADO': 'Entregado',
        'CANCELADO': 'Cancelado',
    }
    estado_display = estados_texto.get(nuevo_estado, nuevo_estado)

    color_estado = colores['primario']
    if nuevo_estado == 'ENTREGADO':
        color_estado = colores['exito']
    elif nuevo_estado == 'CANCELADO':
        color_estado = '#dc3545'

    contenido = f"""
    <h2 style="margin:0 0 16px;color:{colores['primario']};font-size:20px;">
      Actualización de tu pedido
    </h2>
    <p style="margin:0 0 12px;font-size:15px;color:{colores['texto']};">
      Hola <strong>{nombre}</strong>, tu pedido <strong>{ref}</strong> ha cambiado de estado.
    </p>
    <div style="text-align:center;margin:20px 0;">
      <span style="display:inline-block;padding:10px 24px;background:{color_estado};
            color:#ffffff;border-radius:20px;font-weight:bold;font-size:16px;">
        {estado_display}
      </span>
    </div>
    <p style="margin:16px 0 0;font-size:14px;color:{colores['texto_claro']};text-align:center;">
      Si tienes alguna pregunta, no dudes en contactarnos.
    </p>"""

    html = _base_html(contenido, empresa)
    texto = f"Hola {nombre}, tu pedido {ref} ahora está en estado: {estado_display}."
    asunto = f"Tu pedido {ref} - {estado_display}"

    return asunto, texto, html


# ════════════════════════════════════════════════════════════════
# VENTA AUTOMÁTICA DE PLANES (activación, bienvenida, renovaciones)
# ════════════════════════════════════════════════════════════════

def generar_email_activacion_plan(compra, plan, activacion_url):
    """'Tu pago fue aprobado — activa tu tienda' con botón al link único."""
    empresa = _get_empresa_info()
    colores = _get_colores()
    nombre = _esc(compra.get('buyer_nombre') or 'Hola')
    contenido = f"""
    <h2 style="margin:0 0 14px;color:{colores['primario']};">¡Tu pago fue aprobado! 🎉</h2>
    <p style="font-size:15px;line-height:1.6;color:#333;">Hola <strong>{nombre}</strong>,</p>
    <p style="font-size:15px;line-height:1.6;color:#333;">
      Tu compra del plan <strong>{plan.get('nombre')}</strong> está confirmada
      (referencia <code>{compra.get('referencia_pedido')}</code>).
      Solo falta un paso: <strong>activa tu tienda</strong> eligiendo el nombre
      de tu negocio y la dirección web que tendrá.
    </p>
    <p style="text-align:center;margin:28px 0;">
      <a href="{activacion_url}" style="background:{colores['primario']};color:#fff;
         padding:14px 34px;border-radius:8px;text-decoration:none;font-weight:bold;
         font-size:16px;display:inline-block;">Activar mi tienda ahora</a>
    </p>
    <p style="font-size:13px;color:#777;line-height:1.5;">
      El proceso toma 2-3 minutos y al finalizar recibirás otro correo con tus
      accesos. Si el botón no funciona, copia este enlace:<br>
      <a href="{activacion_url}" style="color:{colores['primario']};word-break:break-all;">{activacion_url}</a>
    </p>
    """
    asunto = f"Activa tu tienda — pago aprobado ({plan.get('nombre')})"
    texto = (f"Hola {compra.get('buyer_nombre') or ''}, tu pago del plan {plan.get('nombre')} fue aprobado. "
             f"Activa tu tienda aquí: {activacion_url}")
    return asunto, texto, _base_html(contenido, empresa)


def generar_email_bienvenida_tienda(compra, plan, resultado):
    """Bienvenida con los accesos de la tienda recién creada.
    `resultado` es la respuesta del maestro (domain, admin_email,
    admin_password, client_code)."""
    empresa = _get_empresa_info()
    colores = _get_colores()
    nombre = _esc(compra.get('buyer_nombre') or 'Hola')
    dominio = resultado.get('domain') or compra.get('dominio') or ''
    url_tienda = f"https://{dominio}"
    # /login y no /admin: sin sesión, /admin muestra «No tienes permiso».
    url_admin = f"https://{dominio}/login"
    prueba_html = ''
    if compra.get('es_trial') and compra.get('proximo_pago'):
        prueba_html = f"""
    <p style="font-size:14px;color:#1d4ed8;background:#eef4ff;border-radius:6px;padding:10px 14px;line-height:1.6;">
      🎁 <strong>Tu prueba gratis va hasta el {_fecha(compra['proximo_pago'])}</strong>,
      con todo el plan {_esc(plan.get('nombre'))}. Antes de que termine te escribimos para que elijas tu plan;
      no se cobra nada sin que tú lo pagues.</p>"""
    filas = f"""
      <tr><td style="padding:8px 12px;color:#555;">🌐 Tu tienda</td>
          <td style="padding:8px 12px;"><a href="{url_tienda}" style="color:{colores['primario']};font-weight:bold;">{url_tienda}</a></td></tr>
      <tr style="background:#f8f9fc;"><td style="padding:8px 12px;color:#555;">⚙️ Entrar a tu panel</td>
          <td style="padding:8px 12px;"><a href="{url_admin}" style="color:{colores['primario']};font-weight:bold;">{url_admin}</a></td></tr>
      <tr><td style="padding:8px 12px;color:#555;">👤 Usuario</td>
          <td style="padding:8px 12px;"><strong>{resultado.get('admin_email','')}</strong></td></tr>
      <tr style="background:#f8f9fc;"><td style="padding:8px 12px;color:#555;">🔑 Contraseña temporal</td>
          <td style="padding:8px 12px;"><code style="background:#eef2fa;padding:3px 8px;border-radius:4px;">{resultado.get('admin_password','')}</code></td></tr>
    """
    pos_html = ''
    if plan.get('tiene_app') and resultado.get('client_code'):
        web = (empresa.get('website') or '').strip().rstrip('/')
        if web and not web.startswith(('http://', 'https://')):
            web = 'https://' + web
        url_desc = f"{web or 'https://cybershopcol.com'}/descargar"
        pos_html = f"""
        <h3 style="color:{colores['primario']};margin:24px 0 8px;">🖥️ Tu punto de venta de escritorio</h3>
        <p style="font-size:14px;color:#333;line-height:1.6;">
          Descarga la app que funciona <strong>sin internet</strong> en
          <a href="{url_desc}" style="color:{colores['primario']};">{url_desc}</a>
          usando tu código de cliente:
          <code style="background:#eef2fa;padding:3px 8px;border-radius:4px;font-size:15px;">{resultado.get('client_code')}</code>
        </p>"""
    contenido = f"""
    <h2 style="margin:0 0 14px;color:{colores['primario']};">¡Tu tienda está lista! 🚀</h2>
    <p style="font-size:15px;line-height:1.6;color:#333;">Hola <strong>{nombre}</strong>,
      creamos tu tienda {'de prueba ' if compra.get('es_trial') else ''}del plan <strong>{_esc(plan.get('nombre'))}</strong>.
      Estos son tus accesos:</p>
    {prueba_html}
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e8edf6;border-radius:8px;overflow:hidden;font-size:14px;margin:14px 0;">
      {filas}
    </table>
    <p style="font-size:13px;color:#b45309;background:#fff7e6;border-radius:6px;padding:10px 14px;">
      ⚠️ Por seguridad, <strong>cambia la contraseña</strong> al entrar:
      <strong>Usuarios → Gestión de usuarios → Editar</strong>.
    </p>
    <h3 style="color:{colores['primario']};margin:24px 0 8px;">✨ Tus primeros pasos (5 minutos)</h3>
    <ol style="font-size:14px;color:#333;line-height:1.7;padding-left:20px;margin:0;">
      <li>Entra a <a href="{url_admin}" style="color:{colores['primario']};">{url_admin}</a> con tu usuario y la contraseña temporal.</li>
      <li>En <strong>Mi Negocio</strong>: sube tu logo (hoy ves «Tu logo aquí») y ajusta tus colores y textos.</li>
      <li>En <strong>Inventario</strong>: agrega tu primer producto y míralo en tu tienda.</li>
    </ol>
    {pos_html}
    {_ayuda_html(empresa, colores, f"Hola, necesito ayuda con mi tienda {dominio}")}
    """
    asunto = f"🚀 Tu tienda está lista — {dominio}"
    texto = (f"Hola {compra.get('buyer_nombre') or ''}, tu tienda está lista en {url_tienda}. "
             f"Entra en {url_admin} | Usuario: {resultado.get('admin_email')} | "
             f"Contraseña temporal: {resultado.get('admin_password')} (cámbiala al entrar)."
             + (f" Tu prueba gratis va hasta el {_fecha(compra['proximo_pago'])}."
                if compra.get('es_trial') and compra.get('proximo_pago') else ''))
    return asunto, texto, _base_html(contenido, empresa)


def generar_email_plan_anual(compra, plan):
    """Planes web anuales: confirmación + 'te contactaremos' (manejo manual)."""
    empresa = _get_empresa_info()
    colores = _get_colores()
    nombre = _esc(compra.get('buyer_nombre') or 'Hola')
    contenido = f"""
    <h2 style="margin:0 0 14px;color:{colores['primario']};">¡Gracias por tu compra! ✅</h2>
    <p style="font-size:15px;line-height:1.6;color:#333;">Hola <strong>{nombre}</strong>,</p>
    <p style="font-size:15px;line-height:1.6;color:#333;">
      Recibimos tu pago del plan <strong>{plan.get('nombre')}</strong>
      (referencia <code>{compra.get('referencia_pedido')}</code>).
      Un asesor te contactará en máximo <strong>1 día hábil</strong> para
      iniciar el diseño de tu proyecto web a la medida.
    </p>
    <p style="font-size:14px;color:#333;">¿Prefieres adelantarte? Escríbenos por
      WhatsApp: <strong>{empresa.get('whatsapp') or empresa.get('telefono','')}</strong></p>
    """
    asunto = f"Compra confirmada — {plan.get('nombre')}"
    texto = (f"Hola {compra.get('buyer_nombre') or ''}, recibimos tu pago del plan {plan.get('nombre')}. "
             f"Te contactaremos en máximo 1 día hábil.")
    return asunto, texto, _base_html(contenido, empresa)


def generar_email_aviso_operador(titulo, lineas):
    """Aviso interno al operador (ventas, renovaciones, vencidos).
    `lineas` es una lista de strings clave: valor."""
    empresa = _get_empresa_info()
    colores = _get_colores()
    # Las líneas traen datos que escribió el cliente (nombre, negocio): se escapan.
    from html import escape as _esc
    items = ''.join(f'<li style="padding:3px 0;font-size:14px;color:#333;">{_esc(str(l))}</li>' for l in lineas)
    contenido = f"""
    <h2 style="margin:0 0 14px;color:{colores['primario']};">{titulo}</h2>
    <ul style="padding-left:18px;margin:0;">{items}</ul>
    <p style="font-size:13px;color:#777;margin-top:18px;">
      Panel maestro: <a href="https://admin.cybershopcol.com" style="color:{colores['primario']};">admin.cybershopcol.com</a>
    </p>
    """
    texto = titulo + "\n" + "\n".join(lineas)
    return titulo, texto, _base_html(contenido, empresa)


def generar_email_recordatorio_pago(compra, plan, renovacion_url, etapa, dias=0):
    """Recordatorios de cobro: etapa 'previo' (5 dias antes), 'dia0' o 'vencido'."""
    empresa = _get_empresa_info()
    colores = _get_colores()
    nombre = _esc(compra.get('buyer_nombre') or 'Hola')
    fecha_txt = _fecha(compra.get('proximo_pago'))
    if etapa == 'previo':
        titulo, urgencia = f"Tu plan vence el {fecha_txt}", ''
        asunto = f"Recordatorio: tu plan {plan.get('nombre')} vence el {fecha_txt}"
    elif etapa == 'dia0':
        titulo, urgencia = "Tu plan vence HOY", ''
        asunto = f"Tu plan {plan.get('nombre')} vence hoy"
    else:
        titulo = f"Tu plan está vencido hace {dias} días"
        urgencia = ('<p style="font-size:13px;color:#b42318;background:#fdeaea;'
                    'border-radius:6px;padding:10px 14px;">⚠️ Para evitar la '
                    'suspensión del servicio, renueva lo antes posible.</p>')
        asunto = "⚠️ Plan vencido — renueva para mantener tu tienda activa"
    contenido = f"""
    <h2 style="margin:0 0 14px;color:{colores['primario']};">{titulo}</h2>
    <p style="font-size:15px;line-height:1.6;color:#333;">Hola <strong>{nombre}</strong>,
      tu tienda <strong>{compra.get('dominio') or ''}</strong> tiene el plan
      <strong>{plan.get('nombre')}</strong> con próximo pago el <strong>{fecha_txt}</strong>.</p>
    {urgencia}
    <p style="text-align:center;margin:26px 0;">
      <a href="{renovacion_url}" style="background:{colores['primario']};color:#fff;
         padding:14px 34px;border-radius:8px;text-decoration:none;font-weight:bold;
         font-size:16px;display:inline-block;">Renovar mi plan</a>
    </p>
    <p style="font-size:13px;color:#777;">Si el botón no funciona:
      <a href="{renovacion_url}" style="color:{colores['primario']};word-break:break-all;">{renovacion_url}</a></p>
    """
    texto = f"Hola {compra.get('buyer_nombre') or ''}, {titulo.lower()}. Renueva aquí: {renovacion_url}"
    return asunto, texto, _base_html(contenido, empresa)

def generar_email_confirmacion_trial(compra, confirmar_url, codigo):
    """Verificación de email para la prueba gratis de 15 días: un código de 6
    números que la persona escribe en la página. Abrir el enlace no crea nada
    (los filtros de correo abren los enlaces solos): solo lleva a escribir el código."""
    from services.plan_compras_service import CODIGO_HORAS
    empresa = _get_empresa_info()
    colores = _get_colores()
    # Lo escribe quien se registra (y elige a quién llega el correo): nunca HTML.
    nombre = _esc(compra.get('buyer_nombre') or 'Hola')
    negocio = _esc(compra.get('nombre_negocio') or 'tu negocio')
    codigo = ''.join(ch for ch in str(codigo) if ch.isdigit())
    asunto = f"{codigo} es tu código para crear tu tienda"
    contenido = f"""
    <h2 style="margin:0 0 14px;color:{colores['primario']};">Tu código para crear tu tienda</h2>
    <p style="font-size:15px;line-height:1.6;color:#333;">Hola <strong>{nombre}</strong>,
      escribe este código en la página donde te registraste y creamos la tienda de
      <strong>{negocio}</strong> con <strong>15 días gratis</strong> del plan Ultra. Sin tarjeta.</p>
    <p style="text-align:center;margin:24px 0;">
      <span style="display:inline-block;font-size:34px;font-weight:bold;letter-spacing:10px;
         color:#111;background:#f3f4f6;border:1px solid #d1d5db;border-radius:10px;padding:14px 22px;">{codigo}</span>
    </p>
    <p style="font-size:14px;line-height:1.6;color:#333;">Vale {CODIGO_HORAS} horas. ¿Cerraste la página?
      <a href="{confirmar_url}" style="color:{colores['primario']};font-weight:bold;">Ábrela aquí</a>
      y escribe el código.</p>
    <p style="font-size:12px;color:#999;">Si no pediste esta prueba, ignora este correo: sin el código no se crea nada.</p>
    """
    texto = (f"Hola {compra.get('buyer_nombre') or ''}:\n\nTu código para crear tu tienda es {codigo}. "
             f"Escríbelo en la página donde te registraste (vale {CODIGO_HORAS} horas).\n"
             f"¿Cerraste la página? Ábrela aquí: {confirmar_url}\n\n"
             "Si no pediste esta prueba, ignora este correo: sin el código no se crea nada.")
    return asunto, texto, _base_html(contenido, empresa)


def generar_email_trial_recordatorio(compra, plan, renovacion_url, dias_restantes):
    """Recordatorios de la prueba gratis: quedan 5 / 2 / 0 días."""
    empresa = _get_empresa_info()
    colores = _get_colores()
    nombre = _esc(compra.get('buyer_nombre') or 'Hola')
    dominio = compra.get('dominio') or ''
    if dias_restantes > 0:
        dias_txt = '1 día' if dias_restantes == 1 else f'{dias_restantes} días'
        titulo = f"Te quedan {dias_txt} de prueba gratis"
        asunto = f"⏳ Te quedan {dias_txt} de prueba — activa tu plan"
        aviso = ''
    else:
        from services.tienda_estado_sync import eliminar_desde
        hasta = _fecha(eliminar_desde(compra))
        titulo = "Tu prueba gratis vence HOY"
        asunto = "⏰ Tu prueba gratis vence hoy — no pierdas tu tienda"
        aviso = ('<p style="font-size:13px;color:#b42318;background:#fdeaea;'
                 'border-radius:6px;padding:10px 14px;">Si no activas tu plan, '
                 'mañana la tienda quedará en pausa. Tus productos, ventas y '
                 'configuración se guardan' + (f' hasta el <strong>{hasta}</strong>' if hasta else '')
                 + ' y vuelven al instante al pagar.</p>')
    contenido = f"""
    <h2 style="margin:0 0 14px;color:{colores['primario']};">{titulo}</h2>
    <p style="font-size:15px;line-height:1.6;color:#333;">Hola <strong>{nombre}</strong>,
      esperamos que <strong>{dominio}</strong> esté siendo un gran aliado.
      Para seguir usando todo (tienda en línea, POS, inventario, contabilidad,
      nómina y asistente IA) activa tu plan <strong>{plan.get('nombre')}</strong>
      por <strong>${'{:,.0f}'.format(float(plan.get('precio') or 0)).replace(',', '.')}/{plan.get('periodo','mes')}</strong>.</p>
    {aviso}
    <p style="text-align:center;margin:26px 0;">
      <a href="{renovacion_url}" style="background:{colores['primario']};color:#fff;
         padding:14px 34px;border-radius:8px;text-decoration:none;font-weight:bold;
         font-size:16px;display:inline-block;">Activar mi plan</a>
    </p>
    <p style="font-size:13px;color:#777;">Si el botón no funciona:
      <a href="{renovacion_url}" style="color:{colores['primario']};word-break:break-all;">{renovacion_url}</a></p>
    {_ayuda_html(empresa, colores, f"Hola, tengo una duda sobre el plan de mi tienda {dominio}")}
    """
    texto = f"Hola {compra.get('buyer_nombre') or ''}, {titulo.lower()}. Activa tu plan aquí: {renovacion_url}"
    return asunto, texto, _base_html(contenido, empresa)


def _precio(plan):
    return '${:,.0f}'.format(float(plan.get('precio') or 0)).replace(',', '.')


def generar_email_trial_pausada(compra, plan, renovacion_url, eliminar_desde=None):
    """Día 16: la prueba terminó sin pago y la tienda quedó en pausa (antes se
    reenviaba el «vence hoy, mañana se pausa» cuando ya estaba pausada)."""
    empresa = _get_empresa_info()
    colores = _get_colores()
    nombre = _esc(compra.get('buyer_nombre') or 'Hola')
    dominio = compra.get('dominio') or ''
    termino = _fecha(compra.get('proximo_pago'))
    hasta = _fecha(eliminar_desde)
    asunto = f"Tu prueba gratis terminó — tus datos de {dominio} están guardados"
    contenido = f"""
    <h2 style="margin:0 0 14px;color:{colores['primario']};">Tu prueba gratis terminó</h2>
    <p style="font-size:15px;line-height:1.6;color:#333;">Hola <strong>{nombre}</strong>,
      la prueba gratis de <strong>{dominio}</strong> terminó el {termino}. Tu tienda quedó
      <strong>en pausa</strong>: tus clientes ven un aviso y tú no pierdes nada.</p>
    <p style="font-size:14px;color:#1f2937;background:#f3f6fb;border-radius:6px;padding:10px 14px;line-height:1.6;">
      Tus productos, ventas y configuración quedan guardados{f' hasta el <strong>{hasta}</strong>' if hasta else ''}.
      Activa tu plan <strong>{_esc(plan.get('nombre'))}</strong> por <strong>{_precio(plan)}/{plan.get('periodo', 'mes')}</strong>
      y tu tienda vuelve al instante, tal como la dejaste.</p>
    <p style="text-align:center;margin:26px 0;">
      <a href="{renovacion_url}" style="background:{colores['primario']};color:#fff;
         padding:14px 34px;border-radius:8px;text-decoration:none;font-weight:bold;
         font-size:16px;display:inline-block;">Activar mi plan</a>
    </p>
    <p style="font-size:13px;color:#777;">Si el botón no funciona:
      <a href="{renovacion_url}" style="color:{colores['primario']};word-break:break-all;">{renovacion_url}</a></p>
    {_ayuda_html(empresa, colores, f"Hola, quiero seguir con mi tienda {dominio}")}
    """
    texto = (f"Hola {compra.get('buyer_nombre') or ''}, la prueba gratis de {dominio} terminó el {termino} "
             f"y la tienda quedó en pausa. Tus datos se guardan{(' hasta el ' + hasta) if hasta else ''}. "
             f"Activa tu plan aquí y vuelve al instante: {renovacion_url}")
    return asunto, texto, _base_html(contenido, empresa)


def generar_email_pago_plan_cliente(compra, plan, referencia, convertida=False, reactivada=False):
    """Comprobante del pago de un plan para el CLIENTE (antes recibía el aviso
    interno del operador, con el enlace al panel maestro)."""
    empresa = _get_empresa_info()
    colores = _get_colores()
    nombre = _esc(compra.get('buyer_nombre') or 'Hola')
    dominio = compra.get('dominio') or ''
    proximo = _fecha(compra.get('proximo_pago'))
    plan_nombre = _esc(plan.get('nombre'))
    if convertida:
        asunto = f"Tu plan {plan.get('nombre')} quedó activo — {dominio}"
        titulo = "¡Tu tienda ya es oficial! 🎉"
        mensaje = (f"recibimos tu pago y <strong>{dominio}</strong> dejó de ser una prueba: sigue con "
                   f"todo lo que hiciste, ahora con el plan <strong>{plan_nombre}</strong>.")
        siguiente = ('<p style="font-size:14px;color:#333;line-height:1.6;">Siguiente paso: para recibir '
                     'pagos en línea de tus clientes con <strong>tu propia cuenta PayU</strong>, escríbenos '
                     'y la conectamos contigo.</p>')
    else:
        asunto = f"Pago recibido — tu plan {plan.get('nombre')} sigue activo"
        titulo = "Pago recibido ✅"
        mensaje = (f"recibimos tu pago del plan <strong>{plan_nombre}</strong> de "
                   f"<strong>{dominio}</strong>."
                   + (' Tu tienda ya está activa de nuevo.' if reactivada else ''))
        siguiente = ''
    contenido = f"""
    <h2 style="margin:0 0 14px;color:{colores['primario']};">{titulo}</h2>
    <p style="font-size:15px;line-height:1.6;color:#333;">Hola <strong>{nombre}</strong>, {mensaje}</p>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e8edf6;border-radius:8px;overflow:hidden;font-size:14px;margin:14px 0;">
      <tr><td style="padding:8px 12px;color:#555;">Plan</td><td style="padding:8px 12px;"><strong>{plan_nombre}</strong> · {_precio(plan)}/{plan.get('periodo', 'mes')}</td></tr>
      <tr style="background:#f8f9fc;"><td style="padding:8px 12px;color:#555;">Próximo pago</td><td style="padding:8px 12px;"><strong>{proximo}</strong> (te avisamos antes por correo)</td></tr>
      <tr><td style="padding:8px 12px;color:#555;">Referencia</td><td style="padding:8px 12px;"><code>{_esc(referencia)}</code></td></tr>
    </table>
    {siguiente}
    <p style="font-size:12px;color:#999;">Este correo es tu comprobante de pago; no es una factura electrónica.</p>
    {_ayuda_html(empresa, colores, f"Hola, tengo una pregunta sobre el plan de {dominio}")}
    """
    texto = (f"Hola {compra.get('buyer_nombre') or ''}, recibimos tu pago del plan {plan.get('nombre')} "
             f"({dominio}). Próximo pago: {proximo}. Referencia: {referencia}.")
    return asunto, texto, _base_html(contenido, empresa)

