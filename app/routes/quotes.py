"""
routes/quotes.py — Modulo de cotizaciones PDF.

Permite generar cotizaciones personalizadas con logo,
items de inventario o personalizados, y exportar a PDF.
"""

import os
from datetime import datetime
from flask import Blueprint, render_template, request, Response, session, current_app as app, send_file, url_for, flash, redirect, jsonify
from werkzeug.utils import secure_filename
from xhtml2pdf import pisa
from io import BytesIO

from database import get_db_cursor
from helpers import get_data_app, formatear_moneda, pdf_link_callback, logo_local_path as resolve_logo_path
from security import permiso_requerido, registrar_guard_permiso, rol_requerido, ADMIN_STAFF, ADMIN_FULL

quotes_bp = Blueprint('quotes', __name__)

# Permisos dinámicos (matriz del Propietario): guard 'ver' de todo el
# blueprint. Convive con los @rol_requerido existentes (defensa doble).
registrar_guard_permiso(quotes_bp, 'quotes')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def _get_brand_colors():
    """Lee colores de marca y datos de empresa desde cliente_config con fallback a Config."""
    from config import Config
    colores = dict(Config.BRAND_COLORS)
    colores['website'] = ''
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
    if not colores['website']:
        colores['website'] = _sitio_de_la_tienda()
    return colores


def _sitio_de_la_tienda():
    """«Visítanos en…» de una tienda que no escribió su sitio web: su propia página
    (la dirección desde donde se hace la cotización). La de CyberShop solo en la
    cotización de CyberShop; '' (la línea no sale) si no se puede saber."""
    try:
        from flask import has_request_context
        from services.public_site_service import get_brand_config, is_public_section_enabled
        propio = ((get_brand_config() or {}).get('empresa_website') or '').strip()
        if propio:
            return propio
        if is_public_section_enabled('mostrar_modulo_software', False):
            return 'https://cybershopcol.com'
        return request.url_root.rstrip('/') if has_request_context() else ''
    except Exception:  # noqa: BLE001
        return ''



def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Notas adicionales (impuestos, condiciones, entrega, garantía…) ──────────
# Van al final del PDF, antes de la firma; vacías no salen. Columna aditiva:
# la misma sentencia de la migración del maestro 0025_cotizaciones_notas.sql.
DDL_NOTAS = "ALTER TABLE cotizaciones ADD COLUMN IF NOT EXISTS notas_adicionales TEXT"
NOTAS_MAX = 6000            # notas organizadas por secciones (con IA llegan a ~4.000)
_BD_CON_NOTAS = set()


def _soporta_notas():
    """True si cotizaciones.notas_adicionales existe (la crea si falta, una vez por
    BD y proceso). Nunca frena la cotización: si no se puede, las notas salen en el
    PDF pero no se guardan, y queda en el log."""
    from database import _current_db_name
    bd = _current_db_name()
    if bd in _BD_CON_NOTAS:
        return True
    try:
        with get_db_cursor() as cur:
            cur.execute("""SELECT 1 FROM information_schema.columns
                           WHERE table_schema = current_schema() AND table_name = 'cotizaciones'
                             AND column_name = 'notas_adicionales'""")
            if not cur.fetchone():
                cur.execute(DDL_NOTAS)
        _BD_CON_NOTAS.add(bd)
        return True
    except Exception as exc:  # noqa: BLE001
        app.logger.warning(f"Cotizaciones: no se pudo preparar notas_adicionales ({exc})")
        return False


def _limpiar_notas(texto):
    """Las notas como las escribió la persona, sin espacios sobrantes ni más de una
    línea en blanco seguida, y con un máximo de NOTAS_MAX caracteres."""
    limpio, vacias = [], 0
    for linea in str(texto or '').splitlines():
        linea = linea.rstrip()
        vacias = vacias + 1 if not linea else 0
        if vacias <= 1:
            limpio.append(linea)
    return '\n'.join(limpio).strip()[:NOTAS_MAX].strip()


def _bloques_notas(notas):
    from services.notas_cotizacion import bloques
    return bloques(notas)


def _firma_empresa():
    """Nombre del negocio bajo la firma del PDF. Nunca «CyberShop» (el valor por
    defecto) en la cotización de un cliente: entonces la firma va sin nombre."""
    try:
        from services.public_site_service import (PUBLIC_FIELD_BY_KEY, get_brand_config,
                                                  is_public_section_enabled)
        nombre = ((get_brand_config() or {}).get('empresa_nombre') or '').strip()
        de_cybershop = nombre == PUBLIC_FIELD_BY_KEY['empresa_nombre']['default']
        if de_cybershop and not is_public_section_enabled('mostrar_modulo_software', False):
            return ''
        return nombre
    except Exception:  # noqa: BLE001
        return ''


@quotes_bp.route('/admin/cotizar')
@rol_requerido(ADMIN_STAFF)
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

    # Cotización de una orden de Servicio Técnico: cliente y concepto ya llenos.
    st_orden, detalles = _orden_servicio_para_cotizar(request.args.get('st_orden'))

    return render_template('cotizar.html', datosApp=datosApp, productos=productos,
                           cotizacion=None, detalles=detalles, st_orden=st_orden)


def _orden_servicio_para_cotizar(orden_id):
    """(orden, detalles) si llega una orden válida del módulo Servicio Técnico
    activo; si no, (None, []) y la cotización queda como siempre."""
    if not orden_id or not str(orden_id).isdigit():
        return None, []
    try:
        from tenant_features import MODULE_SERVICIO_TECNICO, is_module_active
        if not is_module_active(MODULE_SERVICIO_TECNICO):
            return None, []
        from services import servicio_tecnico_service as st
        orden = st.obtener_orden(int(orden_id))
        if not orden:
            return None, []
        equipo = st.descripcion_equipo(orden)
        detalle = {
            'descripcion': f"Servicio técnico {orden['numero']}: {equipo}"[:250],
            'cantidad': 1,
            'precio_unitario': int(orden['valor_estimado'] or 0),
            'descuento_porc': 0, 'iva_porc': 0, 'imagen_url': '',
        }
        return orden, [detalle]
    except Exception as exc:  # noqa: BLE001
        app.logger.warning(f"Cotizar desde orden de servicio: {exc}")
        return None, []


@quotes_bp.route('/admin/cotizar/sugerir-notas', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def sugerir_notas():
    """Notas adicionales sugeridas por la IA a partir de lo que se cotiza (1.9.13.0).
    Solo con el módulo Asistente IA activo. Devuelve secciones para que la persona
    escoja cuáles agregar; nada se guarda aquí."""
    from tenant_features import MODULE_AI, is_module_active
    if not is_module_active(MODULE_AI):
        return jsonify({'ok': False, 'error': 'El módulo Asistente IA no está activo en tu plan.'}), 403
    from security import controlar_tasa_solicitudes
    if not controlar_tasa_solicitudes(f"cot-notas:{session.get('usuario_id') or request.remote_addr}",
                                      max_requests=12, interval=600):
        return jsonify({'ok': False, 'error': 'Pediste muchas sugerencias seguidas. Espera unos minutos.'}), 429
    datos = request.get_json(silent=True) or {}
    items = []
    for item in (datos.get('items') or [])[:40]:
        if isinstance(item, dict):
            items.append({'descripcion': str(item.get('descripcion') or '')[:200],
                          'cantidad': item.get('cantidad'), 'iva': item.get('iva')})
    cliente = datos.get('cliente') if isinstance(datos.get('cliente'), dict) else {}
    cliente = {k: str(cliente.get(k) or '')[:120] for k in ('nombre', 'documento', 'ciudad')}
    # Sugerencias que ya se le mostraron en esta pantalla: no se repiten.
    vistas = datos.get('ya_vistas') if isinstance(datos.get('ya_vistas'), list) else []
    ya_vistas = [v[:300] for v in vistas[-80:] if isinstance(v, str) and v.strip()]
    from services import ia_notas_cotizacion
    try:
        resultado = ia_notas_cotizacion.sugerir(items, cliente, str(datos.get('indicaciones') or '')[:500],
                                                str(datos.get('notas_actuales') or '')[:NOTAS_MAX], ya_vistas)
    except Exception as exc:  # noqa: BLE001
        app.logger.error(f"Sugerir notas de cotización: {exc}")
        return jsonify({'ok': False, 'error': 'No se pudieron preparar las sugerencias. Intenta de nuevo.'}), 500
    from services.notas_cotizacion import SECCIONES
    return jsonify({'ok': True, 'orden': list(SECCIONES), **resultado})


@quotes_bp.route('/admin/cotizar/ia/generar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def generar_con_ia():
    """Cotización armada por la IA con lo que mandó el cliente (capturas, PDF, conversación)
    (1.9.14.0). Solo con el módulo Asistente IA. Arranca el análisis en segundo plano (tarda
    minutos y gunicorn corta a los 120 s) y devuelve el trabajo; la pantalla pregunta el
    avance en /estado. Al final, la propuesta para llenar el formulario. Nada se guarda."""
    from tenant_features import MODULE_AI, is_module_active
    if not is_module_active(MODULE_AI):
        return jsonify({'ok': False, 'error': 'El módulo Asistente IA no está activo en tu plan.'}), 403
    from security import controlar_tasa_solicitudes
    if not controlar_tasa_solicitudes(f"cot-ia:{session.get('usuario_id') or request.remote_addr}",
                                      max_requests=6, interval=1800):
        return jsonify({'ok': False, 'error': 'Ya pediste varias cotizaciones con IA seguidas. Espera unos minutos.'}), 429
    from services import ia_cotizacion_auto as auto
    try:
        entrada = auto.leer_entrada(request.get_json(silent=True))
    except auto.EntradaInvalida as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    trabajo = auto.iniciar_trabajo(entrada, session.get('usuario_id'))
    return jsonify({'ok': True, 'trabajo': trabajo}), 202


@quotes_bp.route('/admin/cotizar/ia/estado/<trabajo>')
@rol_requerido(ADMIN_STAFF)
def estado_con_ia(trabajo):
    """Avance del análisis: los eventos nuevos desde `desde` (plan, pasos, resultado)."""
    from services import ia_cotizacion_auto as auto
    estado = auto.leer_trabajo(trabajo, session.get('usuario_id'), request.args.get('desde', 0, type=int))
    if estado is None:
        return jsonify({'ok': False, 'error': 'Ese análisis ya no está disponible. Empieza de nuevo.'}), 404
    respuesta = jsonify({'ok': True, **estado})
    respuesta.headers['Cache-Control'] = 'no-store'
    return respuesta


@quotes_bp.route('/admin/cotizar/ia/cancelar/<trabajo>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def cancelar_con_ia(trabajo):
    """Detiene el análisis (libera el equipo de IA para los demás)."""
    from services import ia_cotizacion_auto as auto
    if not auto.cancelar_trabajo(trabajo, session.get('usuario_id')):
        return jsonify({'ok': False}), 404
    return jsonify({'ok': True})


@quotes_bp.route('/admin/cotizar/generar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
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
        notas_adicionales   = _limpiar_notas(request.form.get('notas_adicionales'))
        con_notas           = _soporta_notas()

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
            logo_local_path = resolve_logo_path(app.root_path)
        # Normalizar: xhtml2pdf necesita path puro, sin file://
        if logo_local_path.startswith('file://'):
            logo_local_path = logo_local_path[7:]

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
                if con_notas:
                    cur.execute("UPDATE cotizaciones SET notas_adicionales=%s WHERE id=%s",
                                (notas_adicionales or None, cotizacion_id_edit))
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
                if con_notas and notas_adicionales:
                    cur.execute("UPDATE cotizaciones SET notas_adicionales=%s WHERE id=%s",
                                (notas_adicionales, cotizacion_id))

            for i in range(len(descripciones)):
                cantidad        = int(cantidades[i]) if i < len(cantidades) and cantidades[i] else 1
                descripcion     = descripciones[i]
                precio_unitario = float(precios[i]) if i < len(precios) and precios[i] else 0
                # SECURITY A4: Limitar descuento al rango válido [0, 100]
                descuento_porc  = max(0.0, min(100.0, float(descuentos[i]) if i < len(descuentos) and descuentos[i] else 0))
                iva_porc        = max(0.0, float(ivas[i]) if i < len(ivas) and ivas[i] else 0)

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

        # F1.3 + F2.3 — asociar cotización a contacto CRM y sincronizar oportunidad
        try:
            from services.crm_service import upsert_contacto, sync_oportunidad_cotizacion
            crm_id = upsert_contacto(
                nombre=cliente_nombre,
                telefono=cliente_telefono,
                ciudad=cliente_ciudad,
                direccion=cliente_direccion,
                tipo='cliente',
                origen='cotizacion',
                tags_add=['cotizado'],
            )
            if crm_id:
                with get_db_cursor() as _cur:
                    _cur.execute(
                        "UPDATE cotizaciones SET crm_contacto_id = %s WHERE id = %s",
                        (crm_id, cotizacion_id),
                    )
                sync_oportunidad_cotizacion(
                    cotizacion_id=cotizacion_id,
                    titulo=f"Cotización COT {str(cotizacion_id).zfill(10)} — {cliente_nombre}",
                    monto=total_cotizacion,
                    contacto_id=crm_id,
                    etapa='propuesta',
                    usuario_id=session.get('usuario_id'),
                )
        except Exception as _ce:
            app.logger.warning(f"CRM sync cotización: {_ce}")

        # Servicio Técnico: la cotización nueva queda enlazada a su orden.
        st_orden_id = request.form.get('st_orden_id')
        if st_orden_id and st_orden_id.isdigit() and not cotizacion_id_edit:
            try:
                from services import servicio_tecnico_service as st
                orden = st.obtener_orden(int(st_orden_id))
                if orden:
                    with get_db_cursor() as _cur:
                        _cur.execute("UPDATE cotizaciones SET crm_contacto_id = %s WHERE id = %s",
                                     (orden['crm_contacto_id'], cotizacion_id))
                    st.vincular_cotizacion(orden['id'], cotizacion_id, session.get('usuario_id'))
                    from services.servicio_tecnico_seguimiento import correo_estado
                    correo_estado(orden['id'], 'cotizado')
            except Exception as _se:
                app.logger.warning(f"Enlazar cotización a orden de servicio: {_se}")

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
            # Sin descuento no sale el renglón: el cliente no lee «Descuentos $0».
            'mostrar_descuento': round(total_descuentos, 2) > 0,
            'iva':      formatear_moneda(total_iva),
            'notas':    notas_adicionales,   # al final; vacías no salen
            # Organizadas: títulos (MAYÚSCULAS o «:») y viñetas, para que se vean bien.
            'notas_bloques': _bloques_notas(notas_adicionales),
            'firma_empresa': _firma_empresa(),
            'logo':     logo_local_path,   # ruta local, sin peticion HTTP
            'colores':  _get_brand_colors()
        }

        rendered_html = render_template('pdf_quote.html', **datos_pdf)

        pdf_output = BytesIO()
        pisa_status = pisa.CreatePDF(rendered_html, dest=pdf_output,
                                     link_callback=pdf_link_callback)

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
@rol_requerido(ADMIN_STAFF)
def ver_cotizaciones():
    """Lista las cotizaciones generadas."""
    from services.cartera_service import soporta_cartera, sql_filtro, FILTROS
    datosApp = get_data_app()
    cotizaciones = []
    cartera_ok = False
    filtro_pago = request.args.get('pago') if request.args.get('pago') in FILTROS else None
    from routes.factura_electronica import sql_columnas_fe
    try:
        # Igual con las de facturación electrónica: en bases sin ellas, pedirlas a
        # secas dejaba la lista entera vacía.
        columnas_fe = sql_columnas_fe('cotizaciones')
        with get_db_cursor(dict_cursor=True) as cur:
            # Las columnas de cobro solo existen si el cliente ya actualizó:
            # se consultan condicionalmente para no romper a quien no lo ha hecho.
            cartera_ok = soporta_cartera(cur, 'cotizaciones')
            extra = (", estado_pago, fecha_pago, nota_pago"
                     if cartera_ok else
                     ", NULL AS estado_pago, NULL AS fecha_pago, NULL AS nota_pago")
            # Filtrar por cobro solo tiene sentido sobre lo aprobado: una
            # cotización pendiente o rechazada no se le cobra a nadie.
            donde = (f"WHERE COALESCE(estado, 'pendiente') = 'aprobada' AND {sql_filtro(filtro_pago)}"
                     if (cartera_ok and filtro_pago) else "")
            cur.execute(f"""
                SELECT id, fecha, cliente_nombre, cliente_documento, total, pdf_path,
                       COALESCE(estado, 'pendiente') AS estado,
                       {columnas_fe}{extra}
                FROM cotizaciones {donde}
                ORDER BY fecha DESC
            """)
            cotizaciones = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error listando cotizaciones: {e}")

    try:
        from routes.factura_electronica import facturacion_habilitada
        fe_habilitada = facturacion_habilitada()
    except Exception:
        fe_habilitada = False

    # El botón de cobro es del módulo de cuentas de cobro (dueño y contador por
    # defecto). Un empleado ve el estado, pero no lo cambia.
    try:
        from services.permisos_service import tiene_permiso
        puede_cobrar = tiene_permiso(session.get('rol_id'), 'billing', 'operar')
    except Exception:
        puede_cobrar = False

    return render_template('mis_cotizaciones.html', datosApp=datosApp,
                           cotizaciones=cotizaciones, fe_habilitada=fe_habilitada,
                           cartera_ok=cartera_ok, filtro_pago=filtro_pago,
                           puede_cobrar=puede_cobrar,
                           puede_facturar=fe_habilitada and _es_admin_full())


def _es_admin_full():
    """¿Dueño o super admin? (incluye roles personalizados basados en ellos)."""
    rol = session.get('rol_id')
    try:
        from services.permisos_service import rol_base_efectivo
        rol = rol if rol in ADMIN_FULL else rol_base_efectivo(rol)
    except Exception:
        pass
    return rol in ADMIN_FULL


@quotes_bp.route('/admin/cotizar/<int:id>/fe', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def toggle_fe_cotizacion(id):
    """Marca/desmarca una cotización para facturarla electrónicamente al aprobarla."""
    data = request.get_json(silent=True) or request.form
    activar = str(data.get('activar', '')).lower() in ('1', 'true', 'on', 'yes')
    try:
        with get_db_cursor() as cur:
            cur.execute("UPDATE cotizaciones SET facturar_electronicamente = %s WHERE id = %s",
                        (activar, id))
        return jsonify({'success': True, 'facturar': activar})
    except Exception as e:
        app.logger.warning(f"toggle FE cotización {id}: {e}")
        return jsonify({'success': False, 'error': 'No se pudo actualizar'}), 500


@quotes_bp.route('/admin/cotizar/<int:id>/facturar', methods=['POST'])
@permiso_requerido('quotes', 'eliminar')
@rol_requerido(ADMIN_FULL)  # mismo nivel que aprobar: registra un documento tributario
def facturar_cotizacion(id):
    """Factura electrónica de una cotización YA aprobada.

    Antes solo se facturaba si se marcaba «Facturar al aprobar» antes de
    aprobarla; una cotización aprobada sin esa marca no tenía forma de facturarse.
    """
    from routes.factura_electronica import emitir_factura_cotizacion, facturacion_habilitada
    if not facturacion_habilitada():
        return jsonify({'success': False,
                        'error': 'Tu plan no incluye facturación electrónica.'}), 403
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT estado FROM cotizaciones WHERE id = %s", (id,))
        cot = cur.fetchone()
    if not cot:
        return jsonify({'success': False, 'error': 'La cotización no existe.'}), 404
    if cot['estado'] != 'aprobada':
        return jsonify({'success': False,
                        'error': 'Solo se facturan cotizaciones aprobadas.'}), 400
    try:
        with get_db_cursor() as cur:
            cur.execute("UPDATE cotizaciones SET facturar_electronicamente = TRUE WHERE id = %s", (id,))
    except Exception:
        pass   # columna no existe → la idempotencia sigue por factura_dian_id
    resultado = emitir_factura_cotizacion(id)
    if resultado.get('error'):
        return jsonify({'success': False, 'error': resultado['error']}), 502
    return jsonify({'success': True, 'factura_id': resultado.get('id'),
                    'estado': resultado.get('estado')})


@quotes_bp.route('/admin/cotizar/editar/<int:id>')
@rol_requerido(ADMIN_STAFF)
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


def _aprobar_cotizacion_core(id):
    """Aprueba una cotización y la registra en contabilidad. Sin flash/redirect.

    Devuelve (ok: bool, msg: str). Reutilizable por la acción individual y la
    acción en bloque. La lógica es idéntica a la del flujo individual previo.
    """
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT id, cliente_nombre, total, estado FROM cotizaciones WHERE id=%s", (id,))
            cot = cur.fetchone()

        if not cot:
            return False, f"COT {str(id).zfill(10)}: no encontrada."

        if cot['estado'] == 'aprobada':
            return False, f"COT {str(id).zfill(10)}: ya estaba aprobada."

        with get_db_cursor() as cur:
            cur.execute("UPDATE cotizaciones SET estado='aprobada' WHERE id=%s", (id,))

        # Cartera: al aprobar queda "pendiente de pago" hasta que alguien
        # registre el cobro. No toca contabilidad ni la aprobación en sí.
        from services.cartera_service import marcar_pendiente_si_falta
        marcar_pendiente_si_falta('cotizacion', id)

        # Servicio Técnico: su orden pasa a «aprobado» (nunca frena la aprobación).
        from services.servicio_tecnico_service import al_aprobar_cotizacion
        al_aprobar_cotizacion(id, session.get('usuario_id'))

        # Registrar ingreso en contabilidad (upsert — no duplica si se re-aprueba)
        from routes.contabilidad import sincronizar_movimiento_referencia
        sincronizar_movimiento_referencia(
            tipo='ingreso',
            categoria='cuenta_cobro',
            descripcion=f"Cotización aprobada COT {str(id).zfill(10)} — {cot['cliente_nombre']}",
            monto=float(cot['total'] or 0),
            referencia_tipo='cotizacion',
            referencia_id=id,
            usuario_id=session.get('usuario_id'),
            auto_generado=False,
        )

        # F2.3 — mover oportunidad a ganada
        try:
            from services.crm_service import sync_oportunidad_cotizacion
            sync_oportunidad_cotizacion(
                cotizacion_id=id,
                etapa='ganada',
                monto=float(cot['total'] or 0),
            )
        except Exception as _oe:
            app.logger.warning(f"Sync oportunidad ganada: {_oe}")

        # Facturación electrónica (opcional — no frena la aprobación)
        try:
            from routes.factura_electronica import (emitir_factura_cotizacion,
                                                    facturacion_habilitada)
            if facturacion_habilitada():
                quiere = False
                try:
                    with get_db_cursor(dict_cursor=True) as cur:
                        cur.execute("SELECT COALESCE(facturar_electronicamente, FALSE) AS f "
                                    "FROM cotizaciones WHERE id=%s", (id,))
                        r = cur.fetchone()
                        quiere = bool(r and r['f'])
                except Exception:
                    quiere = False   # columna no existe → no factura
                if quiere:
                    emitir_factura_cotizacion(id)
        except Exception as _fe:
            app.logger.warning(f"FE cotización {id}: {_fe}")

        return True, f"COT {str(id).zfill(10)} aprobada y registrada en contabilidad."
    except Exception as e:
        app.logger.error(f"Error aprobando cotización {id}: {e}")
        return False, f"COT {str(id).zfill(10)}: error al aprobar (revisa el log)."


def _rechazar_cotizacion_core(id, motivo=None):
    """Marca una cotización como rechazada. Sin flash/redirect. Devuelve (ok, msg)."""
    try:
        with get_db_cursor() as cur:
            cur.execute("UPDATE cotizaciones SET estado='rechazada' WHERE id=%s", (id,))
        # F2.3 — mover oportunidad a perdida
        try:
            from services.crm_service import sync_oportunidad_cotizacion
            sync_oportunidad_cotizacion(
                cotizacion_id=id, etapa='perdida',
                motivo_perdida=motivo or 'Cotización rechazada',
            )
        except Exception as _oe:
            app.logger.warning(f"Sync oportunidad perdida: {_oe}")
        return True, f"COT {str(id).zfill(10)} marcada como rechazada."
    except Exception as e:
        app.logger.error(f"Error rechazando cotización {id}: {e}")
        return False, f"COT {str(id).zfill(10)}: error al rechazar (revisa el log)."


@quotes_bp.route('/admin/cotizar/aprobar/<int:id>', methods=['POST'])
@permiso_requerido('quotes', 'eliminar')
@rol_requerido(ADMIN_FULL)  # SECURITY A2: solo Admin/Propietario puede registrar ingresos
def aprobar_cotizacion(id):
    """Marca la cotización como aprobada y la registra en contabilidad."""
    ok, msg = _aprobar_cotizacion_core(id)
    flash(msg, "success" if ok else ("info" if "ya estaba" in msg else "warning"))
    return redirect(url_for('quotes.ver_cotizaciones'))


@quotes_bp.route('/admin/cotizar/rechazar/<int:id>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def rechazar_cotizacion(id):
    """Marca la cotización como rechazada."""
    motivo = request.form.get('motivo', '').strip()[:160] or None
    ok, msg = _rechazar_cotizacion_core(id, motivo)
    flash(msg, "warning" if ok else "danger")
    return redirect(url_for('quotes.ver_cotizaciones'))


@quotes_bp.route('/admin/cotizar/bulk_accion', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def bulk_accion():
    """Aprueba o rechaza varias cotizaciones a la vez.

    Recibe `ids` (lista) y `accion` ('aprobar'|'rechazar'). Aprobar exige
    ADMIN_FULL (igual que la acción individual, porque registra ingresos).
    """
    accion = (request.form.get('accion') or '').strip().lower()
    raw_ids = request.form.getlist('ids')

    if accion not in ('aprobar', 'rechazar'):
        flash("Acción no válida.", "danger")
        return redirect(url_for('quotes.ver_cotizaciones'))

    # Gating de permiso: aprobar en bloque = mismo nivel que aprobar individual.
    if accion == 'aprobar' and session.get('rol_id') not in ADMIN_FULL:
        flash("No tienes permiso para aprobar cotizaciones.", "danger")
        return redirect(url_for('quotes.ver_cotizaciones'))

    # Normalizar ids a enteros únicos.
    ids = []
    for r in raw_ids:
        try:
            n = int(r)
        except (TypeError, ValueError):
            continue
        if n not in ids:
            ids.append(n)

    if not ids:
        flash("No seleccionaste ninguna cotización.", "warning")
        return redirect(url_for('quotes.ver_cotizaciones'))

    ok_count, fail_count, fail_msgs = 0, 0, []
    for cid in ids:
        if accion == 'aprobar':
            ok, msg = _aprobar_cotizacion_core(cid)
        else:
            ok, msg = _rechazar_cotizacion_core(cid)
        if ok:
            ok_count += 1
        else:
            fail_count += 1
            fail_msgs.append(msg)

    verbo = "aprobada(s)" if accion == 'aprobar' else "rechazada(s)"
    if ok_count:
        flash(f"{ok_count} cotización(es) {verbo}." +
              (f" {fail_count} omitida(s)." if fail_count else ""),
              "success" if accion == 'aprobar' else "warning")
    if fail_count and not ok_count:
        flash(f"No se procesó ninguna. {'; '.join(fail_msgs[:5])}", "danger")
    elif fail_count:
        # Detalle breve de las omitidas (sin saturar).
        flash("Omitidas: " + "; ".join(fail_msgs[:5]) +
              ("…" if len(fail_msgs) > 5 else ""), "info")

    return redirect(url_for('quotes.ver_cotizaciones'))


@quotes_bp.route('/admin/cotizar/eliminar/<int:id>', methods=['POST'])
@permiso_requerido('quotes', 'eliminar')
@rol_requerido(ADMIN_STAFF)
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
            base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
            full_path = os.path.normpath(os.path.join(base_dir, pdf_path.replace('/', os.sep)))
            if full_path.startswith(os.path.normpath(base_dir)) and os.path.exists(full_path):
                os.remove(full_path)

        flash("Cotización eliminada correctamente.", "success")
    except Exception as e:
        app.logger.error(f"Error eliminando cotización {id}: {e}")
        flash(f"Error al eliminar: Revisa el log para más detalles.", "danger")

    return redirect(url_for('quotes.ver_cotizaciones'))
