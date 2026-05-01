"""
routes/admin.py — Blueprint de administracion.

Rutas protegidas con @rol_requerido(ADMIN_STAFF) para gestion de productos,
usuarios y pedidos. Solo accesibles por usuarios con rol Admin.
"""

import hashlib
import hmac
import os
import time
import subprocess
import gzip
import shutil
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, Response, current_app, send_from_directory, abort
import csv
import io
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from psycopg2.extras import DictCursor

from database import get_db_connection, get_db_cursor
from helpers import get_data_app
from security import (
    rol_requerido,
    ADMIN_FULL,
    ADMIN_STAFF,
    ADMIN_CONTADOR,
    CATALOG_DELETE,
    CATALOG_OPERATIONAL,
    POS_OPERATIONAL,
    POS_DELETE,
    ROL_SUPER_ADMIN,
)
from tenant_features import get_module_settings, set_module_state
from services.public_site_service import (
    PUBLIC_BRANDING_FIELDS,
    PUBLIC_COLOR_FIELDS,
    PUBLIC_LANDING_FIELDS,
    get_public_site_admin_context,
    save_public_logo,
    save_public_site_sections,
    save_public_site_settings,
)

admin_bp = Blueprint('admin', __name__)


_PRODUCT_IMAGE_DEFAULTS_REPAIRED = False
_COLUMN_EXISTS_CACHE = {}


def _table_has_column(table_name, column_name):
    cache_key = (table_name, column_name)
    if cache_key in _COLUMN_EXISTS_CACHE:
        return _COLUMN_EXISTS_CACHE[cache_key]

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = %s
                LIMIT 1
            """, (table_name, column_name))
            exists = cur.fetchone() is not None
    except Exception:
        exists = False

    _COLUMN_EXISTS_CACHE[cache_key] = exists
    return exists


def _get_product_schema_flags():
    return {
        'has_online_visibility': _table_has_column('productos', 'visible_en_ecommerce'),
        'has_fe_flag_pos': _table_has_column('ventas_pos', 'facturar_electronicamente'),
    }


def _parse_visible_en_ecommerce(value, default=True):
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in ('', 'none', 'null'):
        return default
    if normalized in ('1', 'true', 'si', 'sí', 'on', 'yes'):
        return True
    if normalized in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError('Valor inválido para visibilidad online.')


def _parse_excel_visible_value(value):
    if value is None:
        return True
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, float):
        try:
            if value != value:
                return True
        except Exception:
            pass

    normalized = str(value).strip().lower()
    if normalized == '':
        return True
    if normalized in ('si', 'sí'):
        return True
    if normalized == 'no':
        return False
    raise ValueError("usa solo 'SI' o 'NO'")


def _parse_facturar_electronicamente(value, default=False):
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in ('', 'none', 'null'):
        return default
    if normalized in ('1', 'true', 'si', 'sí', 'on', 'yes'):
        return True
    if normalized in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError('Valor invalido para facturacion electronica.')


def _build_product_insert_data(*, imagen, nombre, precio, referencia, genero_id, descripcion, stock,
                               visible_en_ecommerce=True):
    schema = _get_product_schema_flags()
    columns = ['imagen', 'nombre', 'precio', 'referencia', 'genero_id', 'descripcion', 'stock']
    values = [imagen, nombre, precio, referencia, genero_id, descripcion, stock]

    if schema['has_online_visibility']:
        columns.append('visible_en_ecommerce')
        values.append(bool(visible_en_ecommerce))

    return columns, values


def _repair_producto_imagenes_defaults():
    """Restaura la secuencia/default de producto_imagenes.id si falta."""
    global _PRODUCT_IMAGE_DEFAULTS_REPAIRED
    if _PRODUCT_IMAGE_DEFAULTS_REPAIRED:
        return

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'producto_imagenes'
                  AND column_name = 'id'
            """)
            row = cur.fetchone()
            if row and not row['column_default']:
                cur.execute("CREATE SEQUENCE IF NOT EXISTS producto_imagenes_id_seq")
                cur.execute("""
                    ALTER SEQUENCE producto_imagenes_id_seq
                    OWNED BY producto_imagenes.id
                """)
                cur.execute("""
                    ALTER TABLE producto_imagenes
                    ALTER COLUMN id SET DEFAULT nextval('producto_imagenes_id_seq')
                """)
                cur.execute("""
                    SELECT setval(
                        'producto_imagenes_id_seq',
                        COALESCE((SELECT MAX(id) FROM producto_imagenes), 0) + 1,
                        false
                    )
                """)
        _PRODUCT_IMAGE_DEFAULTS_REPAIRED = True
    except Exception as exc:
        current_app.logger.warning(f"No fue posible reparar defaults de producto_imagenes: {exc}")


# --- Dashboard ---

@admin_bp.route('/admin')
@rol_requerido(ADMIN_STAFF)
def dashboard_admin():
    """Panel principal de administracion."""
    datosApp = get_data_app()
    return render_template('dashboard_admin.html', datosApp=datosApp)


# --- Gestion de Productos ---

@admin_bp.route('/agregar-producto', methods=['GET', 'POST'])
@rol_requerido(CATALOG_OPERATIONAL)
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
        conn = None
        cur = None
        try:
            _repair_producto_imagenes_defaults()
            archivos = request.files.getlist('imagenes')
            archivos = [f for f in archivos if f and f.filename != '']
            if not archivos:
                flash('Debes subir al menos una imagen.', 'error')
                return redirect(url_for('admin.GestionProductos'))

            nombre = request.form.get('nombre')
            precio = float(request.form.get('precio'))
            referencia = request.form.get('referencia')
            genero_id = request.form.get('genero_id')
            descripcion = request.form.get('descripcion')
            stock = request.form.get('stock', 0)
            visible_en_ecommerce = _parse_visible_en_ecommerce(
                request.form.get('visible_en_ecommerce'),
                default=True,
            )

            # Guardar primera imagen como principal del producto
            primera = archivos[0]
            imagen_nombre = product_images.save(primera, folder='media')
            imagen_url_principal = f"/static/media/{imagen_nombre}"

            conn = get_db_connection()
            cur = conn.cursor()
            insert_columns, insert_values = _build_product_insert_data(
                imagen=imagen_url_principal,
                nombre=nombre,
                precio=precio,
                referencia=referencia,
                genero_id=genero_id,
                descripcion=descripcion,
                stock=stock,
                visible_en_ecommerce=visible_en_ecommerce,
            )
            cur.execute(
                f"INSERT INTO productos ({', '.join(insert_columns)}) VALUES ({', '.join(['%s'] * len(insert_columns))}) RETURNING id",
                tuple(insert_values)
            )
            nuevo_id = cur.fetchone()[0]

            # Guardar todas las imágenes en producto_imagenes
            for orden, archivo in enumerate(archivos):
                if orden == 0:
                    url = imagen_url_principal
                else:
                    nombre_img = product_images.save(archivo, folder='media')
                    url = f"/static/media/{nombre_img}"
                cur.execute(
                    'INSERT INTO producto_imagenes (producto_id, imagen_url, orden, es_principal) VALUES (%s, %s, %s, %s)',
                    (nuevo_id, url, orden, orden == 0)
                )

            conn.commit()
            cur.close()
            conn.close()

            flash('Producto agregado correctamente.', 'success')
            return redirect(url_for('public.productos'))

        except Exception as e:
            if conn:
                conn.rollback()
            if cur:
                cur.close()
            if conn:
                conn.close()
            current_app.logger.error(f"Error al crear producto: {e}")
            error_msg = str(e)

            if "productos_referencia_key" in error_msg:
                flash('Ya existe un producto registrado con esa Referencia. Por favor verifica.', 'warning')
            elif 'producto_imagenes' in error_msg and '"id"' in error_msg:
                flash('Se reparó la secuencia de imágenes. Intenta guardar el producto nuevamente.', 'warning')
            elif "value too long" in error_msg:
                flash('Uno de los campos es demasiado largo para la base de datos.', 'warning')
            else:
                flash(f'Ocurrió un error interno al guardar: Revisa el log para más detalles.', 'error')

            return redirect(url_for('admin.GestionProductos'))
    return render_template('GestionProductos.html', datosApp=datosApp, generos=generos)
@admin_bp.route('/descargar-plantilla-productos')
@rol_requerido(CATALOG_OPERATIONAL)
def descargar_plantilla_productos():
    """Genera y descarga un archivo Excel plantilla para el cargue masivo de productos."""
    import pandas as pd
    import io
    
    # Definir las columnas exactas requeridas
    columnas = ['Nombre del Producto', 'Referencia', 'Género', 'Descripción', 'Precio', 'Visible en E-commerce']
    
    # Crear un DataFrame vacío con esas columnas
    df = pd.DataFrame(columns=columnas)
    
    # Escribir el DataFrame en un buffer de memoria como Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Plantilla Productos')
    
    output.seek(0)
    
    # Retornar el archivo Excel
    return Response(
        output, 
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 
        headers={"Content-Disposition": "attachment;filename=plantilla_productos.xlsx"}
    )

@admin_bp.route('/cargue-masivo-productos', methods=['POST'])
@rol_requerido(CATALOG_OPERATIONAL)
def cargue_masivo_productos():
    """Procesa el cargue masivo de productos desde un archivo Excel."""
    import pandas as pd
    
    if 'archivo_excel' not in request.files:
        flash('No se seleccionó ningún archivo.', 'error')
        return redirect(url_for('admin.GestionProductos'))
        
    file = request.files['archivo_excel']
    if file.filename == '':
        flash('El archivo no tiene nombre.', 'error')
        return redirect(url_for('admin.GestionProductos'))
        
    if not file.filename.endswith('.xlsx'):
        flash('Formato de archivo inválido. Por favor suba un archivo .xlsx', 'error')
        return redirect(url_for('admin.GestionProductos'))
        
    try:
        df = pd.read_excel(file)
        # Limpiar nombres de columnas para evitar problemas con espacios adicionales
        df.columns = df.columns.str.strip()
        
        columnas_requeridas = ['Nombre del Producto', 'Referencia', 'Género', 'Descripción', 'Precio']
        for col in columnas_requeridas:
            if col not in df.columns:
                flash(f'El archivo no tiene la columna requerida: {col}', 'error')
                return redirect(url_for('admin.GestionProductos'))
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Obtener mapeo de géneros
        cur.execute('SELECT id, nombre FROM generos')
        generos_rows = cur.fetchall()
        generos_map = {row[1].strip().lower(): row[0] for row in generos_rows}
        productos_creados = 0
        errores = []
        
        for index, row in df.iterrows():
            try:
                # Validar campos vacíos esenciales
                if pd.isna(row['Nombre del Producto']) or pd.isna(row['Referencia']) or pd.isna(row['Precio']):
                    errores.append(f"Fila {index+2}: Faltan datos obligatorios.")
                    continue

                nombre = str(row['Nombre del Producto']).strip()
                referencia = str(row['Referencia']).strip()
                genero_nombre = str(row['Género']).strip().lower()
                descripcion = '' if pd.isna(row['Descripción']) else str(row['Descripción']).strip()
                precio = float(row['Precio'])
                visible_en_ecommerce = _parse_excel_visible_value(row.get('Visible en E-commerce'))

                if not nombre or not referencia:
                    errores.append(f"Fila {index+2}: El nombre y la referencia no pueden quedar vacíos.")
                    continue
                if precio < 0:
                    errores.append(f"Fila {index+2}: El precio no puede ser negativo.")
                    continue
                    
                # Verificar referencia duplicada en la bd
                cur.execute('SELECT id FROM productos WHERE referencia = %s', (referencia,))
                if cur.fetchone():
                    errores.append(f"Fila {index+2}: La referencia '{referencia}' ya existe en el sistema.")
                    continue
                    
                # Validar género
                if genero_nombre not in generos_map:
                    errores.append(f"Fila {index+2}: El género '{row['Género']}' no existe en la base de datos.")
                    continue
                genero_id = generos_map[genero_nombre]
                
                # Asignamos imagen por defecto
                imagen_final_url = '/static/media/producto_default.png'
                insert_columns, insert_values = _build_product_insert_data(
                    imagen=imagen_final_url,
                    nombre=nombre,
                    precio=precio,
                    referencia=referencia,
                    genero_id=genero_id,
                    descripcion=descripcion,
                    stock=0,
                    visible_en_ecommerce=visible_en_ecommerce,
                )
                
                # Insertar en base de datos
                cur.execute(
                    f"INSERT INTO productos ({', '.join(insert_columns)}) VALUES ({', '.join(['%s'] * len(insert_columns))})",
                    tuple(insert_values)
                )
                productos_creados += 1
                
            except Exception as row_err:
                errores.append(f"Fila {index+2}: Error de datos ({str(row_err)}).")
                
        conn.commit()
        cur.close()
        conn.close()
        
        if productos_creados > 0:
            flash(f'¡Se importaron {productos_creados} productos exitosamente!', 'success')
            
        if errores:
            # Mostramos un resumen de errores en un format amigable
            error_msgs = "\n".join(errores[:10])
            if len(errores) > 10:
                error_msgs += f"\n...y {len(errores)-10} errores más."
            flash(f'Hubo {len(errores)} errores durante la importación:\n{error_msgs}', 'warning')
            
        return redirect(url_for('admin.GestionProductos'))
            
    except Exception as e:
        current_app.logger.error(f"Error procesando excel: {e}")
        flash(f'Ocurrió un error al procesar el archivo Excel: Revisa el log para más detalles.', 'error')
        return redirect(url_for('admin.GestionProductos'))


@admin_bp.route('/editar-productos')
@rol_requerido(CATALOG_OPERATIONAL)
def editar_productos():
    """Lista de productos disponibles para edicion."""
    datosApp = get_data_app()
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if _table_has_column('productos', 'visible_en_ecommerce'):
                cur.execute("""
                    SELECT id, nombre, precio, stock,
                           COALESCE(visible_en_ecommerce, TRUE) AS visible_en_ecommerce
                    FROM productos
                    ORDER BY id ASC
                """)
            else:
                cur.execute("""
                    SELECT id, nombre, precio, stock, TRUE AS visible_en_ecommerce
                    FROM productos
                    ORDER BY id ASC
                """)
            productos = cur.fetchall()
    except Exception as e:
        current_app.logger.exception(f"Error cargando lista de productos: {e}")
        flash('Error cargando productos. Revisa el log del servidor.', 'error')
        productos = []
    return render_template('editar_productos.html', datosApp=datosApp, productos=productos)


@admin_bp.route('/editar-producto/<int:id>', methods=['GET', 'POST'])
@rol_requerido(CATALOG_OPERATIONAL)
def editar_producto(id):
    """Formulario de edicion de un producto existente."""
    from app import product_images

    datosApp = get_data_app()
    imagenes = []
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        if _table_has_column('productos', 'visible_en_ecommerce'):
            cur.execute('SELECT *, COALESCE(visible_en_ecommerce, TRUE) AS visible_en_ecommerce FROM productos WHERE id = %s', (id,))
        else:
            cur.execute('SELECT *, TRUE AS visible_en_ecommerce FROM productos WHERE id = %s', (id,))
        producto = cur.fetchone()
        cur.execute('SELECT * FROM generos')
        generos = cur.fetchall()
        cur.execute(
            'SELECT id, imagen_url, es_principal, orden FROM producto_imagenes WHERE producto_id=%s ORDER BY es_principal DESC, orden ASC, id ASC',
            (id,)
        )
        imagenes = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        current_app.logger.exception(f"Error cargando producto {id} para edición: {e}")
        flash('Error cargando el producto. Revisa el log del servidor.', 'error')
        producto = None
        generos = []

    if request.method == 'POST':
        conn = None
        cur = None
        nombre = request.form.get('nombre')
        precio = request.form.get('precio')
        referencia = request.form.get('referencia')
        genero_id = request.form.get('genero_id')
        stock = request.form.get('stock', 0)
        descripcion = request.form.get('descripcion')
        visible_en_ecommerce = _parse_visible_en_ecommerce(
            request.form.get('visible_en_ecommerce'),
            default=True,
        )
        archivos_nuevos = request.files.getlist('imagenes_nuevas')
        archivos_nuevos = [f for f in archivos_nuevos if f and f.filename != '']
        try:
            _repair_producto_imagenes_defaults()
            conn = get_db_connection()
            cur = conn.cursor()

            # Obtener stock actual antes de actualizar
            cur.execute("SELECT stock FROM productos WHERE id = %s", (id,))
            res = cur.fetchone()
            stock_anterior = res[0] if res else 0
            stock_nuevo = int(stock) if stock else 0
            cantidad_real = stock_nuevo - stock_anterior

            update_sql = 'UPDATE productos SET nombre=%s, precio=%s, referencia=%s, genero_id=%s, descripcion=%s, stock=%s'
            update_params = [nombre, precio, referencia, genero_id, descripcion, stock_nuevo]
            if _table_has_column('productos', 'visible_en_ecommerce'):
                update_sql += ', visible_en_ecommerce=%s'
                update_params.append(visible_en_ecommerce)
            update_sql += ' WHERE id=%s'
            update_params.append(id)
            cur.execute(update_sql, tuple(update_params))

            # Registrar en el historial si hubo cambios de stock
            if cantidad_real != 0:
                tipo_movimiento = 'ENTRADA' if cantidad_real > 0 else 'SALIDA'
                motivo = 'Edición de producto'
                usuario_id = session.get('usuario_id', 1)
                cur.execute("""
                    INSERT INTO inventario_log (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, usuario_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (id, tipo_movimiento, abs(cantidad_real), stock_anterior, stock_nuevo, motivo, usuario_id))
            # Agregar nuevas imágenes
            if archivos_nuevos:
                cur.execute('SELECT COALESCE(MAX(orden), -1) FROM producto_imagenes WHERE producto_id=%s', (id,))
                max_orden = cur.fetchone()[0]
                for i, archivo in enumerate(archivos_nuevos):
                    nombre_img = product_images.save(archivo, folder='media')
                    url = f"/static/media/{nombre_img}"
                    cur.execute(
                        'INSERT INTO producto_imagenes (producto_id, imagen_url, orden, es_principal) VALUES (%s, %s, %s, FALSE)',
                        (id, url, max_orden + 1 + i)
                    )
            conn.commit()
            cur.close()
            conn.close()
            flash('Producto actualizado.', 'success')
            return redirect(url_for('admin.editar_producto', id=id))
        except Exception as e:
            if conn:
                conn.rollback()
            if cur:
                cur.close()
            if conn:
                conn.close()
            current_app.logger.error(f"Error actualizando producto {id}: {e}")
            flash(f'Error actualizando: Revisa el log para más detalles.', 'error')
    return render_template('editar_producto.html', datosApp=datosApp, producto=producto, generos=generos, imagenes=imagenes)


@admin_bp.route('/producto-imagen/eliminar/<int:imagen_id>', methods=['POST'])
@rol_requerido(CATALOG_OPERATIONAL)
def eliminar_imagen_producto(imagen_id):
    """Elimina una imagen de producto (no permite eliminar la principal si es la única)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT producto_id, es_principal FROM producto_imagenes WHERE id=%s', (imagen_id,))
        row = cur.fetchone()
        if not row:
            flash('Imagen no encontrada.', 'error')
            cur.close(); conn.close()
            return redirect(request.referrer or url_for('admin.editar_productos'))

        producto_id = row[0]
        es_principal = row[1]

        # Verificar que no sea la única imagen
        cur.execute('SELECT COUNT(*) FROM producto_imagenes WHERE producto_id=%s', (producto_id,))
        total = cur.fetchone()[0]
        if total <= 1:
            flash('No puedes eliminar la única imagen del producto.', 'warning')
            cur.close(); conn.close()
            return redirect(url_for('admin.editar_producto', id=producto_id))

        cur.execute('DELETE FROM producto_imagenes WHERE id=%s', (imagen_id,))

        # Si era la principal, asignar la siguiente como principal
        if es_principal:
            cur.execute(
                'SELECT id, imagen_url FROM producto_imagenes WHERE producto_id=%s ORDER BY orden ASC, id ASC LIMIT 1',
                (producto_id,)
            )
            nueva = cur.fetchone()
            if nueva:
                cur.execute('UPDATE producto_imagenes SET es_principal=TRUE WHERE id=%s', (nueva[0],))
                cur.execute('UPDATE productos SET imagen=%s WHERE id=%s', (nueva[1], producto_id))

        conn.commit()
        cur.close()
        conn.close()
        flash('Imagen eliminada.', 'success')
    except Exception as e:
        flash(f'Error eliminando imagen: Revisa el log para más detalles.', 'error')
    return redirect(url_for('admin.editar_producto', id=producto_id))


@admin_bp.route('/producto-imagen/principal/<int:imagen_id>', methods=['POST'])
@rol_requerido(CATALOG_OPERATIONAL)
def establecer_imagen_principal(imagen_id):
    """Establece una imagen como la principal del producto."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT producto_id, imagen_url FROM producto_imagenes WHERE id=%s', (imagen_id,))
        row = cur.fetchone()
        if not row:
            flash('Imagen no encontrada.', 'error')
            cur.close(); conn.close()
            return redirect(request.referrer or url_for('admin.editar_productos'))

        producto_id, imagen_url = row[0], row[1]
        cur.execute('UPDATE producto_imagenes SET es_principal=FALSE WHERE producto_id=%s', (producto_id,))
        cur.execute('UPDATE producto_imagenes SET es_principal=TRUE WHERE id=%s', (imagen_id,))
        cur.execute('UPDATE productos SET imagen=%s WHERE id=%s', (imagen_url, producto_id))
        conn.commit()
        cur.close()
        conn.close()
        flash('Imagen principal actualizada.', 'success')
    except Exception as e:
        flash(f'Error: Revisa el log para más detalles.', 'error')
    return redirect(url_for('admin.editar_producto', id=producto_id))


@admin_bp.route('/eliminar-productos')
@rol_requerido(CATALOG_DELETE)
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
@rol_requerido(CATALOG_DELETE)
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
@rol_requerido(ADMIN_FULL)
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
@rol_requerido(ADMIN_FULL)
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
            flash(f'Error: Revisa el log para más detalles.', 'error')
    return render_template('crear_usuario.html', datosApp=datosApp, roles=roles)


@admin_bp.route('/editar-usuario/<int:id>', methods=['GET', 'POST'])
@rol_requerido(ADMIN_FULL)
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
        flash(f'Error cargando: Revisa el log para más detalles.', 'error')
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
            flash(f'Error técnico: Revisa el log para más detalles.', 'error')
            return redirect(url_for('admin.editar_usuario', id=id))

    return render_template('editar_usuario.html', datosApp=datosApp, usuario=usuario, roles=roles)


@admin_bp.route('/cambiar-password/<int:id>', methods=['POST'])
@rol_requerido(ADMIN_FULL)
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


# --- Vista Cliente (prueba para admin) ---

@admin_bp.route('/admin/vista-cliente')
@rol_requerido(ADMIN_STAFF)
def vista_cliente_admin():
    """Permite al admin ver el módulo de pedidos como lo ve un cliente (para pruebas)."""
    from database import get_db_cursor
    datosApp = get_data_app()
    email_buscar = request.args.get('email', '').strip()
    pedidos = []
    if email_buscar:
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    SELECT p.id, p.referencia_pedido, p.fecha_creacion, p.monto_total,
                           p.estado_pago, p.estado_envio, p.metodo_pago,
                           p.cliente_nombre, p.cliente_email,
                           COUNT(dp.id) AS num_items
                    FROM pedidos p
                    LEFT JOIN detalle_pedidos dp ON dp.pedido_id = p.id
                    WHERE p.cliente_email ILIKE %s
                    GROUP BY p.id
                    ORDER BY p.fecha_creacion DESC
                """, (f'%{email_buscar}%',))
                pedidos = cur.fetchall()
        except Exception as e:
            flash(f'Error: Revisa el log para más detalles.', 'danger')
    return render_template('mis_pedidos.html', datosApp=datosApp, pedidos=pedidos,
                           modo_admin=True, email_buscar=email_buscar)


@admin_bp.route('/admin/vista-cliente/pedido/<int:pedido_id>')
@rol_requerido(ADMIN_STAFF)
def vista_detalle_pedido_admin(pedido_id):
    """Permite al admin ver el detalle de un pedido en vista cliente."""
    from database import get_db_cursor
    datosApp = get_data_app()
    pedido = None
    items = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM pedidos WHERE id = %s", (pedido_id,))
            pedido = cur.fetchone()
            if pedido:
                cur.execute("SELECT * FROM detalle_pedidos WHERE pedido_id = %s", (pedido_id,))
                items = cur.fetchall()
    except Exception as e:
        flash(f'Error: Revisa el log para más detalles.', 'danger')
    if not pedido:
        flash("Pedido no encontrado.", "warning")
        return redirect(url_for('admin.vista_cliente_admin'))
    return render_template('detalle_pedido_cliente.html', datosApp=datosApp,
                           pedido=pedido, items=items, modo_admin=True)


# --- Gestion de Pedidos ---

@admin_bp.route('/gestion-pedidos')
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(CATALOG_OPERATIONAL)
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
        flash(f"Error cargando inventario: Revisa el log para más detalles.", "error")
    
    return render_template('gestion_inventario.html', datosApp=datosApp, productos=productos, valor_total=valor_total, categorias=categorias)


@admin_bp.route('/inventario/exportar')
@rol_requerido(CATALOG_OPERATIONAL)
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
@rol_requerido(CATALOG_OPERATIONAL)
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
        flash(f"Error actualizando stock: Revisa el log para más detalles.", "error")
        
    return redirect(url_for('admin.gestion_inventario'))


@admin_bp.route('/inventario/historial/<int:id>')
@rol_requerido(CATALOG_OPERATIONAL)
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
@rol_requerido(ADMIN_STAFF)
def gestion_publicaciones():
    """Lista de publicaciones del home."""
    datosApp = get_data_app()
    publicaciones = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM publicaciones_home ORDER BY fecha_creacion DESC')
            publicaciones = cur.fetchall()
    except Exception:
        flash('Error cargando publicaciones: Revisa el log para más detalles.', 'error')
    return render_template('gestion_publicaciones.html', datosApp=datosApp, publicaciones=publicaciones)


@admin_bp.route('/admin/publicaciones/crear', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
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
        except Exception:
            flash('Error creando publicacion: Revisa el log para más detalles.', 'error')

    return render_template('gestion_publicaciones.html', datosApp=datosApp, publicaciones=[], modo='crear')


@admin_bp.route('/admin/publicaciones/editar/<int:id>', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
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
        except Exception:
            flash('Error actualizando: Revisa el log para más detalles.', 'error')

    return render_template(
        'gestion_publicaciones.html',
        datosApp=datosApp,
        publicaciones=[],
        modo='editar',
        publicacion=publicacion,
    )


@admin_bp.route('/admin/publicaciones/eliminar/<int:id>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(ADMIN_STAFF)
def gestion_slides():
    """Lista de slides del carrusel del home."""
    datosApp = get_data_app()
    slides = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM slides_home ORDER BY orden ASC, id ASC')
            slides = cur.fetchall()
    except Exception:
        flash('Error cargando slides: Revisa el log para más detalles.', 'error')
    return render_template('gestion_slides.html', datosApp=datosApp, slides=slides)


@admin_bp.route('/admin/slides/crear', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
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
        except Exception:
            flash('Error creando slide: Revisa el log para más detalles.', 'error')

    return render_template('gestion_slides.html', datosApp=datosApp, slides=[], modo='crear')


@admin_bp.route('/admin/slides/editar/<int:id>', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
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
        except Exception:
            flash('Error actualizando slide: Revisa el log para más detalles.', 'error')

    return render_template('gestion_slides.html', datosApp=datosApp, slides=[], modo='editar', slide=slide)


@admin_bp.route('/admin/slides/eliminar/<int:id>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(ADMIN_STAFF)
def gestion_servicios():
    """Lista de servicios."""
    datosApp = get_data_app()
    servicios = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM servicios_home ORDER BY orden ASC, id ASC')
            servicios = cur.fetchall()
    except Exception:
        flash('Error cargando servicios: Revisa el log para más detalles.', 'error')
    return render_template('gestion_servicios.html', datosApp=datosApp, servicios=servicios)


@admin_bp.route('/admin/servicios/crear', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
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
        except Exception:
            flash('Error creando servicio: Revisa el log para más detalles.', 'error')

    return render_template('gestion_servicios.html', datosApp=datosApp, servicios=[], modo='crear')


@admin_bp.route('/admin/servicios/editar/<int:id>', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
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
        except Exception:
            flash('Error actualizando: Revisa el log para más detalles.', 'error')

    return render_template(
        'gestion_servicios.html',
        datosApp=datosApp,
        servicios=[],
        modo='editar',
        servicio=servicio,
    )


@admin_bp.route('/admin/servicios/eliminar/<int:id>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
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
@rol_requerido(ADMIN_STAFF)
def toggle_servicio(id):
    """Activar/desactivar servicio."""
    try:
        with get_db_cursor() as cur:
            cur.execute('UPDATE servicios_home SET activo = NOT activo WHERE id = %s', (id,))
        flash('Estado del servicio actualizado.', 'success')
    except Exception:
        flash('Error cambiando estado.', 'error')
    return redirect(url_for('admin.gestion_servicios'))


# --- Configuracion de Secciones del Home (redirige a configuración unificada) ---

@admin_bp.route('/admin/sitio-publico', methods=['GET', 'POST'])
@rol_requerido(ROL_SUPER_ADMIN)
def sitio_publico():
    """Panel de configuración visual del sitio público."""
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        try:
            if form_type == 'branding':
                save_public_site_settings(
                    request.form,
                    [
                        field['key']
                        for field in PUBLIC_BRANDING_FIELDS + PUBLIC_COLOR_FIELDS + PUBLIC_LANDING_FIELDS
                        if field['key'] != 'empresa_logo_url'
                    ],
                )
                save_public_logo(request.files.get('logo'), current_app.root_path)
                flash('Branding y datos públicos actualizados.', 'success')
                return redirect(url_for('admin.sitio_publico') + '#branding')

            if form_type == 'sections':
                save_public_site_sections(request.form)
                flash('Visibilidad del sitio público actualizada.', 'success')
                return redirect(url_for('admin.sitio_publico') + '#sections')

            flash('No se reconoció el formulario enviado.', 'warning')
        except Exception as exc:
            current_app.logger.error(f'Error actualizando sitio publico: {exc}')
            flash('No fue posible guardar la configuración del sitio público.', 'error')
        return redirect(url_for('admin.sitio_publico'))

    return render_template(
        'sitio_publico_admin.html',
        datosApp=get_data_app(),
        **get_public_site_admin_context(),
    )


@admin_bp.route('/admin/config-secciones', methods=['GET', 'POST'])
@rol_requerido(ROL_SUPER_ADMIN)
def config_secciones():
    """Redirige a la configuración pública unificada."""
    return redirect(url_for('admin.sitio_publico') + '#sections')


# --- Punto de Venta (POS) ---

@admin_bp.route('/admin/pos')
@rol_requerido(POS_OPERATIONAL)
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
@rol_requerido(POS_OPERATIONAL)
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
    facturar_electronicamente = _parse_facturar_electronicamente(
        data.get('facturar_electronicamente'),
        default=False,
    )
    usuario_id = session.get('user_id', 1)
    schema = _get_product_schema_flags()

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
        sales_columns = [
            'numero_venta', 'cliente_nombre', 'cliente_documento', 'cliente_telefono',
            'metodo_pago', 'subtotal', 'total', 'notas', 'usuario_id'
        ]
        sales_values = [
            numero_venta, cliente_nombre, cliente_documento, cliente_telefono,
            metodo_pago, total_venta, total_venta, notas, usuario_id
        ]
        if schema['has_fe_flag_pos']:
            sales_columns.append('facturar_electronicamente')
            sales_values.append(facturar_electronicamente)

        cur.execute(f"""
            INSERT INTO ventas_pos ({", ".join(sales_columns)})
            VALUES ({", ".join(["%s"] * len(sales_columns))}) RETURNING id
        """, tuple(sales_values))
        venta_id = cur.fetchone()[0]

        # Registrar en contabilidad
        try:
            from routes.contabilidad import registrar_movimiento
            registrar_movimiento(
                tipo='ingreso',
                categoria='venta_pos',
                descripcion=f"Venta POS {numero_venta} — {cliente_nombre or 'Cliente'}",
                monto=total_venta,
                referencia_tipo='venta_pos',
                referencia_id=venta_id,
                usuario_id=session.get('usuario_id'),
                auto_generado=True
            )
        except Exception as _e:
            current_app.logger.warning(f"Contabilidad POS: {_e}")

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
            'venta_id': venta_id,
            'numero_venta': numero_venta,
            'total': float(total_venta),
            'fecha': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'items': [{'descripcion': d[1], 'cantidad': d[2], 'precio_unitario': d[3], 'subtotal': d[4]} for d in detalles_para_insertar],
            'cliente_nombre': cliente_nombre,
            'metodo_pago': metodo_pago,
            'facturar_electronicamente': facturar_electronicamente,
            'stock_updates': [{'id': pid, 'stock': s} for pid, s in stock_cambios.items()]
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/pos/historial')
@rol_requerido(POS_OPERATIONAL)
def historial_pos():
    """Historial de ventas POS."""
    datosApp = get_data_app()
    ventas = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if _table_has_column('ventas_pos', 'facturar_electronicamente'):
                cur.execute("""
                    SELECT *, COALESCE(facturar_electronicamente, FALSE) AS facturar_electronicamente
                    FROM ventas_pos
                    ORDER BY fecha DESC
                """)
            else:
                cur.execute("""
                    SELECT *, FALSE AS facturar_electronicamente
                    FROM ventas_pos
                    ORDER BY fecha DESC
                """)
            ventas = cur.fetchall()
    except Exception as e:
        flash(f'Error cargando historial: Revisa el log para más detalles.', 'error')
    ventas_activas = [v for v in ventas if v.get('estado', 'activa') != 'anulada']
    total_activas = sum(float(v['total']) for v in ventas_activas)
    return render_template('historial_pos.html', datosApp=datosApp, ventas=ventas,
                           can_void_pos=session.get('rol_id') in POS_DELETE,
                           total_activas=total_activas, num_activas=len(ventas_activas))


@admin_bp.route('/admin/pos/detalle/<int:id>')
@rol_requerido(POS_OPERATIONAL)
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

            # Nota de crédito si existe
            nota_credito_numero = None
            if venta.get('nota_credito_id'):
                cur.execute('SELECT numero_nota FROM notas_credito_pos WHERE id = %s', (venta['nota_credito_id'],))
                nc = cur.fetchone()
                if nc:
                    nota_credito_numero = nc['numero_nota']

        return jsonify({
            'numero_venta': venta['numero_venta'],
            'fecha': venta['fecha'].strftime('%Y-%m-%d %H:%M'),
            'cliente_nombre': venta['cliente_nombre'] or '-',
            'cliente_documento': venta['cliente_documento'] or '-',
            'metodo_pago': venta['metodo_pago'],
            'total': float(venta['total']),
            'notas': venta['notas'] or '',
            'estado': venta.get('estado', 'activa'),
            'facturar_electronicamente': bool(venta.get('facturar_electronicamente')),
            'factura_dian_id': str(venta['factura_dian_id']) if venta.get('factura_dian_id') else None,
            'nota_credito_numero': nota_credito_numero,
            'items': [{
                'descripcion': d['descripcion'],
                'cantidad': d['cantidad'],
                'precio_unitario': float(d['precio_unitario']),
                'subtotal': float(d['subtotal'])
            } for d in detalles]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/admin/pos/<int:venta_id>/anular', methods=['POST'])
@rol_requerido(POS_DELETE)
def anular_venta_pos(venta_id):
    """Anula una venta POS creando una nota de crédito, restaurando stock y registrando egreso contable."""
    from datetime import datetime

    data = request.get_json()
    motivo = (data or {}).get('motivo', '').strip()
    if not motivo:
        return jsonify({'success': False, 'error': 'El motivo de anulación es obligatorio'}), 400

    usuario_id = session.get('user_id', 1)

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)

        # Bloquear la venta para evitar condiciones de carrera
        cur.execute('SELECT * FROM ventas_pos WHERE id = %s FOR UPDATE', (venta_id,))
        venta = cur.fetchone()
        if not venta:
            conn.rollback(); cur.close(); conn.close()
            return jsonify({'success': False, 'error': 'Venta no encontrada'}), 404

        if venta.get('estado') == 'anulada':
            conn.rollback(); cur.close(); conn.close()
            return jsonify({'success': False, 'error': 'Esta venta ya fue anulada'}), 400

        advertencia_dian = bool(venta.get('factura_dian_id'))

        # Generar número de nota de crédito: NC-YYYYMMDD-XXXX
        hoy = datetime.now().strftime('%Y%m%d')
        cur.execute("SELECT COUNT(*) FROM notas_credito_pos WHERE numero_nota LIKE %s", (f'NC-{hoy}-%',))
        secuencial = cur.fetchone()[0] + 1
        numero_nota = f"NC-{hoy}-{secuencial:04d}"

        total_venta = float(venta['total'])
        numero_venta = venta['numero_venta']

        # Insertar nota de crédito
        cur.execute("""
            INSERT INTO notas_credito_pos (numero_nota, venta_id, motivo, total, usuario_id)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
        """, (numero_nota, venta_id, motivo, total_venta, usuario_id))
        nota_credito_id = cur.fetchone()[0]

        # Marcar venta como anulada
        cur.execute(
            "UPDATE ventas_pos SET estado = 'anulada', nota_credito_id = %s WHERE id = %s",
            (nota_credito_id, venta_id)
        )

        # Restaurar stock de productos
        cur.execute('SELECT * FROM detalle_venta_pos WHERE venta_id = %s', (venta_id,))
        detalles = cur.fetchall()

        for det in detalles:
            producto_id = det.get('producto_id')
            if not producto_id:
                continue  # Items libres no tienen stock

            cantidad = det['cantidad']
            cur.execute('SELECT stock FROM productos WHERE id = %s FOR UPDATE', (producto_id,))
            prod = cur.fetchone()
            if not prod:
                continue  # Producto eliminado, no se puede restaurar stock

            stock_actual = prod['stock']
            stock_nuevo = stock_actual + cantidad
            cur.execute('UPDATE productos SET stock = %s WHERE id = %s', (stock_nuevo, producto_id))

            # Registrar entrada en inventario_log
            cur.execute("""
                INSERT INTO inventario_log (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, usuario_id)
                VALUES (%s, 'ENTRADA', %s, %s, %s, %s, %s)
            """, (producto_id, cantidad, stock_actual, stock_nuevo,
                  f'Anulación Venta POS #{numero_venta} / {numero_nota}', usuario_id))

        conn.commit()
        cur.close()
        conn.close()

        # Registrar egreso contable (fuera de la transacción principal, como hace procesar_venta_pos)
        try:
            from routes.contabilidad import registrar_movimiento
            registrar_movimiento(
                tipo='egreso',
                categoria='anulacion_pos',
                descripcion=f"Anulación Venta POS {numero_venta} — NC {numero_nota}",
                monto=total_venta,
                referencia_tipo='nota_credito_pos',
                referencia_id=nota_credito_id,
                usuario_id=usuario_id,
                auto_generado=True
            )
        except Exception as _e:
            current_app.logger.warning(f"Contabilidad NC: {_e}")

        return jsonify({
            'success': True,
            'numero_nota': numero_nota,
            'venta_anulada': numero_venta,
            'total_devuelto': total_venta,
            'advertencia_dian': advertencia_dian
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/admin/pos/buscar-barcode', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
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


# --- Gestion de Generos ---

@admin_bp.route('/admin/generos')
@rol_requerido(CATALOG_OPERATIONAL)
def gestion_generos():
    """Lista todos los géneros y muestra el formulario de gestión."""
    datosApp = get_data_app()
    generos = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('''
                SELECT g.id, g.nombre, COUNT(p.id) AS total_productos
                FROM generos g
                LEFT JOIN productos p ON p.genero_id = g.id
                GROUP BY g.id, g.nombre
                ORDER BY g.nombre ASC
            ''')
            generos = cur.fetchall()
    except Exception as e:
        flash(f'Error al cargar géneros: Revisa el log para más detalles.', 'error')
    return render_template('gestion_generos.html', datosApp=datosApp, generos=generos)


@admin_bp.route('/admin/generos/crear', methods=['POST'])
@rol_requerido(CATALOG_OPERATIONAL)
def crear_genero():
    """Crea un nuevo género de producto."""
    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        flash('El nombre del género no puede estar vacío.', 'warning')
        return redirect(url_for('admin.gestion_generos'))
    try:
        with get_db_cursor() as cur:
            cur.execute('INSERT INTO generos (nombre) VALUES (%s)', (nombre,))
        flash(f'Género "{nombre}" creado correctamente.', 'success')
    except Exception as e:
        if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
            flash(f'Ya existe un género con el nombre "{nombre}".', 'warning')
        else:
            flash(f'Error al crear género: Revisa el log para más detalles.', 'error')
    return redirect(url_for('admin.gestion_generos'))


@admin_bp.route('/admin/generos/editar/<int:id>', methods=['POST'])
@rol_requerido(CATALOG_OPERATIONAL)
def editar_genero(id):
    """Actualiza el nombre de un género existente."""
    nombre = request.form.get('nombre', '').strip()
    if not nombre:
        flash('El nombre del género no puede estar vacío.', 'warning')
        return redirect(url_for('admin.gestion_generos'))
    try:
        with get_db_cursor() as cur:
            cur.execute('UPDATE generos SET nombre = %s WHERE id = %s', (nombre, id))
        flash(f'Género actualizado a "{nombre}".', 'success')
    except Exception as e:
        if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
            flash(f'Ya existe un género con el nombre "{nombre}".', 'warning')
        else:
            flash(f'Error al editar género: Revisa el log para más detalles.', 'error')
    return redirect(url_for('admin.gestion_generos'))


@admin_bp.route('/admin/generos/eliminar/<int:id>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def eliminar_genero(id):
    """Elimina un género si no tiene productos asociados."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT COUNT(*) AS total FROM productos WHERE genero_id = %s', (id,))
            resultado = cur.fetchone()
            if resultado and resultado['total'] > 0:
                flash(
                    f'No se puede eliminar: este género tiene {resultado["total"]} producto(s) asociado(s). '
                    'Reasigna o elimina los productos primero.',
                    'warning'
                )
                return redirect(url_for('admin.gestion_generos'))
            cur.execute('DELETE FROM generos WHERE id = %s', (id,))
        flash('Género eliminado correctamente.', 'success')
    except Exception as e:
        flash(f'Error al eliminar género: Revisa el log para más detalles.', 'error')
    return redirect(url_for('admin.gestion_generos'))


# =============================================================
# Moderación de reseñas
# =============================================================

@admin_bp.route('/admin/resenas')
@rol_requerido(ADMIN_STAFF)
def gestion_resenas():
    """Lista de reseñas pendientes y aprobadas para moderar."""
    datosApp = get_data_app()
    filtro   = request.args.get('filtro', 'pendientes')  # pendientes | aprobadas | todas
    resenas  = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if filtro == 'aprobadas':
                where = 'WHERE c.aprobado = TRUE'
            elif filtro == 'todas':
                where = ''
            else:
                where = 'WHERE c.aprobado = FALSE'
            cur.execute(f'''
                SELECT c.*, p.nombre AS producto_nombre
                FROM producto_comentarios c
                JOIN productos p ON c.producto_id = p.id
                {where}
                ORDER BY c.fecha_creacion DESC
            ''')
            resenas = cur.fetchall()
    except Exception as e:
        current_app.logger.error(f'Error cargando reseñas: {e}')
        flash('Error al cargar las reseñas.', 'error')
    return render_template('gestion_resenas.html', datosApp=datosApp,
                           resenas=resenas, filtro=filtro)


@admin_bp.route('/admin/resenas/<int:resena_id>/aprobar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def aprobar_resena(resena_id):
    """Aprueba una reseña para que sea visible públicamente."""
    try:
        with get_db_cursor() as cur:
            cur.execute('UPDATE producto_comentarios SET aprobado = TRUE WHERE id = %s', (resena_id,))
        flash('Reseña aprobada.', 'success')
    except Exception as e:
        current_app.logger.error(f'Error aprobando reseña {resena_id}: {e}')
        flash('Error al aprobar la reseña.', 'error')
    return redirect(request.referrer or url_for('admin.gestion_resenas'))


@admin_bp.route('/admin/resenas/<int:resena_id>/rechazar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def rechazar_resena(resena_id):
    """Elimina una reseña (rechazo definitivo)."""
    try:
        with get_db_cursor() as cur:
            cur.execute('DELETE FROM producto_comentarios WHERE id = %s', (resena_id,))
        flash('Reseña eliminada.', 'success')
    except Exception as e:
        current_app.logger.error(f'Error rechazando reseña {resena_id}: {e}')
        flash('Error al eliminar la reseña.', 'error')
    return redirect(request.referrer or url_for('admin.gestion_resenas'))


# =============================================================
# Panel de Configuración del Cliente
# =============================================================

@admin_bp.route('/admin/configuracion-cliente', methods=['GET', 'POST'])
@rol_requerido(ROL_SUPER_ADMIN)
def configuracion_cliente():
    """Panel unificado de configuración: colores, empresa, logo y secciones del home. Solo Super Admin."""
    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'secciones':
            # Procesar toggles de secciones del home
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
                flash('Secciones del sitio actualizadas.', 'success')
            except Exception as e:
                flash(f'Error actualizando secciones: Revisa el log para más detalles.', 'error')
            return redirect(url_for('admin.configuracion_cliente') + '#secciones')

        if form_type == 'modulos':
            try:
                for module in get_module_settings():
                    field_name = f"module_{module['code']}"
                    desired_state = bool(request.form.get(field_name))
                    if not set_module_state(module['code'], desired_state):
                        flash(f"No fue posible actualizar el modulo {module['nombre']}.", 'error')
                        return redirect(url_for('admin.configuracion_cliente') + '#modulos-sistema')
                flash('Activacion de modulos actualizada.', 'success')
            except Exception as e:
                current_app.logger.error(f"Error actualizando modulos locales: {e}")
                flash('Error al actualizar los modulos.', 'error')
            return redirect(url_for('admin.configuracion_cliente') + '#modulos-sistema')

        else:
            # Procesar configuración de empresa, colores y logo
            for clave, valor in request.form.items():
                if clave == 'form_type':
                    continue
                try:
                    with get_db_cursor() as cur:
                        cur.execute("UPDATE cliente_config SET valor=%s WHERE clave=%s", (valor, clave))
                        if cur.rowcount == 0:
                            tipo = 'color' if clave.startswith('color_') else 'text'
                            grupo = 'colores' if clave.startswith('color_') else 'empresa'
                            cur.execute(
                                "INSERT INTO cliente_config (clave, valor, tipo, grupo) VALUES (%s, %s, %s, %s)",
                                (clave, valor, tipo, grupo)
                            )
                except Exception as e:
                    current_app.logger.error(f"Error actualizando cliente_config '{clave}': {e}")
            logo = request.files.get('logo')
            if logo and logo.filename:
                try:
                    logo_path = os.path.join(current_app.root_path, 'static', 'img', 'Logo.png')
                    logo.save(logo_path)
                except Exception as e:
                    current_app.logger.error(f"Error guardando logo: {e}")
                    flash('Configuración guardada, pero hubo un error al subir el logo.', 'warning')
                    return redirect(url_for('admin.configuracion_cliente'))
            flash('Configuración actualizada.', 'success')
            return redirect(url_for('admin.configuracion_cliente'))

    grupos = {}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM cliente_config ORDER BY grupo, orden")
            for item in cur.fetchall():
                grupos.setdefault(item['grupo'], []).append(item)
    except Exception as e:
        current_app.logger.error(f"Error cargando cliente_config: {e}")
        flash('Error al cargar la configuración.', 'error')

    secciones = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM config_secciones ORDER BY clave')
            secciones = cur.fetchall()
    except Exception as e:
        current_app.logger.error(f"Error cargando config_secciones: {e}")

    module_toggles = get_module_settings()

    # Estado de Gmail API
    gmail_activo = False
    gmail_email = ''
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'gmail_usuario_id'")
            row = cur.fetchone()
            if row and row['valor']:
                cur.execute("SELECT email FROM usuarios WHERE id = %s", (int(row['valor']),))
                u = cur.fetchone()
                if u:
                    gmail_activo = True
                    gmail_email = u['email']
    except Exception:
        pass

    # Backups de BD (super admin)
    backups = []
    backup_clave_configurada = False
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT id, nombre_descarga, tipo, comprimido, tamano_bytes, fecha_creacion
                FROM backups_db
                ORDER BY fecha_creacion DESC
                LIMIT 50
            """)
            backups = cur.fetchall()
            cur.execute("SELECT clave_hash FROM backup_config WHERE id = 1")
            row = cur.fetchone()
            backup_clave_configurada = bool(row and row['clave_hash'])
    except Exception as e:
        current_app.logger.error(f"Error cargando backups_db: {e}")

    return render_template('configuracion_cliente.html',
                           datosApp=get_data_app(), grupos=grupos,
                           secciones=secciones,
                           module_toggles=module_toggles,
                           gmail_activo=gmail_activo, gmail_email=gmail_email,
                           backups=backups,
                           backup_clave_configurada=backup_clave_configurada)


# ── Facturación DIAN ──────────────────────────────────────────────────────────

@admin_bp.route('/admin/facturacion-dian')
@rol_requerido(ADMIN_CONTADOR)
def facturacion_dian():
    """Genera un token SSO de 30 segundos y redirige al panel de Facturación DIAN.
    Si el módulo no está contratado, muestra la página de módulo bloqueado.
    """
    from routes.factura_electronica import facturacion_habilitada
    if not facturacion_habilitada():
        datosApp = get_data_app()
        return render_template('facturacion_bloqueada.html', datosApp=datosApp)

    master_key = os.getenv('DIAN_MASTER_KEY', '')
    if not master_key:
        flash('DIAN_MASTER_KEY no configurado en .env', 'error')
        return redirect(url_for('admin.dashboard_admin'))

    ts    = int(time.time())
    token = hmac.new(
        master_key.encode(),
        f"{ts}:dian-autologin".encode(),
        hashlib.sha256,
    ).hexdigest()

    dian_base = os.getenv('DIAN_UI_URL', '/ui')
    return redirect(f"{dian_base}/auto-login?token={token}&ts={ts}")


@admin_bp.route('/admin/pos/<int:venta_id>/facturar', methods=['POST'])
@rol_requerido(ADMIN_CONTADOR)
def facturar_venta_pos(venta_id):
    """Emite factura electrónica para una venta POS específica (acción manual)."""
    from routes.factura_electronica import emitir_factura_pos, facturacion_habilitada
    if not facturacion_habilitada():
        return jsonify({'success': False, 'error': 'Módulo de facturación electrónica no contratado'}), 403
    if _table_has_column('ventas_pos', 'facturar_electronicamente'):
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT COALESCE(facturar_electronicamente, FALSE) AS facturar_electronicamente
                FROM ventas_pos
                WHERE id = %s
            """, (venta_id,))
            row = cur.fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Venta no encontrada'}), 404
        if not row['facturar_electronicamente']:
            return jsonify({'success': False, 'error': 'La venta no fue marcada para facturacion electronica'}), 400
    resultado = emitir_factura_pos(venta_id)
    if 'error' in resultado:
        return jsonify({'success': False, 'error': resultado['error']}), 500
    return jsonify({'success': True, 'factura_id': resultado.get('id'), 'estado': resultado.get('estado')})


# ── Backups de base de datos (Super Admin) ────────────────────────────────────

def _backups_dir():
    """Directorio fisico de backups (fuera de static/, igual que uploads/share/)."""
    folder = os.path.join(current_app.root_path, 'uploads', 'backups')
    os.makedirs(folder, exist_ok=True)
    return folder


def _safe_remove(path):
    """Elimina un archivo si existe; ignora si ya no esta."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        current_app.logger.warning(f"No se pudo eliminar {path}: {e}")


def _find_pg_dump():
    """Localiza pg_dump probando PATH extendido y rutas comunes.

    El servicio systemd puede definir un PATH limitado al venv, asi que
    no podemos confiar en shutil.which con el PATH heredado.
    """
    extended_path = os.pathsep.join([
        os.environ.get('PATH', ''),
        '/usr/bin',
        '/usr/local/bin',
        '/usr/lib/postgresql/16/bin',
        '/usr/lib/postgresql/15/bin',
        '/usr/lib/postgresql/14/bin',
    ])
    found = shutil.which('pg_dump', path=extended_path)
    if found:
        return found
    for candidate in ('/usr/bin/pg_dump', '/usr/local/bin/pg_dump'):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


@admin_bp.route('/admin/backup-db/configurar-clave', methods=['POST'])
@rol_requerido(ROL_SUPER_ADMIN)
def backup_db_configurar_clave():
    """Setea o cambia la clave bcrypt de la zona protegida de backups."""
    clave = (request.form.get('clave') or '').strip()
    if len(clave) < 6:
        flash('La clave debe tener al menos 6 caracteres.', 'error')
        return redirect(url_for('admin.configuracion_cliente') + '#backup-db')
    try:
        with get_db_cursor() as cur:
            cur.execute(
                """
                UPDATE backup_config
                SET clave_hash = %s,
                    actualizado_por = %s,
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = 1
                """,
                (generate_password_hash(clave), session.get('user_id')),
            )
        flash('Contraseña de backups actualizada.', 'success')
    except Exception as e:
        current_app.logger.error(f"Error guardando clave de backup: {e}")
        flash('No se pudo guardar la contraseña.', 'error')
    return redirect(url_for('admin.configuracion_cliente') + '#backup-db')


@admin_bp.route('/admin/backup-db/generar', methods=['POST'])
@rol_requerido(ROL_SUPER_ADMIN)
def backup_db_generar():
    """Genera un backup (full o solo schema) usando pg_dump y lo registra."""
    # 1. Validar clave configurada
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT clave_hash FROM backup_config WHERE id = 1")
            row = cur.fetchone()
            if not (row and row['clave_hash']):
                flash('Configura primero la contraseña de backups.', 'error')
                return redirect(url_for('admin.configuracion_cliente') + '#backup-db')
    except Exception as e:
        current_app.logger.error(f"Error verificando clave de backup: {e}")
        flash('No se pudo verificar la configuración de backups.', 'error')
        return redirect(url_for('admin.configuracion_cliente') + '#backup-db')

    # 2. Validar parametros
    tipo = request.form.get('tipo')
    if tipo not in ('full', 'schema'):
        flash('Tipo de backup inválido.', 'error')
        return redirect(url_for('admin.configuracion_cliente') + '#backup-db')
    comprimir = request.form.get('comprimir') == '1'

    # 3. Preparar nombres y registro previo en BD
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    ext = '.sql.gz' if comprimir else '.sql'
    nombre_descarga = f"backup_{tipo}_{timestamp}{ext}"
    user_id = session.get('user_id')
    backup_id = None
    nombre_archivo = None
    ruta_destino = None

    try:
        with get_db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO backups_db (nombre_archivo, nombre_descarga, tipo, comprimido, creado_por)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                ('pendiente', nombre_descarga, tipo, comprimir, user_id),
            )
            backup_id = cur.fetchone()[0]
            nombre_archivo = secure_filename(f"{backup_id}__{nombre_descarga}")
            cur.execute(
                "UPDATE backups_db SET nombre_archivo = %s WHERE id = %s",
                (nombre_archivo, backup_id),
            )
    except Exception as e:
        current_app.logger.error(f"Error registrando backup en BD: {e}")
        flash('No se pudo iniciar el backup.', 'error')
        return redirect(url_for('admin.configuracion_cliente') + '#backup-db')

    ruta_destino = os.path.join(_backups_dir(), nombre_archivo)

    # 4. Localizar pg_dump (PATH del servicio systemd suele estar restringido al venv)
    pg_dump_bin = _find_pg_dump()
    if not pg_dump_bin:
        try:
            with get_db_cursor() as cur:
                cur.execute("DELETE FROM backups_db WHERE id = %s", (backup_id,))
        except Exception:
            pass
        flash('pg_dump no está instalado o no se encuentra en el PATH del servicio.', 'error')
        return redirect(url_for('admin.configuracion_cliente') + '#backup-db')

    # 5. Construir comando pg_dump (lista, no shell=True → seguro contra inyección)
    cmd = [
        pg_dump_bin,
        '-h', os.getenv('DB_HOST', 'localhost'),
        '-p', str(os.getenv('DB_PORT', '5432')),
        '-U', os.getenv('DB_USER', 'postgres'),
        '-d', os.getenv('DB_NAME', 'cybershop'),
        '--no-owner',
        '--no-acl',
    ]
    if tipo == 'schema':
        cmd.append('-s')

    env = {**os.environ, 'PGPASSWORD': os.getenv('DB_PASSWORD', '')}

    # 6. Ejecutar pg_dump escribiendo a disco (no a memoria)
    try:
        if comprimir:
            # Escribimos en streaming a gzip via Popen para no cargar todo a memoria
            with gzip.open(ruta_destino, 'wb') as f_out:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
                )
                # Stream stdout chunk a chunk
                while True:
                    chunk = proc.stdout.read(65536)
                    if not chunk:
                        break
                    f_out.write(chunk)
                stderr = proc.stderr.read()
                returncode = proc.wait(timeout=600)
                if returncode != 0:
                    raise subprocess.CalledProcessError(returncode, cmd, stderr=stderr)
        else:
            with open(ruta_destino, 'wb') as f_out:
                subprocess.run(
                    cmd,
                    stdout=f_out,
                    stderr=subprocess.PIPE,
                    env=env,
                    timeout=600,
                    check=True,
                )

        tamano = os.path.getsize(ruta_destino)
        with get_db_cursor() as cur:
            cur.execute(
                "UPDATE backups_db SET tamano_bytes = %s WHERE id = %s",
                (tamano, backup_id),
            )
        flash(f'Backup generado: {nombre_descarga}', 'success')

    except subprocess.TimeoutExpired:
        _safe_remove(ruta_destino)
        try:
            with get_db_cursor() as cur:
                cur.execute("DELETE FROM backups_db WHERE id = %s", (backup_id,))
        except Exception:
            pass
        flash('Timeout: el backup tardó más de 10 minutos.', 'error')

    except subprocess.CalledProcessError as e:
        _safe_remove(ruta_destino)
        try:
            with get_db_cursor() as cur:
                cur.execute("DELETE FROM backups_db WHERE id = %s", (backup_id,))
        except Exception:
            pass
        stderr_text = (e.stderr or b'').decode('utf-8', errors='ignore')[:300]
        current_app.logger.error(f"pg_dump fallo: {stderr_text}")
        flash(f'pg_dump falló: {stderr_text or "error desconocido"}', 'error')

    except FileNotFoundError:
        _safe_remove(ruta_destino)
        try:
            with get_db_cursor() as cur:
                cur.execute("DELETE FROM backups_db WHERE id = %s", (backup_id,))
        except Exception:
            pass
        flash('pg_dump no está instalado en el servidor.', 'error')

    except OSError as e:
        _safe_remove(ruta_destino)
        try:
            with get_db_cursor() as cur:
                cur.execute("DELETE FROM backups_db WHERE id = %s", (backup_id,))
        except Exception:
            pass
        current_app.logger.error(f"OSError generando backup: {e}")
        flash(f'Error de E/S al generar backup: {e}', 'error')

    return redirect(url_for('admin.configuracion_cliente') + '#backup-db')


@admin_bp.route('/admin/backup-db/descargar/<int:archivo_id>')
@rol_requerido(ROL_SUPER_ADMIN)
def backup_db_descargar(archivo_id):
    """Descarga un archivo de backup. Solo super admin."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT nombre_archivo, nombre_descarga, comprimido FROM backups_db WHERE id = %s",
                (archivo_id,),
            )
            row = cur.fetchone()
    except Exception as e:
        current_app.logger.error(f"Error consultando backup {archivo_id}: {e}")
        abort(500)

    if not row:
        abort(404)

    folder = _backups_dir()
    ruta = os.path.join(folder, row['nombre_archivo'])
    if not os.path.isfile(ruta):
        flash('El archivo de backup ya no existe en disco.', 'error')
        return redirect(url_for('admin.configuracion_cliente') + '#backup-db')

    mimetype = 'application/gzip' if row['comprimido'] else 'application/sql'
    return send_from_directory(
        folder,
        row['nombre_archivo'],
        as_attachment=True,
        download_name=row['nombre_descarga'],
        mimetype=mimetype,
    )


@admin_bp.route('/admin/backup-db/eliminar/<int:archivo_id>', methods=['POST'])
@rol_requerido(ROL_SUPER_ADMIN)
def backup_db_eliminar(archivo_id):
    """Elimina un backup (archivo fisico + registro)."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT nombre_archivo FROM backups_db WHERE id = %s",
                (archivo_id,),
            )
            row = cur.fetchone()
            if not row:
                flash('Backup no encontrado.', 'error')
                return redirect(url_for('admin.configuracion_cliente') + '#backup-db')
            ruta = os.path.join(_backups_dir(), row['nombre_archivo'])
            _safe_remove(ruta)
            cur.execute("DELETE FROM backups_db WHERE id = %s", (archivo_id,))
        flash('Backup eliminado.', 'success')
    except Exception as e:
        current_app.logger.error(f"Error eliminando backup {archivo_id}: {e}")
        flash('No se pudo eliminar el backup.', 'error')
    return redirect(url_for('admin.configuracion_cliente') + '#backup-db')
