import psycopg2
from flask import render_template, request, redirect, url_for, session, flash
from database import get_db_connection
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from app import app, get_common_data, images
from app import app , get_data_app
from psycopg2.extras import DictCursor
from app import mail
from flask_mail import Message  
from datetime import datetime
import locale
import logging
#importaciones PAY U
from flask import request, jsonify, redirect, url_for, flash , session
import requests
import time
import hashlib
import json 
from validators import PSEValidator
from security import requiere_autenticacion


locale.setlocale(locale.LC_ALL, 'es_CO.UTF-8')


@app.route('/registrar-cliente', methods=['GET', 'POST'])
def registrar_cliente():
    datosApp = get_common_data()  # Obtener los datos comunes

    if request.method == 'POST':
        # Obtener los datos del formulario
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        fecha_nacimiento = request.form.get('fecha_nacimiento')
        telefono = request.form.get('telefono', '')  # Campo opcional
        direccion = request.form.get('direccion', '')  # Campo opcional

        # Validar campos obligatorios
        if not nombre or not email or not password or not fecha_nacimiento:
            flash('Por favor, complete todos los campos obligatorios.', 'error')
            return redirect(url_for('registrar_cliente'))

        # Verificar si el correo ya está registrado
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
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
                '''INSERT INTO usuarios 
                (nombre, email, contraseña, rol_id, fecha_nacimiento, telefono, direccion, estado) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'habilitado')''',
                (nombre, email, hashed_password, 3, fecha_nacimiento, telefono, direccion)
            )
            conn.commit()

            flash('Cliente registrado correctamente. Por favor, inicie sesión.', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            print(f"Error al registrar cliente: {e}")
            flash(f'Error al registrar el cliente: {str(e)}', 'error')

        finally:
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


def autenticar_usuario(email, password):
    """
    Autentica a un usuario verificando si el correo electrónico existe en la base de datos,
    si la contraseña ingresada coincide con el hash almacenado y si el usuario está habilitado.

    Parámetros:
        email (str): Correo electrónico ingresado por el usuario.
        password (str): Contraseña ingresada por el usuario.

    Retorna:
        dict or None: Un diccionario con los datos del usuario si la autenticación es exitosa.
                      Retorna None si el usuario no existe, la contraseña es incorrecta o el usuario está inhabilitado.
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

        # Verificar si el usuario existe, si la contraseña es correcta y si está habilitado
        if usuario and check_password_hash(usuario['contraseña'], password):  # Cambiado a 'contraseña'
            if usuario['estado'] != 'habilitado':  # Verificar si no está habilitado
                print(f"Usuario no habilitado: {usuario['email']}")  # Depuración
                flash('Tu cuenta está inhabilitada. Por favor, contacta al administrador.', 'error')
                return None
            else:
                print(f"Usuario autenticado: {usuario['email']}")  # Depuración
                # Actualizar última conexión (opcional)
                actualizar_ultima_conexion(usuario['id'])
                return usuario  # Retornar los datos del usuario
        else:
            print("Correo no encontrado o contraseña incorrecta.")  # Depuración
            flash('Correo o contraseña incorrectos.', 'error')
            return None

    except Exception as e:
        # Manejar errores (por ejemplo, problemas de conexión a la base de datos)
        print(f"Error al autenticar usuario: {e}")
        flash('Error al autenticar usuario. Por favor, inténtalo de nuevo.', 'error')
        return None

def actualizar_ultima_conexion(user_id):
    """Actualiza la fecha de última conexión del usuario"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'UPDATE usuarios SET ultima_conexion = CURRENT_TIMESTAMP WHERE id = %s',
            (user_id,)
        )
        conn.commit()
    except Exception as e:
        print(f"Error al actualizar última conexión: {e}")
    finally:
        cur.close()
        conn.close()

 # Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    datosApp = get_common_data()

    if request.method == 'POST':
        if 'email' not in request.form or 'password' not in request.form:
            flash('Por favor, complete todos los campos.', 'error')
            return redirect(url_for('login'))

        email = request.form['email']
        password = request.form['password']

        print(f"Intento de login: Correo={email}, Contraseña={password}")  # Depuración

        usuario = autenticar_usuario(email, password)

        if usuario:
            print(f"Usuario autenticado: {usuario['email']}, Rol: {usuario['rol_id']}")  # Depuración

            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute('UPDATE usuarios SET ultima_conexion = CURRENT_TIMESTAMP WHERE id = %s', (usuario['id'],))
                conn.commit()
                cur.close()
                conn.close()
                print(f"Última conexión actualizada para el usuario: {usuario['email']}")  # Depuración
            except Exception as e:
                print(f"Error al actualizar la última conexión: {e}")  # Depuración

            # Guardar datos del usuario en la sesión
            session['usuario_id'] = usuario['id']
            session['email'] = usuario['email']
            session['rol_id'] = usuario['rol_id']
            session['username'] = usuario['nombre']

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
            # El mensaje de error ya se maneja en la función autenticar_usuario
            return redirect(url_for('login'))
        
    return render_template('login.html', datosApp=datosApp)


# Ruta para clientes
@app.route('/cliente')
@rol_requerido(3)
def dashboard_cliente():
    datosApp = get_data_app()
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
@rol_requerido(1) 
def GestionProductos():
    datosApp = get_data_app()

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

def formatear_moneda(valor):
    return locale.currency(valor, symbol=True, grouping=True)

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

        for i, producto in enumerate(productos):
            productos[i] = list(producto)
            monto = producto[3]  # Asegúrate de que este índice sea el del precio
            productos[i][3] = formatear_moneda(float(monto))# ← conversión aquí

        datosApp['productos'] = productos
    except Exception as e:
        print("Error al obtener productos:", e)
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

#ruta para contactenos
@app.route('/contactenos')
def contactenos():
    return redirect(url_for('index', _anchor='contactenos'))

# Manejo de errores 404
@app.errorhandler(404)
def pagina_no_encontrada(error):
    return render_template('404.html'), 404

#Editar productos
@app.route('/editar-productos')
@rol_requerido(1)  # Solo para superadministradores
def editar_productos():
    datosApp = get_data_app()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM productos')
        productos = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error al obtener productos: {e}")
        productos = []
    return render_template('editar_productos.html', datosApp=datosApp, productos=productos)

#EditarProductos
@app.route('/editar-producto/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)  # Solo para superadministradores
def editar_producto(id):
    datosApp = get_data_app()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM productos WHERE id = %s', (id,))
        producto = cur.fetchone()
        cur.execute('SELECT * FROM generos')  # Obtener la lista de géneros
        generos = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error al obtener el producto: {e}")
        producto = None
        generos = []

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        precio = request.form.get('precio')
        referencia = request.form.get('referencia')
        genero_id = request.form.get('genero_id')
        descripcion = request.form.get('descripcion')
        file = request.files.get('imagen')

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Si se subió una nueva imagen
            if file and file.filename != '':
                # Guardar la nueva imagen
                imagen_nombre = images.save(file, folder='media')
                imagen_url = f"/static/media/{imagen_nombre}"
                
                # Actualizar producto incluyendo la nueva imagen
                cur.execute(
                    'UPDATE productos SET nombre = %s, precio = %s, referencia = %s, genero_id = %s, descripcion = %s, imagen = %s WHERE id = %s',
                    (nombre, precio, referencia, genero_id, descripcion, imagen_url, id)
                )
            else:
                # Actualizar producto sin cambiar la imagen
                cur.execute(
                    'UPDATE productos SET nombre = %s, precio = %s, referencia = %s, genero_id = %s, descripcion = %s WHERE id = %s',
                    (nombre, precio, referencia, genero_id, descripcion, id)
                )
            
            conn.commit()
            cur.close()
            conn.close()
            flash('Producto actualizado correctamente.', 'success')
            return redirect(url_for('editar_productos'))
        except Exception as e:
            print(f"Error al actualizar el producto: {e}")
            flash('Error al actualizar el producto.', 'error')

    return render_template('editar_producto.html', datosApp=datosApp, producto=producto, generos=generos)
# Ruta para eliminar productos (lista de productos)
@app.route('/eliminar-productos')
@rol_requerido(1)  # Solo para superadministradores
def eliminar_productos():
    datosApp = get_data_app()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM productos')
        productos = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error al obtener productos: {e}")
        productos = []
    return render_template('eliminar_productos.html', datosApp=datosApp, productos=productos)

# Ruta para eliminar un producto específico
@app.route('/eliminar-producto/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)  # Solo para superadministradores
def eliminar_producto(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('DELETE FROM productos WHERE id = %s', (id,))
        conn.commit()
        cur.close()
        conn.close()
        flash('Producto eliminado correctamente.', 'success')
    except Exception as e:
        print(f"Error al eliminar el producto: {e}")
        flash('Error al eliminar el producto.', 'error')
    
    return redirect(url_for('eliminar_productos'))


# Ruta para superadministradores
@app.route('/admin')
@rol_requerido(1)  # Solo para superadministradores
def dashboard_admin():
    datosApp = get_data_app()
    return render_template('dashboard_admin.html', datosApp=datosApp)


@app.route('/enviar-mensaje', methods=['POST'])
def enviar_mensaje():
    try:
        # 1. Verificar Honeypot (campo oculto)
        if request.form.get('website'):  # Si este campo viene lleno => SPAM
            flash('Solicitud sospechosa detectada.', 'error')
            return redirect(url_for('index'))

        # 2. Validar Google reCAPTCHA
        recaptcha_response = request.form.get('g-recaptcha-response')
        if not recaptcha_response:
            flash('Por favor confirma que no eres un robot.', 'error')
            return redirect(url_for('index'))

        recaptcha_secret = "TU_CLAVE_SECRETA"  # La obtienes en Google reCAPTCHA
        r = requests.post(
            'https://www.google.com/recaptcha/api/siteverify',
            data={'secret': recaptcha_secret, 'response': recaptcha_response}
        )
        result = r.json()

        if not result.get('success'):
            flash('Error en la verificación de reCAPTCHA. Intenta nuevamente.', 'error')
            return redirect(url_for('index'))

        # 3. Bloquear mensajes sospechosos relacionados con SEO
        spam_keywords = ['seo', 'marketing', 'linkbuilding', 'posicionamiento', 'backlinks']
        mensaje = request.form.get('message', '').lower()

        if any(word in mensaje for word in spam_keywords):
            flash('Contenido sospechoso detectado. Mensaje bloqueado.', 'error')
            return redirect(url_for('index'))

        # 4. Preparar correo
        msg = Message(
            subject=f"{request.form.get('name', 'Sin nombre')} quiere contactar contigo - {datetime.now().strftime('%d/%m/%Y')}",
            sender=app.config['MAIL_USERNAME'],
            recipients=[app.config['MAIL_DEFAULT_SENDER']],
            html=f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        background-color: #f5f7fa;
                        margin: 0;
                        padding: 0;
                        color: #333;
                        line-height: 1.6;
                    }}
                    .email-container {{
                        max-width: 600px;
                        margin: 20px auto;
                        background: white;
                        border-radius: 8px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
                        overflow: hidden;
                    }}
                    .email-header {{
                        background-color: #3498db;
                        color: white;
                        padding: 25px;
                        font-size: 26px;
                        text-align: center;
                    }}
                    .content-wrapper {{
                        padding: 25px;
                    }}
                    .info-item {{
                        margin-bottom: 18px;
                        font-size: 18px;
                    }}
                    .info-label {{
                        font-weight: bold;
                        color: #2c3e50;
                        display: inline-block;
                        min-width: 80px;
                    }}
                    .message-box {{
                        background-color: #f8f9fa;
                        padding: 20px;
                        border-radius: 6px;
                        margin: 25px 0;
                        border-left: 4px solid #3498db;
                    }}
                    .message-title {{
                        font-size: 20px;
                        color: #2c3e50;
                        margin-bottom: 15px;
                    }}
                    .email-footer {{
                        text-align: center;
                        padding: 15px;
                        background-color: #f5f7fa;
                        color: #7f8c8d;
                        font-size: 14px;
                    }}
                </style>
            </head>
            <body>
                <div class="email-container">
                    <div class="email-header">
                        ✉ Nuevo mensaje de contacto
                    </div>
                    <div class="content-wrapper">
                        <div class="info-item">
                            <span class="info-label">👤 Nombre:</span>
                            {request.form.get('name', 'No especificado')}
                        </div>
                        <div class="info-item">
                            <span class="info-label">📧 Email:</span>
                            {request.form.get('email', 'No especificado')}
                        </div>
                        <div class="info-item">
                            <span class="info-label">📞 Teléfono:</span>
                            {request.form.get('phone', 'No especificado')}
                        </div>
                        <div class="info-item">
                            <span class="info-label">📅 Fecha:</span>
                            {datetime.now().strftime('%d/%m/%Y %H:%M')}
                        </div>
                        <div class="message-box">
                            <h3 class="message-title">📝 Mensaje:</h3>
                            <p>{request.form.get('message', 'Sin mensaje')}</p>
                        </div>
                    </div>
                    <div class="email-footer">
                        <p>Este mensaje fue enviado desde el formulario de contacto de tu sitio web</p>
                        <p>© {datetime.now().year} {app.config['MAIL_DEFAULT_SENDER']}</p>
                    </div>
                </div>
            </body>
            </html>
            """,
            body=f"""
            NUEVO MENSAJE DE CONTACTO
            -------------------------
            Nombre: {request.form.get('name', 'No especificado')}
            Email: {request.form.get('email', 'No especificado')}
            Teléfono: {request.form.get('phone', 'No especificado')}
            Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}

            Mensaje:
            {request.form.get('message', 'Sin mensaje')}

            ---
            Enviado desde el formulario de contacto
            """
        )

        # 5. Enviar correo
        with mail.connect() as conn:
            conn.send(msg)

        flash('Mensaje enviado correctamente ✅', 'success')

    except Exception as e:
        print(f"ERROR CRÍTICO: {str(e)}")
        flash('Error al enviar el mensaje ❌', 'error')

    return redirect(url_for('index'))


    # Añade estas rutas al final de tu routes.py

# Ruta para listar usuarios (solo admin)
@app.route('/gestion-usuarios')
@rol_requerido(1)  # Solo superadmin
def gestion_usuarios():
    datosApp = get_data_app()
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        # Obtenemos usuarios con el nombre del rol
        cur.execute('''
            SELECT u.*, r.nombre as rol_nombre 
            FROM usuarios u
            JOIN roles r ON u.rol_id = r.id
            ORDER BY u.id
        ''')
        usuarios = cur.fetchall()
        # Obtenemos lista de roles para el formulario
        cur.execute('SELECT * FROM roles')
        roles = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error al obtener usuarios: {e}")
        flash('Error al cargar la lista de usuarios', 'error')
        usuarios = []
        roles = []
    
    return render_template('gestion_usuarios.html', 
                         datosApp=datosApp, 
                         usuarios=usuarios,
                         roles=roles)

# Ruta para crear usuario (solo admin)
@app.route('/crear-usuario', methods=['GET', 'POST'])
@rol_requerido(1)  # Solo superadmin
def crear_usuario():
    datosApp = get_data_app()
    
    # Obtener lista de roles para el formulario
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute('SELECT * FROM roles ORDER BY id')
        roles = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error al obtener roles: {e}")
        flash('Error al cargar los roles de usuario', 'error')
        roles = []

    if request.method == 'POST':
        # Obtener datos del formulario
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        rol_id = request.form.get('rol_id')
        fecha_nacimiento = request.form.get('fecha_nacimiento')
        telefono = request.form.get('telefono')
        direccion = request.form.get('direccion')
        fotografia = None

        # Validaciones básicas
        errors = []
        if not nombre:
            errors.append('El nombre es obligatorio')
        if not email:
            errors.append('El email es obligatorio')
        elif not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            errors.append('El email no tiene un formato válido')
        if not password:
            errors.append('La contraseña es obligatoria')
        elif len(password) < 8:
            errors.append('La contraseña debe tener al menos 8 caracteres')
        if password != confirm_password:
            errors.append('Las contraseñas no coinciden')
        if not rol_id:
            errors.append('Debe seleccionar un rol')

        if errors:
            for error in errors:
                flash(error, 'error')
            return redirect(url_for('crear_usuario'))

        # Manejo de la imagen
        if 'fotografia' in request.files:
            file = request.files['fotografia']
            if file.filename != '':
                try:
                    # Validar tipo de archivo
                    allowed_extensions = {'jpg', 'jpeg', 'png'}
                    filename = file.filename.lower()
                    if '.' in filename and filename.rsplit('.', 1)[1] in allowed_extensions:
                        filename = user_images.save(file)
                        fotografia = f"/static/user/{filename}"
                    else:
                        flash('Formato de imagen no válido. Use JPG, JPEG o PNG', 'error')
                        return redirect(url_for('crear_usuario'))
                except Exception as e:
                    print(f"Error al guardar imagen: {e}")
                    flash('Error al subir la imagen del usuario', 'error')
                    return redirect(url_for('crear_usuario'))

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Verificar si el email ya existe
            cur.execute('SELECT id FROM usuarios WHERE email = %s', (email,))
            if cur.fetchone():
                flash('El correo electrónico ya está registrado', 'error')
                return redirect(url_for('crear_usuario'))

            # Crear el usuario
            hashed_password = generate_password_hash(password)
            cur.execute('''
                INSERT INTO usuarios 
                (nombre, email, contraseña, rol_id, fecha_nacimiento, 
                 telefono, direccion, fotografia, estado)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'habilitado')
                RETURNING id
            ''', (nombre, email, hashed_password, rol_id, fecha_nacimiento, 
                 telefono, direccion, fotografia))
            
            nuevo_usuario_id = cur.fetchone()[0]
            conn.commit()
            
            flash('Usuario creado exitosamente', 'success')
            return redirect(url_for('gestion_usuarios'))
            
        except psycopg2.IntegrityError as e:
            conn.rollback()
            print(f"Error de integridad al crear usuario: {e}")
            flash('Error al crear el usuario. Verifique los datos.', 'error')
        except Exception as e:
            conn.rollback()
            print(f"Error al crear usuario: {e}")
            flash('Error al crear el usuario', 'error')
        finally:
            cur.close()
            conn.close()

        return redirect(url_for('crear_usuario'))

    # Si es GET, mostrar formulario
    return render_template('crear_usuario.html', 
                         datosApp=datosApp,
                         roles=roles)

#editar usuarios
@app.route('/editar-usuario/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)  # Solo superadmin
def editar_usuario(id):
    datosApp = get_data_app()
    
    # Obtener datos del usuario y roles
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute('SELECT * FROM usuarios WHERE id = %s', (id,))
        usuario = cur.fetchone()
        cur.execute('SELECT * FROM roles ORDER BY id')
        roles = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error al obtener datos: {e}")
        flash('Error al cargar datos del usuario', 'error')
        return redirect(url_for('gestion_usuarios'))

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        rol_id = request.form.get('rol_id')
        fecha_nacimiento = request.form.get('fecha_nacimiento')
        telefono = request.form.get('telefono', '')
        direccion = request.form.get('direccion', '')
        estado = request.form.get('estado', 'habilitado')
        fotografia = usuario['fotografia']  # Mantener la imagen actual por defecto

        # Manejo de la nueva imagen
        if 'fotografia' in request.files:
            file = request.files['fotografia']
            if file.filename != '':
                try:
                    # Eliminar la imagen anterior si existe
                    if usuario['fotografia']:
                        old_filename = usuario['fotografia'].split('/')[-1]
                        old_path = os.path.join(app.config['UPLOADED_USERIMAGES_DEST'], old_filename)
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    
                    # Guardar la nueva imagen
                    filename = user_images.save(file)
                    fotografia = f"/static/user/{filename}"
                except Exception as e:
                    print(f"Error al actualizar imagen: {e}")
                    flash('Error al actualizar la imagen del usuario', 'error')

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Actualizar usuario
            cur.execute('''
                UPDATE usuarios SET
                nombre = %s,
                email = %s,
                rol_id = %s,
                fecha_nacimiento = %s,
                telefono = %s,
                direccion = %s,
                estado = %s,
                fotografia = %s,
                fecha_modificacion = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (nombre, email, rol_id, fecha_nacimiento, telefono, 
                 direccion, estado, fotografia, id))
            
            conn.commit()
            flash('Usuario actualizado exitosamente', 'success')
        except Exception as e:
            conn.rollback()
            print(f"Error al actualizar usuario: {e}")
            flash('Error al actualizar el usuario', 'error')
        finally:
            cur.close()
            conn.close()
        return redirect(url_for('gestion_usuarios'))

    return render_template('editar_usuario.html',
                         datosApp=datosApp,
                         usuario=usuario,
                         roles=roles)

# Ruta para cambiar contraseña (solo admin)
@app.route('/cambiar-password/<int:id>', methods=['POST'])
@rol_requerido(1)  # Solo superadmin
def cambiar_password(id):
    if request.method == 'POST':
        nueva_password = request.form.get('nueva_password')
        confirmar_password = request.form.get('confirmar_password')

        if not nueva_password or nueva_password != confirmar_password:
            flash('Las contraseñas no coinciden o están vacías', 'error')
            return redirect(url_for('editar_usuario', id=id))

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            hashed_password = generate_password_hash(nueva_password)
            cur.execute('''
                UPDATE usuarios SET
                contraseña = %s,
                fecha_modificacion = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (hashed_password, id))
            
            conn.commit()
            flash('Contraseña actualizada exitosamente', 'success')
        except Exception as e:
            conn.rollback()
            print(f"Error al cambiar contraseña: {e}")
            flash('Error al cambiar la contraseña', 'error')
        finally:
            cur.close()
            conn.close()

    return redirect(url_for('editar_usuario', id=id))


 #PASARELA DE PAGO 

@app.route('/metodos-pago')
def metodos_pago():
    carrito_pendiente = {'items': [], 'total': 0}
    
    # 1. Intentar obtener de los parámetros de la URL
    carrito_json = request.args.get('carrito')
    if carrito_json:
        try:
            carrito_pendiente = json.loads(carrito_json)
            # Guardar en sesión para futuras referencias
            session['carritoPendiente'] = carrito_pendiente
        except Exception as e:
            print(f"Error parsing cart from URL: {e}")
    
    # 2. Si no hay en URL, intentar de la sesión Flask
    if not carrito_pendiente or not carrito_pendiente.get('items'):
        carrito_pendiente = session.get('carritoPendiente', {'items': [], 'total': 0})
    
    # 3. Asegurar la estructura correcta
    if 'items' not in carrito_pendiente:
        carrito_pendiente['items'] = []
    
    if 'total' not in carrito_pendiente:
        try:
            carrito_pendiente['total'] = sum(
                float(item.get('precio', 0)) * int(item.get('cantidad', 1)) 
                for item in carrito_pendiente.get('items', [])
            )
        except:
            carrito_pendiente['total'] = 0

    datosApp = get_common_data()
    return render_template('metodos_pago.html', 
                         datosApp=datosApp, 
                         carrito=carrito_pendiente)



@app.route('/procesar-carrito', methods=['POST'])
def procesar_carrito():
    try:
        data = request.get_json()
        
        # Validación básica
        if not data or 'items' not in data:
            return jsonify({"success": False, "error": "Datos inválidos"}), 400
        
        # Guardar en la sesión de Flask
        session['carritoPendiente'] = data
        
        return jsonify({
            "success": True,
            "message": "Carrito procesado correctamente"
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/payu/bancos')
@requiere_autenticacion
def obtener_bancos_pse():
    try:
        # Configuración del payload específico para obtener bancos
        payload = {
            "language": "es",
            "command": "GET_BANKS_LIST",
            "merchant": {
                "apiKey": app.config['PAYU_API_KEY'],
                "apiLogin": app.config['PAYU_API_LOGIN']
            },
            "test": True if app.config.get('PAYU_ENV') == 'sandbox' else False,
            "bankListInformation": {  # Este es el objeto que debe contener paymentMethod y paymentCountry
                "paymentMethod": "PSE",
                "paymentCountry": "CO"
            }
        }

        # Configuración de la solicitud
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        # Enviar solicitud a PayU
        response = requests.post(
            app.config['PAYU_URL'],
            json=payload,
            headers=headers,
            timeout=10
        )

        # Verificar errores en la respuesta
        response.raise_for_status()
        
        # Procesar la respuesta
        respuesta_payu = response.json()
        
        if respuesta_payu.get('code') != 'SUCCESS':
            app.logger.error(f"Error en respuesta de PayU: {respuesta_payu}")
            return jsonify({
                "success": False,
                "error": "Error al obtener bancos",
                "details": respuesta_payu.get('error', '')
            }), 400

        # Filtrar solo bancos activos y con código PSE
        bancos = [
            {
                "pseCode": banco.get("pseCode"),
                "description": banco.get("description"),
                "active": banco.get("active", True)  # Asumir activo si no se especifica
            }
            for banco in respuesta_payu.get('banks', [])
            if banco.get("pseCode")  # Solo bancos con código PSE
        ]

        # Ordenar bancos alfabéticamente
        bancos.sort(key=lambda x: x['description'])

        return jsonify({
            "success": True,
            "bancos": bancos
        })

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error de conexión con PayU: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Error al conectarse con PayU",
            "details": str(e)
        }), 500
        
    except Exception as e:
        app.logger.error(f"Error inesperado en obtener_bancos_pse: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Error interno del servidor",
            "details": str(e)
        }), 500




@app.route('/api/payu/procesar-pse', methods=['POST'])
def procesar_pago_pse():
    try:
        # 1. Verify JSON content
        if not request.is_json:
            app.logger.warning("Payment attempt without JSON content")
            return jsonify({
                "success": False,
                "error": "Content-Type must be application/json"
            }), 400

        data = request.get_json()
        
        # 2. Validate input data
        is_valid, validation_result = PSEValidator.validate_payment_data(data)
        if not is_valid:
            app.logger.error(f"Validation failed: {validation_result}")
            return jsonify({
                "success": False,
                "errors": validation_result
            }), 400

        # 3. Validate cart exists and amount matches
        carrito_pendiente = session.get('carritoPendiente', {})
        if not carrito_pendiente or not carrito_pendiente.get('items'):
            app.logger.error("Payment attempt without cart in session")
            return jsonify({
                "success": False,
                "error": "No products in cart"
            }), 400

        # Calculate cart total with decimal precision
        total_carrito = round(sum(
            float(item.get('precio', 0)) * int(item.get('cantidad', 0)) 
            for item in carrito_pendiente.get('items', [])
        ), 2)
        
        monto_solicitado = round(float(data['amount']), 2)
        
        if monto_solicitado != total_carrito:
            app.logger.error(
                f"Amount discrepancy: Cart {total_carrito} vs Payment {monto_solicitado}"
            )
            return jsonify({
                "success": False,
                "error": f"Requested amount ({monto_solicitado}) doesn't match cart total ({total_carrito})"
            }), 400

        # 4. Generate unique reference and security signature
        referencia = f"PED{int(time.time())}"
        firma = hashlib.md5(
            f"{app.config['PAYU_API_KEY']}~{app.config['PAYU_MERCHANT_ID']}~{referencia}~{monto_solicitado}~COP"
            .encode('utf-8')
        ).hexdigest()

        # 5. Prepare complete PayU payload with all mandatory fields
        payload = {
            "language": "es",
            "command": "SUBMIT_TRANSACTION",
            "test": True if app.config.get('PAYU_ENV', 'sandbox') == 'sandbox' else False,
            "merchant": {
                "apiKey": app.config['PAYU_API_KEY'],
                "apiLogin": app.config['PAYU_API_LOGIN']
            },
            "transaction": {
                "order": {
                    "accountId": app.config['PAYU_MERCHANT_ID'],
                    "referenceCode": referencia,
                    "description": f"Compra en {app.config.get('APP_NAME', 'Tienda')}",
                    "language": "es",
                    "signature": firma,
                    "additionalValues": {
                        "TX_VALUE": {
                            "value": monto_solicitado,
                            "currency": "COP"
                        }
                    },
                    "buyer": {
                        "merchantBuyerId": data.get('buyerId', referencia),
                        "fullName": data['buyerFullName'],
                        "emailAddress": data['buyerEmail'],
                        "contactPhone": data['buyerPhone'],
                        "dniNumber": data['pseReference3'],
                        "shippingAddress": {
                            "street1": data.get('shippingStreet1', 'Not provided'),
                            "street2": data.get('shippingStreet2', ''),
                            "city": data.get('shippingCity', 'Bogotá'),
                            "state": data.get('shippingState', 'Bogotá'),
                            "country": "CO",
                            "postalCode": data.get('shippingPostalCode', '110111'),
                            "phone": data['buyerPhone']
                        }
                    }
                },
                "payer": {
                    "fullName": data['buyerFullName'],
                    "emailAddress": data['buyerEmail'],
                    "contactPhone": data['buyerPhone'],
                    "dniNumber": data['pseReference3'],
                    "dniType": data['pseReference2'],
                    "billingAddress": {
                        "street1": data.get('billingStreet1', data.get('shippingStreet1', 'Not provided')),
                        "street2": data.get('billingStreet2', ''),
                        "city": data.get('billingCity', data.get('shippingCity', 'Bogotá')),
                        "state": data.get('billingState', data.get('shippingState', 'Bogotá')),
                        "country": "CO",
                        "postalCode": data.get('billingPostalCode', data.get('shippingPostalCode', '110111')),
                        "phone": data['buyerPhone']
                    }
                },
                "type": "AUTHORIZATION_AND_CAPTURE",
                "paymentMethod": "PSE",
                "paymentCountry": "CO",
                "deviceSessionId": data.get('deviceSessionId', f"dsid_{int(time.time())}"),
                "ipAddress": request.remote_addr,
                "cookie": data.get('cookie', f"ck_{int(time.time())}"),
                "userAgent": request.headers.get('User-Agent', 'Unknown'),
                "extraParameters": {
                    "FINANCIAL_INSTITUTION_CODE": data['financialInstitutionCode'],
                    "USER_TYPE": data['userType'],
                    "PSE_REFERENCE2": data['pseReference2'],
                    "PSE_REFERENCE3": data['pseReference3'],
                    "RESPONSE_URL": url_for('respuesta_pago', _external=True),
                    "CONFIRMATION_URL": url_for('confirmacion_pago', _external=True)
                }
            }
        }

        # 6. Audit log before sending to PayU
        audit_log = {
            "timestamp": datetime.utcnow().isoformat(),
            "reference": referencia,
            "amount": monto_solicitado,
            "buyer": {
                "name": data['buyerFullName'],
                "email": data['buyerEmail'],
                "doc_type": data['pseReference2'],
                "doc_number": "***" + data['pseReference3'][-4:]
            },
            "bank": data['financialInstitutionCode'],
            "ip": request.remote_addr,
            "user_agent": request.headers.get('User-Agent')
        }
        app.logger.info(f"Initiating PSE transaction: {audit_log}")

        # 7. Send to PayU with timeout
        response = requests.post(
            app.config['PAYU_URL'],
            json=payload,
            timeout=15  # 15 seconds timeout
        )
        response.raise_for_status()
        respuesta_payu = response.json()

        # 8. Validate PayU response
        if respuesta_payu.get('code') != 'SUCCESS':
            app.logger.error(f"Unsuccessful PayU response: {respuesta_payu}")
            return jsonify({
                "success": False,
                "error": "Payment gateway error",
                "details": respuesta_payu.get('error'),
                "payu_response": respuesta_payu
            }), 400

        # 9. Store transaction in database (pseudo-code)
        try:
            # transaction = Transaction(
            #     reference=referencia,
            #     amount=monto_solicitado,
            #     status=respuesta_payu.get('transactionResponse', {}).get('state'),
            #     payu_id=respuesta_payu.get('transactionResponse', {}).get('transactionId'),
            #     payment_method='PSE',
            #     bank_url=respuesta_payu.get('transactionResponse', {}).get('bankURL')
            # )
            # db.session.add(transaction)
            # db.session.commit()
            pass
        except Exception as db_error:
            app.logger.error(f"Error saving transaction to DB: {str(db_error)}")

        # 10. Return success response
        app.logger.info(f"Transaction {referencia} created in PayU")
        return jsonify({
            "success": True,
            "transaction": {
                "reference": referencia,
                "amount": monto_solicitado,
                "paymentUrl": respuesta_payu.get('transactionResponse', {}).get('extraParameters', {}).get('BANK_URL'),
                "status": respuesta_payu.get('transactionResponse', {}).get('state'),
                "transactionId": respuesta_payu.get('transactionResponse', {}).get('transactionId')
            }
        })

    except requests.exceptions.RequestException as e:
        app.logger.error(f"PayU communication error: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Error communicating with payment gateway",
            "details": str(e)
        }), 500
        
    except Exception as e:
        app.logger.error(f"Unexpected error in procesar_pago_pse: {str(e)}")
        return jsonify({
            "success": False,
            "error": "Internal server error",
            "details": str(e)
        }), 500

@app.route('/respuesta-pago')
def respuesta_pago():
    # Handle PayU response
    return render_template('respuesta_pago.html')

@app.route('/confirmacion-pago', methods=['POST'])
def confirmacion_pago():
    # Handle PayU confirmation
    return '', 200

@app.route('/debug-session')
def debug_session():
    # Endpoint para verificar el contenido de la sesión
    return jsonify({
        'carritoPendiente': session.get('carritoPendiente'),
        'session_keys': list(session.keys())
    })