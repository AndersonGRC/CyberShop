from flask import render_template, request, redirect, url_for
from flask_uploads import UploadSet, IMAGES
import psycopg2
from app import app, get_db_connection, get_common_data, images

# Ruta principal
@app.route('/')
def index():
    datosApp = get_common_data()
    return render_template('index.html', datosApp=datosApp)

# Ruta para agregar productos
@app.route('/agregar-producto', methods=['GET', 'POST'])
def GestionProductos():
    datosApp = get_common_data()
    if request.method == 'POST':
        try:
            if 'imagen' not in request.files:
                return "No se envió ningún archivo", 400

            file = request.files['imagen']

            if file.filename == '':
                return "Nombre de archivo no válido", 400

            imagen_nombre = images.save(file)
            imagen_url = f"/static/img/{imagen_nombre}"
            print(f"Imagen guardada en: {imagen_url}")

            nombre = request.form.get('nombre')
            precio = request.form.get('precio')
            referencia = request.form.get('referencia')
            genero = request.form.get('genero')
            descripcion = request.form.get('descripcion')

            try:
                precio = float(precio)
                if precio <= 0:
                    return "El precio debe ser un valor positivo", 400
            except ValueError:
                return "El precio debe ser un número válido", 400

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO productos (imagen, nombre, precio, referencia, genero, descripcion) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *',
                (imagen_url, nombre, precio, referencia, genero, descripcion)
            )
            producto = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            print("Producto creado con éxito:", producto)
            return redirect(url_for('productos'))
        except psycopg2.IntegrityError as e:
            print("Error de integridad en la base de datos:", e)
            return "La referencia ya está en uso", 400
        except Exception as e:
            print("Error al crear el producto:", e)
            return "Error al crear el producto", 500
    return render_template('GestionProductos.html', datosApp=datosApp)

# Ruta para mostrar productos
@app.route('/productos')
def productos():
    datosApp = get_common_data()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM productos')
        productos = cur.fetchall()
        cur.close()
        conn.close()
        datosApp['productos'] = productos
    except Exception as e:
        print(e)
        datosApp['productos'] = []
    return render_template('productos.html', datosApp=datosApp)

# Ruta para servicios
@app.route('/servicios')
def servicios():
    datosApp = get_common_data()
    return render_template('servicios.html', datosApp=datosApp)

# Manejo de errores 404
@app.errorhandler(404)
def pagina_no_encontrada(error):
    return render_template('404.html'), 404
# - Login 

@app.route('/login')
def login():
    datosApp = get_common_data()
    return render_template('login.html', datosApp=datosApp)