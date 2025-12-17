from flask import Flask
from flask_uploads import UploadSet, configure_uploads, IMAGES
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from flask_mail import Mail
from dotenv import load_dotenv
import os
import requests
import time
from flask_cors import CORS
import logging

load_dotenv()

# =============================================
# INICIALIZACIÓN DE LA APLICACIÓN
# =============================================
app = Flask(__name__)
app.secret_key = 'Omegafito7217*'

# =============================================
# CONFIGURACIÓN GENERAL
# =============================================
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'una-clave-secreta-muy-segura-y-compleja')
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# =============================================
# CONFIG PAYU SANDBOX (tus credenciales)
# =============================================
app.config['PAYU_API_KEY'] = 'Egc0YoZIz87uaI7P67OmTD9r9w'
app.config['PAYU_API_LOGIN'] = 'IN19b1OVTQKsjNx'
app.config['PAYU_MERCHANT_ID'] = '1021517'
app.config['PAYU_ACCOUNT_ID'] = '1030609'   # account id usado en tu template
app.config['PAYU_ENV'] = 'production'          # sandbox / production

#app.config['PAYU_API_KEY'] = '4Vj8eK4rloUd272L48hsrarnUA'
#app.config['PAYU_API_LOGIN'] = 'pRRXKOl8ikMmt9u'
#app.config['PAYU_MERCHANT_ID'] = '508029'
#app.config['PAYU_ACCOUNT_ID'] = '512321' 
#app.config['PAYU_ENV'] = 'sandbox'
# Endpoints PayU
app.config['PAYU_URL'] = 'https://api.payulatam.com/payments-api/4.0/service.cgi'
app.config['PAYU_PSE_URL'] = f"{app.config['PAYU_URL']}service.cgi"

# Configuración de callbacks (ajusta si tu dominio no es localhost)
app.config['PAYU_RESPONSE_URL'] = 'http://localhost:5001/respuesta-pago'
app.config['PAYU_CONFIRMATION_URL'] = 'http://localhost:5001/confirmacion-pago'

# =============================================
# CORS para desarrollo (solo /api/*)
# =============================================
if app.config.get('PAYU_ENV') == 'sandbox':
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Authorization", "Content-Type"],
            "supports_credentials": True
        }
    })

# =============================================
# LOGS
# =============================================
logging.basicConfig(level=logging.INFO)
app.logger.addHandler(logging.FileHandler('payu_integration.log'))

# Timeout PayU
app.config['PAYU_TIMEOUT'] = 45

# =============================================
# VERIFICAR CONFIGURACIÓN PAYU (útil en arranque)
# =============================================
def verificar_configuracion_payu():
    required_keys = ['PAYU_API_KEY', 'PAYU_API_LOGIN', 'PAYU_MERCHANT_ID', 'PAYU_URL']
    for key in required_keys:
        if not app.config.get(key):
            raise ValueError(f"Configuración faltante: {key}")

    if app.config['PAYU_ENV'] == 'sandbox':
        app.logger.info("Modo Sandbox activado:")
        app.logger.info(f"API Login: {app.config['PAYU_API_LOGIN']}")
        app.logger.info(f"Merchant ID: {app.config['PAYU_MERCHANT_ID']}")
        app.logger.info(f"Endpoint: {app.config['PAYU_URL']}")

# =============================================
# MAIL (puedes mantener las credenciales)
# =============================================
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_DEBUG'] = True
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'cybershop.digitalsales@gmail.com'  # Tu correo Gmail
app.config['MAIL_PASSWORD'] = 'r k j q x v q a p o y t r v d q'  # Contraseña o App Password de Gmail
app.config['MAIL_DEFAULT_SENDER'] = 'yalgomasachiras@gmail.com'  # Correo remitente por defecto



# Inicializa Flask-Mail
mail = Mail(app)

# =============================================
# UPLOADS (imágenes)
# =============================================
app.config['UPLOADED_IMAGES_DEST'] = os.path.join('static', 'media')
app.config['UPLOADED_IMAGES_URL'] = '/static/media/'
images = UploadSet('images', IMAGES)

app.config['UPLOADED_USERIMAGES_DEST'] = os.path.join('static', 'user')
app.config['UPLOADED_USERIMAGES_URL'] = '/static/user/'
user_images = UploadSet('userimages', IMAGES)

configure_uploads(app, images)
configure_uploads(app, user_images)

os.makedirs(app.config['UPLOADED_IMAGES_DEST'], exist_ok=True)
os.makedirs(app.config['UPLOADED_USERIMAGES_DEST'], exist_ok=True)

# =============================================
# FUNCIONES AUXILIARES (get_common_data / get_data_app)
# =============================================
def get_common_data():
    MenuApp = [
        {"nombre": "Inicio", "url": "index"},
        {"nombre": "Productos", "url": "productos"},
        #{"nombre": "Servicios", "url": "servicios"},
        {"nombre": "¿Quienes Somos?", "url": "index#quienes_somos"},
        #{"nombre": "Contactanos", "url": "index#contactenos"},
        {"nombre": "Ingresar", "url": "login"}
    ]
    return {
        'titulo': 'Achiras de mi tierra',
        'MenuAppindex': MenuApp,
        'longMenuAppindex': len(MenuApp)
    }

def get_data_app():
    App = [
        {"nombre": "Menu Principal", "url": "dashboard_admin", "icono": "home"},
        {"nombre": "Dashboard", "url": "dashboard_admin", "icono": "chart-line"},
        {
            "nombre": "Gestion Productos",
            "url": "GestionProductos",
            "icono": "box",
            "submodulos": [
                {"nombre": "Agregar Producto", "url": "GestionProductos", "icono": "plus"},
                {"nombre": "Editar Producto", "url": "editar_productos", "icono": "edit"},
                {"nombre": "Eliminar Producto", "url": "eliminar_productos", "icono": "trash"}
            ]
        },
        {
            "nombre": "Gestion Usuarios",
            "url": "gestion_usuarios",
            "icono": "users",
            "submodulos": [
                {"nombre": "Lista de Usuarios", "url": "gestion_usuarios", "icono": "list"},
            ]
        },
         {
            "nombre": "Gestión de Pedidos",
            "url": "gestion_pedidos", 
            "icono": "truck",        
        },
        {"nombre": "Cerrar Sesion", "url": "logout", "icono": "sign-out-alt"}
    ]
    return {
        'titulo': 'Achiras de mi tierra',
        'MenuAppindex': App,
        'longMenuAppindex': len(App)
    }

# =============================================
# IMPORTAR RUTAS (dentro de app context para evitar errores)
# =============================================
with app.app_context():
    # routes.py usará: from app import app, get_common_data, get_data_app, images, user_images, mail
    from routes import *

# =============================================
# RUN
# =============================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6001, debug=True)
