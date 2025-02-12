from flask import Flask, render_template, url_for

app = Flask(__name__)

# Ruta principal
@app.route('/')
def index():
    MenuApp = [
        {"nombre": "Inicio", "url": "index"},
        {"nombre": "Productos", "url": "productos"},
        {"nombre": "Servicios", "url": "servicios"},
        {"nombre": "¿Quienes Somos?", "url": "#"},
        {"nombre": "Contactanos", "url": "#"},
        {"nombre": "Ingresar", "url": "login"}
    ]
    
    datosApp = {
        'titulo': 'CyberShop',
        'MenuAppindex': MenuApp,
        'longMenuAppindex': len(MenuApp)
    }

    return render_template('index.html', datosApp=datosApp)


# Ruta para cargar otras páginas, asegurando que `datosApp` siempre esté presente
@app.route('/pagina/<filename>')
def pagina(filename):
    MenuApp = [
        {"nombre": "Inicio", "url": "index"},
        {"nombre": "Productos", "url": "productos"},
        {"nombre": "Servicios", "url": "servicios"},
        {"nombre": "¿Quienes Somos?", "url": "#"},
        {"nombre": "Contactanos", "url": "#"},
        {"nombre": "Ingresar", "url": "login"}
    ]
    
    datosApp = {
        'titulo': 'CyberShop',
        'MenuAppindex': MenuApp,
        'longMenuAppindex': len(MenuApp)
    }

    return render_template(f"{filename}.html", datosApp=datosApp)


# Manejo de errores 404
@app.errorhandler(404)
def pagina_no_encontrada(error):
    return render_template('404.html'), 404


if __name__ == '__main__':
    app.run(debug=True, port=8080)
