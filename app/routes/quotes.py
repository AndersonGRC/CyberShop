"""
routes/quotes.py — Modulo de cotizaciones PDF.

Permite generar cotizaciones personalizadas con logo,
items de inventario o personalizados, y exportar a PDF.
"""

import os
from datetime import datetime
from flask import Blueprint, render_template, request, Response, session, current_app as app, send_file, url_for
from werkzeug.utils import secure_filename
from xhtml2pdf import pisa
from io import BytesIO

from database import get_db_cursor
from helpers import get_data_app, formatear_moneda
from security import rol_requerido

quotes_bp = Blueprint('quotes', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@quotes_bp.route('/admin/cotizar')
@rol_requerido(1)
def cotizar():
    """Renderiza la interfaz de generacion de cotizaciones."""
    datosApp = get_data_app()
    productos = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT id, nombre, precio, stock, imagen FROM productos ORDER BY nombre')
            productos = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando productos para cotizacion: {e}")
        
    return render_template('cotizar.html', datosApp=datosApp, productos=productos)

@quotes_bp.route('/admin/cotizar/generar', methods=['POST'])
@rol_requerido(1)
def generar_cotizacion():
    """Procesa el formulario, guarda la cotizacion y genera el PDF."""
    try:
        # 1. Datos del Cliente
        cliente_nombre = request.form.get('cliente_nombre')
        cliente_documento = request.form.get('cliente_documento')
        
        # 2. Manejo del Logo
        logo_url = None
        if 'logo' in request.files:
            file = request.files['logo']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Guardar en static/uploads
                upload_folder = os.path.join(app.root_path, 'static', 'uploads')
                os.makedirs(upload_folder, exist_ok=True)
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)
                logo_url = url_for('static', filename=f'uploads/{filename}', _external=True)

        # 3. Procesar Items
        items = []
        cantidades = request.form.getlist('cantidad[]')
        descripciones = request.form.getlist('descripcion[]')
        precios = request.form.getlist('precio[]')
        descuentos = request.form.getlist('descuento[]')
        ivas = request.form.getlist('iva[]')
        imagenes_ref = request.form.getlist('imagen_ref[]') # URLs de inventario
        
        total_cotizacion = 0
        total_subtotal = 0
        total_descuentos = 0
        total_iva = 0
        
        # Guardar Encabezado
        cotizacion_id = 0
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                INSERT INTO cotizaciones (cliente_nombre, cliente_documento, logo_url, total)
                VALUES (%s, %s, %s, 0) RETURNING id
            """, (cliente_nombre, cliente_documento, logo_url))
            cotizacion_id = cur.fetchone()['id']
            
            # Guardar Detalles
            for i in range(len(descripciones)):
                cantidad = int(cantidades[i])
                descripcion = descripciones[i]
                precio_unitario = float(precios[i])
                
                # Descuentos e IVA
                descuento_porc = float(descuentos[i]) if i < len(descuentos) and descuentos[i] else 0
                tiene_iva = float(ivas[i]) if i < len(ivas) and ivas[i] else 0 # 19 o 0

                # Calculos
                subtotal_linea = cantidad * precio_unitario
                monto_descuento = subtotal_linea * (descuento_porc / 100)
                subtotal_menos_desc = subtotal_linea - monto_descuento
                
                monto_iva = 0
                if tiene_iva > 0:
                    monto_iva = subtotal_menos_desc * (tiene_iva / 100)
                
                total_linea = subtotal_menos_desc + monto_iva

                # Acumulados
                total_subtotal += subtotal_linea
                total_descuentos += monto_descuento
                total_iva += monto_iva
                total_cotizacion += total_linea
                
                # Manejo de Imagen
                img_path_final = None # Para xhtml2pdf (ruta absoluta sistema)
                img_url_db = None     # Para guardar en BD
                
                # 1. Revisar si hay archivo subido: imagen_upload_{i}
                file_key = f'imagen_upload_{i}'
                if file_key in request.files and request.files[file_key].filename != '':
                    file = request.files[file_key]
                    if allowed_file(file.filename):
                        fname = secure_filename(file.filename)
                        # Guardar temporalmente para el PDF
                        upload_folder = os.path.join(app.root_path, 'static', 'uploads')
                        os.makedirs(upload_folder, exist_ok=True)
                        fpath = os.path.join(upload_folder, fname)
                        file.save(fpath)
                        
                        img_path_final = fpath
                        img_url_db = url_for('static', filename=f'uploads/{fname}', _external=True)
                
                # 2. Si no hay archivo, revisar referencia (inventario)
                elif i < len(imagenes_ref) and imagenes_ref[i]:
                    ref_url = imagenes_ref[i]
                    img_url_db = ref_url
                    try:
                        if 'static' in ref_url:
                            part_static = ref_url.split('static')[-1]
                            if part_static.startswith('/'): part_static = part_static[1:]
                            if part_static.startswith('\\'): part_static = part_static[1:]
                            img_path_final = os.path.join(app.root_path, 'static', part_static)
                    except:
                        pass

                cur.execute("""
                    INSERT INTO detalle_cotizacion (cotizacion_id, descripcion, cantidad, precio_unitario, subtotal, imagen_url)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (cotizacion_id, descripcion, cantidad, precio_unitario, total_linea, img_url_db))
                
                items.append({
                    'descripcion': descripcion,
                    'cantidad': cantidad,
                    'precio_unitario': formatear_moneda(precio_unitario),
                    'subtotal': formatear_moneda(total_linea),
                    'imagen_local_path': img_path_final,
                    'descuento': f"{int(descuento_porc)}%" if descuento_porc > 0 else "0%",
                    'iva': f"{int(tiene_iva)}%" if tiene_iva > 0 else "0%"
                })

            # Actualizar total
            cur.execute("UPDATE cotizaciones SET total = %s WHERE id = %s", (total_cotizacion, cotizacion_id))
            
        # 4. Generar PDF
        # Formato de fecha en español
        meses = {
            1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
            7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
        }
        hoy = datetime.now()
        fecha_actual = f"Bogotá {hoy.day} de {meses[hoy.month]} de {hoy.year}"

        # Datos adicionales del cliente (Recibidos del form, no guardados en BD por ahora)
        datos_cliente = {
            'nombre': cliente_nombre,
            'documento': cliente_documento,
            'direccion': request.form.get('cliente_direccion', ''),
            'ciudad': request.form.get('cliente_ciudad', 'Bogotá'),
            'telefono': request.form.get('cliente_telefono', ''),
            'representante': request.form.get('cliente_representante', 'N/A'),
            'cargo': request.form.get('cliente_cargo', 'N/A'), 
            'localidad': request.form.get('cliente_localidad', '')
        }

        datos_pdf = {
            'id': f"COT {str(cotizacion_id).zfill(10)}", # Formato COT 0000000001
            'fecha': fecha_actual,
            'cliente': datos_cliente, # Pasamos el objeto completo
            'items': items,
            'total': formatear_moneda(total_cotizacion),
            'subtotal': formatear_moneda(total_subtotal),
            'descuento': formatear_moneda(total_descuentos),
            'iva': formatear_moneda(total_iva),
            'logo': logo_url or url_for('static', filename='img/Logo.png', _external=True),
            'colores': app.config.get('BRAND_COLORS', {
                'primario': '#122C94',
                'primario_oscuro': '#091C5A',
                'secundario': '#0e1b33',
                'texto': '#333333',
                'texto_claro': '#888888',
                'fondo_claro': '#f9f9f9',
                'exito': '#28a745',
                'borde': '#000000',
            })
        }
        
        rendered_html = render_template('pdf_quote.html', **datos_pdf)
        
        # Crear PDF en memoria
        pdf_output = BytesIO()
        pisa_status = pisa.CreatePDF(rendered_html, dest=pdf_output)
        
        if pisa_status.err:
            return Response("Error generando PDF", status=500)
            
        pdf_output.seek(0)

        # Guardar en disco static/cotizaciones/pdf/Cotizacion_{id}.pdf
        try:
            filename_pdf = f"Cotizacion_{cotizacion_id}.pdf"
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # app/
            pdf_folder = os.path.join(base_dir, 'static', 'cotizaciones', 'pdf')
            os.makedirs(pdf_folder, exist_ok=True)
            
            pdf_path_disk = os.path.join(pdf_folder, filename_pdf)
            
            with open(pdf_path_disk, 'wb') as f:
                f.write(pdf_output.getvalue())
            
            # Actualizar DB con path relativo
            pdf_rel_path = f"cotizaciones/pdf/{filename_pdf}"
            with get_db_cursor() as cur:
                cur.execute("UPDATE cotizaciones SET pdf_path = %s WHERE id = %s", (pdf_rel_path, cotizacion_id))
                
        except Exception as e:
            app.logger.error(f"Error guardando PDF en disco: {e}")
            # No fallamos la respuesta si no guarda en disco, pero logueamos
        
        return send_file(
            pdf_output,
            as_attachment=True,
            download_name=f"Cotizacion_{cotizacion_id}.pdf",
            mimetype='application/pdf'
        )

    except Exception as e:
        app.logger.error(f"Error generando cotizacion: {e}")
        return Response(f"Error: {e}", status=500)

@quotes_bp.route('/admin/mis_cotizaciones')
@rol_requerido(1)
def ver_cotizaciones():
    """Lista las cotizaciones generadas."""
    datosApp = get_data_app()
    cotizaciones = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT id, fecha, cliente_nombre, cliente_documento, total, pdf_path 
                FROM cotizaciones 
                ORDER BY fecha DESC
            """)
            cotizaciones = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error listando cotizaciones: {e}")
        
    return render_template('mis_cotizaciones.html', datosApp=datosApp, cotizaciones=cotizaciones)

@quotes_bp.route('/admin/cotizar/editar/<int:id>')
@rol_requerido(1)
def editar_cotizacion(id):
    """Renderiza el formulario con datos de una cotización existente."""
    from flask import flash, redirect
    datosApp = get_data_app()
    cotizacion = None
    detalles = []
    productos = []
    
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # Cargar productos
            cur.execute('SELECT id, nombre, precio, stock, imagen FROM productos ORDER BY nombre')
            productos = cur.fetchall()
            
            # Cargar Cotización
            cur.execute('SELECT * FROM cotizaciones WHERE id = %s', (id,))
            cotizacion = cur.fetchone()
            
            if cotizacion:
                # Cargar Detalles
                cur.execute('SELECT * FROM detalle_cotizacion WHERE cotizacion_id = %s ORDER BY id', (id,))
                detalles = cur.fetchall()
                
    except Exception as e:
        app.logger.error(f"Error cargando cotización {id}: {e}")
        flash("Error al cargar la cotización.", "danger")
        return redirect(url_for('quotes.ver_cotizaciones'))
        
    if not cotizacion:
        flash("Cotización no encontrada.", "warning")
        return redirect(url_for('quotes.ver_cotizaciones'))

    return render_template('cotizar.html', 
                          datosApp=datosApp, 
                          productos=productos,
                          cotizacion=cotizacion,
                          detalles=detalles)

@quotes_bp.route('/admin/cotizar/eliminar/<int:id>', methods=['POST'])
@rol_requerido(1)
def eliminar_cotizacion(id):
    """Elimina una cotización y su archivo PDF."""
    from flask import flash, redirect
    try:
        pdf_path = None
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT pdf_path FROM cotizaciones WHERE id=%s", (id,))
            res = cur.fetchone()
            if res and res['pdf_path']:
                pdf_path = res['pdf_path']
            
            cur.execute("DELETE FROM cotizaciones WHERE id=%s", (id,))
            
        # Borrar archivo físico
        if pdf_path:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            full_path = os.path.join(base_dir, 'static', pdf_path.replace('/', os.sep))
            if os.path.exists(full_path):
                os.remove(full_path)
                
        flash("Cotización eliminada correctamente.", "success")
    except Exception as e:
        app.logger.error(f"Error eliminando cotización {id}: {e}")
        flash(f"Error al eliminar: {e}", "danger")
        
    return redirect(url_for('quotes.ver_cotizaciones'))
