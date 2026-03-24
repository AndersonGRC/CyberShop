"""
routes/quotes.py — Modulo de cotizaciones PDF.

Permite generar cotizaciones personalizadas con logo,
items de inventario o personalizados, y exportar a PDF.
"""

import os
from datetime import datetime
from flask import Blueprint, render_template, request, Response, session, current_app as app, send_file, url_for, flash, redirect
from werkzeug.utils import secure_filename
from xhtml2pdf import pisa
from io import BytesIO

from database import get_db_cursor
from helpers import get_data_app, formatear_moneda
from security import rol_requerido

quotes_bp = Blueprint('quotes', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def _get_brand_colors():
    """Lee colores de marca y datos de empresa desde cliente_config con fallback a Config."""
    from config import Config
    colores = dict(Config.BRAND_COLORS)
    colores['website'] = 'https://cybershopcol.com'
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT clave, valor FROM cliente_config WHERE grupo IN ('colores', 'empresa')")
            mapping = {
                'color_primario':        'primario',
                'color_primario_oscuro': 'primario_oscuro',
                'color_secundario':      'secundario',
            }
            for row in cur.fetchall():
                if row['clave'] in mapping:
                    colores[mapping[row['clave']]] = row['valor']
                elif row['clave'] == 'empresa_website' and row['valor']:
                    colores['website'] = row['valor']
    except Exception:
        pass
    return colores


def _pdf_link_callback(uri, rel):
    """Resuelve URLs a rutas locales absolutas para xhtml2pdf.
    Evita peticiones HTTP durante la generación del PDF."""
    from flask import current_app as _app
    # Si ya es file://, devolver como está
    if uri.startswith('file://'):
        return uri
    # Resolver URLs que apunten a static/
    if 'static/' in uri:
        try:
            after_static = uri.split('static/')[-1].split('?')[0]
            local = os.path.join(_app.root_path, 'static', after_static)
            if os.path.isfile(local):
                return local
        except Exception:
            pass
    return uri


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

    return render_template('cotizar.html', datosApp=datosApp, productos=productos,
                           cotizacion=None, detalles=[])


@quotes_bp.route('/admin/cotizar/generar', methods=['POST'])
@rol_requerido(1)
def generar_cotizacion():
    """Procesa el formulario, guarda la cotizacion y genera el PDF."""
    try:
        cotizacion_id_edit = request.form.get('cotizacion_id')  # Si existe, es edicion

        # 1. Datos del Cliente
        cliente_nombre      = request.form.get('cliente_nombre', '')
        cliente_documento   = request.form.get('cliente_documento', '')
        cliente_direccion   = request.form.get('cliente_direccion', '')
        cliente_ciudad      = request.form.get('cliente_ciudad', 'Bogotá')
        cliente_telefono    = request.form.get('cliente_telefono', '')
        cliente_representante = request.form.get('cliente_representante', 'N/A')
        cliente_cargo       = request.form.get('cliente_cargo', 'N/A')
        cliente_localidad   = request.form.get('cliente_localidad', '')

        # 2. Logo: ruta local para PDF, URL para BD
        logo_local_path = None
        logo_url_db     = None
        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                upload_folder = os.path.join(app.root_path, 'static', 'uploads')
                os.makedirs(upload_folder, exist_ok=True)
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)
                logo_local_path = file_path
                logo_url_db = url_for('static', filename=f'uploads/{filename}', _external=True)

        if logo_local_path is None:
            logo_local_path = 'file://' + os.path.join(app.root_path, 'static', 'img', 'Logo.PNG')
        elif not logo_local_path.startswith('file://'):
            logo_local_path = 'file://' + logo_local_path

        # 3. Procesar Items
        items = []
        cantidades    = request.form.getlist('cantidad[]')
        descripciones = request.form.getlist('descripcion[]')
        precios       = request.form.getlist('precio[]')
        descuentos    = request.form.getlist('descuento[]')
        ivas          = request.form.getlist('iva[]')
        imagenes_ref  = request.form.getlist('imagen_ref[]')

        total_cotizacion = 0
        total_subtotal   = 0
        total_descuentos = 0
        total_iva        = 0

        cotizacion_id = 0
        with get_db_cursor(dict_cursor=True) as cur:
            if cotizacion_id_edit:
                # Actualizar cabecera
                cur.execute("""
                    UPDATE cotizaciones SET
                        cliente_nombre=%s, cliente_documento=%s, logo_url=%s,
                        cliente_direccion=%s, cliente_ciudad=%s, cliente_telefono=%s,
                        cliente_representante=%s, cliente_cargo=%s, cliente_localidad=%s
                    WHERE id=%s
                """, (cliente_nombre, cliente_documento, logo_url_db,
                      cliente_direccion, cliente_ciudad, cliente_telefono,
                      cliente_representante, cliente_cargo, cliente_localidad,
                      cotizacion_id_edit))
                cotizacion_id = int(cotizacion_id_edit)
                cur.execute("DELETE FROM detalle_cotizacion WHERE cotizacion_id=%s", (cotizacion_id,))
            else:
                # Insertar nuevo
                cur.execute("""
                    INSERT INTO cotizaciones (
                        cliente_nombre, cliente_documento, logo_url,
                        cliente_direccion, cliente_ciudad, cliente_telefono,
                        cliente_representante, cliente_cargo, cliente_localidad, total
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0) RETURNING id
                """, (cliente_nombre, cliente_documento, logo_url_db,
                      cliente_direccion, cliente_ciudad, cliente_telefono,
                      cliente_representante, cliente_cargo, cliente_localidad))
                cotizacion_id = cur.fetchone()['id']

            for i in range(len(descripciones)):
                cantidad        = int(cantidades[i]) if i < len(cantidades) and cantidades[i] else 1
                descripcion     = descripciones[i]
                precio_unitario = float(precios[i]) if i < len(precios) and precios[i] else 0
                descuento_porc  = float(descuentos[i]) if i < len(descuentos) and descuentos[i] else 0
                iva_porc        = float(ivas[i]) if i < len(ivas) and ivas[i] else 0

                subtotal_linea     = cantidad * precio_unitario
                monto_descuento    = subtotal_linea * (descuento_porc / 100)
                subtotal_menos_desc = subtotal_linea - monto_descuento
                monto_iva          = subtotal_menos_desc * (iva_porc / 100) if iva_porc > 0 else 0
                total_linea        = subtotal_menos_desc + monto_iva

                total_subtotal   += subtotal_linea
                total_descuentos += monto_descuento
                total_iva        += monto_iva
                total_cotizacion += total_linea

                # Imagen: ruta local para PDF, URL para BD
                img_path_final = None
                img_url_db     = None

                file_key = f'imagen_upload_{i}'
                if file_key in request.files and request.files[file_key].filename != '':
                    file = request.files[file_key]
                    if allowed_file(file.filename):
                        fname = secure_filename(file.filename)
                        upload_folder = os.path.join(app.root_path, 'static', 'uploads')
                        os.makedirs(upload_folder, exist_ok=True)
                        fpath = os.path.join(upload_folder, fname)
                        file.save(fpath)
                        img_path_final = 'file://' + fpath
                        img_url_db = url_for('static', filename=f'uploads/{fname}', _external=True)
                elif i < len(imagenes_ref) and imagenes_ref[i]:
                    ref_url = imagenes_ref[i]
                    img_url_db = ref_url
                    try:
                        if 'static' in ref_url:
                            part_static = ref_url.split('static')[-1].lstrip('/').lstrip('\\')
                            local = os.path.join(app.root_path, 'static', part_static)
                            if os.path.isfile(local):
                                img_path_final = 'file://' + local
                    except Exception:
                        pass

                cur.execute("""
                    INSERT INTO detalle_cotizacion
                        (cotizacion_id, descripcion, cantidad, precio_unitario, subtotal,
                         imagen_url, descuento_porc, iva_porc)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (cotizacion_id, descripcion, cantidad, precio_unitario, total_linea,
                      img_url_db, descuento_porc, iva_porc))

                items.append({
                    'descripcion':     descripcion,
                    'cantidad':        cantidad,
                    'precio_unitario': formatear_moneda(precio_unitario),
                    'subtotal':        formatear_moneda(total_linea),
                    'imagen_local_path': img_path_final,
                    'descuento': f"{int(descuento_porc)}%" if descuento_porc > 0 else "0%",
                    'iva':       f"{int(iva_porc)}%" if iva_porc > 0 else "0%"
                })

            cur.execute("UPDATE cotizaciones SET total = %s WHERE id = %s",
                        (total_cotizacion, cotizacion_id))

        # 4. Generar PDF
        meses = {
            1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
            5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
            9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
        }
        hoy = datetime.now()
        fecha_actual = f"Bogotá {hoy.day} de {meses[hoy.month]} de {hoy.year}"

        datos_pdf = {
            'id':     f"COT {str(cotizacion_id).zfill(10)}",
            'fecha':  fecha_actual,
            'cliente': {
                'nombre':         cliente_nombre,
                'documento':      cliente_documento,
                'direccion':      cliente_direccion,
                'ciudad':         cliente_ciudad,
                'telefono':       cliente_telefono,
                'representante':  cliente_representante,
                'cargo':          cliente_cargo,
                'localidad':      cliente_localidad,
            },
            'items':    items,
            'total':    formatear_moneda(total_cotizacion),
            'subtotal': formatear_moneda(total_subtotal),
            'descuento': formatear_moneda(total_descuentos),
            'iva':      formatear_moneda(total_iva),
            'logo':     logo_local_path,   # ruta local, sin peticion HTTP
            'colores':  _get_brand_colors()
        }

        rendered_html = render_template('pdf_quote.html', **datos_pdf)

        pdf_output = BytesIO()
        pisa_status = pisa.CreatePDF(rendered_html, dest=pdf_output,
                                     link_callback=_pdf_link_callback)

        if pisa_status.err:
            return Response("Error generando PDF", status=500)

        pdf_output.seek(0)

        # Guardar en disco
        try:
            filename_pdf = f"Cotizacion_{cotizacion_id}.pdf"
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            pdf_folder = os.path.join(base_dir, 'static', 'cotizaciones', 'pdf')
            os.makedirs(pdf_folder, exist_ok=True)
            pdf_path_disk = os.path.join(pdf_folder, filename_pdf)
            with open(pdf_path_disk, 'wb') as f:
                f.write(pdf_output.getvalue())
            pdf_rel_path = f"cotizaciones/pdf/{filename_pdf}"
            with get_db_cursor() as cur:
                cur.execute("UPDATE cotizaciones SET pdf_path = %s WHERE id = %s",
                            (pdf_rel_path, cotizacion_id))
        except Exception as e:
            app.logger.error(f"Error guardando PDF en disco: {e}")

        pdf_output.seek(0)
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
    datosApp = get_data_app()
    cotizacion = None
    detalles = []
    productos = []

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT id, nombre, precio, stock, imagen FROM productos ORDER BY nombre')
            productos = cur.fetchall()

            cur.execute('SELECT * FROM cotizaciones WHERE id = %s', (id,))
            cotizacion = cur.fetchone()

            if cotizacion:
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
    try:
        pdf_path = None
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT pdf_path FROM cotizaciones WHERE id=%s", (id,))
            res = cur.fetchone()
            if res and res['pdf_path']:
                pdf_path = res['pdf_path']
            cur.execute("DELETE FROM cotizaciones WHERE id=%s", (id,))

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
