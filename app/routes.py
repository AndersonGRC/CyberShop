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
from app import app, mail, get_common_data, get_data_app, images as product_images, user_images
import os
import re
import locale
import logging

#importaciones PAY U
from flask import request, jsonify, redirect, url_for, flash
import requests
import time
from datetime import datetime
import hashlib
from flask import jsonify


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
        # Debug: Imprime datos recibidos
        print("\n Datos recibidos:")
        print(request.form)
        
        msg = Message(
    subject=f"{request.form.get('name', 'Sin nombre')} quiere contactar contigo - {datetime.now().strftime('%d/%m/%Y')}",
    sender=app.config['MAIL_USERNAME'],
    recipients=[app.config['MAIL_DEFAULT_SENDER']],
    html=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style type="text/css">
            /* Estilos base mejorados */
            body {{
                font-family: 'Arial', sans-serif;
                background-color: #f5f7fa;
                margin: 0;
                padding: 0;
                color: #333333;
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
                margin-top: 0;
                margin-bottom: 15px;
            }}
            .email-footer {{
                text-align: center;
                padding: 15px;
                background-color: #f5f7fa;
                color: #7f8c8d;
                font-size: 14px;
            }}
            .icon {{
                margin-right: 10px;
                vertical-align: middle;
                width: 20px;
                height: 20px;
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
    Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}
    
    Mensaje:
    {request.form.get('message', 'Sin mensaje')}
    
    ---
    Enviado desde el formulario de contacto
    """
)
        # Debug: Verifica conexión SMTP
        with mail.connect() as conn:
            conn.send(msg)  # Forza conexión explícita
        
        flash('Mensaje enviado', 'success')
    except Exception as e:
        print(f"ERROR CRÍTICO: {str(e)}")  # Esto DEBE aparecer en la terminal
        flash('Error al enviar', 'error')
    
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

# Ruta para la página de pago
@app.route('/pagar', methods=['GET'])
def pagar():
    datos_app = get_common_data()
    return render_template('pagoPSE.html', datosApp=datos_app)

# Función para generar firma de transacción para PayU
def generate_payu_signature(api_key, merchant_id, reference_code, amount, currency):
    signature_str = f"{api_key}~{merchant_id}~{reference_code}~{amount}~{currency}"
    return hashlib.md5(signature_str.encode('utf-8')).hexdigest()

# Ruta para iniciar el pago con PayU
@app.route('/iniciar_pago', methods=['POST'])
def iniciar_pago():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Datos no proporcionados', 'success': False}), 400
            
        productos = data.get('productos', [])
        total = data.get('total', 0)
        buyer_email = data.get('email', '')
        buyer_name = data.get('nombreCompleto', '')
        
        if not productos or total <= 0:
            return jsonify({'error': 'Carrito vacío o monto inválido', 'success': False}), 400
        
        # Crear una referencia única para la orden
        reference_code = f"ORDER_{int(time.time())}"
        
        # Generar firma para PayU
        signature = generate_payu_signature(
            app.config['PAYU_API_KEY'],
            app.config['PAYU_MERCHANT_ID'],
            reference_code,
            total,
            'COP'
        )
        
        # Construir la URL de redirección a PayU
        url_pago = (
            "https://sandbox.checkout.payulatam.com/ppp-web-gateway-payu/?" +
            f"merchantId={app.config['PAYU_MERCHANT_ID']}&" +
            f"accountId={app.config['PAYU_MERCHANT_ID']}&" +
            f"description=Compra en CyberShop&" +
            f"referenceCode={reference_code}&" +
            f"amount={total}&" +
            f"currency=COP&" +
            f"signature={signature}&" +
            f"test=True&" +  # True para sandbox
            f"buyerEmail={buyer_email}&" +
            f"buyerFullName={buyer_name}&" +
            f"responseUrl={url_for('respuesta_pago', _external=True)}&" +
            f"confirmationUrl={url_for('confirmacion_pago', _external=True)}"
        )
        
        return jsonify({
            'success': True,
            'url_pago': url_pago,
            'reference_code': reference_code
        })
        
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

# Ruta para la respuesta de PayU (redirección después del pago)

@app.route('/respuesta_pago', methods=['GET'])
def respuesta_pago():
    try:
        # 1. Capturar parámetros esenciales
        params = {
            'transaction_state': request.args.get('transactionState'),
            'reference_code': request.args.get('referenceCode'),
            'amount': request.args.get('TX_VALUE'),
            'currency': request.args.get('currency'),
            'signature': request.args.get('signature'),
            'payment_method': request.args.get('paymentMethodType'),
            'transaction_id': request.args.get('transactionId')
        }

        # 2. Validación mínima
        if None in params.values():
            logging.error(f'Parámetros incompletos: {request.args}')
            flash('Respuesta de pago incompleta', 'error')
            return redirect(url_for('pago_fallido'))

        # 3. Verificar firma (seguridad crítica)
        signature_check = hashlib.md5(
            f"{app.config['PAYU_API_KEY']}~{app.config['PAYU_MERCHANT_ID']}~{params['reference_code']}~{params['amount']}~{params['currency']}"
            .encode('utf-8')
        ).hexdigest()

        if params['signature'] != signature_check:
            logging.warning(f'Firma inválida en pago {params["reference_code"]}')
            flash('Error de verificación de seguridad', 'error')
            return redirect(url_for('pago_fallido'))

        # 4. Redirigir según estado
        estado = params['transaction_state']
        referencia = params['reference_code']

        if estado == '4':  # Aprobado
            logging.info(f"Pago aprobado: {referencia}")
            flash('¡Pago exitoso!', 'success')
            return redirect(url_for('pago_exitoso', referencia=referencia))

        elif estado == '6':  # Declinado
            logging.info(f"Pago declinado: {referencia}")
            flash('Pago declinado por el banco', 'warning')
            return redirect(url_for('reintentar_pago', referencia=referencia))

        elif estado == '7':  # Pendiente
            logging.info(f"Pago pendiente: {referencia}")
            flash('Pago en proceso de verificación', 'info')
            return redirect(url_for('pago_pendiente', referencia=referencia))

        else:  # Estado desconocido
            logging.error(f"Estado desconocido: {estado} - Ref: {referencia}")
            flash('Estado de pago no reconocido', 'error')
            return redirect(url_for('pago_fallido'))

    except Exception as e:
        logging.critical(f"Error en respuesta_pago: {str(e)} - Args: {request.args}")
        flash('Error procesando tu pago', 'error')
        return redirect(url_for('pago_fallido'))
    
    # Verificar la firma de respuesta
    expected_signature = generate_payu_signature(
        app.config['PAYU_API_KEY'],
        app.config['PAYU_MERCHANT_ID'],
        reference_code,
        amount,
        currency
    )
    
    if signature != expected_signature:
        flash('Error en la verificación del pago', 'danger')
        return redirect(url_for('index'))
    
    if transaction_state == '4':  # Aprobado
        flash('Pago aprobado correctamente', 'success')
        # Registrar en base de datos
    elif transaction_state == '6':  # Declinado
        flash('Pago declinado por la entidad financiera', 'danger')
    elif transaction_state == '7':  # Pendiente
        flash('Pago pendiente de confirmación', 'warning')
    else:
        flash('Estado de pago desconocido', 'warning')
    
    return redirect(url_for('index'))



# Ruta para la confirmación de PayU (notificación instantánea)
@app.route('/confirmacion_pago', methods=['POST'])
def confirmacion_pago():
    try:
        transaction_state = request.form.get('transactionState')
        reference_code = request.form.get('referenceCode')
        amount = request.form.get('TX_VALUE')
        currency = request.form.get('currency')
        signature = request.form.get('signature')
        
        expected_signature = generate_payu_signature(
            app.config['PAYU_API_KEY'],
            app.config['PAYU_MERCHANT_ID'],
            reference_code,
            amount,
            currency
        )
        
        if signature != expected_signature:
            return jsonify({'status': 'ERROR', 'message': 'Firma inválida'}), 400
        
        # Procesar según estado
        if transaction_state == '4':  # Aprobado
            pass  # Registrar pago
        elif transaction_state == '6':  # Declinado
            pass
        elif transaction_state == '7':  # Pendiente
            pass
        
        return jsonify({'status': 'OK'}), 200
        
    except Exception as e:
        return jsonify({'status': 'ERROR', 'message': str(e)}), 500

# Ruta para obtener bancos PSE
@app.route('/get_banks', methods=['GET'])
def get_banks():
    url = f"{app.config['PAYU_URL']}getBanksList"
    payload = {
        "language": "es",
        "command": "GET_BANKS_LIST",
        "merchant": {
            "apiKey": app.config['PAYU_API_KEY'],
            "apiLogin": app.config['PAYU_API_LOGIN']
        },
        "test": True,
        "bankListInformation": {
            "paymentMethod": "PSE",
            "paymentCountry": "CO"
        }
    }
    
    try:
        response = requests.post(url, json=payload)
        return jsonify(response.json()) if response.status_code == 200 else jsonify({"error": response.text}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500