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
from flask import Flask, request
from flask_uploads import UploadSet, configure_uploads, IMAGES
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config, verificar_configuracion_payu
from routes import register_blueprints

# --- Crear aplicacion ---
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.from_object(Config)
app.secret_key = app.config['SECRET_KEY']

# --- CSRF Protection ---
csrf = CSRFProtect(app)

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
    from database import get_db_cursor
    config = {}
    brand  = {}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT clave, valor FROM config_secciones')
            for row in cur.fetchall():
                config[row['clave']] = row['valor'] == 'true'
            cur.execute('SELECT clave, valor FROM cliente_config')
            for row in cur.fetchall():
                brand[row['clave']] = row['valor']
    except Exception:
        pass
    from datetime import datetime
    from flask import session as _s
    session_usuario = None
    if _s.get('usuario_id'):
        session_usuario = {
            'id':     _s['usuario_id'],
            'nombre': _s.get('username', ''),
            'email':  _s.get('email', ''),
            'rol_id': _s.get('rol_id'),
        }
    return dict(config_global=config, brand_config=brand, now=datetime.now(),
                session_usuario=session_usuario)

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

# --- Registrar blueprints ---
register_blueprints(app)

# --- Ejecutar ---
if __name__ == '__main__':
    with app.app_context():
        verificar_configuracion_payu(app)
    app.run(host='0.0.0.0', port=5001, debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')
