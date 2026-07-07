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

# --- Logging (con request-id + tenant, sink con nombre correcto y rotacion) ---
import uuid as _uuid
from flask import g as _g
from logging.handlers import RotatingFileHandler


class _RequestContextFilter(logging.Filter):
    """Inyecta request_id y tenant en cada log (fuera de request usa '-')."""
    def filter(self, record):
        rid, tenant = '-', '-'
        try:
            from flask import has_request_context
            if has_request_context():
                rid = getattr(_g, 'request_id', '-') or '-'
                t = getattr(_g, 'current_tenant', None)
                if isinstance(t, dict):
                    tenant = t.get('db_name', '-') or '-'
        except Exception:
            pass
        record.request_id = rid
        record.tenant = tenant
        return True


def _pick_log_dir():
    """Primer directorio escribible: /var/log/cybershop → <app>/logs."""
    for d in ('/var/log/cybershop', os.path.join(app.root_path, 'logs')):
        try:
            os.makedirs(d, exist_ok=True)
            _t = os.path.join(d, '.wtest')
            with open(_t, 'w') as _f:
                _f.write('x')
            os.remove(_t)
            return d
        except Exception:
            continue
    return app.root_path


_LOG_DIR = _pick_log_dir()
_LOG_FMT = '%(asctime)s %(levelname)s [rid=%(request_id)s tenant=%(tenant)s] %(name)s: %(message)s'
logging.basicConfig(level=logging.INFO, format=_LOG_FMT)

_file_handler = RotatingFileHandler(os.path.join(_LOG_DIR, 'app.log'),
                                    maxBytes=5 * 1024 * 1024, backupCount=5)
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter(_LOG_FMT))
_ctx_filter = _RequestContextFilter()
_file_handler.addFilter(_ctx_filter)
app.logger.addHandler(_file_handler)
app.logger.addFilter(_ctx_filter)
for _h in logging.getLogger().handlers:      # que el root (basicConfig) tambien tenga request-id
    _h.addFilter(_ctx_filter)
app.logger.setLevel(logging.INFO)


# --- Request-ID: identifica cada request en logs y en la respuesta ---
@app.before_request
def _assign_request_id():
    _g.request_id = request.headers.get('X-Request-Id') or _uuid.uuid4().hex[:12]


@app.after_request
def _emit_request_id(response):
    rid = getattr(_g, 'request_id', None)
    if rid:
        response.headers['X-Request-Id'] = rid
    return response


# --- Manejo de errores no capturados (500) ---
from werkzeug.exceptions import HTTPException as _HTTPException


def _wants_json():
    return (request.is_json
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.headers.get('Accept', '').startswith('application/json')
            or request.path.startswith('/api/'))


def _render_error_500():
    rid = getattr(_g, 'request_id', '-')
    if _wants_json():
        from flask import jsonify as _jsonify
        return _jsonify({'success': False, 'error': 'Error interno del servidor',
                         'request_id': rid}), 500
    try:
        from flask import render_template as _rt
        return _rt('500.html', request_id=rid), 500
    except Exception:
        return 'Error interno del servidor', 500


@app.errorhandler(500)
def _handle_500(e):
    return _render_error_500()


@app.errorhandler(Exception)
def _handle_unexpected(e):
    # Deja pasar las HTTPException (404/403/redirects/CSRF) a sus handlers propios.
    if isinstance(e, _HTTPException):
        return e
    rid = getattr(_g, 'request_id', '-')
    try:
        app.logger.exception(f"Unhandled exception en {request.method} {request.path}")
    except Exception:
        pass
    return _render_error_500()

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

# --- Enforcement de suspensión (defensa en profundidad; además de detener la
#     instancia). Si el tenant de ESTA instancia no está 'activo', bloquea el sitio
#     con una página "tienda suspendida" salvo las rutas para pagar/reactivar.
#     FAIL-OPEN: ante cualquier error de lookup NO se bloquea (nunca tumbar un
#     tenant activo por un hipo del control plane). Estado cacheado por proceso. ---
import time as _time_susp
from services.db_layer import control_plane_cursor as _cp_cursor_susp

_INSTANCE_TENANT_ID = int(os.getenv('DEFAULT_TENANT_ID', '1') or 1)
_estado_cache = {'estado': None, 'exp': 0.0}
_ESTADO_TTL = 60  # s

def _instance_tenant_estado():
    now = _time_susp.time()
    if _estado_cache['exp'] > now:
        return _estado_cache['estado']
    estado = None
    try:
        with _cp_cursor_susp(dict_cursor=True) as cur:
            cur.execute("SELECT estado FROM tenants WHERE id = %s", (_INSTANCE_TENANT_ID,))
            row = cur.fetchone()
        if row:
            estado = row['estado']
    except Exception:
        estado = None  # fail-open
    _estado_cache['estado'] = estado
    _estado_cache['exp'] = now + _ESTADO_TTL
    return estado

# Rutas que SIEMPRE pasan aunque el tenant esté suspendido (para poder pagar/reactivar,
# servir estáticos y no romper las APIs, que validan su propio estado).
_SUSPEND_ALLOW_PREFIXES = (
    '/static/', '/favicon', '/health', '/api/',
    '/planes', '/renovar', '/activar-tienda', '/comprar-plan',
    '/metodos-pago', '/redireccion-payu', '/confirmacion-pago', '/respuesta-pago',
)

@app.before_request
def _bloquear_si_suspendido():
    if _instance_tenant_estado() in ('suspendido', 'cancelado'):
        path = request.path or '/'
        if not path.startswith(_SUSPEND_ALLOW_PREFIXES):
            try:
                from flask import render_template as _rt
                return _rt('tienda_suspendida.html'), 503
            except Exception:
                return ('<!doctype html><meta charset="utf-8">'
                        '<title>Tienda suspendida</title>'
                        '<h1>Tienda temporalmente suspendida</h1>'
                        '<p>Este comercio está inactivo. Si eres el propietario, '
                        'renueva tu plan para reactivarlo.</p>'), 503

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
