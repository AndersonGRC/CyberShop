import psycopg2
from flask import render_template, request, redirect, url_for, session, flash
from database import get_db_connection
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from app import app, get_common_data, images
from psycopg2.extras import DictCursor


@app.route('/registrar-cliente', methods=['GET', 'POST'])
def registrar_cliente():
    datosApp = get_common_data()  # Obtener los datos comunes

    if request.method == 'POST':
        # Obtener los datos del formulario
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        fecha_nacimiento = request.form.get('fecha_nacimiento')

        # Validar que todos los campos estén presentes
        if not nombre or not email or not password or not fecha_nacimiento:
            flash('Por favor, complete todos los campos.', 'error')
            return redirect(url_for('registrar_cliente'))

        # Verificar si el correo ya está registrado
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)  # Usar DictCursor
        try:
            cur.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
            usuario_existente = cur.fetchone()

            if usuario_existente:
                flash('El correo electrónico ya está registrado.', 'error')
                return redirect(url_for('registrar_cliente'))

            # Generar el hash de la contraseña
            hashed_password = generate_password_hash(password)

            # Insertar el usuario en la base de datos con rol_id = 3 (Cliente)
            cur.execute(
                'INSERT INTO usuarios (nombre, email, password, rol_id, fecha_nacimiento) VALUES (%s, %s, %s, %s, %s)',
                (nombre, email, hashed_password, 3, fecha_nacimiento)
            )
            conn.commit()

            flash('Cliente registrado correctamente. Por favor, inicie sesión.', 'success')
            return redirect(url_for('login'))  # Redirigir al login después del registro

        except Exception as e:
            print(f"Error al registrar cliente: {e}")
            flash('Error al registrar el cliente. Inténtelo de nuevo.', 'error')

        finally:
            # Cerrar la conexión a la base de datos
            cur.close()
            conn.close()

    return render_template('registrarcliente.html', datosApp=datosApp)


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


# Función de autenticación modificada
def autenticar_usuario(email, password):
    """
    Autentica a un usuario verificando si el correo electrónico existe en la base de datos
    y si la contraseña ingresada coincide con el hash almacenado.

    Parámetros:
        email (str): Correo electrónico ingresado por el usuario.
        password (str): Contraseña ingresada por el usuario.

    Retorna:
        dict or None: Un diccionario con los datos del usuario si la autenticación es exitosa.
                      Retorna None si el usuario no existe o la contraseña es incorrecta.
    """
    try:
        # Conectar a la base de datos
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)  # Usar DictCursor

        # Buscar al usuario por correo electrónico
        cur.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
        usuario = cur.fetchone()  # Obtener el primer resultado (si existe)

        # Cerrar la conexión a la base de datos
        cur.close()
        conn.close()

        # Verificar si el usuario existe y si la contraseña es correcta
        if usuario and check_password_hash(usuario['password'], password):
            print(f"Usuario autenticado: {usuario['email']}")  # Depuración
            return usuario  # Retornar los datos del usuario
        else:
            print("Correo no encontrado o contraseña incorrecta.")  # Depuración
            return None  # Retornar None si la autenticación falla

    except Exception as e:
        # Manejar errores (por ejemplo, problemas de conexión a la base de datos)
        print(f"Error al autenticar usuario: {e}")
        return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    datosApp = get_common_data()

    if request.method == 'POST':
        # Verifica si el campo 'email' está en el formulario
        if 'email' not in request.form or 'password' not in request.form:
            flash('Por favor, complete todos los campos.', 'error')
            return redirect(url_for('login'))

        email = request.form['email']
        password = request.form['password']

        print(f"Intento de login: Correo={email}, Contraseña={password}")  # Depuración

        usuario = autenticar_usuario(email, password)

        if usuario:
            print(f"Usuario autenticado: {usuario['email']}, Rol: {usuario['rol_id']}")  # Depuración
            session['usuario_id'] = usuario['id']
            session['email'] = usuario['email']
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
            flash('Correo o contraseña incorrectos.', 'error')
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
def GestionProductos():
    datosApp = get_common_data()

    # Obtener la lista de géneros desde la base de datos
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM generos')  # Selecciona solo id y nombre
        generos = cur.fetchall()
        print("Géneros obtenidos:", generos)  # Depuración
        cur.close()
        conn.close()
    except Exception as e:
        print("Error al obtener géneros:", e)  # Depuración
        generos = []

    if request.method == 'POST':
        try:
            if 'imagen' not in request.files:
                return "No se envió ningún archivo", 400

            file = request.files['imagen']

            if file.filename == '':
                return "Nombre de archivo no válido", 400

            # Guardar la imagen en el directorio 'media'
            imagen_nombre = images.save(file, folder='media')  # Guardar en 'media'
            imagen_url = f"/static/media/{imagen_nombre}"  # Ruta accesible desde Flask

            print(f"Imagen guardada en: {imagen_url}")

            nombre = request.form.get('nombre')
            precio = request.form.get('precio')
            referencia = request.form.get('referencia')
            genero_id = request.form.get('genero_id')  # Obtiene el ID del género seleccionado
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
                'INSERT INTO productos (imagen, nombre, precio, referencia, genero_id, descripcion) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *',
                (imagen_url, nombre, precio, referencia, genero_id, descripcion)
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

    return render_template('GestionProductos.html', datosApp=datosApp, generos=generos)


# Ruta para mostrar productos
@app.route('/productos')
def productos():
    datosApp = get_common_data()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT p.*, g.nombre AS genero FROM productos p JOIN generos g ON p.genero_id = g.id')
        productos = cur.fetchall()
        cur.close()
        conn.close()

        # Asegurarse de que los datos de los productos estén en el formato correcto
        datosApp['productos'] = productos
    except Exception as e:
        print("Error al obtener productos:", e)  # Depuración
        datosApp['productos'] = []

    return render_template('productos.html', datosApp=datosApp)

# Ruta para servicios
@app.route('/servicios')
def servicios():
    datosApp = get_common_data()
    return render_template('servicios.html', datosApp=datosApp)

#ruta para quienes somos
@app.route('/quienes_somos')
def quienes_somos():
    return redirect(url_for('index', _anchor='quienes_somos'))


# Manejo de errores 404
@app.errorhandler(404)
def pagina_no_encontrada(error):
    return render_template('404.html'), 404