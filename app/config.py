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

    # --- Versión del software (admin web) ---
    # Esquema A.B.C.D (ver docs/VERSIONADO.md). REGLA: cada desarrollo bumpea
    # esta versión. Se muestra en el footer del panel admin (para TODOS los
    # clientes, código compartido → todos ven la misma = la última desplegada).
    #   A = cambio radical de plataforma · B = módulo nuevo grande
    #   C = estabilización / mejora · D = correcciones y ajustes de UI
    APP_VERSION = "1.0.0.0"

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

    # --- Meta Pixel + Conversions API ---
    # Pixel ID — visible en el código del pixel del template
    META_PIXEL_ID = os.getenv('META_PIXEL_ID', '4412332785657284')
    # Access token de System User con permiso `ads_management` sobre el pixel.
    # Generar en: Events Manager → Configurar → Conversions API → Generar token
    META_CAPI_ACCESS_TOKEN = os.getenv('META_CAPI_ACCESS_TOKEN', '')
    # Test code: pegarlo mientras validás; quitarlo cuando el server envíe a producción.
    # Eventos con test_event_code aparecen en "Test Events" sin contar como reales.
    META_CAPI_TEST_EVENT_CODE = os.getenv('META_CAPI_TEST_EVENT_CODE', '')

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

    # --- Overrides de interfaz por instancia (theme a medida del SITIO PÚBLICO) ---
    # Cada instancia de cliente puede tener una carpeta de overrides FUERA del
    # repo compartido. Si existe, sus plantillas/estáticos pisan a los
    # compartidos SOLO para ese cliente (el código y el /admin no se overridean).
    # La lógica vive en el backend; las plantillas son solo presentación, así un
    # fix global llega a todos. Ver app.py (ChoiceLoader + override de 'static').
    INSTANCE_SLUG = os.getenv('DEFAULT_TENANT_SLUG', '')
    INSTANCE_OVERRIDES_ROOT = os.getenv('INSTANCE_OVERRIDES_ROOT', '/var/www/cybershop-overrides')
    # Dir efectivo del cliente actual: explícito desde el env (lo escribe el
    # provisioning del maestro) o derivado de root+slug. Vacío si no hay slug.
    # app.py valida que exista antes de activar overrides.
    INSTANCE_OVERRIDES_DIR = os.getenv('INSTANCE_OVERRIDES_DIR') or (
        os.path.join(INSTANCE_OVERRIDES_ROOT, INSTANCE_SLUG) if INSTANCE_SLUG else ''
    )

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
    # Venta automática: secreto compartido con el maestro (API interna localhost)
    INTERNAL_API_KEY    = os.getenv('INTERNAL_API_KEY', '')
    MASTER_INTERNAL_URL = os.getenv('MASTER_INTERNAL_URL', 'http://127.0.0.1:5002')
    # Suspensión automática por no-pago: días de gracia tras vencer (0 = solo notificar)
    AUTO_SUSPENDER_DIAS = int(os.getenv('AUTO_SUSPENDER_DIAS', '0'))

    # --- Asistente IA (módulo ai_assistant, plan ultra) ---
    # Endpoint compatible con OpenAI (Ollama lo expone en /v1). El módulo habla
    # SOLO con la BD del tenant actual; la máquina Ollama puede ser compartida
    # porque cada request es stateless y solo lleva datos del cliente actual.
    AI_BASE_URL = os.getenv('AI_BASE_URL', '')          # ej. http://10.200.0.2:11434
    AI_MODEL    = os.getenv('AI_MODEL', 'qwen2.5:7b')
    # Fallback automático: si AI_MODEL falla (memoria/timeout/error del server)
    # se reintenta UNA vez con este modelo más liviano. Vacío = sin fallback.
    AI_MODEL_FALLBACK = os.getenv('AI_MODEL_FALLBACK', 'qwen2.5:7b')
    AI_API_KEY  = os.getenv('AI_API_KEY', '')           # vacío para Ollama
    # read timeout amplio: el cold-start del modelo (carga a VRAM) puede tardar.
    # El connect timeout es corto (fast-fail si la GPU está apagada) — ver ai_service.
    AI_TIMEOUT  = int(os.getenv('AI_TIMEOUT', '120'))

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
