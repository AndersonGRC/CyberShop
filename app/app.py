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
        {"nombre": "¿Quienes Somos?", "url": "index"},
        {"nombre": "Contactanos", "url": "quienes_somos"},
        {"nombre": "Ingresar", "url": "login"}
    ]
    
    return {
        'titulo': 'CyberShop',
        'MenuAppindex': MenuApp,
        'longMenuAppindex': len(MenuApp)
    }

# Importar las rutas desde routes.py
from routes import *

# Servidor 
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
