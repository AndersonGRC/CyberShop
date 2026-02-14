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
    PAYU_API_KEY = 'Egc0YoZIz87uaI7P67OmTD9r9w'
    PAYU_API_LOGIN = 'IN19b1OVTQKsjNx'
    PAYU_MERCHANT_ID = '1021517'
    PAYU_ACCOUNT_ID = '1030609'
    PAYU_ENV = 'production'  # sandbox / production
    PAYU_URL = 'https://api.payulatam.com/payments-api/4.0/service.cgi'
    PAYU_RESPONSE_URL = 'http://localhost:5001/respuesta-pago'
    PAYU_CONFIRMATION_URL = 'http://localhost:5001/confirmacion-pago'
    PAYU_TIMEOUT = 45

    # --- Mail (Gmail SMTP) ---
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_DEBUG = True
    MAIL_USE_TLS = True
    MAIL_USERNAME = 'cybershop.digitalsales@gmail.com'
    MAIL_PASSWORD = 'r k j q x v q a p o y t r v d q'
    MAIL_DEFAULT_SENDER = 'cybershop.digitalsales@gmail.com'

    # --- Uploads (imagenes) ---
    UPLOADED_IMAGES_DEST = os.path.join('static', 'media')
    UPLOADED_IMAGES_URL = '/static/media/'
    UPLOADED_USERIMAGES_DEST = os.path.join('static', 'user')
    UPLOADED_USERIMAGES_URL = '/static/user/'


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
