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

app = Flask(__name__)
app.secret_key = 'Omegafito7217*'  # Clave secreta para manejar sesiones

# Configuración para el envío de correos
app.config['MAIL_SERVER'] = 'smtp.gmail.com'  # Servidor SMTP de Gmail
app.config['MAIL_PORT'] = 587  # Puerto para TLS
app.config['MAIL_DEBUG'] = True
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'cybershop.digitalsales@gmail.com'  # Tu correo Gmail
app.config['MAIL_PASSWORD'] = 'r k j q x v q a p o y t r v d q'  # Contraseña o App Password de Gmail
app.config['MAIL_DEFAULT_SENDER'] = 'yalgomasachiras@gmail.com'  # Correo remitente por defecto


# Configuración PayU 
app.config['PAYU_API_KEY'] = 'Egc0YoZIz87uaI7P67OmTD9r9w'
app.config['PAYU_API_LOGIN'] = 'IN19b1OVTQKsjNx'
app.config['PAYU_MERCHANT_ID'] = '1021517'
app.config['PAYU_URL'] = 'https://sandbox.api.payulatam.com/payments-api/4.0/service.cgi'


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