"""
config.py — Configuracion centralizada de CyberShop.

Todas las variables de entorno, credenciales de servicios externos
(PayU, Mail, Uploads) y parametros de sesion se definen aqui en una
sola clase ``Config`` que luego se aplica a la app Flask.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuracion principal de la aplicacion Flask."""

    # --- General / Sesion ---
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'una-clave-secreta-muy-segura-y-compleja')
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

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

    # --- Mail (Gmail SMTP) ---
    MAIL_SERVER       = 'smtp.gmail.com'
    MAIL_PORT         = 587
    MAIL_DEBUG        = True
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
        app.logger.info("Modo Sandbox activado:")
        app.logger.info(f"API Login: {app.config['PAYU_API_LOGIN']}")
        app.logger.info(f"Merchant ID: {app.config['PAYU_MERCHANT_ID']}")
        app.logger.info(f"Endpoint: {app.config['PAYU_URL']}")
