"""
routes/google_calendar.py — Blueprint para autenticación Google OAuth 2.0
y webhooks de sincronización bidireccional con Google Calendar.

Rutas (prefijo /admin/google):
  GET  /autorizar    → Redirige al flujo OAuth de Google
  GET  /callback     → Recibe el code, guarda tokens, registra watch
  POST /desconectar  → Borra tokens y watch del usuario
  POST /webhook      → Recibe notificaciones push de Google
"""

from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, redirect, request, url_for, flash, session, current_app
)
from google_auth_oauthlib.flow import Flow
from googleapiclient.errors import HttpError

from database import get_db_cursor
from helpers_google import get_calendar_service, registrar_watch
from security import rol_requerido

google_bp = Blueprint('google', __name__, url_prefix='/admin/google')


# ------------------------------------------------------------------
# Helpers internos
# ------------------------------------------------------------------

def _build_flow():
    """Construye el flujo OAuth 2.0 con la configuración de la app."""
    cfg = current_app.config
    return Flow.from_client_config(
        {
            'web': {
                'client_id':     cfg['GOOGLE_CLIENT_ID'],
                'client_secret': cfg['GOOGLE_CLIENT_SECRET'],
                'auth_uri':      'https://accounts.google.com/o/oauth2/auth',
                'token_uri':     'https://oauth2.googleapis.com/token',
                'redirect_uris': [cfg['GOOGLE_REDIRECT_URI']],
            }
        },
        scopes=cfg['GOOGLE_SCOPES'],
        redirect_uri=cfg['GOOGLE_REDIRECT_URI'],
    )


# ------------------------------------------------------------------
# Paso 1: Redirigir al consentimiento de Google
# ------------------------------------------------------------------

@google_bp.route('/autorizar')
@rol_requerido(1)
def autorizar():
    flow = _build_flow()
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
    )
    session['google_oauth_state'] = state
    session['google_calendar_code_verifier'] = flow.code_verifier
    return redirect(auth_url)


# ------------------------------------------------------------------
# Paso 2: Callback con el código de autorización
# ------------------------------------------------------------------

@google_bp.route('/callback')
@rol_requerido(1)
def callback():
    state = session.get('google_oauth_state')
    if not state or state != request.args.get('state'):
        flash('Estado OAuth inválido. Intenta de nuevo.', 'danger')
        return redirect(url_for('crm.crm_dashboard'))

    flow = _build_flow()
    flow.code_verifier = session.get('google_calendar_code_verifier')
    flow.state = state

    try:
        # Reconstruir la URL de respuesta usando el redirect_uri configurado
        # para evitar mismatch entre http/https cuando hay proxy reverso
        redirect_uri = current_app.config['GOOGLE_REDIRECT_URI']
        query_string = request.query_string.decode('utf-8')
        auth_response = f"{redirect_uri}?{query_string}"
        flow.fetch_token(authorization_response=auth_response)
    except Exception as e:
        current_app.logger.error(f"Google Calendar token error: {e}")
        flash(f'Error al obtener token de Google: {e}', 'danger')
        return redirect(url_for('crm.crm_dashboard'))

    creds = flow.credentials
    usuario_id = session.get('usuario_id')

    expiry = creds.expiry
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    with get_db_cursor() as cur:
        cur.execute("""
            INSERT INTO google_oauth_tokens
                (usuario_id, access_token, refresh_token, token_expiry, scope)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (usuario_id) DO UPDATE SET
                access_token  = EXCLUDED.access_token,
                refresh_token = COALESCE(EXCLUDED.refresh_token, google_oauth_tokens.refresh_token),
                token_expiry  = EXCLUDED.token_expiry,
                scope         = EXCLUDED.scope,
                updated_at    = NOW()
        """, (
            usuario_id,
            creds.token,
            creds.refresh_token,
            expiry,
            ' '.join(creds.scopes or []),
        ))

    # Registrar webhook de notificaciones
    service = get_calendar_service(usuario_id)
    if service:
        try:
            registrar_watch(usuario_id, service)
        except Exception:
            pass

    flash('Google Calendar conectado exitosamente.', 'success')
    return redirect(url_for('crm.crm_dashboard'))


# ------------------------------------------------------------------
# Desconectar
# ------------------------------------------------------------------

@google_bp.route('/desconectar', methods=['POST'])
@rol_requerido(1)
def desconectar():
    usuario_id = session.get('usuario_id')

    with get_db_cursor() as cur:
        cur.execute(
            "DELETE FROM google_calendar_watches WHERE usuario_id = %s",
            (usuario_id,)
        )
        cur.execute(
            "DELETE FROM google_oauth_tokens WHERE usuario_id = %s",
            (usuario_id,)
        )

    flash('Google Calendar desconectado.', 'info')
    return redirect(url_for('crm.crm_dashboard'))


# ------------------------------------------------------------------
# Webhook de sincronización bidireccional
# ------------------------------------------------------------------

@google_bp.route('/webhook', methods=['POST'])
def webhook():
    channel_id  = request.headers.get('X-Goog-Channel-ID')
    resource_id = request.headers.get('X-Goog-Resource-ID')

    if not channel_id:
        return '', 400

    # Buscar el usuario dueño del canal
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT usuario_id FROM google_calendar_watches
            WHERE channel_id = %s
        """, (channel_id,))
        row = cur.fetchone()

    if not row:
        return '', 200  # canal desconocido, ignorar

    usuario_id = row['usuario_id']
    service = get_calendar_service(usuario_id)
    if not service:
        return '', 200

    # Obtener eventos modificados en los últimos 2 minutos
    updated_min = (
        datetime.now(timezone.utc) - timedelta(minutes=2)
    ).isoformat()

    try:
        result = service.events().list(
            calendarId=current_app.config['GOOGLE_CALENDAR_ID'],
            updatedMin=updated_min,
            singleEvents=True,
            showDeleted=False,
        ).execute()
    except HttpError:
        return '', 200

    for ev in result.get('items', []):
        event_id = ev.get('id')
        if not event_id:
            continue

        nuevo_summary = ev.get('summary', '')
        start_info    = ev.get('start', {})
        nueva_fecha   = start_info.get('date') or start_info.get('dateTime', '')[:10]

        # Intentar actualizar tarea
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE crm_tareas
                SET titulo      = %s,
                    fecha_limite = %s
                WHERE google_event_id = %s
            """, (nuevo_summary, nueva_fecha or None, event_id))

        # Intentar actualizar actividad
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE crm_actividades
                SET asunto          = %s,
                    fecha_actividad = %s
                WHERE google_event_id = %s
            """, (nuevo_summary, nueva_fecha or None, event_id))

    return '', 200
