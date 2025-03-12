from flask import Flask
from flask_uploads import UploadSet, configure_uploads, IMAGES
from werkzeug.utils import secure_filename  # Corrección en la importación
from werkzeug.datastructures import FileStorage  # Corrección en la importación

app = Flask(__name__)
app.secret_key = 'Omegafito7217*'  # Clave secreta para manejar sesiones

# Configuración para subir imágenes
app.config['UPLOADED_IMAGES_DEST'] = 'static/media'
images = UploadSet('images', IMAGES)
configure_uploads(app, images)

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
        'titulo': 'CyberShop',
        'MenuAppindex': MenuApp,
        'longMenuAppindex': len(MenuApp)
    }

# Función para obtener datos comunes

def get_data_app():
    App = [
        {"nombre": "Menu Principal", "url": "dashboard_admin"},
        {"nombre": "Dashboard", "url": "dashboard_admin"},
        {"nombre": "Gestion Productos", "url": "GestionProductos"},
        {"nombre": "Cerrar Sesion", "url": "logout"}
    ]
    return {
        'titulo': 'CyberShop',
        'MenuAppindex': App,  # Pasar la lista App, no la instancia de Flask
        'longMenuAppindex': len(App)  # Calcular la longitud de la lista App
    }

# Importar las rutas desde routes.py
from routes import *

# Servidor 
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
