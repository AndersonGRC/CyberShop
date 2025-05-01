from flask import Flask
from flask_uploads import UploadSet, configure_uploads, IMAGES
from werkzeug.utils import secure_filename  # Corrección en la importación
from werkzeug.datastructures import FileStorage  # Corrección en la importación
from flask_mail import Mail
from dotenv import load_dotenv
from flask_mail import Message  


app = Flask(__name__)
app.secret_key = 'Omegafito7217*'  # Clave secreta para manejar sesiones

# Configuración para el envío de correos
app.config['MAIL_SERVER'] = 'smtp.gmail.com'  # Servidor SMTP de Gmail
app.config['MAIL_PORT'] = 587  # Puerto para TLS
app.config['MAIL_DEBUG'] = True
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'cybershop.digitalsales@gmail.com'  # Tu correo Gmail
app.config['MAIL_PASSWORD'] = 'u n c x i k z b k u a m e o n g'  # Contraseña o App Password de Gmail
app.config['MAIL_DEFAULT_SENDER'] = 'yalgomasachiras@gmail.com'  # Correo remitente por defecto

# Inicializa Flask-Mail
mail = Mail(app)

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
        'titulo': 'Achiras de Mi tierra Facatativá',
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
        {"nombre": "Cerrar Sesion", "url": "logout", "icono": "sign-out-alt"}
    ]
    return {
        'titulo': 'Achiras de Mi tierra Facatativá',
        'MenuAppindex': App,  # Pasar la lista App, no la instancia de Flask
        'longMenuAppindex': len(App)  # Calcular la longitud de la lista App
    }

# Importar las rutas desde routes.py
from routes import *

# Servidor 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6001, debug=False)
    # app.run(host='0.0.0.0:5678', debug=True)
