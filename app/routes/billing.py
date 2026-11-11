
"""
routes/billing.py — Modulo de Cuentas de Cobro PDF.

Permite generar documentos de cobro equivalentes a nomina/facturacion simplificada
para contratistas, con generacion de PDF y soporte para edicion/eliminacion.
"""

import os
import locale
from datetime import datetime, date
from flask import Blueprint, render_template, request, Response, session, current_app as app, send_file, url_for, redirect, flash, jsonify
from werkzeug.utils import secure_filename
from xhtml2pdf import pisa
from io import BytesIO
import num2words

from database import get_db_cursor
from helpers import get_data_app, formatear_moneda, pdf_link_callback, logo_local_path as resolve_logo_path
from security import permiso_requerido, registrar_guard_permiso, rol_requerido, ADMIN_CONTADOR

billing_bp = Blueprint('billing', __name__)

# Permisos dinámicos (matriz del Propietario): guard 'ver' de todo el
# blueprint. Convive con los @rol_requerido existentes (defensa doble).
registrar_guard_permiso(billing_bp, 'billing')



def _get_empresa_website():
    """Lee la URL del sitio web de la empresa desde cliente_config."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave='empresa_website'")
            row = cur.fetchone()
            if row and row['valor']:
                return row['valor']
    except Exception:
        pass
    return 'https://cybershopcol.com'

# Intentar configurar locale para fechas en español
try:
    locale.setlocale(locale.LC_TIME, 'es_ES.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_TIME, 'Spanish_Spain.1252')
    except:
        pass # Fallback a default

@billing_bp.route('/admin/cuenta_cobro')
@rol_requerido(ADMIN_CONTADOR)
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
@rol_requerido(ADMIN_CONTADOR)
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
@rol_requerido(ADMIN_CONTADOR)
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

        # F1.3 — vincular la cuenta de cobro con un contacto CRM
        try:
            from services.crm_service import upsert_contacto
            crm_id = upsert_contacto(
                nombre=cliente_nombre,
                telefono=cliente_telefono,
                ciudad=cliente_ciudad,
                direccion=cliente_direccion,
                tipo='cliente',
                origen='cuenta_cobro',
                tags_add=['facturado'],
            )
            if crm_id:
                with get_db_cursor() as _cur:
                    _cur.execute(
                        "UPDATE cuentas_cobro SET crm_contacto_id = %s WHERE id = %s",
                        (crm_id, cuenta_id),
                    )
        except Exception as _ce:
            app.logger.warning(f"CRM sync cuenta cobro: {_ce}")

        # Sincronizar contabilidad: upsert por (referencia_tipo, referencia_id)
        # → create nuevo: inserta
        # → edit existente: actualiza el mismo movimiento (no duplica)
        try:
            from routes.contabilidad import sincronizar_movimiento_referencia
            sincronizar_movimiento_referencia(
                tipo='ingreso',
                categoria='cuenta_cobro',
                descripcion=f"Cuenta de cobro #{cuenta_id} — {cliente_nombre}",
                monto=total,
                fecha=fecha_str,
                referencia_tipo='cuenta_cobro',
                referencia_id=cuenta_id,
                usuario_id=session.get('usuario_id'),
                auto_generado=True,
            )
        except Exception as _e:
            app.logger.warning(f"No se pudo sincronizar contabilidad: {_e}")

        # Cartera: una cuenta nueva nace "pendiente de pago" (el ingreso ya
        # quedó en contabilidad, pero la plata todavía no entra). En una
        # edición no se toca: pudo haberse marcado pagada antes.
        if not request.form.get('cuenta_id'):
            from services.cartera_service import marcar_pendiente_si_falta
            marcar_pendiente_si_falta('cuenta_cobro', cuenta_id)

        # 2. Generar PDF. No se guarda en disco (antes quedaba público en static/ y
        # mezclado entre tiendas): «PDF» y el enlace del cliente lo arman de nuevo.
        contenido_pdf = _pdf_cuenta(
            cuenta_id, fecha_str,
            {'nombre': cliente_nombre, 'nit': cliente_nit,
             'direccion': cliente_direccion, 'ciudad': cliente_ciudad},
            {'nombre': contractor_nombre, 'id': contractor_id, 'texto_pago': texto_pago,
             'email': contractor_email, 'telefono': contractor_telefono},
            items_data, total)

        if contenido_pdf is None:
            return Response("Error generando PDF", status=500)

        return send_file(
            BytesIO(contenido_pdf),
            as_attachment=True,
            download_name=f"CueCob_{cuenta_id}.pdf",
            mimetype='application/pdf'
        )

    except Exception as e:
        app.logger.error(f"Error procesando cuenta de cobro: {e}")
        return Response(f"Error: {e}", status=500)


# ── El PDF se arma con lo guardado, no se deja en disco (1.9.19.0) ──────────
def _pdf_cuenta(cuenta_id, fecha_str, cliente, contractor, items_data, total):
    """El PDF de la cuenta de cobro en bytes; None si xhtml2pdf falla.
    `fecha_str`: AAAA-MM-DD; `items_data`: [{fecha, descripcion, valor, valor_formatted}]."""
    # Convertir total a texto
    try:
        total_texto = num2words.num2words(total, lang='es').upper() + " PESOS M/CTE"
    except Exception:  # noqa: BLE001
        total_texto = f"{total} PESOS M/CTE"

    # Fecha formateada
    try:
        date_obj = datetime.strptime(fecha_str, '%Y-%m-%d')
        meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
        fecha_larga = f"{date_obj.day} de {meses[date_obj.month-1]} de {date_obj.year}"
        # Consecutivo con formato: dia-mes-año-consecutivo
        consecutivo_formatted = f"{date_obj.day:02d}-{date_obj.month:02d}-{date_obj.year}-{cuenta_id}"
    except Exception:  # noqa: BLE001
        fecha_larga = fecha_str
        consecutivo_formatted = f"CDC-{cuenta_id}"

    pdf_data = {
        'id': cuenta_id,
        'consecutivo': consecutivo_formatted,
        'fecha': fecha_larga,
        'cliente': cliente,
        'contractor': contractor,
        'items': items_data,
        'total_valor': formatear_moneda(total),
        'total_texto': total_texto,
        'logo': resolve_logo_path(app.root_path),
        'brand': app.config.get('BRAND_COLORS', {}),
        'empresa_website': _get_empresa_website()
    }
    salida = BytesIO()
    estado = pisa.CreatePDF(render_template('pdf_cuenta_cobro.html', **pdf_data), dest=salida,
                            link_callback=pdf_link_callback)
    return None if estado.err else salida.getvalue()


def pdf_cuenta_desde_bd(cuenta_id):
    """El PDF de una cuenta de cobro de ESTA tienda, armado con lo guardado en su
    base. None si no existe."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM cuentas_cobro WHERE id = %s", (cuenta_id,))
        cuenta = cur.fetchone()
        if not cuenta:
            return None
        cur.execute("SELECT * FROM detalle_cuenta_cobro WHERE cuenta_id = %s ORDER BY id", (cuenta_id,))
        detalles = cur.fetchall()
    fecha_str = str(cuenta.get('fecha') or '')[:10]
    items = [{'fecha': str(d.get('fecha_labor') or fecha_str)[:10], 'descripcion': d['descripcion'],
              'valor': float(d['valor'] or 0), 'valor_formatted': formatear_moneda(float(d['valor'] or 0))}
             for d in detalles]
    return _pdf_cuenta(
        cuenta_id, fecha_str,
        {'nombre': cuenta.get('cliente_nombre') or '', 'nit': cuenta.get('cliente_nit') or '',
         'direccion': cuenta.get('cliente_direccion') or '', 'ciudad': cuenta.get('cliente_ciudad') or ''},
        {'nombre': cuenta.get('contractor_nombre') or '', 'id': cuenta.get('contractor_id') or '',
         'texto_pago': cuenta.get('texto_pago') or '', 'email': cuenta.get('contractor_email') or '',
         'telefono': cuenta.get('contractor_telefono') or ''},
        items, float(cuenta.get('total') or 0))


@billing_bp.route('/admin/cuenta_cobro/<int:id>/pdf')
@rol_requerido(ADMIN_CONTADOR)
def pdf_cuenta(id):
    """El PDF de la cuenta de cobro, con la sesión de la tienda (ya no es un archivo público)."""
    from services import documentos_privados as docs
    contenido = docs.pdf_de('cuenta_cobro', id)
    if not contenido:
        flash("No se pudo abrir el PDF de esa cuenta de cobro.", "danger")
        return redirect(url_for('billing.listar_cuentas'))
    return docs.respuesta_pdf(contenido, docs.nombre_archivo('cuenta_cobro', id))


@billing_bp.route('/admin/cuenta_cobro/eliminar/<int:id>', methods=['POST'])
@permiso_requerido('billing', 'eliminar')
@rol_requerido(ADMIN_CONTADOR)
def eliminar_cuenta(id):
    """Elimina una cuenta de cobro. No toca archivos: el PDF ya no se guarda, y el
    viejo de static/ era compartido (borrarlo se llevaba el de otra tienda)."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("DELETE FROM cuentas_cobro WHERE id=%s", (id,))

        flash("Cuenta de cobro eliminada correctamente.", "success")
    except Exception as e:
        app.logger.error(f"Error eliminando cuenta {id}: {e}")
        flash(f"Error al eliminar: Revisa el log para más detalles.", "danger")
        
    return redirect(url_for('billing.listar_cuentas'))


@billing_bp.route('/admin/cuenta_cobro/<int:id>/facturar', methods=['POST'])
@rol_requerido(ADMIN_CONTADOR)
def facturar_cuenta_cobro(id):
    """Emite factura electrónica para una cuenta de cobro (acción manual)."""
    from routes.factura_electronica import (emitir_factura_cuenta_cobro,
                                            facturacion_habilitada)
    if not facturacion_habilitada():
        return jsonify({'success': False,
                        'error': 'Módulo de facturación electrónica no contratado'}), 403
    try:
        with get_db_cursor() as cur:
            cur.execute("UPDATE cuentas_cobro SET facturar_electronicamente = TRUE "
                        "WHERE id = %s", (id,))
    except Exception:
        pass   # columna no existe → idempotencia igual por factura_dian_id
    resultado = emitir_factura_cuenta_cobro(id)
    if 'error' in resultado:
        return jsonify({'success': False, 'error': resultado['error']}), 500
    return jsonify({'success': True, 'factura_id': resultado.get('id'),
                    'estado': resultado.get('estado')})


@billing_bp.route('/admin/mis_cuentas_cobro')
@rol_requerido(ADMIN_CONTADOR)
def listar_cuentas():
    """Lista el historial de cuentas de cobro generadas."""
    from services.cartera_service import soporta_cartera, resumen_cartera, sql_filtro, FILTROS
    datosApp = get_data_app()
    cuentas = []
    cartera_ok = False
    filtro = request.args.get('pago') if request.args.get('pago') in FILTROS else None
    from routes.factura_electronica import sql_columnas_fe
    try:
        # Igual con las de facturación electrónica: en bases sin ellas, pedirlas a
        # secas dejaba la lista entera vacía.
        columnas_fe = sql_columnas_fe('cuentas_cobro')
        with get_db_cursor(dict_cursor=True) as cur:
            # Los clientes que aún no han actualizado no tienen las columnas de
            # cobro: se consultan solo si existen, y la lista sale igual que antes.
            cartera_ok = soporta_cartera(cur, 'cuentas_cobro')
            extra = (", estado_pago, fecha_pago, nota_pago, "
                     "COALESCE(fecha_vencimiento, (fecha + INTERVAL '30 days'))::date AS vence"
                     if cartera_ok else
                     ", NULL AS estado_pago, NULL AS fecha_pago, NULL AS nota_pago, NULL AS vence")
            donde = f"WHERE {sql_filtro(filtro)}" if (cartera_ok and filtro) else ""
            cur.execute(f"""
                SELECT id, consecutivo, fecha, cliente_nombre, cliente_telefono, total, pdf_path,
                       {columnas_fe}{extra}
                FROM cuentas_cobro {donde} ORDER BY fecha DESC, id DESC
            """)
            cuentas = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error listando cuentas: {e}")

    # «PDF» con sesión + enlace privado (30 días) para WhatsApp o copiar.
    from services import documentos_privados as docs
    cuentas = docs.preparar_filas('cuenta_cobro', cuentas, lambda fila, enlace: (
        f"Hola{' ' + fila['cliente_nombre'].strip() if (fila.get('cliente_nombre') or '').strip() else ''}, "
        f"te compartimos la cuenta de cobro {fila.get('consecutivo') or fila['id']}. "
        f"Puedes verla aquí: {enlace}"))

    try:
        from routes.factura_electronica import facturacion_habilitada
        fe_habilitada = facturacion_habilitada()
    except Exception:
        fe_habilitada = False

    return render_template('mis_cuentas_cobro.html', datosApp=datosApp,
                           cuentas=cuentas, fe_habilitada=fe_habilitada,
                           cartera_ok=cartera_ok, cartera=resumen_cartera() if cartera_ok else None,
                           filtro_pago=filtro, puede_cobrar=_puede_cobrar(),
                           hoy=date.today())


# ── Cartera: qué está aprobado y todavía no lo han pagado ──────
# Las tres rutas viven en este blueprint (módulo 'billing' = dueño y contador)
# y no en el de cotizaciones, cuyo permiso 'ver' por defecto NO incluye al
# contador: si la de cotizaciones estuviera allá, él no podría marcar cobros.
#
# Se protegen con @permiso_requerido (matriz del negocio) en vez de un rol fijo:
# por defecto da dueño + contador, y si un negocio quiere delegar el cobro a
# alguien más lo habilita desde su pantalla de Roles y Permisos, sin tocar código.

def _puede_cobrar():
    """¿Este usuario puede marcar pagos? (matriz del negocio, módulo cobros)."""
    try:
        from services.permisos_service import tiene_permiso
        return tiene_permiso(session.get('rol_id'), 'billing', 'operar')
    except Exception:
        return False


@billing_bp.route('/admin/cuenta_cobro/cartera')
@permiso_requerido('billing', 'ver')
def cartera():
    """Cotizaciones aprobadas y cuentas de cobro con su estado de cobro."""
    from services.cartera_service import documentos_cartera, resumen_cartera, FILTROS
    datosApp = get_data_app()
    filtro = request.args.get('pago') if request.args.get('pago') in FILTROS else None
    return render_template('cartera.html', datosApp=datosApp,
                           documentos=documentos_cartera(filtro),
                           cartera=resumen_cartera(), filtro_pago=filtro,
                           puede_cobrar=_puede_cobrar())


def _marcar_y_volver(tipo, doc_id, destino):
    from services.cartera_service import marcar_pago
    ok, msg = marcar_pago(tipo, doc_id,
                          request.form.get('estado'),
                          nota=request.form.get('nota'))
    flash(msg, 'success' if ok else 'warning')
    volver = request.form.get('volver') or ''
    if volver.startswith('/admin/'):
        return redirect(volver)
    return redirect(url_for(destino))


@billing_bp.route('/admin/cuenta_cobro/cartera/cuenta/<int:id>/pago', methods=['POST'])
@permiso_requerido('billing', 'operar')
def marcar_pago_cuenta(id):
    """Marca una cuenta de cobro como pendiente de pago o pagada."""
    return _marcar_y_volver('cuenta_cobro', id, 'billing.listar_cuentas')


@billing_bp.route('/admin/cuenta_cobro/cartera/cotizacion/<int:id>/pago', methods=['POST'])
@permiso_requerido('billing', 'operar')
def marcar_pago_cotizacion(id):
    """Marca una cotización aprobada como pendiente de pago o pagada."""
    return _marcar_y_volver('cotizacion', id, 'billing.cartera')
