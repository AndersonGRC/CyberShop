"""
helpers_gmail.py — Envio de correos del sistema.

Prioridad: Gmail API (OAuth 2.0) si esta autorizado.
Respaldo:  Flask-Mail (SMTP) si Gmail no esta configurado.
"""

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import current_app
from flask_mail import Message
from googleapiclient.discovery import build

from database import get_db_cursor
from helpers_google import get_credentials


def _get_gmail_usuario_id():
    """Obtiene el usuario_id configurado para enviar correos del sistema."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT valor FROM cliente_config WHERE clave = 'gmail_usuario_id'"
            )
            row = cur.fetchone()
            if row and row['valor']:
                return int(row['valor'])
    except Exception:
        pass
    return None


def gmail_configurado():
    """Retorna True si Gmail API esta autorizado y listo para enviar."""
    uid = _get_gmail_usuario_id()
    if not uid:
        return False
    scopes = current_app.config.get('GOOGLE_GMAIL_SCOPES')
    creds = get_credentials(uid, scopes=scopes)
    return creds is not None


def _enviar_via_gmail(destinatario, asunto, cuerpo, html=None):
    """Intenta enviar via Gmail API. Retorna True/False."""
    uid = _get_gmail_usuario_id()
    if not uid:
        return False

    scopes = current_app.config.get('GOOGLE_GMAIL_SCOPES')
    creds = get_credentials(uid, scopes=scopes)
    if not creds:
        return False

    try:
        service = build('gmail', 'v1', credentials=creds, cache_discovery=False)

        if html:
            message = MIMEMultipart('alternative')
            message.attach(MIMEText(cuerpo, 'plain', 'utf-8'))
            message.attach(MIMEText(html, 'html', 'utf-8'))
        else:
            message = MIMEText(cuerpo, 'plain', 'utf-8')

        message['To'] = destinatario
        message['Subject'] = asunto

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
        service.users().messages().send(
            userId='me', body={'raw': raw}
        ).execute()

        return True
    except Exception as e:
        current_app.logger.error(f"Gmail API error enviando a {destinatario}: {e}")
        return False


def _enviar_via_smtp(destinatario, asunto, cuerpo, html=None):
    """Respaldo: envia via Flask-Mail SMTP."""
    try:
        from app import mail
        msg = Message(
            subject=asunto,
            sender=current_app.config.get('MAIL_USERNAME'),
            recipients=[destinatario],
            body=cuerpo,
            html=html
        )
        with mail.connect() as conn:
            conn.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f"SMTP error enviando a {destinatario}: {e}")
        return False


def enviar_email_gmail(destinatario, asunto, cuerpo, html=None):
    """Envia un correo: Gmail API si esta autorizado, SMTP como respaldo.

    Args:
        destinatario: Email del destinatario.
        asunto: Asunto del correo.
        cuerpo: Cuerpo en texto plano.
        html: (Opcional) version HTML del correo.

    Returns:
        True si se envio exitosamente por cualquiera de los dos medios.
    """
    if _enviar_via_gmail(destinatario, asunto, cuerpo, html):
        return True

    current_app.logger.info("Gmail API no disponible, usando SMTP como respaldo")
    return _enviar_via_smtp(destinatario, asunto, cuerpo, html)
