"""
app.py — Punto de entrada de CyberShop.

Crea la aplicacion Flask, aplica la configuracion centralizada,
inicializa extensiones (Mail, Uploads, CORS) y registra los
blueprints de rutas. Ejecutar con ``python app.py``.
"""

import os
import logging

from flask import Flask
from flask_uploads import UploadSet, configure_uploads, IMAGES
from flask_mail import Mail
from flask_cors import CORS

from config import Config, verificar_configuracion_payu
from routes import register_blueprints

# --- Crear aplicacion ---
app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = app.config['SECRET_KEY']

# --- CORS (solo en sandbox) ---
if app.config.get('PAYU_ENV') == 'sandbox':
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Authorization", "Content-Type"],
            "supports_credentials": True
        }
    })

# --- Logging ---
logging.basicConfig(level=logging.INFO)
app.logger.addHandler(logging.FileHandler('payu_integration.log'))

# --- Mail ---
mail = Mail(app)

# --- Uploads (imagenes de productos y usuarios) ---
product_images = UploadSet('images', IMAGES)
user_images = UploadSet('userimages', IMAGES)

configure_uploads(app, product_images)
configure_uploads(app, user_images)

os.makedirs(app.config['UPLOADED_IMAGES_DEST'], exist_ok=True)
os.makedirs(app.config['UPLOADED_USERIMAGES_DEST'], exist_ok=True)

# --- Registrar blueprints ---
register_blueprints(app)

# --- Ejecutar ---
if __name__ == '__main__':
    with app.app_context():
        verificar_configuracion_payu(app)
    app.run(host='0.0.0.0', port=5001, debug=True)
