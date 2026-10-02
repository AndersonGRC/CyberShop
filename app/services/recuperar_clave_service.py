"""Recuperar la contraseña por correo.

El enlace va firmado con la SECRET_KEY de la instancia, vence en 30 minutos y
sirve UNA sola vez: lleva un pedazo del hash actual de la contraseña, así que
en cuanto se cambia la contraseña el enlace deja de valer. Nunca se guarda ni
se envía la contraseña; solo el enlace para crear una nueva.
"""

import html

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

from database import get_db_cursor

_SALT = 'recuperar-clave-v1'
VIGENCIA_S = 30 * 60
MIN_LARGO = 8


def _serializador():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=_SALT)


def _huella(hash_actual):
    return (hash_actual or '')[-16:]


def usuario_por_email(email):
    email = (email or '').strip().lower()
    if not email:
        return None
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT id, nombre, email, estado, \"contraseña\" AS hash FROM usuarios "
                    "WHERE lower(email) = %s LIMIT 1", (email,))
        fila = cur.fetchone()
    if not fila or fila['estado'] != 'habilitado':
        return None
    return dict(fila)


def crear_token(usuario):
    return _serializador().dumps({'u': usuario['id'], 'h': _huella(usuario['hash'])})


def usuario_del_token(token):
    """El usuario si el enlace es válido, vigente y aún no se usó; si no, None."""
    try:
        datos = _serializador().loads(token, max_age=VIGENCIA_S)
    except (SignatureExpired, BadSignature):
        return None
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT id, nombre, email, estado, \"contraseña\" AS hash FROM usuarios WHERE id = %s",
                    (datos.get('u'),))
        fila = cur.fetchone()
    if not fila or fila['estado'] != 'habilitado' or _huella(fila['hash']) != datos.get('h'):
        return None
    return dict(fila)


def validar_clave(nueva, confirmacion):
    if len(nueva or '') < MIN_LARGO:
        return f'La contraseña debe tener al menos {MIN_LARGO} caracteres.'
    if nueva != confirmacion:
        return 'Las dos contraseñas no coinciden.'
    return None


def cambiar_clave(usuario_id, nueva):
    with get_db_cursor() as cur:
        cur.execute("UPDATE usuarios SET \"contraseña\" = %s WHERE id = %s",
                    (generate_password_hash(nueva), usuario_id))


def enviar_correo(usuario, url, negocio):
    from helpers_gmail import enviar_email_gmail
    nombre = html.escape(usuario.get('nombre') or '')
    negocio_html = html.escape(negocio or 'tu tienda')
    asunto = f'Crea una contraseña nueva · {negocio}'
    texto = (f"Hola {usuario.get('nombre') or ''}:\n\n"
             f"Pediste crear una contraseña nueva para entrar a {negocio}.\n"
             f"Ábrela aquí (vence en 30 minutos y sirve una sola vez):\n{url}\n\n"
             "Si no fuiste tú, ignora este correo: tu contraseña actual sigue igual.")
    cuerpo = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#1f2937">
      <h2 style="color:#122C94">Crea una contraseña nueva</h2>
      <p>Hola {nombre}:</p>
      <p>Pediste crear una contraseña nueva para entrar a <strong>{negocio_html}</strong>.</p>
      <p style="margin:28px 0">
        <a href="{html.escape(url)}" style="background:#122C94;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:bold">Crear mi contraseña</a>
      </p>
      <p style="font-size:13px;color:#4b5563">El enlace vence en 30 minutos y sirve una sola vez.
      Si no fuiste tú, ignora este correo: tu contraseña actual sigue igual.</p>
    </div>"""
    return enviar_email_gmail(usuario['email'], asunto, texto, html=cuerpo)
