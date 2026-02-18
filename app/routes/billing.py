
"""
routes/billing.py — Modulo de Cuentas de Cobro PDF.

Permite generar documentos de cobro equivalentes a nomina/facturacion simplificada
para contratistas, con generacion de PDF y soporte para edicion/eliminacion.
"""

import os
import locale
from datetime import datetime
from flask import Blueprint, render_template, request, Response, session, current_app as app, send_file, url_for, redirect, flash
from werkzeug.utils import secure_filename
from xhtml2pdf import pisa
from io import BytesIO
import num2words

from database import get_db_cursor
from helpers import get_data_app, formatear_moneda
from security import rol_requerido

billing_bp = Blueprint('billing', __name__)

# Intentar configurar locale para fechas en español
try:
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'Spanish_Spain.1252')
    except:
        pass # Fallback a default

@billing_bp.route('/admin/cuenta_cobro')
@rol_requerido(1)
def crear_cuenta():
    """Renderiza el formulario para crear una nueva cuenta de cobro."""
    datosApp = get_data_app()
    
    # Cargar configuracion por defecto
    default_info = app.config.get('BILLING_INFO', {})
    
    # Cargar productos para autocompletado
    productos = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT id, nombre, precio FROM productos ORDER BY nombre')
            productos = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando productos: {e}")
        
    return render_template('crear_cuenta_cobro.html', 
                          datosApp=datosApp, 
                          productos=productos,
                          defaults=default_info,
                          cuenta=None)

@billing_bp.route('/admin/cuenta_cobro/editar/<int:id>')
@rol_requerido(1)
def editar_cuenta(id):
    """Renderiza el formulario con datos de una cuenta existente."""
    datosApp = get_data_app()
    cuenta = None
    detalles = []
    productos = []
    
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # Cargar productos
            cur.execute('SELECT id, nombre, precio FROM productos ORDER BY nombre')
            productos = cur.fetchall()
            
            # Cargar Cuenta
            cur.execute('SELECT * FROM cuentas_cobro WHERE id = %s', (id,))
            cuenta = cur.fetchone()
            
            if cuenta:
                # Cargar Detalles
                cur.execute('SELECT * FROM detalle_cuenta_cobro WHERE cuenta_id = %s ORDER BY id', (id,))
                detalles = cur.fetchall()
                
    except Exception as e:
        app.logger.error(f"Error cargando cuenta {id}: {e}")
        flash("Error al cargar la cuenta de cobro.", "danger")
        return redirect(url_for('billing.listar_cuentas'))
        
    if not cuenta:
        flash("Cuenta de cobro no encontrada.", "warning")
        return redirect(url_for('billing.listar_cuentas'))

    return render_template('crear_cuenta_cobro.html', 
                          datosApp=datosApp, 
                          productos=productos,
                          cuenta=cuenta,
                          detalles=detalles)

@billing_bp.route('/admin/cuenta_cobro/generar', methods=['POST'])
@rol_requerido(1)
def guardar_generar_cuenta():
    """Guarda (inserta o actualiza) la cuenta y genera el PDF."""
    try:
        cuenta_id = request.form.get('cuenta_id') # Si existe, es edicion
        
        # 1. Recoger datos del formulario
        cliente_nombre = request.form.get('cliente_nombre')
        cliente_nit = request.form.get('cliente_nit')
        cliente_direccion = request.form.get('cliente_direccion')
        cliente_telefono = request.form.get('cliente_telefono')
        cliente_ciudad = request.form.get('cliente_ciudad')
        
        contractor_nombre = request.form.get('contractor_nombre')
        contractor_id = request.form.get('contractor_id')
        contractor_telefono = request.form.get('contractor_telefono')
        contractor_email = request.form.get('contractor_email')
        texto_pago = request.form.get('texto_pago')
        
        fecha_str = request.form.get('fecha') # YYYY-MM-DD
        
        # Items
        fechas_labor = request.form.getlist('item_fecha[]')
        descripciones = request.form.getlist('item_descripcion[]')
        valores = request.form.getlist('item_valor[]')
        
        total = 0
        items_data = [] # Para el PDF
        
        # Calcular total
        for v in valores:
            try:
                total += float(v)
            except:
                pass

        with get_db_cursor(dict_cursor=True) as cur:
            if cuenta_id:
                # Actualizar
                cur.execute("""
                    UPDATE cuentas_cobro SET 
                        cliente_nombre=%s, cliente_nit=%s, cliente_direccion=%s, 
                        cliente_telefono=%s, cliente_ciudad=%s,
                        contractor_nombre=%s, contractor_id=%s, contractor_telefono=%s, 
                        contractor_email=%s, texto_pago=%s, fecha=%s, total=%s
                    WHERE id=%s
                """, (cliente_nombre, cliente_nit, cliente_direccion, cliente_telefono, cliente_ciudad,
                      contractor_nombre, contractor_id, contractor_telefono, contractor_email,
                      texto_pago, fecha_str, total, cuenta_id))
                
                # Borrar detalles viejos para insertar nuevos
                cur.execute("DELETE FROM detalle_cuenta_cobro WHERE cuenta_id=%s", (cuenta_id,))
                
            else:
                # Insertar Nuevo
                # Generar consecutivo simple (podria mejorarse)
                cur.execute("SELECT COUNT(*) as count FROM cuentas_cobro")
                count = cur.fetchone()['count'] + 1
                consecutivo = f"CC-{str(count).zfill(4)}"
                
                cur.execute("""
                    INSERT INTO cuentas_cobro (
                        consecutivo, fecha, cliente_nombre, cliente_nit, cliente_direccion,
                        cliente_telefono, cliente_ciudad, contractor_nombre, contractor_id,
                        contractor_telefono, contractor_email, texto_pago, total
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (consecutivo, fecha_str, cliente_nombre, cliente_nit, cliente_direccion,
                      cliente_telefono, cliente_ciudad, contractor_nombre, contractor_id,
                      contractor_telefono, contractor_email, texto_pago, total))
                cuenta_id = cur.fetchone()['id']
            
            # Insertar Detalles
            for i in range(len(descripciones)):
                f_labor = fechas_labor[i] if i < len(fechas_labor) else fecha_str
                desc = descripciones[i]
                val = float(valores[i]) if i < len(valores) and valores[i] else 0
                
                cur.execute("""
                    INSERT INTO detalle_cuenta_cobro (cuenta_id, fecha_labor, descripcion, valor)
                    VALUES (%s, %s, %s, %s)
                """, (cuenta_id, f_labor, desc, val))
                
                items_data.append({
                    'fecha': f_labor,
                    'descripcion': desc,
                    'valor': val,
                    'valor_formatted': formatear_moneda(val)
                })
        
        # 2. Generar PDF
        # Convertir total a texto
        try:
            total_texto = num2words.num2words(total, lang='es').upper() + " PESOS M/CTE"
        except:
            total_texto = f"{total} PESOS M/CTE"

        # Fecha formateada
        try:
            date_obj = datetime.strptime(fecha_str, '%Y-%m-%d')
            meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
            fecha_larga = f"{date_obj.day} de {meses[date_obj.month-1]} de {date_obj.year}"
            # Consecutivo con formato: dia-mes-año-consecutivo
            consecutivo_formatted = f"{date_obj.day:02d}-{date_obj.month:02d}-{date_obj.year}-{cuenta_id}"
        except:
            fecha_larga = fecha_str
            consecutivo_formatted = f"CDC-{cuenta_id}"

        pdf_data = {
            'id': cuenta_id,
            'consecutivo': consecutivo_formatted,
            'fecha': fecha_larga,
            'cliente': {
                'nombre': cliente_nombre,
                'nit': cliente_nit,
                'direccion': cliente_direccion,
                'ciudad': cliente_ciudad
            },
            'contractor': {
                'nombre': contractor_nombre,
                'id': contractor_id,
                'texto_pago': texto_pago,
                'email': contractor_email,
                'telefono': contractor_telefono
            },
            'items': items_data,
            'total_valor': formatear_moneda(total),
            'total_texto': total_texto,
            'logo': url_for('static', filename='img/Logo.PNG', _external=True),
            'brand': app.config.get('BRAND_COLORS', {})
        }
        
        rendered_html = render_template('pdf_cuenta_cobro.html', **pdf_data)
        
        pdf_output = BytesIO()
        pisa_status = pisa.CreatePDF(rendered_html, dest=pdf_output)
        
        if pisa_status.err:
            return Response("Error generando PDF", status=500)
            
        pdf_output.seek(0)
        
        # Guardar en disco
        filename_pdf = f"CueCob_{cuenta_id}.pdf"
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdf_folder = os.path.join(base_dir, 'static', 'cotizaciones', 'pdf') # Reusamos carpeta o creamos nueva 'cuentas'
        # Mejor creamos una carpeta 'cuentas_cobro'
        pdf_folder = os.path.join(base_dir, 'static', 'cuentas_cobro', 'pdf')
        os.makedirs(pdf_folder, exist_ok=True)
        
        pdf_path_disk = os.path.join(pdf_folder, filename_pdf)
        with open(pdf_path_disk, 'wb') as f:
            f.write(pdf_output.getvalue())
            
        # Update path in DB
        pdf_rel_path = f"cuentas_cobro/pdf/{filename_pdf}"
        with get_db_cursor() as cur:
            cur.execute("UPDATE cuentas_cobro SET pdf_path=%s WHERE id=%s", (pdf_rel_path, cuenta_id))
            
        return send_file(
            pdf_output,
            as_attachment=True,
            download_name=filename_pdf,
            mimetype='application/pdf'
        )

    except Exception as e:
        app.logger.error(f"Error procesando cuenta de cobro: {e}")
        return Response(f"Error: {e}", status=500)

@billing_bp.route('/admin/cuenta_cobro/eliminar/<int:id>', methods=['POST'])
@rol_requerido(1)
def eliminar_cuenta(id):
    """Elimina una cuenta de cobro y su archivo PDF."""
    try:
        pdf_path = None
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT pdf_path FROM cuentas_cobro WHERE id=%s", (id,))
            res = cur.fetchone()
            if res and res['pdf_path']:
                pdf_path = res['pdf_path']
            
            cur.execute("DELETE FROM cuentas_cobro WHERE id=%s", (id,))
            
        # Borrar archivo fisico
        if pdf_path:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            full_path = os.path.join(base_dir, 'static', pdf_path.replace('/', os.sep))
            if os.path.exists(full_path):
                os.remove(full_path)
                
        flash("Cuenta de cobro eliminada correctamente.", "success")
    except Exception as e:
        app.logger.error(f"Error eliminando cuenta {id}: {e}")
        flash(f"Error al eliminar: {e}", "danger")
        
    return redirect(url_for('billing.listar_cuentas'))

@billing_bp.route('/admin/mis_cuentas_cobro')
@rol_requerido(1)
def listar_cuentas():
    """Lista el historial de cuentas de cobro generadas."""
    datosApp = get_data_app()
    cuentas = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT id, consecutivo, fecha, cliente_nombre, total, pdf_path 
                FROM cuentas_cobro 
                ORDER BY fecha DESC, id DESC
            """)
            cuentas = cur.fetchall()
            
    except Exception as e:
        app.logger.error(f"Error listando cuentas: {e}")
        
    return render_template('mis_cuentas_cobro.html', datosApp=datosApp, cuentas=cuentas)
