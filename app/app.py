from flask import Flask
from flask_uploads import UploadSet, configure_uploads, IMAGES

app = Flask(__name__)
app.secret_key = 'tu_clave_secreta_aqui'  # Clave secreta para manejar sesiones

# Configuración para subir imágenes
app.config['UPLOADED_IMAGES_DEST'] = 'static/img'
images = UploadSet('images', IMAGES)
configure_uploads(app, images)

# Función para obtener datos comunes
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