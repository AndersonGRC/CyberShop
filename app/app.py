from flask import Flask
from flask_uploads import UploadSet, configure_uploads, IMAGES
from werkzeug.utils import secure_filename  # Corrección en la importación
from werkzeug.datastructures import FileStorage  # Corrección en la importación
from flask_mail import Mail
from dotenv import load_dotenv
from flask_mail import Message  
import os
import re
import requests
import time
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
app.secret_key = 'Omegafito7217*'  # Clave secreta para manejar sesiones
# =============================================
# CONFIGURACIÓN BÁSICA DE LA APLICACIÓN
# =============================================

# Configuración general de la aplicación
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'una-clave-secreta-muy-segura-y-compleja')
app.config['SESSION_COOKIE_SECURE'] = False  # True en producción
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# =============================================
# CONFIGURACIÓN CORS (Para desarrollo)
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
# CONFIGURACIÓN PAYU SANDBOX
# =============================================

# Credenciales de PayU Sandbox
app.config['PAYU_API_KEY'] = 'Egc0YoZIz87uaI7P67OmTD9r9w'
app.config['PAYU_API_LOGIN'] = 'IN19b1OVTQKsjNx'
app.config['PAYU_MERCHANT_ID'] = '1021517'
app.config['PAYU_ENV'] = 'sandbox'  # 'sandbox' o 'production'

# URLs de PayU
app.config['PAYU_URL'] = 'https://sandbox.api.payulatam.com/payments-api/rest/v4.3/'
app.config['PAYU_PSE_URL'] = f"{app.config['PAYU_URL']}service.cgi"

# Configuración de URLs de respuesta (ajusta según tu dominio)
app.config['PAYU_RESPONSE_URL'] = 'http://localhost:5000/respuesta-pago'
app.config['PAYU_CONFIRMATION_URL'] = 'http://localhost:5000/confirmacion-pago'

# =============================================
# CONFIGURACIÓN ADICIONAL RECOMENDADA
# =============================================

# Configuración de logs
import logging
logging.basicConfig(level=logging.INFO)
app.logger.addHandler(logging.FileHandler('payu_integration.log'))

# Configuración de tiempo máximo para transacciones
app.config['PAYU_TIMEOUT'] = 45  # segundos

# =============================================
# INICIALIZACIÓN DE EXTENSIONES
# =============================================

# Ejemplo para inicializar otras extensiones
# from flask_sqlalchemy import SQLAlchemy
# db = SQLAlchemy(app)

# =============================================
# FUNCIÓN PARA VERIFICAR CONFIGURACIÓN
# =============================================

def verificar_configuracion_payu():
    """Verifica que la configuración de PayU sea correcta"""
    required_keys = ['PAYU_API_KEY', 'PAYU_API_LOGIN', 'PAYU_MERCHANT_ID', 'PAYU_URL']
    for key in required_keys:
        if not app.config.get(key):
            raise ValueError(f"Configuración faltante: {key}")
    
    if app.config['PAYU_ENV'] == 'sandbox':
        app.logger.info("Modo Sandbox activado - Configuración PayU:")
        app.logger.info(f"API Login: {app.config['PAYU_API_LOGIN']}")
        app.logger.info(f"Merchant ID: {app.config['PAYU_MERCHANT_ID']}")
        app.logger.info(f"Endpoint: {app.config['PAYU_URL']}")

# Configuración para el envío de correos
app.config['MAIL_SERVER'] = 'smtp.gmail.com'  # Servidor SMTP de Gmail
app.config['MAIL_PORT'] = 587  # Puerto para TLS
app.config['MAIL_DEBUG'] = True
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'cybershop.digitalsales@gmail.com'  # Tu correo Gmail
app.config['MAIL_PASSWORD'] = 'r k j q x v q a p o y t r v d q'  # Contraseña o App Password de Gmail
app.config['MAIL_DEFAULT_SENDER'] = 'yalgomasachiras@gmail.com'  # Correo remitente por defecto



# Inicializa Flask-Mail
mail = Mail(app)

# Configuración para imágenes de productos
app.config['UPLOADED_IMAGES_DEST'] = os.path.join('static', 'media')
app.config['UPLOADED_IMAGES_URL'] = '/static/media/'
images = UploadSet('images', IMAGES)

# Configuración para imágenes de usuarios
app.config['UPLOADED_USERIMAGES_DEST'] = os.path.join('static', 'user')
app.config['UPLOADED_USERIMAGES_URL'] = '/static/user/'
user_images = UploadSet('userimages', IMAGES)

# Configurar ambos conjuntos de uploads
configure_uploads(app, images)
configure_uploads(app, user_images)

# Crear directorios si no existen
os.makedirs(app.config['UPLOADED_IMAGES_DEST'], exist_ok=True)
os.makedirs(app.config['UPLOADED_USERIMAGES_DEST'], exist_ok=True)

# Función para obtener datos comunes
def get_common_data():
    MenuApp = [
        {"nombre": "Inicio", "url": "index"},
        {"nombre": "Productos", "url": "productos"},
        {"nombre": "Servicios", "url": "servicios"},
        {"nombre": "¿Quienes Somos?", "url": "index#quienes_somos"},
        {"nombre": "Contactanos", "url": "index#contactenos"},
        {"nombre": "Ingresar", "url": "login"}
    ]
    
    return {
        'titulo': 'Achiras de mi tierra',
        'MenuAppindex': MenuApp,
        'longMenuAppindex': len(MenuApp)
    }

# Función para obtener datos comunes

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
            "url": "gestion_usuarios",  # Nombre exacto de la función de vista
            "icono": "users",
            "submodulos": [
                {"nombre": "Lista de Usuarios", "url": "gestion_usuarios", "icono": "list"},
            ]
        },
        {"nombre": "Cerrar Sesion", "url": "logout", "icono": "sign-out-alt"}
    ]
    return {
        'titulo': 'Achiras de mi tierra',
        'MenuAppindex': App,
        'longMenuAppindex': len(App)
    }

# Importar las rutas desde routes.py
from routes import *

# Servidor 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6001, debug=True)