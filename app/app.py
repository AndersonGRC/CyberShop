"""
app.py — Punto de entrada de CyberShop.

Crea la aplicacion Flask, aplica la configuracion centralizada,
inicializa extensiones (Mail, Uploads, CORS) y registra los
blueprints de rutas. Ejecutar con ``python app.py``.
"""

import os
import logging

# Permite que oauthlib acepte scopes equivalentes devueltos por Google
# (e.g. "profile" vs "https://www.googleapis.com/auth/userinfo.profile")
os.environ.setdefault('OAUTHLIB_RELAX_TOKEN_SCOPE', '1')
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import safe_join
from flask import Flask, request, url_for as flask_url_for, send_from_directory
from flask_uploads import UploadSet, configure_uploads, IMAGES
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from jinja2 import ChoiceLoader, FileSystemLoader


from config import Config, verificar_configuracion_payu
from routes import register_blueprints

# --- Crear aplicacion ---
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.from_object(Config)
app.secret_key = app.config['SECRET_KEY']
FLASK_SECRET_KEY='Omegafito7217*'

# --- Overrides de interfaz por instancia (SOLO sitio público; ver config.py) ---
# Si esta instancia de cliente tiene una carpeta de overrides (fuera del repo
# compartido), sus plantillas/estáticos pisan a los compartidos SOLO para él.
# La lógica vive en el backend y el /admin NO se overridea → los fixes globales
# llegan a todos; aquí solo cambia la PRESENTACIÓN del sitio público del cliente.
_OVERRIDE_DIR = app.config.get('INSTANCE_OVERRIDES_DIR') or ''
_OVERRIDE_TEMPLATES = os.path.join(_OVERRIDE_DIR, 'templates') if _OVERRIDE_DIR else ''
_OVERRIDE_STATIC = os.path.join(_OVERRIDE_DIR, 'static') if _OVERRIDE_DIR else ''

# Plantillas: el theme del cliente (si existe) tiene prioridad sobre lo compartido.
if _OVERRIDE_TEMPLATES and os.path.isdir(_OVERRIDE_TEMPLATES):
    app.jinja_loader = ChoiceLoader([FileSystemLoader(_OVERRIDE_TEMPLATES), app.jinja_loader])
    app.logger.info(f"Overrides de plantillas activos: {_OVERRIDE_TEMPLATES}")


def _resolve_static_path(filename):
    """Ruta absoluta del estático: primero el override del cliente, luego el compartido.
    Devuelve None si no resuelve. Usa safe_join (anti path-traversal)."""
    if not filename:
        return None
    if _OVERRIDE_STATIC:
        cand = safe_join(_OVERRIDE_STATIC, filename)
        if cand and os.path.isfile(cand):
            return cand
    shared = safe_join(app.static_folder, filename)
    return shared if (shared and os.path.isfile(shared)) else None


# Estáticos: servir primero desde el override del cliente si ese archivo existe.
if _OVERRIDE_STATIC and os.path.isdir(_OVERRIDE_STATIC):
    def _static_with_override(filename):
        cand = safe_join(_OVERRIDE_STATIC, filename) if filename else None
        if cand and os.path.isfile(cand):
            return send_from_directory(_OVERRIDE_STATIC, filename)
        return send_from_directory(app.static_folder, filename)
    app.view_functions['static'] = _static_with_override
    app.logger.info(f"Overrides de estáticos activos: {_OVERRIDE_STATIC}")


def versioned_url_for(endpoint, **values):
    """Agrega cache-busting a assets estaticos usando su fecha de modificacion
    (del archivo que realmente resuelve: override del cliente o compartido)."""
    if endpoint == 'static':
        filename = values.get('filename')
        if filename and 'v' not in values:
            asset_path = _resolve_static_path(filename) or os.path.join(app.static_folder, filename)
            try:
                values['v'] = int(os.path.getmtime(asset_path))
            except OSError:
                pass
    return flask_url_for(endpoint, **values)


@app.context_processor
def inject_template_helpers():
    return {'url_for': versioned_url_for}

# --- CSRF Protection ---
csrf = CSRFProtect(app)

from flask_wtf.csrf import CSRFError

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Devuelve JSON en peticiones AJAX cuando el token CSRF es invalido."""
    if (request.is_json
            or request.headers.get('Accept', '').startswith('application/json')
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'):
        from flask import jsonify as _jsonify
        return _jsonify({'success': False, 'error': f'Token CSRF inválido: {e.description}'}), 400
    # Para peticiones HTML: avisar y volver atrás en vez de un 500 crudo.
    from flask import flash as _flash, redirect as _redirect
    _flash('Tu sesión expiró o el formulario no es válido. Recarga la página e inténtalo de nuevo.', 'error')
    return _redirect(request.referrer or '/')

# --- CORS (solo en sandbox) ---
if app.config.get('PAYU_ENV') == 'sandbox':
    CORS(app, resources={
        r"/api/*": {
            "origins": ["http://localhost:5001"],
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Authorization", "Content-Type"],
            "supports_credentials": True
        }
    })

# --- Logging ---
logging.basicConfig(level=logging.INFO)
from logging.handlers import RotatingFileHandler
file_handler = RotatingFileHandler('payu_integration.log', maxBytes=5*1024*1024, backupCount=3)
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)

from flask_mail import Mail
# --- Mail (Gmail API es prioritario; Flask-Mail SMTP queda como respaldo) ---
mail = Mail(app)

# --- Uploads (imagenes de productos y usuarios) ---
product_images = UploadSet('images', IMAGES)
user_images = UploadSet('userimages', IMAGES)

configure_uploads(app, product_images)
configure_uploads(app, user_images)

os.makedirs(app.config['UPLOADED_IMAGES_DEST'], exist_ok=True)
os.makedirs(app.config['UPLOADED_USERIMAGES_DEST'], exist_ok=True)

# --- Context processor: inyecta config_secciones a todos los templates ---
@app.context_processor
def inject_config_global():
    from tenant_features import get_active_module_codes, get_current_tenant_id
    from services.public_site_service import get_brand_config, get_public_sections

    config = get_public_sections()
    brand = get_brand_config()
    active_modules = set()
    current_tenant_id = get_current_tenant_id()
    from datetime import datetime
    from flask import session as _s
    session_usuario = None
    if _s.get('usuario_id'):
        session_usuario = {
            'id':     _s['usuario_id'],
            'nombre': _s.get('username', ''),
            'email':  _s.get('email', ''),
            'rol_id': _s.get('rol_id'),
            'tenant_id': _s.get('tenant_id'),
        }
    try:
        active_modules = get_active_module_codes(current_tenant_id)
    except Exception:
        active_modules = set()

    # Degradación elegante por integraciones: cada flag indica si la
    # integración tiene credenciales en el entorno de ESTA instancia.
    # Si falta, las plantillas ocultan esa pieza (el sitio sigue funcionando).
    integraciones = {
        'payu':   bool(Config.PAYU_MERCHANT_ID and Config.PAYU_ACCOUNT_ID
                       and Config.PAYU_API_KEY and Config.PAYU_API_LOGIN),
        'google': bool(Config.GOOGLE_CLIENT_ID and Config.GOOGLE_CLIENT_SECRET),
        'mail':   bool(Config.MAIL_USERNAME and Config.MAIL_PASSWORD),
        'whatsapp': bool(brand.get('empresa_whatsapp')),
    }

    return dict(
        config_global=config,
        brand_config=brand,
        now=datetime.now(),
        session_usuario=session_usuario,
        active_modules=active_modules,
        current_tenant_id=current_tenant_id,
        integraciones=integraciones,
    )

# --- Security headers ---
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Permitir camara/microfono solo en rutas de videollamada
    if request.path.startswith('/sala/') or request.path.startswith('/admin/video'):
        response.headers['Permissions-Policy'] = 'camera=(self), microphone=(self), geolocation=()'
    else:
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    return response

# --- Resolver tenant activo en cada request ---
from services.tenant_resolver import resolve_current_tenant
app.before_request(resolve_current_tenant)

# --- Meta CAPI: PageView automatico con dedup vs el Pixel ---
import uuid as _uuid
from flask import g as _g
from services import meta_capi as _meta_capi


@app.before_request
def _meta_capi_assign_event_id():
    """Si la request es un page-view candidato, genera un event_id que
    el pixel del template usara como `eventID` y CAPI usara como `event_id`."""
    if _meta_capi.should_track_pageview(request):
        _g.fb_pageview_event_id = str(_uuid.uuid4())


@app.context_processor
def _meta_capi_inject_event_id():
    """Expone el event_id de PageView al template para que el pixel lo use."""
    return {'fb_pageview_event_id': getattr(_g, 'fb_pageview_event_id', None)}


@app.after_request
def _meta_capi_send_pageview(response):
    """Despacha PageView a CAPI con el mismo event_id que uso el pixel.
    Solo si la response es HTML 200 (no errores, no redirects, no JSON)."""
    event_id = getattr(_g, 'fb_pageview_event_id', None)
    if not event_id or response.status_code != 200:
        return response
    if not (response.content_type or '').startswith('text/html'):
        return response
    try:
        _meta_capi.send_event_async(
            event_name='PageView',
            event_id=event_id,
            user_data=_meta_capi.build_user_data(request),
            event_source_url=request.url,
        )
    except Exception as exc:
        app.logger.warning(f"CAPI PageView dispatch error: {exc}")
    return response

# --- Registrar blueprints ---
api_blueprints = register_blueprints(app)

# --- Exentar webhook de PayU de la proteccion CSRF ---
# PayU envia POST server-to-server sin token CSRF; la firma MD5 lo autentica.
csrf.exempt(app.view_functions['payments.confirmacion_pago'])

# --- Exentar blueprints de la API REST del CSRF (usan Bearer JWT) ---
if api_blueprints:
    for bp in api_blueprints:
        csrf.exempt(bp)

# --- Ejecutar ---
if __name__ == '__main__':
    with app.app_context():
        verificar_configuracion_payu(app)
    app.run(host='0.0.0.0', port=5001, debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')
