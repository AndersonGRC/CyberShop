"""
routes/admin.py — Blueprint de administracion.

Rutas protegidas con @rol_requerido(1) para gestion de productos,
usuarios y pedidos. Solo accesibles por usuarios con rol Admin.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask import current_app as app
from werkzeug.security import generate_password_hash
from psycopg2.extras import DictCursor

from database import get_db_connection
from helpers import get_data_app
from security import rol_requerido

admin_bp = Blueprint('admin', __name__)


# --- Dashboard ---

@admin_bp.route('/admin')
@rol_requerido(1)
def dashboard_admin():
    """Panel principal de administracion."""
    datosApp = get_data_app()
    return render_template('dashboard_admin.html', datosApp=datosApp)


# --- Gestion de Productos ---

@admin_bp.route('/agregar-producto', methods=['GET', 'POST'])
@rol_requerido(1)
def GestionProductos():
    """Formulario para agregar nuevos productos al catalogo."""
    from app import product_images

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
                return redirect(url_for('admin.GestionProductos'))

            file = request.files['imagen']
            if file.filename == '':
                flash('El archivo de imagen no tiene nombre.', 'error')
                return redirect(url_for('admin.GestionProductos'))

            imagen_nombre = product_images.save(file, folder='media')
            imagen_url = f"/static/media/{imagen_nombre}"

            nombre = request.form.get('nombre')
            precio = float(request.form.get('precio'))
            referencia = request.form.get('referencia')
            genero_id = request.form.get('genero_id')
            descripcion = request.form.get('descripcion')

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                'INSERT INTO productos (imagen, nombre, precio, referencia, genero_id, descripcion) VALUES (%s, %s, %s, %s, %s, %s)',
                (imagen_url, nombre, precio, referencia, genero_id, descripcion)
            )
            conn.commit()
            cur.close()
            conn.close()

            flash('Producto agregado correctamente.', 'success')
            return redirect(url_for('public.productos'))

        except Exception as e:
            app.logger.error(f"Error al crear producto: {e}")
            error_msg = str(e)

            if "productos_referencia_key" in error_msg:
                flash('Ya existe un producto registrado con esa Referencia. Por favor verifica.', 'warning')
            elif "value too long" in error_msg:
                flash('Uno de los campos es demasiado largo para la base de datos.', 'warning')
            else:
                flash(f'Ocurrió un error interno al guardar: {error_msg}', 'error')

            return redirect(url_for('admin.GestionProductos'))
    return render_template('GestionProductos.html', datosApp=datosApp, generos=generos)


@admin_bp.route('/editar-productos')
@rol_requerido(1)
def editar_productos():
    """Lista de productos disponibles para edicion."""
    datosApp = get_data_app()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM productos')
        productos = cur.fetchall()
        cur.close()
        conn.close()
    except Exception:
        productos = []
    return render_template('editar_productos.html', datosApp=datosApp, productos=productos)


@admin_bp.route('/editar-producto/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)
def editar_producto(id):
    """Formulario de edicion de un producto existente."""
    from app import product_images

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
    except Exception:
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
            if file and file.filename != '':
                imagen_nombre = product_images.save(file, folder='media')
                imagen_url = f"/static/media/{imagen_nombre}"
                cur.execute(
                    'UPDATE productos SET nombre=%s, precio=%s, referencia=%s, genero_id=%s, descripcion=%s, imagen=%s WHERE id=%s',
                    (nombre, precio, referencia, genero_id, descripcion, imagen_url, id)
                )
            else:
                cur.execute(
                    'UPDATE productos SET nombre=%s, precio=%s, referencia=%s, genero_id=%s, descripcion=%s WHERE id=%s',
                    (nombre, precio, referencia, genero_id, descripcion, id)
                )
            conn.commit()
            cur.close()
            conn.close()
            flash('Producto actualizado.', 'success')
            return redirect(url_for('admin.editar_productos'))
        except Exception:
            flash('Error actualizando.', 'error')
    return render_template('editar_producto.html', datosApp=datosApp, producto=producto, generos=generos)


@admin_bp.route('/eliminar-productos')
@rol_requerido(1)
def eliminar_productos():
    """Lista de productos disponibles para eliminacion."""
    datosApp = get_data_app()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT * FROM productos')
        productos = cur.fetchall()
        cur.close()
        conn.close()
    except Exception:
        productos = []
    return render_template('eliminar_productos.html', datosApp=datosApp, productos=productos)


@admin_bp.route('/eliminar-producto/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)
def eliminar_producto(id):
    """Elimina un producto del catalogo por su ID."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('DELETE FROM productos WHERE id = %s', (id,))
        conn.commit()
        cur.close()
        conn.close()
        flash('Producto eliminado.', 'success')
    except Exception:
        flash('Error eliminando.', 'error')
    return redirect(url_for('admin.eliminar_productos'))


# --- Gestion de Usuarios ---

@admin_bp.route('/gestion-usuarios')
@rol_requerido(1)
def gestion_usuarios():
    """Lista de todos los usuarios del sistema con sus roles."""
    datosApp = get_data_app()
    usuarios = []
    roles = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute('SELECT u.*, r.nombre as rol_nombre FROM usuarios u JOIN roles r ON u.rol_id = r.id ORDER BY u.id')
        usuarios = cur.fetchall()
        cur.execute('SELECT * FROM roles')
        roles = cur.fetchall()
        cur.close()
        conn.close()
    except Exception:
        pass
    return render_template('gestion_usuarios.html', datosApp=datosApp, usuarios=usuarios, roles=roles)


@admin_bp.route('/crear-usuario', methods=['GET', 'POST'])
@rol_requerido(1)
def crear_usuario():
    """Formulario para crear nuevos usuarios con cualquier rol."""
    from app import user_images

    datosApp = get_data_app()
    roles = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute('SELECT * FROM roles ORDER BY id')
        roles = cur.fetchall()
        cur.close()
        conn.close()
    except Exception:
        pass
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
            return redirect(url_for('admin.gestion_usuarios'))
        except Exception as e:
            flash(f'Error: {e}', 'error')
    return render_template('crear_usuario.html', datosApp=datosApp, roles=roles)


@admin_bp.route('/editar-usuario/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)
def editar_usuario(id):
    """Formulario de edicion de datos de un usuario existente."""
    from app import user_images

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
        return redirect(url_for('admin.gestion_usuarios'))

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
            return redirect(url_for('admin.gestion_usuarios'))
        except Exception as e:
            flash(f'Error técnico: {e}', 'error')
            return redirect(url_for('admin.editar_usuario', id=id))

    return render_template('editar_usuario.html', datosApp=datosApp, usuario=usuario, roles=roles)


@admin_bp.route('/cambiar-password/<int:id>', methods=['POST'])
@rol_requerido(1)
def cambiar_password(id):
    """Cambia la contrasena de un usuario por su ID."""
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
    except Exception:
        flash('Error', 'error')
    return redirect(url_for('admin.editar_usuario', id=id))


# --- Gestion de Pedidos ---

@admin_bp.route('/gestion-pedidos')
@rol_requerido(1)
def gestion_pedidos():
    """Lista de todos los pedidos con detalle de productos comprados."""
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
