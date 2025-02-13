from flask import Flask
from flask_uploads import UploadSet, configure_uploads, IMAGES
import psycopg2

app = Flask(__name__)

# Configuración para subir imágenes
app.config['UPLOADED_IMAGES_DEST'] = 'static/img'
images = UploadSet('images', IMAGES)
configure_uploads(app, images)

# Configuración de la base de datos
def get_db_connection():
    conn = psycopg2.connect(
        dbname="cybershop",
        user="postgres",
        password="Omegafito7217*",
        host="localhost",
        port="5432"
    )
    return conn

# Datos comunes para todas las páginas
def get_common_data():
    MenuApp = [
        {"nombre": "Inicio", "url": "index"},
        {"nombre": "Productos", "url": "productos"},
        {"nombre": "Servicios", "url": "servicios"},
        {"nombre": "¿Quienes Somos?", "url": "productos"},
        {"nombre": "Contactanos", "url": "productos"},
        {"nombre": "Ingresar", "url": "login"}
    ]
    
    return {
        'titulo': 'CyberShop',
        'MenuAppindex': MenuApp,
        'longMenuAppindex': len(MenuApp)
    }

# Importar las rutas desde routes.py
from routes import *

if __name__ == '__main__':
    app.run(debug=True, port=8080)