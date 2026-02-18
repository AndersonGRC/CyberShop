"""
routes/admin.py — Blueprint de administracion.

Rutas protegidas con @rol_requerido(1) para gestion de productos,
usuarios y pedidos. Solo accesibles por usuarios con rol Admin.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, Response, current_app
import csv
import io
from werkzeug.security import generate_password_hash
from psycopg2.extras import DictCursor

from database import get_db_connection, get_db_cursor
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
                'INSERT INTO productos (imagen, nombre, precio, referencia, genero_id, descripcion, stock) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (imagen_url, nombre, precio, referencia, genero_id, descripcion, request.form.get('stock', 0))
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
        stock = request.form.get('stock', 0)
        descripcion = request.form.get('descripcion')
        file = request.files.get('imagen')
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            if file and file.filename != '':
                imagen_nombre = product_images.save(file, folder='media')
                imagen_url = f"/static/media/{imagen_nombre}"
                cur.execute(
                    'UPDATE productos SET nombre=%s, precio=%s, referencia=%s, genero_id=%s, descripcion=%s, imagen=%s, stock=%s WHERE id=%s',
                    (nombre, precio, referencia, genero_id, descripcion, imagen_url, stock, id)
                )
            else:
                cur.execute(
                    'UPDATE productos SET nombre=%s, precio=%s, referencia=%s, genero_id=%s, descripcion=%s, stock=%s WHERE id=%s',
                    (nombre, precio, referencia, genero_id, descripcion, stock, id)
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


# --- Gestion de Inventario ---

@admin_bp.route('/inventario')
@rol_requerido(1)
def gestion_inventario():
    """Lista de productos con su stock actual."""
    datosApp = get_data_app()
    productos = []
    valor_total = 0
    categorias = []
    
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # id, imagen, nombre, referencia, genero_id, descripcion, stock
            cur.execute('SELECT p.*, g.nombre as categoria FROM productos p JOIN generos g ON p.genero_id = g.id ORDER BY p.id')
            productos_data = cur.fetchall()
            
            # Convertir a lista de dicts para asegurar compatibilidad en template si cursor se cierra
            # Aunque con fetchall ya deberia ser lista de DictRow
            productos = [dict(p) for p in productos_data]
            
            # Calcular valor total
            valor_total = sum(p['precio'] * p['stock'] for p in productos)
            
            # Obtener categorias para filtro
            cur.execute('SELECT * FROM generos ORDER BY nombre')
            categorias = cur.fetchall()
            
    except Exception as e:
        current_app.logger.error(f"Error cargando inventario: {e}")
        flash(f"Error cargando inventario: {e}", "error")
    
    return render_template('gestion_inventario.html', datosApp=datosApp, productos=productos, valor_total=valor_total, categorias=categorias)


@admin_bp.route('/inventario/exportar')
@rol_requerido(1)
def exportar_inventario():
    """Genera y descarga un CSV del inventario."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT p.id, p.nombre, p.referencia, p.precio, p.stock, g.nombre as categoria FROM productos p JOIN generos g ON p.genero_id = g.id ORDER BY p.id')
            productos = cur.fetchall()
        
        # Crear CSV en memoria
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['ID', 'Nombre', 'Referencia', 'Categoria', 'Precio', 'Stock', 'Valor Total'])
        
        for p in productos:
            valor = p['precio'] * p['stock']
            cw.writerow([p['id'], p['nombre'], p['referencia'], p['categoria'], p['precio'], p['stock'], valor])
            
        output = si.getvalue()
        return Response(output, mimetype='text/csv', headers={"Content-Disposition": "attachment;filename=inventario.csv"})
        
    except Exception as e:
        current_app.logger.error(f"Error exportando CSV: {e}")
        flash("Error generando reporte", "error")
        return redirect(url_for('admin.gestion_inventario'))


@admin_bp.route('/inventario/actualizar', methods=['POST'])
@rol_requerido(1)
def actualizar_stock():
    """Actualiza el stock de un producto (Sumar o Fijar) y registra el movimiento."""
    try:
        producto_id = request.form.get('producto_id')
        cantidad = int(request.form.get('cantidad', 0))
        accion = request.form.get('accion') # 'sumar' o 'fijar'
        motivo = request.form.get('motivo', 'Ajuste manual')
        
        if not producto_id:
            flash("ID de producto no válido", "error")
            return redirect(url_for('admin.gestion_inventario'))

        conn = get_db_connection()
        cur = conn.cursor()
        
        # Obtener stock actual
        cur.execute("SELECT stock FROM productos WHERE id = %s", (producto_id,))
        res = cur.fetchone()
        stock_actual = res[0] if res else 0
        
        stock_nuevo = stock_actual
        tipo_movimiento = 'AJUSTE'
        cantidad_real = 0

        if accion == 'sumar':
            stock_nuevo = stock_actual + cantidad
            tipo_movimiento = 'ENTRADA'
            cantidad_real = cantidad
        elif accion == 'restar':
            stock_nuevo = stock_actual - cantidad
            if stock_nuevo < 0:
                flash("El stock no puede ser negativo", "error")
                return redirect(url_for('admin.gestion_inventario'))
            tipo_movimiento = 'SALIDA'
            cantidad_real = -cantidad
        elif accion == 'fijar':
            if cantidad < 0:
                flash("El stock no puede ser negativo", "error")
                return redirect(url_for('admin.gestion_inventario'))
            stock_nuevo = cantidad
            cantidad_real = stock_nuevo - stock_actual
            tipo_movimiento = 'ENTRADA' if cantidad_real > 0 else 'SALIDA'
            if cantidad_real == 0:
                 tipo_movimiento = 'AJUSTE' # Sin cambio

        if stock_nuevo != stock_actual:
            # Actualizar producto
            cur.execute("UPDATE productos SET stock = %s WHERE id = %s", (stock_nuevo, producto_id))
            
            # Registrar log
            # Asumimos usuario_id=1 para admin si no hay session['user_id'] disponible facil, 
            # pero mejor intentemos sacarlo de sesion si fuera posible o query.
            # En security.py no se ve que se guarde user_id en session, verifiquemos.
            # Si no, usaremos NULL o 1.
            usuario_id = session.get('user_id', 1) 
            
            cur.execute("""
                INSERT INTO inventario_log (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, usuario_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (producto_id, tipo_movimiento, abs(cantidad_real), stock_actual, stock_nuevo, motivo, usuario_id))

        conn.commit()
        cur.close()
        conn.close()
        flash("Inventario actualizado correctamente", "success")
        
    except Exception as e:
        app.logger.error(f"Error actualizando stock: {e}")
        flash(f"Error actualizando stock: {e}", "error")
        
    return redirect(url_for('admin.gestion_inventario'))


@admin_bp.route('/inventario/historial/<int:id>')
@rol_requerido(1)
def historial_inventario(id):
    """Retorna el historial de movimientos de un producto."""
    movimientos = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        query = """
            SELECT l.tipo, l.cantidad, l.stock_anterior, l.stock_nuevo, l.motivo, l.fecha, u.nombre
            FROM inventario_log l
            LEFT JOIN usuarios u ON l.usuario_id = u.id
            WHERE l.producto_id = %s
            ORDER BY l.fecha DESC
        """
        cur.execute(query, (id,))
        movimientos = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        app.logger.error(f"Error cargando historial: {e}")
    
    # Retornar partial view o json? 
    # JSON es mas facil para cargar en modal via JS fetch
    lista = []
    for m in movimientos:
        lista.append({
            'tipo': m[0],
            'cantidad': m[1],
            'stock_anterior': m[2],
            'stock_nuevo': m[3],
            'motivo': m[4],
            'fecha': m[5].strftime('%Y-%m-%d %H:%M'),
            'usuario': m[6] or 'Sistema'
        })
    return jsonify(lista)


# --- Gestion de Publicaciones del Home ---

@admin_bp.route('/admin/publicaciones')
@rol_requerido(1)
def gestion_publicaciones():
    """Lista de publicaciones del home."""
    datosApp = get_data_app()
    publicaciones = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM publicaciones_home ORDER BY fecha_creacion DESC')
            publicaciones = cur.fetchall()
    except Exception as e:
        flash(f'Error cargando publicaciones: {e}', 'error')
    return render_template('gestion_publicaciones.html', datosApp=datosApp, publicaciones=publicaciones)


@admin_bp.route('/admin/publicaciones/crear', methods=['GET', 'POST'])
@rol_requerido(1)
def crear_publicacion():
    """Crear nueva publicacion del home."""
    from app import product_images

    datosApp = get_data_app()
    if request.method == 'POST':
        titulo = request.form.get('titulo')
        descripcion = request.form.get('descripcion')
        imagen_url = None

        file = request.files.get('imagen')
        if file and file.filename != '':
            imagen_nombre = product_images.save(file, folder='media')
            imagen_url = f"/static/media/{imagen_nombre}"

        try:
            with get_db_cursor() as cur:
                cur.execute(
                    'INSERT INTO publicaciones_home (titulo, descripcion, imagen) VALUES (%s, %s, %s)',
                    (titulo, descripcion, imagen_url)
                )
            flash('Publicacion creada correctamente.', 'success')
            return redirect(url_for('admin.gestion_publicaciones'))
        except Exception as e:
            flash(f'Error creando publicacion: {e}', 'error')

    return render_template('gestion_publicaciones.html', datosApp=datosApp, publicaciones=[], modo='crear')


@admin_bp.route('/admin/publicaciones/editar/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)
def editar_publicacion(id):
    """Editar publicacion existente."""
    from app import product_images

    datosApp = get_data_app()
    publicacion = None

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM publicaciones_home WHERE id = %s', (id,))
            publicacion = cur.fetchone()
    except Exception:
        flash('Error cargando publicacion.', 'error')
        return redirect(url_for('admin.gestion_publicaciones'))

    if request.method == 'POST':
        titulo = request.form.get('titulo')
        descripcion = request.form.get('descripcion')
        file = request.files.get('imagen')

        try:
            with get_db_cursor() as cur:
                if file and file.filename != '':
                    imagen_nombre = product_images.save(file, folder='media')
                    imagen_url = f"/static/media/{imagen_nombre}"
                    cur.execute(
                        'UPDATE publicaciones_home SET titulo=%s, descripcion=%s, imagen=%s WHERE id=%s',
                        (titulo, descripcion, imagen_url, id)
                    )
                else:
                    cur.execute(
                        'UPDATE publicaciones_home SET titulo=%s, descripcion=%s WHERE id=%s',
                        (titulo, descripcion, id)
                    )
            flash('Publicacion actualizada.', 'success')
            return redirect(url_for('admin.gestion_publicaciones'))
        except Exception as e:
            flash(f'Error actualizando: {e}', 'error')

    return render_template('gestion_publicaciones.html', datosApp=datosApp, publicaciones=[], modo='editar', publicacion=publicacion)


@admin_bp.route('/admin/publicaciones/eliminar/<int:id>', methods=['POST'])
@rol_requerido(1)
def eliminar_publicacion(id):
    """Eliminar publicacion."""
    try:
        with get_db_cursor() as cur:
            cur.execute('DELETE FROM publicaciones_home WHERE id = %s', (id,))
        flash('Publicacion eliminada.', 'success')
    except Exception:
        flash('Error eliminando publicacion.', 'error')
    return redirect(url_for('admin.gestion_publicaciones'))


@admin_bp.route('/admin/publicaciones/toggle/<int:id>', methods=['POST'])
@rol_requerido(1)
def toggle_publicacion(id):
    """Activar/desactivar publicacion."""
    try:
        with get_db_cursor() as cur:
            cur.execute('UPDATE publicaciones_home SET activo = NOT activo WHERE id = %s', (id,))
        flash('Estado de publicacion actualizado.', 'success')
    except Exception:
        flash('Error cambiando estado.', 'error')
    return redirect(url_for('admin.gestion_publicaciones'))


# --- Gestion de Slides del Carrusel ---

@admin_bp.route('/admin/slides')
@rol_requerido(1)
def gestion_slides():
    """Lista de slides del carrusel del home."""
    datosApp = get_data_app()
    slides = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM slides_home ORDER BY orden ASC, id ASC')
            slides = cur.fetchall()
    except Exception as e:
        flash(f'Error cargando slides: {e}', 'error')
    return render_template('gestion_slides.html', datosApp=datosApp, slides=slides)


@admin_bp.route('/admin/slides/crear', methods=['GET', 'POST'])
@rol_requerido(1)
def crear_slide():
    """Crear nuevo slide del carrusel."""
    from app import product_images

    datosApp = get_data_app()
    if request.method == 'POST':
        titulo = request.form.get('titulo')
        descripcion = request.form.get('descripcion')
        orden = request.form.get('orden', 0)

        file = request.files.get('imagen')
        if not file or file.filename == '':
            flash('La imagen es obligatoria para el slide.', 'error')
            return redirect(url_for('admin.gestion_slides'))

        imagen_nombre = product_images.save(file, folder='media')
        imagen_url = f"/static/media/{imagen_nombre}"

        try:
            with get_db_cursor() as cur:
                cur.execute(
                    'INSERT INTO slides_home (imagen, titulo, descripcion, orden) VALUES (%s, %s, %s, %s)',
                    (imagen_url, titulo, descripcion, orden)
                )
            flash('Slide creado correctamente.', 'success')
            return redirect(url_for('admin.gestion_slides'))
        except Exception as e:
            flash(f'Error creando slide: {e}', 'error')

    return render_template('gestion_slides.html', datosApp=datosApp, slides=[], modo='crear')


@admin_bp.route('/admin/slides/editar/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)
def editar_slide(id):
    """Editar slide existente."""
    from app import product_images

    datosApp = get_data_app()
    slide = None

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM slides_home WHERE id = %s', (id,))
            slide = cur.fetchone()
    except Exception:
        flash('Error cargando slide.', 'error')
        return redirect(url_for('admin.gestion_slides'))

    if request.method == 'POST':
        titulo = request.form.get('titulo')
        descripcion = request.form.get('descripcion')
        orden = request.form.get('orden', 0)
        file = request.files.get('imagen')

        try:
            with get_db_cursor() as cur:
                if file and file.filename != '':
                    imagen_nombre = product_images.save(file, folder='media')
                    imagen_url = f"/static/media/{imagen_nombre}"
                    cur.execute(
                        'UPDATE slides_home SET imagen=%s, titulo=%s, descripcion=%s, orden=%s WHERE id=%s',
                        (imagen_url, titulo, descripcion, orden, id)
                    )
                else:
                    cur.execute(
                        'UPDATE slides_home SET titulo=%s, descripcion=%s, orden=%s WHERE id=%s',
                        (titulo, descripcion, orden, id)
                    )
            flash('Slide actualizado.', 'success')
            return redirect(url_for('admin.gestion_slides'))
        except Exception as e:
            flash(f'Error actualizando slide: {e}', 'error')

    return render_template('gestion_slides.html', datosApp=datosApp, slides=[], modo='editar', slide=slide)


@admin_bp.route('/admin/slides/eliminar/<int:id>', methods=['POST'])
@rol_requerido(1)
def eliminar_slide(id):
    """Eliminar slide del carrusel."""
    try:
        with get_db_cursor() as cur:
            cur.execute('DELETE FROM slides_home WHERE id = %s', (id,))
        flash('Slide eliminado.', 'success')
    except Exception:
        flash('Error eliminando slide.', 'error')
    return redirect(url_for('admin.gestion_slides'))


@admin_bp.route('/admin/slides/toggle/<int:id>', methods=['POST'])
@rol_requerido(1)
def toggle_slide(id):
    """Activar/desactivar slide."""
    try:
        with get_db_cursor() as cur:
            cur.execute('UPDATE slides_home SET activo = NOT activo WHERE id = %s', (id,))
        flash('Estado del slide actualizado.', 'success')
    except Exception:
        flash('Error cambiando estado.', 'error')
    return redirect(url_for('admin.gestion_slides'))


# --- Gestion de Servicios ---

@admin_bp.route('/admin/servicios')
@rol_requerido(1)
def gestion_servicios():
    """Lista de servicios."""
    datosApp = get_data_app()
    servicios = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM servicios_home ORDER BY orden ASC, id ASC')
            servicios = cur.fetchall()
    except Exception as e:
        flash(f'Error cargando servicios: {e}', 'error')
    return render_template('gestion_servicios.html', datosApp=datosApp, servicios=servicios)


@admin_bp.route('/admin/servicios/crear', methods=['GET', 'POST'])
@rol_requerido(1)
def crear_servicio():
    """Crear nuevo servicio."""
    from app import product_images

    datosApp = get_data_app()
    if request.method == 'POST':
        titulo = request.form.get('titulo')
        descripcion = request.form.get('descripcion')
        beneficios = request.form.get('beneficios')
        orden = request.form.get('orden', 0)
        imagen_url = None

        file = request.files.get('imagen')
        if file and file.filename != '':
            imagen_nombre = product_images.save(file, folder='media')
            imagen_url = f"/static/media/{imagen_nombre}"

        try:
            with get_db_cursor() as cur:
                cur.execute(
                    'INSERT INTO servicios_home (titulo, descripcion, beneficios, imagen, orden) VALUES (%s, %s, %s, %s, %s)',
                    (titulo, descripcion, beneficios, imagen_url, orden)
                )
            flash('Servicio creado correctamente.', 'success')
            return redirect(url_for('admin.gestion_servicios'))
        except Exception as e:
            flash(f'Error creando servicio: {e}', 'error')

    return render_template('gestion_servicios.html', datosApp=datosApp, servicios=[], modo='crear')


@admin_bp.route('/admin/servicios/editar/<int:id>', methods=['GET', 'POST'])
@rol_requerido(1)
def editar_servicio(id):
    """Editar servicio existente."""
    from app import product_images

    datosApp = get_data_app()
    servicio = None

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM servicios_home WHERE id = %s', (id,))
            servicio = cur.fetchone()
    except Exception:
        flash('Error cargando servicio.', 'error')
        return redirect(url_for('admin.gestion_servicios'))

    if request.method == 'POST':
        titulo = request.form.get('titulo')
        descripcion = request.form.get('descripcion')
        beneficios = request.form.get('beneficios')
        orden = request.form.get('orden', 0)
        file = request.files.get('imagen')

        try:
            with get_db_cursor() as cur:
                if file and file.filename != '':
                    imagen_nombre = product_images.save(file, folder='media')
                    imagen_url = f"/static/media/{imagen_nombre}"
                    cur.execute(
                        'UPDATE servicios_home SET titulo=%s, descripcion=%s, beneficios=%s, imagen=%s, orden=%s WHERE id=%s',
                        (titulo, descripcion, beneficios, imagen_url, orden, id)
                    )
                else:
                    cur.execute(
                        'UPDATE servicios_home SET titulo=%s, descripcion=%s, beneficios=%s, orden=%s WHERE id=%s',
                        (titulo, descripcion, beneficios, orden, id)
                    )
            flash('Servicio actualizado.', 'success')
            return redirect(url_for('admin.gestion_servicios'))
        except Exception as e:
            flash(f'Error actualizando: {e}', 'error')

    return render_template('gestion_servicios.html', datosApp=datosApp, servicios=[], modo='editar', servicio=servicio)


@admin_bp.route('/admin/servicios/eliminar/<int:id>', methods=['POST'])
@rol_requerido(1)
def eliminar_servicio(id):
    """Eliminar servicio."""
    try:
        with get_db_cursor() as cur:
            cur.execute('DELETE FROM servicios_home WHERE id = %s', (id,))
        flash('Servicio eliminado.', 'success')
    except Exception:
        flash('Error eliminando servicio.', 'error')
    return redirect(url_for('admin.gestion_servicios'))


@admin_bp.route('/admin/servicios/toggle/<int:id>', methods=['POST'])
@rol_requerido(1)
def toggle_servicio(id):
    """Activar/desactivar servicio."""
    try:
        with get_db_cursor() as cur:
            cur.execute('UPDATE servicios_home SET activo = NOT activo WHERE id = %s', (id,))
        flash('Estado del servicio actualizado.', 'success')
    except Exception:
        flash('Error cambiando estado.', 'error')
    return redirect(url_for('admin.gestion_servicios'))


# --- Configuracion de Secciones del Home ---

@admin_bp.route('/admin/config-secciones', methods=['GET', 'POST'])
@rol_requerido(1)
def config_secciones():
    """Panel para activar/desactivar secciones del home."""
    datosApp = get_data_app()

    if request.method == 'POST':
        try:
            with get_db_cursor() as cur:
                cur.execute('SELECT clave FROM config_secciones')
                todas_claves = [row[0] for row in cur.fetchall()]

                for clave in todas_claves:
                    valor = 'true' if request.form.get(clave) else 'false'
                    cur.execute(
                        'UPDATE config_secciones SET valor = %s WHERE clave = %s',
                        (valor, clave)
                    )
            flash('Configuracion actualizada correctamente.', 'success')
        except Exception as e:
            flash(f'Error actualizando configuracion: {e}', 'error')

    secciones = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM config_secciones ORDER BY clave')
            secciones = cur.fetchall()
    except Exception as e:
        flash(f'Error cargando configuracion: {e}', 'error')

    return render_template('config_secciones.html', datosApp=datosApp, secciones=secciones)


# --- Punto de Venta (POS) ---

@admin_bp.route('/admin/pos')
@rol_requerido(1)
def facturacion_pos():
    """Interfaz de punto de venta para facturacion en fisico."""
    datosApp = get_data_app()
    productos = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT id, nombre, precio, stock, imagen FROM productos WHERE stock > 0 ORDER BY nombre')
            productos = cur.fetchall()
    except Exception:
        pass
    return render_template('facturacion_pos.html', datosApp=datosApp, productos=productos)


@admin_bp.route('/admin/pos/procesar', methods=['POST'])
@rol_requerido(1)
def procesar_venta_pos():
    """Procesa una venta POS: guarda, descuenta stock y registra en inventario_log."""
    from datetime import datetime

    data = request.get_json()
    if not data or not data.get('items'):
        return jsonify({'success': False, 'error': 'No hay items en la venta'}), 400

    items = data['items']
    cliente_nombre = data.get('cliente_nombre', '')
    cliente_documento = data.get('cliente_documento', '')
    cliente_telefono = data.get('cliente_telefono', '')
    metodo_pago = data.get('metodo_pago', 'EFECTIVO')
    notas = data.get('notas', '')
    usuario_id = session.get('user_id', 1)

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Generar numero de venta: POS-YYYYMMDD-XXXX
        hoy = datetime.now().strftime('%Y%m%d')
        cur.execute(
            "SELECT COUNT(*) FROM ventas_pos WHERE numero_venta LIKE %s",
            (f'POS-{hoy}-%',)
        )
        secuencial = cur.fetchone()[0] + 1
        numero_venta = f"POS-{hoy}-{secuencial:04d}"

        # Calcular totales
        total_venta = 0
        detalles_para_insertar = []
        stock_cambios = {}  # {producto_id: nuevo_stock} para actualizar frontend

        for item in items:
            producto_id = item.get('producto_id')  # None si es item libre
            descripcion = item.get('descripcion', 'Item')
            cantidad = int(item.get('cantidad', 1))
            precio_unitario = float(item.get('precio_unitario', 0))
            subtotal_item = cantidad * precio_unitario
            total_venta += subtotal_item

            # Si es producto de inventario, verificar y descontar stock
            if producto_id:
                producto_id = int(producto_id)
                cur.execute('SELECT stock FROM productos WHERE id = %s FOR UPDATE', (producto_id,))
                res = cur.fetchone()
                if not res:
                    conn.rollback()
                    cur.close()
                    conn.close()
                    return jsonify({'success': False, 'error': f'Producto ID {producto_id} no encontrado'}), 400

                stock_actual = res[0]
                stock_nuevo = stock_actual - cantidad
                if stock_nuevo < 0:
                    conn.rollback()
                    cur.close()
                    conn.close()
                    return jsonify({'success': False, 'error': f'Stock insuficiente para "{descripcion}". Disponible: {stock_actual}'}), 400

                # Descontar stock
                cur.execute('UPDATE productos SET stock = %s WHERE id = %s', (stock_nuevo, producto_id))
                stock_cambios[producto_id] = stock_nuevo

                # Registrar en inventario_log
                cur.execute("""
                    INSERT INTO inventario_log (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, usuario_id)
                    VALUES (%s, 'SALIDA', %s, %s, %s, %s, %s)
                """, (producto_id, cantidad, stock_actual, stock_nuevo, f'Venta POS #{numero_venta}', usuario_id))

            detalles_para_insertar.append((producto_id, descripcion, cantidad, precio_unitario, subtotal_item))

        # Insertar venta
        cur.execute("""
            INSERT INTO ventas_pos (numero_venta, cliente_nombre, cliente_documento, cliente_telefono, metodo_pago, subtotal, total, notas, usuario_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (numero_venta, cliente_nombre, cliente_documento, cliente_telefono, metodo_pago, total_venta, total_venta, notas, usuario_id))
        venta_id = cur.fetchone()[0]

        # Insertar detalles
        for det in detalles_para_insertar:
            cur.execute("""
                INSERT INTO detalle_venta_pos (venta_id, producto_id, descripcion, cantidad, precio_unitario, subtotal)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (venta_id, det[0], det[1], det[2], det[3], det[4]))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            'success': True,
            'numero_venta': numero_venta,
            'total': float(total_venta),
            'fecha': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'items': [{'descripcion': d[1], 'cantidad': d[2], 'precio_unitario': d[3], 'subtotal': d[4]} for d in detalles_para_insertar],
            'cliente_nombre': cliente_nombre,
            'metodo_pago': metodo_pago,
            'stock_updates': [{'id': pid, 'stock': s} for pid, s in stock_cambios.items()]
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/pos/historial')
@rol_requerido(1)
def historial_pos():
    """Historial de ventas POS."""
    datosApp = get_data_app()
    ventas = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM ventas_pos ORDER BY fecha DESC')
            ventas = cur.fetchall()
    except Exception as e:
        flash(f'Error cargando historial: {e}', 'error')
    return render_template('historial_pos.html', datosApp=datosApp, ventas=ventas)


@admin_bp.route('/admin/pos/detalle/<int:id>')
@rol_requerido(1)
def detalle_venta_pos(id):
    """Retorna detalle de una venta POS en JSON."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM ventas_pos WHERE id = %s', (id,))
            venta = cur.fetchone()
            if not venta:
                return jsonify({'error': 'Venta no encontrada'}), 404

            cur.execute('SELECT * FROM detalle_venta_pos WHERE venta_id = %s ORDER BY id', (id,))
            detalles = cur.fetchall()

        return jsonify({
            'numero_venta': venta['numero_venta'],
            'fecha': venta['fecha'].strftime('%Y-%m-%d %H:%M'),
            'cliente_nombre': venta['cliente_nombre'] or '-',
            'cliente_documento': venta['cliente_documento'] or '-',
            'metodo_pago': venta['metodo_pago'],
            'total': float(venta['total']),
            'notas': venta['notas'] or '',
            'items': [{
                'descripcion': d['descripcion'],
                'cantidad': d['cantidad'],
                'precio_unitario': float(d['precio_unitario']),
                'subtotal': float(d['subtotal'])
            } for d in detalles]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/admin/pos/buscar-barcode', methods=['POST'])
@rol_requerido(1)
def buscar_producto_barcode():
    """Busca un producto por su código de barras (referencia)."""
    data = request.get_json()
    barcode = data.get('barcode', '').strip()
    
    if not barcode:
        return jsonify({'success': False, 'error': 'Código de barras vacío'}), 400
    
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('''
                SELECT id, nombre, precio, stock, referencia
                FROM productos
                WHERE UPPER(TRIM(referencia)) = UPPER(TRIM(%s)) AND stock > 0
            ''', (barcode,))
            producto = cur.fetchone()
            
            if not producto:
                return jsonify({'success': False, 'error': 'Producto no encontrado o sin stock'}), 404
            
            return jsonify({
                'success': True,
                'producto': {
                    'id': producto['id'],
                    'nombre': producto['nombre'],
                    'precio': float(producto['precio']),
                    'stock': producto['stock'],
                    'referencia': producto['referencia']
                }
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
