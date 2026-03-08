"""
helpers_google.py — Utilidades para la integración con Google Calendar.

Provee funciones para obtener credenciales OAuth del usuario desde la BD,
construir el cliente de la API y realizar operaciones CRUD sobre eventos.
"""

import uuid
from datetime import datetime, timezone, timedelta

from flask import current_app, session
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from database import get_db_cursor


# ------------------------------------------------------------------
# Credenciales
# ------------------------------------------------------------------

def get_credentials(usuario_id):
    """Carga el token OAuth del usuario desde la BD y lo refresca si venció.

    Returns:
        google.oauth2.credentials.Credentials o None si el usuario no
        tiene Google Calendar conectado.
    """
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT access_token, refresh_token, token_expiry, scope
            FROM google_oauth_tokens
            WHERE usuario_id = %s
        """, (usuario_id,))
        row = cur.fetchone()

    if not row or not row['refresh_token']:
        return None

    creds = Credentials(
        token=row['access_token'],
        refresh_token=row['refresh_token'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=current_app.config['GOOGLE_CLIENT_ID'],
        client_secret=current_app.config['GOOGLE_CLIENT_SECRET'],
        scopes=current_app.config['GOOGLE_SCOPES'],
    )

    # Forzar expiración si ya pasó
    if row['token_expiry']:
        expiry = row['token_expiry']
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        creds.expiry = expiry

    if not creds.valid:
        try:
            creds.refresh(Request())
            _guardar_tokens(usuario_id, creds)
        except Exception:
            return None

    return creds


def get_calendar_service(usuario_id):
    """Construye y retorna el cliente autenticado de Google Calendar API.

    Returns:
        Resource de googleapiclient o None si no hay credenciales.
    """
    creds = get_credentials(usuario_id)
    if not creds:
        return None
    return build('calendar', 'v3', credentials=creds, cache_discovery=False)


def session_user_tiene_google():
    """Comprueba si el usuario en sesión tiene Google Calendar conectado."""
    usuario_id = session.get('id')
    if not usuario_id:
        return False
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(
            "SELECT 1 FROM google_oauth_tokens WHERE usuario_id = %s",
            (usuario_id,)
        )
        return cur.fetchone() is not None


# ------------------------------------------------------------------
# Operaciones sobre eventos
# ------------------------------------------------------------------

def crear_evento(usuario_id, summary, description, start_date, end_date, attendees=None):
    """Crea un evento en Google Calendar del usuario.

    Args:
        start_date / end_date: date o datetime. Si es date se trata como
            evento de día completo.
        attendees: lista de strings con emails.

    Returns:
        str con el eventId o None si falla.
    """
    service = get_calendar_service(usuario_id)
    if not service:
        return None

    event = {
        'summary': summary,
        'description': description or '',
    }

    if isinstance(start_date, datetime):
        event['start'] = {'dateTime': start_date.isoformat(), 'timeZone': 'America/Bogota'}
        event['end']   = {'dateTime': end_date.isoformat(),   'timeZone': 'America/Bogota'}
    else:
        event['start'] = {'date': start_date.isoformat()}
        event['end']   = {'date': end_date.isoformat()}

    if attendees:
        event['attendees'] = [{'email': e} for e in attendees]

    try:
        result = service.events().insert(
            calendarId=current_app.config['GOOGLE_CALENDAR_ID'],
            body=event,
            sendUpdates='all' if attendees else 'none',
        ).execute()
        return result.get('id')
    except HttpError:
        return None


def actualizar_evento(usuario_id, event_id, **kwargs):
    """Actualiza campos de un evento existente en Google Calendar.

    kwargs aceptados: summary, description, start_date, end_date.
    """
    service = get_calendar_service(usuario_id)
    if not service or not event_id:
        return

    try:
        event = service.events().get(
            calendarId=current_app.config['GOOGLE_CALENDAR_ID'],
            eventId=event_id,
        ).execute()

        if 'summary' in kwargs:
            event['summary'] = kwargs['summary']
        if 'description' in kwargs:
            event['description'] = kwargs['description']
        if 'start_date' in kwargs:
            d = kwargs['start_date']
            if isinstance(d, datetime):
                event['start'] = {'dateTime': d.isoformat(), 'timeZone': 'America/Bogota'}
            else:
                event['start'] = {'date': d.isoformat()}
        if 'end_date' in kwargs:
            d = kwargs['end_date']
            if isinstance(d, datetime):
                event['end'] = {'dateTime': d.isoformat(), 'timeZone': 'America/Bogota'}
            else:
                event['end'] = {'date': d.isoformat()}

        service.events().update(
            calendarId=current_app.config['GOOGLE_CALENDAR_ID'],
            eventId=event_id,
            body=event,
        ).execute()
    except HttpError:
        pass


def eliminar_evento(usuario_id, event_id):
    """Elimina un evento de Google Calendar."""
    service = get_calendar_service(usuario_id)
    if not service or not event_id:
        return
    try:
        service.events().delete(
            calendarId=current_app.config['GOOGLE_CALENDAR_ID'],
            eventId=event_id,
        ).execute()
    except HttpError:
        pass


# ------------------------------------------------------------------
# Webhooks (watch)
# ------------------------------------------------------------------

def registrar_watch(usuario_id, service):
    """Suscribe un canal de notificaciones push para el calendario del usuario.

    El canal dura 7 días; debe renovarse periódicamente.
    """
    channel_id = str(uuid.uuid4())
    expiry_ms = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp() * 1000)

    try:
        resp = service.events().watch(
            calendarId=current_app.config['GOOGLE_CALENDAR_ID'],
            body={
                'id': channel_id,
                'type': 'web_hook',
                'address': current_app.config.get(
                    'GOOGLE_WEBHOOK_URL',
                    'http://localhost:5001/admin/google/webhook'
                ),
                'expiration': str(expiry_ms),
            },
        ).execute()

        resource_id = resp.get('resourceId')
        expiry_ts = datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc)

        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO google_calendar_watches
                    (usuario_id, channel_id, resource_id, expiry)
                VALUES (%s, %s, %s, %s)
            """, (usuario_id, channel_id, resource_id, expiry_ts))
    except HttpError:
        pass


# ------------------------------------------------------------------
# Helpers internos
# ------------------------------------------------------------------

def _guardar_tokens(usuario_id, creds):
    """Persiste los tokens actualizados en la BD."""
    expiry = creds.expiry
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    with get_db_cursor() as cur:
        cur.execute("""
            UPDATE google_oauth_tokens
            SET access_token = %s,
                token_expiry  = %s,
                updated_at    = NOW()
            WHERE usuario_id = %s
        """, (creds.token, expiry, usuario_id))
