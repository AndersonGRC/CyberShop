from flask import render_template, request, redirect, url_for, session, flash
from database import get_db_connection
from werkzeug.security import check_password_hash
from functools import wraps
from app import app, get_common_data, images

# Decorador para verificar roles
def rol_requerido(rol_id):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'rol_id' not in session or session['rol_id'] != rol_id:
                flash('No tienes permiso para acceder a esta página.', 'error')
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Función de autenticación
def autenticar_usuario(username, password):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM usuarios WHERE username = %s', (username,))
    usuario = cur.fetchone()
    cur.close()
    conn.close()

    if usuario and check_password_hash(usuario['password'], password):
        return usuario
    return None

# Ruta de inicio de sesión
@app.route('/login', methods=['GET', 'POST'])
def login():
    datosApp = get_common_data()

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        usuario = autenticar_usuario(username, password)

        if usuario:
            session['usuario_id'] = usuario['id']
            session['username'] = usuario['username']
            session['rol_id'] = usuario['rol_id']

            # Redirigir según el rol
            if usuario['rol_id'] == 1:  # Superadministrador
                return redirect(url_for('dashboard_admin'))
            elif usuario['rol_id'] == 2:  # Administrador
                return redirect(url_for('dashboard_admin'))
            elif usuario['rol_id'] == 3:  # Cliente
                return redirect(url_for('dashboard_cliente'))
            else:
                flash('Rol no válido.', 'error')
                return redirect(url_for('login'))
        else:
            flash('Usuario o contraseña incorrectos.', 'error')
            return redirect(url_for('login'))

    return render_template('login.html', datosApp=datosApp)

# Ruta para superadministradores
@app.route('/admin')
@rol_requerido(1)
def dashboard_admin():
    datosApp = get_common_data()
    return render_template('dashboard_admin.html', datosApp=datosApp)

# Ruta para clientes
@app.route('/cliente')
@rol_requerido(3)
def dashboard_cliente():
    datosApp = get_common_data()
    return render_template('dashboard_cliente.html', datosApp=datosApp)

# Ruta de cierre de sesión
@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión correctamente.', 'success')
    return redirect(url_for('login'))

# Ruta principal
@app.route('/')
def index():
    datosApp = get_common_data()
    return render_template('index.html', datosApp=datosApp)

# Ruta para agregar productos
@app.route('/agregar-producto', methods=['GET', 'POST'])
@rol_requerido(1)  # Solo superadministradores pueden agregar productos
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