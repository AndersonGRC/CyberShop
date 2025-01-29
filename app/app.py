from flask import Flask , render_template , url_for
from flask import send_from_directory


app = Flask(__name__)
@app.route('/')

@app.route('/templates/<filename>')
def templates(filename):
    # Lógica para servir archivos desde otra carpeta
    return send_from_directory('templates', filename)


def index():
    MenuApp =[{"nombre": "Inicio", "url": "index.html"},
    {"nombre": "Productos", "url": "#"},
    {"nombre": "Servicios", "url":"servicios.html"},
    {"nombre": "¿Quienes Somos?", "url": "#"},
    {"nombre": "Contactanos", "url": "#"},
    {"nombre": "Ingresar", "url": "#"}]
    datosApp = {
        'titulo' : 'CyberShop',
        'MenuAppindex' : MenuApp,
        'longMenuAppindex' : len(MenuApp)
    }

    #return"Hola"
    
    return render_template('index.html' , datosApp=datosApp)

    
    return render_template(data=data)

def pagina_no_encontrada(error):
    return render_template('404.html'), 404

if __name__ == '__main__':
    app.register_error_handler(404, pagina_no_encontrada)
    app.run(debug=True , port= 8080)
    
    