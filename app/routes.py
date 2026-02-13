import psycopg2
import requests  # Requerido para la consulta automática
import time      # Requerido para la espera de 10 segundos
from flask import render_template, request, redirect, url_for, session, flash, jsonify
from database import get_db_connection
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from app import app, get_common_data, get_data_app, images as product_images, user_images, mail
from psycopg2.extras import DictCursor
from flask_mail import Message
from datetime import datetime
import os
import re
import locale
import logging
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
import urllib.parse 

# Configuración regional
try:
    locale.setlocale(locale.LC_ALL, 'es_CO.utf8')
except:
    try:
        locale.setlocale(locale.LC_ALL, '')
    except:
        pass 

# ==========================================================================
# FUNCIONALIDAD ADICIONAL PARA PAGOS (SÓLO PARA AUTOMATIZACIÓN)
# ==========================================================================
def consultar_estado_real_payu(referencia):
    try:
        is_sandbox = app.config.get('PAYU_ENV') == 'sandbox'
        url = "https://sandbox.api.payulatam.com/reports-api/4.0/service.cgi" if is_sandbox else "https://api.payulatam.com/reports-api/4.0/service.cgi"
        
        payload = {
            "test": is_sandbox,
            "language": "es",
            "command": "ORDER_DETAIL_BY_REFERENCE_CODE",
            "merchant": {
                "apiLogin": app.config['PAYU_API_LOGIN'],
                "apiKey": app.config['PAYU_API_KEY']
            },
            "details": {"referenceCode": referencia}
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        data = response.json()

        if data.get('code') == 'SUCCESS' and data.get('result'):
            payload_result = data['result'].get('payload')
            if payload_result:
                tx = payload_result[0]['transactions'][0]
                estado_payu = tx['transactionResponse']['state'] 
                mapa = {'APPROVED': '4', 'DECLINED': '6', 'EXPIRED': '5', 'PENDING': '7'}
                return mapa.get(estado_payu, '7')
    except Exception as e:
        app.logger.error(f"Error en Polling PayU: {e}")
    return '7'

# ==========================================================================
# 1. GESTIÓN DE CLIENTES Y AUTENTICACIÓN (ORIGINAL)
# ==========================================================================

@app.route('/registrar-cliente', methods=['GET', 'POST'])
def registrar_cliente():
    datosApp = get_common_data()
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        fecha_nacimiento = request.form.get('fecha_nacimiento')
        telefono = request.form.get('telefono', '')
        direccion = request.form.get('direccion', '')

        if not nombre or not email or not password or not fecha_nacimiento:
            flash('Por favor, complete todos los campos obligatorios.', 'error')
            return redirect(url_for('registrar_cliente'))

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        try:
            cur.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
            usuario_existente = cur.fetchone()
            if usuario_existente:
                flash('El correo electrónico ya está registrado.', 'error')
                return redirect(url_for('registrar_cliente'))

            hashed_password = generate_password_hash(password)
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
            app.logger.error(f"Error al registrar cliente: {e}")
            flash(f'Error al registrar el cliente: {str(e)}', 'error')
        finally:
            cur.close()
            conn.close()

    return render_template('registrarcliente.html', datosApp=datosApp)

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
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
        usuario = cur.fetchone()
        cur.close()
        conn.close()
        if usuario and check_password_hash(usuario['contraseña'], password):
            if usuario['estado'] != 'habilitado':
                flash('Tu cuenta está inhabilitada.', 'error')
                return None
            else:
                actualizar_ultima_conexion(usuario['id'])
                return usuario
        else:
            flash('Correo o contraseña incorrectos.', 'error')
            return None
    except Exception as e:
        print(f"Error al autenticar usuario: {e}")
        return None

def actualizar_ultima_conexion(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('UPDATE usuarios SET ultima_conexion = CURRENT_TIMESTAMP WHERE id = %s', (user_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error al actualizar última conexión: {e}")

@app.route('/login', methods=['GET', 'POST'])
def login():
    datosApp = get_common_data()
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        usuario = autenticar_usuario(email, password)
        if usuario:
            session['usuario_id'] = usuario['id']
            session['email'] = usuario['email']
            session['rol_id'] = usuario['rol_id']
            session['username'] = usuario['nombre']
            if usuario['rol_id'] == 1: return redirect(url_for('dashboard_admin'))
            elif usuario['rol_id'] == 2: return redirect(url_for('dashboard_admin'))
            elif usuario['rol_id'] == 3: return redirect(url_for('dashboard_cliente'))
            else: return redirect(url_for('login'))
        else: return redirect(url_for('login'))
    return render_template('login.html', datosApp=datosApp)

@app.route('/cliente')
@rol_requerido(3)
def dashboard_cliente():
    datosApp = get_data_app()
    return render_template('dashboard_cliente.html', datosApp=datosApp)

@app.route('/logout')
def logout():
    session.clear()
    flash('Has cerrado sesión correctamente.', 'success')
    return redirect(url_for('login'))

@app.route('/')
def index():
    datosApp = get_common_data()
    return render_template('index.html', datosApp=datosApp)

# ==========================================================================
# 2. GESTIÓN DE PRODUCTOS Y VISTAS GENERALES (ORIGINAL)
# ==========================================================================

@app.route('/agregar-producto', methods=['GET', 'POST'])
@rol_requerido(1) 
def GestionProductos():
    datosApp = get_data_app()
    generos = []
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM generos')
        generos = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e: 
        print("Error cargando géneros:", e)

    if request.method == 'POST':
        try:
            if 'imagen' not in request.files: 
                flash('No se seleccionó ninguna imagen.', 'error')
                return redirect(url_for('GestionProductos'))

            file = request.files['imagen']
            if file.filename == '': 
                flash('El archivo de imagen no tiene nombre.', 'error')
                return redirect(url_for('GestionProductos'))

            imagen_nombre = product_images.save(file, folder='media')
            imagen_url = f"/static/media/{imagen_nombre}"
            
            nombre = request.form.get('nombre')
            precio = float(request.form.get('precio'))
            referencia = request.form.get('referencia')
            genero_id = request.form.get('genero_id')
            descripcion = request.form.get('descripcion')
            
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('INSERT INTO productos (imagen, nombre, precio, referencia, genero_id, descripcion) VALUES (%s, %s, %s, %s, %s, %s)', (imagen_url, nombre, precio, referencia, genero_id, descripcion))
            conn.commit()
            cur.close()
            conn.close()
            
            flash('Producto agregado correctamente.', 'success')
            return redirect(url_for('productos'))
            
        except Exception as e: 
            app.logger.error(f"Error al crear producto: {e}")
            error_msg = str(e)
            
            if "productos_referencia_key" in error_msg:
                flash('⚠️ Ya existe un producto registrado con esa Referencia. Por favor verifica.', 'warning')
            elif "value too long" in error_msg:
                flash('Uno de los campos es demasiado largo para la base de datos.', 'warning')
            else:
                flash(f'Ocurrió un error interno al guardar: {error_msg}', 'error')
            
            return redirect(url_for('GestionProductos'))
    return render_template('GestionProductos.html', datosApp=datosApp, generos=generos)

def formatear_moneda(valor):
    try: return locale.currency(valor, symbol=True, grouping=True)
    except: return f"${valor:,.2f}"

@app.route('/productos')
def productos():
    datosApp = get_common_data()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT p.*, g.nombre AS genero FROM productos p JOIN generos g ON p.genero_id = g.id')
        raw_productos = cur.fetchall()
        cur.close()
        conn.close()
        productos_lista = []
        for p in raw_productos:
            prod = list(p)
            prod[3] = formatear_moneda(float(prod[3])) 
            productos_lista.append(prod)
        datosApp['productos'] = productos_lista
    except: datosApp['productos'] = []
    return render_template('productos.html', datosApp=datosApp)

@app.route('/servicios')
def servicios():
    datosApp = get_common_data()
    return render_template('servicios.html', datosApp=datosApp)

@app.route('/quienes_somos')
def quienes_somos():
    return redirect(url_for('index', _anchor='quienes_somos'))

@app.route('/contactenos')
def contactenos():
    return redirect(url_for('index', _anchor='contactenos'))

@app.errorhandler(404)
def pagina_no_encontrada(error):
    return render_template('404.html'), 404

# ==========================================================================
# 3. ADMINISTRACIÓN (ORIGINAL)
# ==========================================================================

@app.route('/editar-productos')
@rol_requerido(1)
def editar_productos():
    datosApp = get_data_app()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM productos')
        productos = cur.fetchall()
        cur.close()
        conn.close()
    except: productos = []
    return render_template('editar_productos.html', datosApp=datosApp, productos=productos)

@app.route('/editar-producto/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)
def editar_producto(id):
    datosApp = get_data_app()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM productos WHERE id = %s', (id,))
        producto = cur.fetchone()
        cur.execute('SELECT * FROM generos')
        generos = cur.fetchall()
        cur.close()
        conn.close()
    except: producto = None; generos = []

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
            if file and file.filename != '':
                imagen_nombre = product_images.save(file, folder='media')
                imagen_url = f"/static/media/{imagen_nombre}"
                cur.execute('UPDATE productos SET nombre=%s, precio=%s, referencia=%s, genero_id=%s, descripcion=%s, imagen=%s WHERE id=%s', (nombre, precio, referencia, genero_id, descripcion, imagen_url, id))
            else:
                cur.execute('UPDATE productos SET nombre=%s, precio=%s, referencia=%s, genero_id=%s, descripcion=%s WHERE id=%s', (nombre, precio, referencia, genero_id, descripcion, id))
            conn.commit()
            cur.close()
            conn.close()
            flash('Producto actualizado.', 'success')
            return redirect(url_for('editar_productos'))
        except: flash('Error actualizando.', 'error')
    return render_template('editar_producto.html', datosApp=datosApp, producto=producto, generos=generos)

@app.route('/eliminar-productos')
@rol_requerido(1)
def eliminar_productos():
    datosApp = get_data_app()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM productos')
        productos = cur.fetchall()
        cur.close()
        conn.close()
    except: productos = []
    return render_template('eliminar_productos.html', datosApp=datosApp, productos=productos)

@app.route('/eliminar-producto/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)
def eliminar_producto(id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('DELETE FROM productos WHERE id = %s', (id,))
        conn.commit()
        cur.close()
        conn.close()
        flash('Producto eliminado.', 'success')
    except: flash('Error eliminando.', 'error')
    return redirect(url_for('eliminar_productos'))

@app.route('/admin')
@rol_requerido(1)
def dashboard_admin():
    datosApp = get_data_app()
    return render_template('dashboard_admin.html', datosApp=datosApp)

@app.route('/enviar-mensaje', methods=['POST'])
def enviar_mensaje():
    try:
        if request.form.get('website'): return redirect(url_for('index'))
        msg = Message(
            subject=f"Contacto: {request.form.get('name')}",
            sender=app.config['MAIL_USERNAME'],
            recipients=[app.config['MAIL_DEFAULT_SENDER']],
            body=f"Mensaje de {request.form.get('name')} ({request.form.get('email')}): \n\n {request.form.get('message')}"
        )
        with mail.connect() as conn: conn.send(msg)
        flash('Mensaje enviado.', 'success')
    except: flash('Error enviando.', 'error')
    return redirect(url_for('index'))

@app.route('/gestion-usuarios')
@rol_requerido(1)
def gestion_usuarios():
    datosApp = get_data_app()
    usuarios = []; roles = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute('SELECT u.*, r.nombre as rol_nombre FROM usuarios u JOIN roles r ON u.rol_id = r.id ORDER BY u.id')
        usuarios = cur.fetchall()
        cur.execute('SELECT * FROM roles')
        roles = cur.fetchall()
        cur.close()
        conn.close()
    except: pass
    return render_template('gestion_usuarios.html', datosApp=datosApp, usuarios=usuarios, roles=roles)

@app.route('/crear-usuario', methods=['GET', 'POST'])
@rol_requerido(1)
def crear_usuario():
    datosApp = get_data_app()
    roles = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute('SELECT * FROM roles ORDER BY id')
        roles = cur.fetchall()
        cur.close()
        conn.close()
    except: pass
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        rol_id = request.form.get('rol_id')
        telefono = request.form.get('telefono')
        fecha_nacimiento = request.form.get('fecha_nacimiento')
        direccion = request.form.get('direccion')

        nombre_foto = 'Perfil_dafault.png'
        file = request.files.get('fotografia')
        if file and file.filename != '':
            from werkzeug.utils import secure_filename
            filename = secure_filename(file.filename)
            imagen_nombre = user_images.save(file, folder='users')
            nombre_foto = f"/static/media/users/{imagen_nombre}"

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            hashed = generate_password_hash(password)
            cur.execute("""
                INSERT INTO usuarios (nombre, email, contraseña, rol_id, estado, telefono, fecha_nacimiento, direccion, fotografia) 
                VALUES (%s,%s,%s,%s,'habilitado', %s, %s, %s, %s)
            """, (nombre, email, hashed, rol_id, telefono, fecha_nacimiento, direccion, nombre_foto))
            conn.commit()
            cur.close()
            conn.close()
            flash('Usuario creado', 'success')
            return redirect(url_for('gestion_usuarios'))
        except Exception as e: flash(f'Error: {e}', 'error')
    return render_template('crear_usuario.html', datosApp=datosApp, roles=roles)

@app.route('/editar-usuario/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)
def editar_usuario(id):
    datosApp = get_data_app()
    usuario = None
    roles = []

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute('SELECT * FROM usuarios WHERE id=%s', (id,))
        usuario = cur.fetchone()
        cur.execute('SELECT * FROM roles')
        roles = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        flash(f'Error cargando: {e}', 'error')
        return redirect(url_for('gestion_usuarios'))

    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        rol_id = request.form.get('rol_id')
        estado = request.form.get('estado')

        try:
            conn = get_db_connection()
            cur = conn.cursor()

            file = request.files.get('fotografia')
            if file and file.filename != '':
                imagen_nombre = user_images.save(file, folder='users')
                fotografia_url = f"/static/media/users/{imagen_nombre}"
                query = """UPDATE usuarios SET nombre=%s, email=%s, rol_id=%s, estado=%s, fecha_nacimiento=%s, telefono=%s, direccion=%s, fotografia=%s WHERE id=%s"""
                valores = (nombre, email, rol_id, estado, request.form.get('fecha_nacimiento'), request.form.get('telefono'), request.form.get('direccion'), fotografia_url, id)
            else:
                query = """UPDATE usuarios SET nombre=%s, email=%s, rol_id=%s, estado=%s, fecha_nacimiento=%s, telefono=%s, direccion=%s WHERE id=%s"""
                valores = (nombre, email, rol_id, estado, request.form.get('fecha_nacimiento'), request.form.get('telefono'), request.form.get('direccion'), id)

            cur.execute(query, valores)
            conn.commit()
            cur.close()
            conn.close()
            flash('Usuario actualizado correctamente.', 'success')
            return redirect(url_for('gestion_usuarios'))
        except Exception as e:
            flash(f'Error técnico: {e}', 'error')
            return redirect(url_for('editar_usuario', id=id))

    return render_template('editar_usuario.html', datosApp=datosApp, usuario=usuario, roles=roles)

@app.route('/cambiar-password/<int:id>', methods=['POST'])
@rol_requerido(1)
def cambiar_password(id):
    nueva = request.form.get('nueva_password')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        hashed = generate_password_hash(nueva)
        cur.execute('UPDATE usuarios SET contraseña=%s WHERE id=%s', (hashed, id))
        conn.commit()
        cur.close()
        conn.close()
        flash('Contraseña cambiada', 'success')
    except: flash('Error', 'error')
    return redirect(url_for('editar_usuario', id=id))

@app.route('/gestion-pedidos')
@rol_requerido(1)
def gestion_pedidos():
    datosApp = get_data_app()
    pedidos = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        query = """
            SELECT p.*, 
                   STRING_AGG('<li>' || d.producto_nombre || ' <strong>(x' || d.cantidad || ')</strong>', '') as detalles_compra
            FROM pedidos p
            LEFT JOIN detalle_pedidos d ON p.id = d.pedido_id
            GROUP BY p.id
            ORDER BY p.fecha_creacion DESC
        """
        cur.execute(query)
        pedidos = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error gestion pedidos: {e}")
    
    return render_template('gestion_pedidos.html', datosApp=datosApp, pedidos=pedidos)

# ==========================================================================
# 4. GESTIÓN DE PEDIDOS Y PAGOS (ACTUALIZADO CON AUTOMATIZACIÓN)
# ==========================================================================

def generar_reference_code():
    import uuid
    fecha = datetime.now().strftime("%Y%m%d")
    random_code = uuid.uuid4().hex[:6].upper()
    return f"CYBERSHOP-{fecha}-{random_code}"

@app.route('/metodos-pago')
def metodos_pago():
    carrito_json = request.args.get('carrito')
    if carrito_json:
        try:
            session['carritoPendiente'] = json.loads(carrito_json)
        except Exception as e:
            app.logger.warning(f"Error parsing cart: {e}")
    
    carrito = session.get('carritoPendiente', {'items': [], 'total': 0})
    
    if 'total' not in carrito or carrito['total'] == 0:
        try:
            carrito['total'] = sum(float(item.get('precio', 0)) * int(item.get('cantidad', 1)) for item in carrito['items'])
        except:
            carrito['total'] = 0

    datosApp = get_common_data()
    return render_template('metodos_pago.html', datosApp=datosApp, carrito=carrito)

@app.route('/crear-orden', methods=['POST'])
def crear_orden():
    nombre = request.form.get('buyerFullName')
    email = request.form.get('buyerEmail')
    tipo_doc = request.form.get('payerDocumentType')
    documento = request.form.get('payerDocument')
    telefono = request.form.get('buyerPhone')
    direccion = request.form.get('shippingAddress')
    ciudad = request.form.get('shippingCity')
    
    carrito = session.get('carritoPendiente', {})
    if not carrito or not carrito.get('items'):
        flash("Tu carrito está vacío o ha expirado.", "error")
        return redirect(url_for('productos'))

    total_amount = carrito.get('total', 0)
    referencia = generar_reference_code()
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pedidos 
            (referencia_pedido, cliente_nombre, cliente_email, 
             cliente_tipo_documento, cliente_documento, cliente_telefono, 
             direccion_envio, ciudad, monto_total, estado_pago, estado_envio)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDIENTE', 'ESPERA_PAGO')
            RETURNING id
        """, (referencia, nombre, email, tipo_doc, documento, telefono, direccion, ciudad, total_amount))
        
        pedido_id_generado = cur.fetchone()[0]

        for item in carrito['items']:
            prod_nombre = item.get('nombre')
            cantidad = int(item.get('cantidad', 1))
            precio = float(item.get('precio', 0))
            subtotal = precio * cantidad
            cur.execute("""
                INSERT INTO detalle_pedidos (pedido_id, producto_nombre, cantidad, precio_unitario, subtotal)
                VALUES (%s, %s, %s, %s, %s)
            """, (pedido_id_generado, prod_nombre, cantidad, precio, subtotal))

        conn.commit()
        cur.close()
        conn.close()
        
    except Exception as e:
        app.logger.error(f"Error BD Pedidos: {e}")
        flash("Error interno procesando pedido.", "error") 
        return redirect(url_for('metodos_pago'))
    
    merchant_id = app.config.get('PAYU_MERCHANT_ID')
    account_id = app.config.get('PAYU_ACCOUNT_ID', merchant_id)
    api_key = app.config.get('PAYU_API_KEY')
    payu_env = app.config.get('PAYU_ENV', 'sandbox')
    
    amount_dec = Decimal(total_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    amount_str = f"{amount_dec:.2f}"
    currency = 'COP'
    
    signature_raw = f"{api_key}~{merchant_id}~{referencia}~{amount_str}~{currency}"
    payu_signature = hashlib.md5(signature_raw.encode('utf-8')).hexdigest()
    
    payu_url = "https://sandbox.checkout.payulatam.com/ppp-web-gateway-payu/" if payu_env == "sandbox" else "https://checkout.payulatam.com/ppp-web-gateway-payu/"

    return render_template('redireccion_payu.html', 
                           merchantId=merchant_id,
                           accountId=account_id,
                           description=f"Compra {referencia}",
                           referenceCode=referencia,
                           amount=amount_str,
                           currency=currency,
                           signature=payu_signature,
                           test="1" if payu_env == "sandbox" else "0",
                           buyerEmail=email,
                           buyerFullName=nombre,
                           payu_url=payu_url,
                           responseUrl=url_for('respuesta_pago', _external=True),
                           confirmationUrl=url_for('confirmacion_pago', _external=True))

@app.route('/confirmacion-pago', methods=['POST'])
def confirmacion_pago():
    try:
        data = request.form.to_dict()
        api_key = app.config.get('PAYU_API_KEY')
        merchant_id = data.get('merchant_id')
        reference_sale = data.get('reference_sale')
        value = data.get('value')
        currency = data.get('currency')
        state_pol = data.get('state_pol')
        sign_received = data.get('sign')

        try:
            val_dec = Decimal(value)
            if val_dec % 1 == 0: value_formatted = f"{val_dec:.1f}"
            else:
                if str(value).endswith('0') and '.' in str(value): value_formatted = str(value).rstrip('0')
                else: value_formatted = value
        except: value_formatted = value

        msg = f"{api_key}~{merchant_id}~{reference_sale}~{value_formatted}~{currency}~{state_pol}"
        sign_local = hashlib.md5(msg.encode('utf-8')).hexdigest()

        if sign_local != sign_received: 
            app.logger.warning("Firma inválida en confirmación PayU")

        estado_bd = 'PENDIENTE'
        estado_envio_bd = 'ESPERA_PAGO'

        if state_pol == '4': 
            estado_bd = 'APROBADO'
            estado_envio_bd = 'POR_DESPACHAR'
        elif state_pol == '6': 
            estado_bd = 'RECHAZADO'
            estado_envio_bd = 'CANCELADO'
        elif state_pol == '5': 
            estado_bd = 'EXPIRADO'
            estado_envio_bd = 'CANCELADO'

        transaccion_id = data.get('transaction_id')
        metodo = data.get('payment_method_name')

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE pedidos 
            SET estado_pago = %s, id_transaccion_payu = %s, metodo_pago = %s, estado_envio = %s
            WHERE referencia_pedido = %s
        """, (estado_bd, transaccion_id, metodo, estado_envio_bd, reference_sale))
        conn.commit()
        cur.close()
        conn.close()
        return "OK", 200
    except Exception as e:
        app.logger.error(f"Error PayU Confirm: {e}")
        return "Error", 500

@app.route('/respuesta-pago')
def respuesta_pago():
    datosApp = get_common_data() 
    estado_tx = request.args.get('transactionState')
    transaccion_id = request.args.get('transactionId')
    referencia = request.args.get('referenceCode')
    valor = request.args.get('TX_VALUE')
    moneda = request.args.get('currency')
    mensaje_pol = request.args.get('message') 
    metodo = request.args.get('lapPaymentMethod')

    # Bucle de Polling: Intentamos 4 veces (8 seg) si el estado es Pendiente
    if estado_tx == '7' or not estado_tx:
        for i in range(4):
            time.sleep(2)
            nuevo_estado = consultar_estado_real_payu(referencia)
            if nuevo_estado != '7':
                estado_tx = nuevo_estado
                if nuevo_estado == '6': mensaje_pol = "Rechazada por entidad financiera"
                elif nuevo_estado == '4': mensaje_pol = "Aprobada exitosamente"
                break

    estado_bd = 'PENDIENTE'
    estado_envio_bd = 'ESPERA_PAGO'
    datos_comprobante = {
        'estado': 'PENDIENTE', 'titulo': 'Validando Pago', 'id': transaccion_id,
        'referencia': referencia, 'monto': f"{valor} {moneda}", 'mensaje': mensaje_pol,
        'fecha': datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    if estado_tx == '4': 
        estado_bd = 'APROBADO'
        estado_envio_bd = 'POR_DESPACHAR'
        datos_comprobante.update({'estado': 'APROBADO', 'titulo': '¡Transacción Exitosa!'})
        session.pop('carritoPendiente', None)
    elif estado_tx == '6': 
        estado_bd = 'RECHAZADO'
        estado_envio_bd = 'CANCELADO'
        datos_comprobante.update({'estado': 'RECHAZADO', 'titulo': 'Transacción Rechazada'})
    elif estado_tx == '7': 
        datos_comprobante.update({'estado': 'PENDIENTE', 'titulo': 'Pago en Proceso'})
        session.pop('carritoPendiente', None)

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE pedidos 
            SET estado_pago = %s, id_transaccion_payu = %s, metodo_pago = %s, estado_envio = %s
            WHERE referencia_pedido = %s
        """, (estado_bd, transaccion_id, metodo, estado_envio_bd, referencia))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        app.logger.error(f"Error BD Respuesta: {e}")

    return render_template('respuesta_pago.html', datosApp=datosApp, datos=datos_comprobante)

@app.route('/procesar-carrito', methods=['POST'])
def procesar_carrito():
    try:
        data = request.get_json()
        session['carritoPendiente'] = data
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/debug-session')
def debug_session():
    return jsonify({
        'carritoPendiente': session.get('carritoPendiente'),
        'session_keys': list(session.keys())
    })


# En routes.py

@app.route('/carrito')
def ver_carrito():
    datosApp = get_common_data()
    # Renderiza la nueva plantilla del carrito
    return render_template('carrito.html', datosApp=datosApp)