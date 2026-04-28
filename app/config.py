"""
config.py — Configuracion centralizada de CyberShop.

Todas las variables de entorno, credenciales de servicios externos
(PayU, Mail, Uploads) y parametros de sesion se definen aqui en una
sola clase ``Config`` que luego se aplica a la app Flask.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.cybershop.conf')


class Config:
    """Configuracion principal de la aplicacion Flask."""

    # --- General / Sesion ---
    # SECURITY M2: Sin fallback débil — falla explícitamente si no está configurado
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError("FLASK_SECRET_KEY no está configurada. Define esta variable de entorno.")
    # SECURITY A5: Activar en producción (HTTPS). En desarrollo local (HTTP) dejar en false.
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hora
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB max upload

    # --- PayU Latam ---
    PAYU_API_KEY    = os.getenv('PAYU_API_KEY')
    PAYU_API_LOGIN  = os.getenv('PAYU_API_LOGIN')
    PAYU_MERCHANT_ID = os.getenv('PAYU_MERCHANT_ID')
    PAYU_ACCOUNT_ID  = os.getenv('PAYU_ACCOUNT_ID')
    PAYU_ENV         = os.getenv('PAYU_ENV', 'sandbox')
    PAYU_URL         = 'https://api.payulatam.com/payments-api/4.0/service.cgi'
    PAYU_RESPONSE_URL    = os.getenv('PAYU_RESPONSE_URL', 'http://localhost:5001/respuesta-pago')
    PAYU_CONFIRMATION_URL = os.getenv('PAYU_CONFIRMATION_URL', 'http://localhost:5001/confirmacion-pago')
    PAYU_TIMEOUT = 45

    # --- reCAPTCHA ---
    RECAPTCHA_SECRET_KEY = os.getenv('RECAPTCHA_SECRET_KEY')

    # --- Mail (Gmail SMTP — respaldo cuando Gmail API no está autorizado) ---
    MAIL_SERVER       = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT         = int(os.getenv('MAIL_PORT', 587))
    MAIL_DEBUG        = False
    MAIL_USE_TLS      = True
    MAIL_USERNAME     = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD     = os.getenv('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')

    # --- Uploads (imagenes) ---
    UPLOADED_IMAGES_DEST = os.path.join('static', 'media')
    UPLOADED_IMAGES_URL = '/static/media/'
    UPLOADED_USERIMAGES_DEST = os.path.join('static', 'user')
    UPLOADED_USERIMAGES_URL = '/static/user/'

    # --- Colores de Marca (usados en PDFs y emails) ---
    # xhtml2pdf no soporta CSS variables, asi que los colores del PDF
    # se toman de aqui. Deben coincidir con variables.css.
    BRAND_COLORS = {
        'primario': '#122C94',
        'primario_oscuro': '#091C5A',
        'secundario': '#0e1b33',
        'texto': '#333333',
        'texto_claro': '#888888',
        'fondo_claro': '#f9f9f9',
        'exito': '#28a745',
        'borde': '#000000',
    }

    # --- Google Calendar OAuth 2.0 ---
    GOOGLE_CLIENT_ID     = os.getenv('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
    GOOGLE_REDIRECT_URI  = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:5001/admin/google/callback')
    GOOGLE_CALENDAR_ID   = 'primary'
    GOOGLE_SCOPES        = [
        'https://www.googleapis.com/auth/calendar.events',
        'openid', 'email'
    ]

    # --- Gmail API OAuth 2.0 (envío de notificaciones) ---
    GOOGLE_GMAIL_SCOPES       = [
        'https://www.googleapis.com/auth/gmail.send',
        'openid', 'email'
    ]
    GOOGLE_GMAIL_REDIRECT_URI = os.getenv(
        'GOOGLE_GMAIL_REDIRECT_URI',
        'http://localhost:5001/admin/google/gmail/callback'
    )

    # --- Google Login OAuth 2.0 ---
    GOOGLE_LOGIN_REDIRECT_URI = os.getenv('GOOGLE_LOGIN_REDIRECT_URI', 'http://localhost:5001/google/login/callback')
    GOOGLE_LOGIN_SCOPES       = ['openid', 'email', 'profile']

    # --- Datos por Defecto para Cuentas de Cobro ---
    BILLING_INFO = {
        'contractor_nombre':  os.getenv('BILLING_NOMBRE', ''),
        'contractor_id':      os.getenv('BILLING_ID', ''),
        'contractor_telefono': os.getenv('BILLING_TELEFONO', ''),
        'contractor_email':   os.getenv('BILLING_EMAIL', ''),
        'texto_pago':         os.getenv('BILLING_TEXTO_PAGO', ''),
    }


def verificar_configuracion_payu(app):
    """Valida que las claves PayU requeridas esten presentes en la config.

    Lanza ``ValueError`` si falta alguna clave obligatoria.
    En modo sandbox registra las credenciales activas en el log.
    """
    required_keys = ['PAYU_API_KEY', 'PAYU_API_LOGIN', 'PAYU_MERCHANT_ID', 'PAYU_URL']
    for key in required_keys:
        if not app.config.get(key):
            raise ValueError(f"Configuracion faltante: {key}")

    if app.config['PAYU_ENV'] == 'sandbox':
        # SECURITY M3: No registrar credenciales en logs
        app.logger.info("Modo Sandbox activado.")
