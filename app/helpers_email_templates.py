"""
helpers_email_templates.py — Templates HTML para emails del sistema.

Genera cuerpos HTML con branding dinamico usando Config.BRAND_COLORS
y datos de cliente_config (empresa_nombre, empresa_email).
"""

from database import get_db_cursor
from helpers import formatear_moneda


def _get_empresa_info():
    """Obtiene nombre, email, telefono y URL de la empresa desde cliente_config."""
    info = {'nombre': 'CyberShop', 'email': '', 'telefono': '', 'url': ''}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT clave, valor FROM cliente_config WHERE clave IN "
                "('empresa_nombre', 'empresa_email', 'empresa_telefono', 'empresa_url')"
            )
            for row in cur.fetchall():
                if row['clave'] == 'empresa_nombre' and row['valor']:
                    info['nombre'] = row['valor']
                elif row['clave'] == 'empresa_email' and row['valor']:
                    info['email'] = row['valor']
                elif row['clave'] == 'empresa_telefono' and row['valor']:
                    info['telefono'] = row['valor']
                elif row['clave'] == 'empresa_url' and row['valor']:
                    info['url'] = row['valor']
    except Exception:
        pass
    return info


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
