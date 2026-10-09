"""
routes/servicio_tecnico.py — Módulo «Servicio Técnico».

Equipos de los clientes (computadores, celulares, tablets, televisores, UPS…),
órdenes de servicio de la recepción a la entrega, garantía y bitácora. La
lógica vive en services/servicio_tecnico_service.py; aquí solo HTTP.

  /admin/servicio-tecnico/...   panel (módulo activo + permiso 'servicio_tecnico')
                                («Traer desde Excel o PDF»: /equipos/importar e /importacion/<id>)
  /servicio/<token>             estado de la orden para el cliente (sin sesión,
                                sin datos sensibles, con límite de peticiones)
"""

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)

from extensions import limiter
from helpers import get_common_data, get_data_app
from security import ADMIN_STAFF, permiso_requerido, registrar_guard_permiso, rol_requerido
from services import servicio_tecnico_clasificador as clasif
from services import servicio_tecnico_empresas as emp
from services import servicio_tecnico_ficha as ficha_st
from services import servicio_tecnico_ia as st_ia
from services import servicio_tecnico_importar as imp
from services import servicio_tecnico_mensajes as msj
from services import servicio_tecnico_seguimiento as seg
from services import servicio_tecnico_service as st
from services import servicio_tecnico_tipos as tipos
from tenant_features import MODULE_CRM, MODULE_SERVICIO_TECNICO, is_module_active, module_required

servicio_tecnico_bp = Blueprint('servicio_tecnico', __name__)

PREFIJO = '/admin/servicio-tecnico'

# Permiso 'ver' para todo el panel; la página pública por token queda fuera.
registrar_guard_permiso(servicio_tecnico_bp, 'servicio_tecnico', solo_prefijos=(PREFIJO,))


@servicio_tecnico_bp.before_request
def _tablas():
    if request.path.startswith(PREFIJO) or request.path.startswith('/servicio/'):
        if is_module_active(MODULE_SERVICIO_TECNICO) and not st.asegurar_tablas():
            if request.path.startswith(PREFIJO):
                flash('El módulo de Servicio Técnico está pendiente de actualizar en esta tienda.', 'warning')
                return redirect(url_for('admin.dashboard_admin'))
            abort(404)
        if request.path.startswith(PREFIJO) and is_module_active(MODULE_SERVICIO_TECNICO):
            seg.recordar_url_base()
    return None


def _usuario():
    return session.get('usuario_id')


def _ctx(**extra):
    try:
        pendientes = seg.contar_pendientes_cache()
    except Exception:  # noqa: BLE001
        pendientes = 0
    base = dict(datosApp=get_data_app(), estados=st.ESTADOS, estado_info=st.ESTADO_POR_CODIGO,
                pasos=st.PASOS, tipos_lista=tipos.TIPOS, tipo_nombre=tipos.nombre, marca_modelo=st.marca_modelo,
                tipo_icono=tipos.icono, etiquetas=tipos.ETIQUETAS_COMUNES, st_pendientes=pendientes)
    base.update(extra)
    return base


def _form_dict():
    return {k: v for k, v in request.form.items()}


# ── Órdenes ─────────────────────────────────────────────────────
@servicio_tecnico_bp.route(PREFIJO + '/')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def ordenes():
    estado = request.args.get('estado', '')
    q = request.args.get('q', '')
    tecnico = request.args.get('tecnico', type=int)
    abiertas = estado == '' and not q
    lista = st.listar_ordenes(estado=estado, q=q, tecnico_id=tecnico, abiertas=abiertas)
    return render_template('servicio_tecnico/ordenes.html', **_ctx(
        ordenes=lista, filtro_estado=estado, q=q, filtro_tecnico=tecnico,
        conteo=st.resumen_estados(), tecnicos=st.tecnicos(), solo_abiertas=abiertas,
        st_activo='ordenes'))


@servicio_tecnico_bp.route(PREFIJO + '/nueva', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def nueva_orden():
    if request.method == 'POST':
        f = request.form
        datos = {
            'crm_contacto_id': f.get('crm_contacto_id', type=int),
            'cliente': {k: f.get('cliente_' + k) for k in ('nombre', 'telefono', 'whatsapp', 'email',
                                                           'direccion', 'ciudad')},
            'equipo_id': f.get('equipo_id', type=int),
            'equipo': {**{k[7:]: v for k, v in f.items() if k.startswith('equipo_') and k != 'equipo_id'},
                       'tipo': f.get('equipo_tipo')},
            'falla_reportada': f.get('falla_reportada'),
            'estado_fisico': f.get('estado_fisico'),
            'accesorios': ', '.join(f.getlist('accesorios')) + (
                (', ' if f.getlist('accesorios') and f.get('accesorios_otros') else '') + (f.get('accesorios_otros') or '')),
            'clave': f.get('clave'),
            'tecnico_id': f.get('tecnico_id', type=int),
            'valor_estimado': f.get('valor_estimado'),
            'fecha_promesa': f.get('fecha_promesa'),
            'garantia_dias': f.get('garantia_dias'),
        }
        try:
            orden_id = st.crear_orden(datos, _usuario())
        except st.ErrorServicio as exc:
            flash(str(exc), 'warning')
            cid = f.get('crm_contacto_id', type=int)
            return render_template('servicio_tecnico/nueva.html', **_ctx(
                previo=f, tipos_json=tipos.para_plantilla(), tecnicos=st.tecnicos(),
                cliente_inicial=st.obtener_cliente(cid) if cid else None,
                st_activo='nueva')), 400
        orden = st.obtener_orden(orden_id)
        aviso = ' Le enviamos un correo con el enlace de estado.' if seg.correo_estado(orden_id, 'recibido') else ''
        flash(f"Orden {orden['numero']} creada. Imprime el comprobante para el cliente.{aviso}", 'success')
        return redirect(url_for('servicio_tecnico.orden_ver', orden_id=orden_id))
    return render_template('servicio_tecnico/nueva.html', **_ctx(
        previo={}, tipos_json=tipos.para_plantilla(), tecnicos=st.tecnicos(),
        cliente_inicial=st.obtener_cliente(request.args.get('cliente', type=int))
        if request.args.get('cliente', type=int) else None,
        st_activo='nueva'))


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def orden_ver(orden_id):
    orden = st.obtener_orden(orden_id)
    if not orden:
        abort(404)
    return render_template('servicio_tecnico/orden.html', **_ctx(
        orden=orden, eventos=st.eventos(orden_id=orden_id),
        siguientes=st.TRANSICIONES.get(orden['estado'], ()),
        tecnicos=st.tecnicos(), tiene_clave=bool(orden.get('clave_cifrada')),
        enlace_publico=url_for('servicio_tecnico.publico', token=orden['token_publico'], _external=True),
        aviso=seg.aviso_estado(orden), seguimientos=seg.de_orden(orden_id), ia_estado=st_ia.estado(),
        fallas=clasif.FALLAS, componentes=clasif.COMPONENTES, soluciones=clasif.SOLUCIONES,
        nombre_falla=clasif.NOMBRE_FALLA, nombre_componente=clasif.NOMBRE_COMPONENTE,
        nombre_solucion=clasif.NOMBRE_SOLUCION,
        calificacion=seg.encuesta_respondida(orden_id),
        st_activo='ordenes'))


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/estado', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_estado(orden_id):
    nuevo = request.form.get('estado', '')
    try:
        st.cambiar_estado(orden_id, nuevo, _usuario(), nota=request.form.get('nota'),
                          datos=_form_dict())
        aviso = ' Se le envió un correo al cliente.' if seg.correo_estado(orden_id, nuevo) else ''
        if nuevo in ('diagnostico', 'reparacion', 'listo', 'entregado', 'cancelado') or request.form.get('solucion'):
            clasif.clasificar_en_segundo_plano(orden_id)
        flash(f"Estado actualizado: {st.ESTADO_POR_CODIGO[nuevo][1]}.{aviso}", 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.orden_ver', orden_id=orden_id))


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/editar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_actualizar(orden_id):
    permitidos = ('diagnostico', 'solucion', 'estado_fisico', 'accesorios', 'valor_estimado', 'valor_final',
                  'fecha_promesa', 'tecnico_id', 'garantia_dias', 'clave')
    datos = {k: request.form.get(k) for k in permitidos if k in request.form}
    try:
        st.actualizar_orden(orden_id, datos, _usuario())
        if any(k in datos for k in ('diagnostico', 'solucion')):
            clasif.clasificar_en_segundo_plano(orden_id)
        flash('Orden actualizada.', 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.orden_ver', orden_id=orden_id))


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/nota', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_nota(orden_id):
    try:
        st.agregar_nota(orden_id, request.form.get('texto'), _usuario(), tipo=request.form.get('tipo', 'nota'))
        flash('Nota agregada a la bitácora.', 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.orden_ver', orden_id=orden_id) + '#bitacora')


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/clave', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_clave(orden_id):
    clave = st.ver_clave(orden_id, _usuario())
    if clave is None:
        return jsonify({'ok': False, 'error': 'Esta orden no tiene clave guardada o no se pudo leer.'}), 404
    return jsonify({'ok': True, 'clave': clave})


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/imprimir')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def orden_imprimir(orden_id):
    orden = st.obtener_orden(orden_id)
    if not orden:
        abort(404)
    formato = 'tiquete' if request.args.get('formato') == 'tiquete' else 'carta'
    return render_template('servicio_tecnico/imprimir.html', **_ctx(
        orden=orden, formato=formato,
        enlace_publico=url_for('servicio_tecnico.publico', token=orden['token_publico'], _external=True)))


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/cotizar')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_cotizar(orden_id):
    return redirect(url_for('quotes.cotizar', st_orden=orden_id))


# ── Equipos ─────────────────────────────────────────────────────
@servicio_tecnico_bp.route(PREFIJO + '/equipos')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def equipos():
    """Equipos por carpeta: una por empresa y «Particulares» (los de personas)."""
    q = request.args.get('q', '')
    tipo = request.args.get('tipo', '')
    pedida = request.args.get('carpeta', '')
    carpeta, carpeta_actual = None, None
    if pedida == 'particulares':
        carpeta, carpeta_actual = 'particulares', {'id': 'particulares', 'nombre': emp.PARTICULARES}
    elif pedida.isdigit():
        carpeta_actual = emp.obtener(int(pedida))
        carpeta = carpeta_actual['id'] if carpeta_actual else None
    return render_template('servicio_tecnico/equipos.html', **_ctx(
        equipos=st.listar_equipos(q=q, tipo=tipo, carpeta=carpeta), q=q, filtro_tipo=tipo,
        carpetas=emp.listar(), carpeta_actual=carpeta_actual, st_activo='equipos'))


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/carpeta', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_carpeta(equipo_id):
    """Pasa el equipo a la carpeta de una empresa (o a «Particulares»)."""
    eleccion = (request.form.get('carpeta') or '').strip()
    destino = request.form.get('carpeta_nombre', '') if eleccion == 'nueva' else eleccion
    if eleccion == 'nueva' and not (destino or '').strip():
        flash('Escribe el nombre de la empresa nueva.', 'warning')
        return _a_la_ficha(equipo_id, 'carpeta')
    try:
        nombre = st.mover_a_carpeta(equipo_id, destino, _usuario(), por_nombre=eleccion == 'nueva')
        flash(f'El equipo quedó en la carpeta «{nombre}».', 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return _a_la_ficha(equipo_id, 'carpeta')


@servicio_tecnico_bp.route(PREFIJO + '/equipos/nuevo', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_nuevo():
    """Registrar un equipo sin abrir una orden: cliente del CRM, ficha,
    información del sistema, fotos y plan de mantenimiento en una sola página."""
    if request.method == 'POST':
        f = request.form
        datos = {
            'crm_contacto_id': f.get('crm_contacto_id', type=int),
            'cliente': {k: f.get('cliente_' + k) for k in ('nombre', 'telefono', 'whatsapp', 'email',
                                                           'direccion', 'ciudad')},
            'equipo': {**{k[7:]: v for k, v in f.items() if k.startswith('equipo_')},
                       'tipo': f.get('equipo_tipo')},
            'mant_cada_meses': f.get('mant_cada_meses'),
            'mant_proximo': f.get('mant_proximo'),
            'empresa': (f.get('empresa') or '').strip(),
        }
        try:
            equipo_id = st.registrar_equipo(datos, _usuario())
        except st.ErrorServicio as exc:
            flash(str(exc), 'warning')
            cid = f.get('crm_contacto_id', type=int)
            return render_template('servicio_tecnico/equipo_nuevo.html', **_ctx(
                previo=f, tipos_json=tipos.para_plantilla(), momentos=st.MOMENTOS_FOTO,
                cliente_inicial=st.obtener_cliente(cid) if cid else None,
                carpetas=emp.listar(incluir_vacias=True)['empresas'], st_activo='equipo_nuevo')), 400
        guardadas, errores = st.guardar_fotos(equipo_id, request.files.getlist('fotos'), 'recepcion',
                                              usuario_id=_usuario())
        texto = 'Equipo registrado.'
        if guardadas:
            texto += f" Se guardaron {guardadas} foto{'s' if guardadas != 1 else ''}."
        flash(texto, 'success')
        for e in errores[:5]:
            flash(e, 'warning')
        return redirect(url_for('servicio_tecnico.equipo_ver', equipo_id=equipo_id))
    cid = request.args.get('cliente', type=int)
    empresa_inicial = emp.obtener(request.args.get('carpeta', type=int)) if request.args.get('carpeta', type=int) else None
    return render_template('servicio_tecnico/equipo_nuevo.html', **_ctx(
        previo={'empresa': empresa_inicial['nombre']} if empresa_inicial else {}, tipos_json=tipos.para_plantilla(),
        momentos=st.MOMENTOS_FOTO, cliente_inicial=st.obtener_cliente(cid) if cid else None,
        carpetas=emp.listar(incluir_vacias=True)['empresas'], st_activo='equipo_nuevo'))


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def equipo_ver(equipo_id):
    equipo = st.obtener_equipo(equipo_id)
    if not equipo:
        abort(404)
    fotos = st.fotos_de_equipo(equipo_id)
    pendientes, atendidos = seg.de_equipo(equipo_id)
    ordenes_equipo = st.ordenes_de_equipo(equipo_id)
    mantenimientos = st.mantenimientos_de_equipo(equipo_id)
    cambios = st.cambios_de_equipo(equipo_id)
    return render_template('servicio_tecnico/equipo.html', **_ctx(
        hoja_vida=st.hoja_de_vida(mantenimientos, ordenes_equipo, cambios),
        crm_activo=is_module_active(MODULE_CRM),
        equipo=equipo, campos_extra=tipos.campos_extra(equipo['tipo']),
        orden_abierta=st.orden_abierta_de_equipo(equipo_id), ia_estado=st_ia.estado(),
        ia_ok=st_ia.estado()[0],
        columnas=tipos.columnas(equipo['tipo']), cambios=cambios,
        ordenes_equipo=ordenes_equipo, eventos=st.eventos(equipo_id=equipo_id),
        fotos=fotos, momentos=st.MOMENTOS_FOTO, nombre_momento=st.MOMENTO_FOTO, fotos_max=st.FOTOS_MAX,
        mantenimientos=mantenimientos, tipos_mant=st.TIPOS_MANTENIMIENTO,
        tipo_mant=st.TIPO_MANTENIMIENTO, tecnicos=st.tecnicos(),
        recordatorios=pendientes, atendidos=atendidos, canales=seg.CANALES_RECORDATORIO,
        validacion=st.validacion_equipo(equipo, fotos=len(fotos), recordatorios=len(pendientes)),
        documentos=st.documentos_de_equipo(equipo_id), acepta_documentos=st.ACEPTA_DOCUMENTOS,
        documentos_max=st.DOCUMENTOS_MAX, carpetas=emp.listar(incluir_vacias=True)['empresas'],
        st_activo='equipos'))


def _a_la_ficha(equipo_id, seccion=''):
    return redirect(url_for('servicio_tecnico.equipo_ver', equipo_id=equipo_id) + (('#' + seccion) if seccion else ''))


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/fotos', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_fotos(equipo_id):
    try:
        guardadas, errores = st.guardar_fotos(equipo_id, request.files.getlist('fotos'),
                                              request.form.get('momento', 'ficha'), request.form.get('descripcion'),
                                              _usuario(), orden_id=request.form.get('orden_id', type=int))
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
        return _a_la_ficha(equipo_id, 'fotos')
    if guardadas:
        flash(f"Se guardaron {guardadas} foto{'s' if guardadas != 1 else ''}.", 'success')
    elif not errores:
        flash('Escoge al menos una foto.', 'warning')
    for e in errores[:5]:
        flash(e, 'warning')
    return _a_la_ficha(equipo_id, 'fotos')


@servicio_tecnico_bp.route(PREFIJO + '/foto/<int:foto_id>')
@servicio_tecnico_bp.route(PREFIJO + '/foto/<int:foto_id>/mini', endpoint='foto_mini')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def foto_ver(foto_id):
    contenido = st.foto_contenido(foto_id, miniatura=request.endpoint.endswith('foto_mini'))
    if not contenido:
        abort(404)
    from flask import Response
    respuesta = Response(contenido[1], mimetype=contenido[0])
    # Solo con sesión: que ningún intermediario (Cloudflare) la guarde.
    respuesta.headers['Cache-Control'] = 'private, max-age=86400'
    respuesta.headers['X-Content-Type-Options'] = 'nosniff'
    return respuesta


@servicio_tecnico_bp.route(PREFIJO + '/foto/<int:foto_id>/quitar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def foto_quitar(foto_id):
    equipo_id = st.quitar_foto(foto_id, _usuario())
    if not equipo_id:
        abort(404)
    flash('Foto retirada de la ficha.', 'success')
    return _a_la_ficha(equipo_id, 'fotos')


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/plan', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_plan(equipo_id):
    try:
        proximo = st.guardar_plan_mantenimiento(equipo_id, request.form.get('mant_cada_meses'),
                                                request.form.get('mant_proximo'), _usuario())
        flash(f"Próximo mantenimiento: {proximo.strftime('%d/%m/%Y')}. Aparecerá en «Hoy» ese día."
              if proximo else 'Plan de mantenimiento retirado.', 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return _a_la_ficha(equipo_id, 'mantenimientos')


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/mantenimiento', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_mantenimiento(equipo_id):
    try:
        st.registrar_mantenimiento(equipo_id, _form_dict(), _usuario())
        flash('Mantenimiento registrado en la hoja de vida del equipo.', 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return _a_la_ficha(equipo_id, 'mantenimientos')


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/recordatorio', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_recordatorio(equipo_id):
    try:
        seg.programar_recordatorio(equipo_id, request.form.get('fecha'), request.form.get('motivo'),
                                   request.form.get('canal', 'whatsapp'), _usuario())
        flash('Recordatorio programado. Aparecerá en «Hoy» ese día.', 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return _a_la_ficha(equipo_id, 'recordatorios')


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/editar', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_editar(equipo_id):
    equipo = st.obtener_equipo(equipo_id)
    if not equipo:
        abort(404)
    if request.method == 'POST':
        datos = {k[7:]: v for k, v in request.form.items() if k.startswith('equipo_')}
        datos['tipo'] = request.form.get('equipo_tipo')
        try:
            st.actualizar_equipo(equipo_id, datos, _usuario())
            flash('Ficha del equipo actualizada.', 'success')
            return redirect(url_for('servicio_tecnico.equipo_ver', equipo_id=equipo_id))
        except st.ErrorServicio as exc:
            flash(str(exc), 'warning')
            equipo.update({k: v for k, v in datos.items() if k != 'tipo'})
    return render_template('servicio_tecnico/equipo_form.html', **_ctx(
        equipo=equipo, tipos_json=tipos.para_plantilla(), st_activo='equipos'))


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/cambio', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_cambio(equipo_id):
    if not st.obtener_equipo(equipo_id):
        abort(404)
    try:
        st.registrar_cambio(equipo_id, _form_dict(), _usuario(),
                            orden_id=request.form.get('orden_id', type=int))
        if request.form.get('orden_id', type=int):
            clasif.clasificar_en_segundo_plano(request.form.get('orden_id', type=int))
        flash('Pieza registrada en la ficha del equipo.', 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.equipo_ver', equipo_id=equipo_id) + '#piezas')


# ── Traer equipos desde Excel o PDF (importador) ────────────────
def _a_la_importacion(lote_id, ancla=''):
    destino = url_for('servicio_tecnico.importacion', lote_id=lote_id)
    ver = request.form.get('ver') or request.args.get('ver')
    pagina = request.form.get('pagina') or request.args.get('pagina')
    params = '&'.join(f'{k}={v}' for k, v in (('ver', ver), ('pagina', pagina))
                      if v and str(v).replace('_', '').isalnum())
    return redirect(destino + (('?' + params) if params else '') + (('#' + ancla) if ancla else ''))


@servicio_tecnico_bp.route(PREFIJO + '/equipos/importar', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def importar():
    """Paso 1: subir los archivos (Excel, CSV, PDF o texto)."""
    if request.method == 'POST':
        try:
            lote_id, errores = imp.crear_lote(request.files.getlist('archivos'), _usuario())
        except st.ErrorServicio as exc:
            flash(str(exc), 'warning')
            return redirect(url_for('servicio_tecnico.importar'))
        for e in errores[:6]:
            flash(e, 'warning')
        return redirect(url_for('servicio_tecnico.importacion', lote_id=lote_id))
    return render_template('servicio_tecnico/importar.html', **_ctx(
        lotes=imp.lotes_recientes(), estados_lote=imp.ESTADOS_LOTE, acepta=imp.ACEPTA,
        archivos_max=imp.ARCHIVOS_MAX, ia_ok=st_ia.estado()[0], st_activo='equipos'))


@servicio_tecnico_bp.route(PREFIJO + '/importacion/plantilla.xlsx')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def importacion_plantilla():
    from flask import Response
    respuesta = Response(imp.plantilla_excel(),
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta.headers['Content-Disposition'] = 'attachment; filename="plantilla_equipos.xlsx"'
    respuesta.headers['Cache-Control'] = 'private, no-store'
    return respuesta


@servicio_tecnico_bp.route(PREFIJO + '/importacion/<int:lote_id>')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def importacion(lote_id):
    """Paso 2 (leyendo con IA), 3 (revisar) o 4 (resultado), según el lote."""
    lote = imp.obtener_lote(lote_id)
    if not lote:
        abort(404)
    base = dict(lote=lote, estados_lote=imp.ESTADOS_LOTE, st_activo='equipos')
    if lote['estado'] == 'leyendo':
        return render_template('servicio_tecnico/importar_leer.html', **_ctx(
            conteo=imp._conteo_lectura(lote['archivos']), **base))
    if lote['estado'] != 'revision':
        return render_template('servicio_tecnico/importar_resultado.html', **_ctx(
            equipos_lote=imp.equipos_del_resultado(lote), **base))
    vista = imp.revisar(lote)
    ver = request.args.get('ver', '')
    filas = vista['filas']
    if ver == 'revisar':
        filas = [v for v in filas if v['estado'] == 'aviso']
    elif ver == 'error':
        filas = [v for v in filas if v['estado'] == 'error']
    elif ver == 'quitadas':
        filas = [v for v in filas if v['estado'] == 'quitada']
    else:
        ver = ''
    por_pagina = 40
    paginas = max(1, (len(filas) + por_pagina - 1) // por_pagina)
    pagina = min(max(request.args.get('pagina', 1, type=int), 1), paginas)
    equipos_lista = [(v['n'], v['titulo']) for v in vista['filas']
                     if v['clase'] == 'equipo' and v['estado'] in ('ok', 'aviso')]
    return render_template('servicio_tecnico/importar_revisar.html', **_ctx(
        vista=vista, resumen=vista['resumen'], filas=filas[(pagina - 1) * por_pagina:pagina * por_pagina],
        ver=ver, pagina=pagina, paginas=paginas, equipos_lista=equipos_lista,
        ajustes=lote.get('ajustes') or {}, vencidos=imp.VENCIDOS, tipos_lista=tipos.TIPOS,
        ia_ok=st_ia.estado()[0], se_puede_releer=imp.se_puede_releer(lote),
        cliente_defecto=(st.obtener_cliente(lote['ajustes']['cliente_id'])
                         if (lote.get('ajustes') or {}).get('cliente_id') else None),
        carpetas=emp.listar(incluir_vacias=True)['empresas'], **base))


@servicio_tecnico_bp.route(PREFIJO + '/importacion/<int:lote_id>/leer', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def importacion_leer(lote_id):
    """Lee con IA la siguiente parte (JSON para la pantalla; sin JS, vuelve a la página)."""
    try:
        res = imp.leer_siguiente(lote_id)
    except st.ErrorServicio as exc:
        if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            flash(str(exc), 'warning')
            return redirect(url_for('servicio_tecnico.importar'))
        return jsonify({'ok': False, 'error': str(exc)}), 404
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return redirect(url_for('servicio_tecnico.importacion', lote_id=lote_id))
    return jsonify({'ok': True, **res})


@servicio_tecnico_bp.route(PREFIJO + '/importacion/<int:lote_id>/seguir', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def importacion_seguir(lote_id):
    try:
        imp.terminar_lectura(lote_id)
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.importacion', lote_id=lote_id))


@servicio_tecnico_bp.route(PREFIJO + '/importacion/<int:lote_id>/releer', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def importacion_releer(lote_id):
    try:
        imp.volver_a_leer(lote_id)
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.importacion', lote_id=lote_id))


@servicio_tecnico_bp.route(PREFIJO + '/importacion/<int:lote_id>/ajustes', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def importacion_ajustes(lote_id):
    try:
        imp.guardar_ajustes(lote_id, _form_dict())
        flash('Listo: se aplicó a la revisión.', 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return _a_la_importacion(lote_id, 'ajustes')


@servicio_tecnico_bp.route(PREFIJO + '/importacion/<int:lote_id>/fila/<int:n>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def importacion_fila(lote_id, n):
    try:
        imp.editar_fila(lote_id, n, _form_dict())
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return _a_la_importacion(lote_id, f'fila-{n}')


@servicio_tecnico_bp.route(PREFIJO + '/importacion/<int:lote_id>/importar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def importacion_importar(lote_id):
    try:
        res = imp.importar(lote_id, _usuario())
    except st.ErrorServicio as exc:
        flash(f'No se importó nada: {exc}', 'warning')
        return _a_la_importacion(lote_id)
    r = res['resumen']
    flash(f"Listo: {r['equipos_creados']} equipo(s) nuevos, {r['equipos_completados']} completado(s), "
          f"{r['contactos_creados']} cliente(s) nuevos en el CRM y {r['mantenimientos']} mantenimiento(s) "
          'en las hojas de vida.', 'success')
    return redirect(url_for('servicio_tecnico.importacion', lote_id=lote_id))


@servicio_tecnico_bp.route(PREFIJO + '/importacion/<int:lote_id>/deshacer', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def importacion_deshacer(lote_id):
    try:
        d = imp.deshacer(lote_id, _usuario())
        texto = f"Importación deshecha: {d['equipos_retirados']} equipo(s) retirados."
        if d['equipos_conservados']:
            texto += f" {len(d['equipos_conservados'])} se dejaron porque ya tienen órdenes de servicio."
        flash(texto, 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.importacion', lote_id=lote_id))


@servicio_tecnico_bp.route(PREFIJO + '/importacion/<int:lote_id>/descartar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def importacion_descartar(lote_id):
    try:
        imp.descartar(lote_id, _usuario())
        flash('Importación descartada: no se guardó nada.', 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
        return redirect(url_for('servicio_tecnico.importacion', lote_id=lote_id))
    return redirect(url_for('servicio_tecnico.importar'))


# ── Documentos del equipo ───────────────────────────────────────
@servicio_tecnico_bp.route(PREFIJO + '/documento/<int:doc_id>')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def documento_ver(doc_id):
    contenido = st.documento_contenido(doc_id)
    if not contenido:
        abort(404)
    mime, nombre, datos = contenido
    from urllib.parse import quote

    from flask import Response
    # Solo el PDF se abre en el navegador; lo demás se descarga.
    en_linea = mime == 'application/pdf' and request.args.get('descargar') != '1'
    simple = ''.join(ch for ch in nombre if 32 <= ord(ch) < 127 and ch not in '"\\;') or 'documento'
    respuesta = Response(datos, mimetype=mime)
    respuesta.headers['Content-Disposition'] = (f'{"inline" if en_linea else "attachment"}; filename="{simple}"; '
                                                f"filename*=UTF-8''{quote(nombre)}")
    respuesta.headers['Cache-Control'] = 'private, max-age=3600'
    respuesta.headers['X-Content-Type-Options'] = 'nosniff'
    return respuesta


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/documentos', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_documentos(equipo_id):
    try:
        guardados, errores = st.adjuntar_documentos(equipo_id, request.files.getlist('documentos'),
                                                    request.form.get('descripcion'), _usuario())
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
        return _a_la_ficha(equipo_id, 'documentos')
    if guardados:
        flash(f"Se guardaron {guardados} documento{'s' if guardados != 1 else ''}.", 'success')
    elif not errores:
        flash('Escoge al menos un documento.', 'warning')
    for e in errores[:5]:
        flash(e, 'warning')
    return _a_la_ficha(equipo_id, 'documentos')


@servicio_tecnico_bp.route(PREFIJO + '/documento/<int:doc_id>/quitar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def documento_quitar(doc_id):
    equipo_id = st.quitar_documento(doc_id, _usuario())
    if not equipo_id:
        abort(404)
    flash('Documento retirado de la ficha.', 'success')
    return _a_la_ficha(equipo_id, 'documentos')


# ── Ficha técnica en PDF ────────────────────────────────────────
def _datos_form_ficha():
    datos = request.form.to_dict()
    datos['fotos'] = request.form.getlist('fotos')
    return datos


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/ficha', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_ficha(equipo_id):
    """La ficha técnica del equipo: qué dice y de qué color sale (roja o azul)."""
    if request.method == 'POST':
        try:
            ficha_st.guardar(equipo_id, _datos_form_ficha(), _usuario())
            flash('Ficha técnica guardada.', 'success')
        except st.ErrorServicio as exc:
            flash(str(exc), 'warning')
        return redirect(url_for('servicio_tecnico.equipo_ficha', equipo_id=equipo_id))
    try:
        datos = ficha_st.armar(equipo_id)
    except st.ErrorServicio:
        abort(404)
    return render_template('servicio_tecnico/ficha.html', **_ctx(
        d=datos, equipo=datos['equipo'], fotos_equipo=st.fotos_de_equipo(equipo_id),
        fotos_max=ficha_st.FOTOS_EN_FICHA, ia_ok=st_ia.estado()[0], st_activo='equipos'))


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/ficha.pdf', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_ficha_pdf(equipo_id):
    """Genera la ficha en PDF (si viene del formulario, primero la guarda). La
    primera vez le asigna su código consecutivo."""
    if not st.obtener_equipo(equipo_id):
        abort(404)
    if request.form.get('guardar') == '1':
        try:
            ficha_st.guardar(equipo_id, _datos_form_ficha(), _usuario())
        except st.ErrorServicio as exc:
            flash(str(exc), 'warning')
            return redirect(url_for('servicio_tecnico.equipo_ficha', equipo_id=equipo_id))
    ficha_st.asignar_codigo(equipo_id)
    datos = ficha_st.armar(equipo_id)
    contenido = ficha_st.pdf(datos)
    nombre = ficha_st.nombre_pdf(datos)
    if request.form.get('copia') == '1':
        ficha_st.guardar_copia(equipo_id, nombre, contenido, datos['codigo'], _usuario())
    from urllib.parse import quote

    from flask import Response
    simple = ''.join(ch for ch in nombre if 32 <= ord(ch) < 127 and ch not in '"\\;') or 'ficha.pdf'
    respuesta = Response(contenido, mimetype='application/pdf')
    respuesta.headers['Content-Disposition'] = f"inline; filename=\"{simple}\"; filename*=UTF-8''{quote(nombre)}"
    respuesta.headers['Cache-Control'] = 'private, no-store'
    respuesta.headers['X-Content-Type-Options'] = 'nosniff'
    return respuesta


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/ficha/proponer', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_ficha_proponer(equipo_id):
    """Textos de la ficha: con IA (estilo del taller) o con reglas. No guarda."""
    try:
        datos = ficha_st.armar(equipo_id)
    except st.ErrorServicio as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 404
    borrador = ficha_st.borrador(datos['equipo'])
    filas = [(f['etiqueta'], f['valor']) for f in datos['filas']]
    return jsonify({'ok': True, **st_ia.redactar_ficha(datos['equipo'], filas, borrador)})


# ── Búsquedas para el formulario ────────────────────────────────
@servicio_tecnico_bp.route(PREFIJO + '/api/clientes')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def api_clientes():
    return jsonify({'ok': True, 'clientes': st.buscar_clientes(request.args.get('q', ''))})


@servicio_tecnico_bp.route(PREFIJO + '/api/clientes/<int:contacto_id>/equipos')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def api_equipos_cliente(contacto_id):
    lista = st.equipos_de_cliente(contacto_id)
    for e in lista:
        e['descripcion'] = st.descripcion_equipo(e)
        e['icono'] = tipos.icono(e['tipo'])
    return jsonify({'ok': True, 'equipos': lista})


# ── Página pública del cliente ──────────────────────────────────
@servicio_tecnico_bp.route('/servicio/<token>')
@limiter.limit('30 per minute; 300 per hour')
def publico(token):
    if not is_module_active(MODULE_SERVICIO_TECNICO) or len(token or '') > 64:
        abort(404)
    orden = st.obtener_orden(token=token)
    if not orden:
        abort(404)
    # Solo lo que el cliente necesita: nunca la clave, el diagnóstico interno
    # ni los datos de contacto.
    visible = {
        'numero': orden['numero'], 'estado': orden['estado'],
        'equipo': st.descripcion_equipo(orden), 'tipo': orden['tipo'],
        'fecha_recibido': orden['fecha_recibido'], 'fecha_promesa': orden['fecha_promesa'],
        'fecha_listo': orden['fecha_listo'], 'fecha_entregado': orden['fecha_entregado'],
        'garantia_hasta': orden['garantia_hasta'],
        'valor': orden['valor_final'] if orden['valor_final'] is not None else (
            orden['valor_estimado'] if orden['estado'] in ('aprobado', 'reparacion', 'listo') else None),
        'cliente_nombre': (orden.get('cliente_nombre') or '').split(' ')[0],
        'token': token,
    }
    if orden['estado'] == 'cotizado' and orden.get('cotizacion_id'):
        visible['valor'] = seg.total_cotizacion(orden['cotizacion_id'])
    encuesta = None
    if orden['estado'] in ('entregado', 'garantia'):
        encuesta = {'respondida': seg.encuesta_respondida(orden['id']),
                    'gracias': request.args.get('gracias') == '1'}
    return render_template('servicio_tecnico/publico.html', **_ctx(o=visible, encuesta=encuesta,
                                                                    datosApp=get_common_data()))


@servicio_tecnico_bp.route('/servicio/<token>/encuesta', methods=['POST'])
@limiter.limit('5 per minute; 20 per hour')
def encuesta(token):
    if not is_module_active(MODULE_SERVICIO_TECNICO) or len(token or '') > 64:
        abort(404)
    orden = st.obtener_orden(token=token)
    if not orden or orden['estado'] not in ('entregado', 'garantia'):
        abort(404)
    try:
        seg.registrar_encuesta(orden, request.form.get('calificacion'), request.form.get('comentario'))
    except ValueError as exc:
        flash(str(exc), 'warning')
        return redirect(url_for('servicio_tecnico.publico', token=token) + '#encuesta')
    return redirect(url_for('servicio_tecnico.publico', token=token, gracias=1) + '#encuesta')


# ── Seguimiento: bandeja «Hoy» ──────────────────────────────────
@servicio_tecnico_bp.route(PREFIJO + '/hoy')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def hoy():
    grupos = seg.bandeja()
    return render_template('servicio_tecnico/hoy.html', **_ctx(
        grupos=grupos, total=sum(len(v) for v in grupos.values()), ia_ok=st_ia.estado()[0], st_activo='hoy'))


def _volver_a_bandeja():
    destino = request.form.get('volver') or ''
    if destino.startswith(PREFIJO):
        return redirect(destino)
    return redirect(url_for('servicio_tecnico.hoy'))


@servicio_tecnico_bp.route(PREFIJO + '/seguimiento/<int:seg_id>/completar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def seguimiento_completar(seg_id):
    estado = 'omitido' if request.form.get('estado') == 'omitido' else 'hecho'
    canal = request.form.get('canal')
    canal = canal if canal in ('whatsapp', 'llamada', 'correo', 'presencial') else None
    hecho = seg.completar(seg_id, estado, canal, (request.form.get('comentario') or '').strip() or None, _usuario())
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': bool(hecho)})
    if hecho:
        flash('Seguimiento ' + ('omitido.' if estado == 'omitido' else 'registrado.'), 'success')
    return _volver_a_bandeja()


@servicio_tecnico_bp.route(PREFIJO + '/seguimiento/<int:seg_id>/correo', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def seguimiento_correo(seg_id):
    ok, error = seg.enviar_correo_seguimiento(seg_id, _usuario())
    flash('Correo enviado al cliente.' if ok else error, 'success' if ok else 'warning')
    return _volver_a_bandeja()


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/correo-estado', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_correo_estado(orden_id):
    orden = st.obtener_orden(orden_id)
    if not orden:
        abort(404)
    if not orden.get('cliente_email'):
        flash('El cliente no tiene correo registrado.', 'warning')
    elif seg.correo_estado(orden_id, orden['estado'], forzar=True):
        flash('Correo enviado al cliente.', 'success')
    else:
        flash('Este estado no tiene correo para el cliente.', 'warning')
    return redirect(url_for('servicio_tecnico.orden_ver', orden_id=orden_id))


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/whatsapp', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_whatsapp(orden_id):
    """Deja en la bitácora que se abrió WhatsApp con el aviso del estado."""
    nombre = st.ESTADO_POR_CODIGO.get(request.form.get('estado', ''), ('', 'estado'))[1]
    try:
        st.agregar_nota(orden_id, f'Aviso por WhatsApp: {nombre}', _usuario(), tipo='whatsapp')
    except st.ErrorServicio:
        return jsonify({'ok': False}), 404
    return jsonify({'ok': True})


@servicio_tecnico_bp.route(PREFIJO + '/configuracion', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def configuracion():
    if request.method == 'POST':
        msj.guardar_config(request.form)
        flash('Configuración guardada.', 'success')
        return redirect(url_for('servicio_tecnico.configuracion'))
    return render_template('servicio_tecnico/configuracion.html', **_ctx(
        cfg=msj.config(), dias=msj.DIAS, correos=msj.CORREOS, plantillas=msj.PLANTILLAS,
        st_activo='configuracion'))



# ── F3: IA ──────────────────────────────────────────────────────
def _json_entrada():
    return request.get_json(silent=True) or request.form


@servicio_tecnico_bp.route(PREFIJO + '/api/leer-info', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def api_leer_info():
    """Lee el texto pegado (lector fijo + IA) y devuelve propuestas. No guarda nada."""
    d = _json_entrada()
    equipo_id = d.get('equipo_id')
    if equipo_id and str(equipo_id).isdigit():
        equipo = st.obtener_equipo(int(equipo_id))
        if not equipo:
            return jsonify({'ok': False, 'error': 'El equipo no existe.'}), 404
    else:
        tipo = d.get('tipo') or ''
        if not tipos.es_valido(tipo):
            return jsonify({'ok': False, 'error': 'Escoge primero el tipo de equipo.'}), 400
        actual = d.get('actual') if isinstance(d.get('actual'), dict) else {}
        equipo = {'tipo': tipo, **{k: v for k, v in actual.items() if k != 'extras'},
                  'extras': actual.get('extras') if isinstance(actual.get('extras'), dict) else {}}
    res = st_ia.leer_informacion(equipo, d.get('texto') or '', usar_ia=str(d.get('ia', '1')) != '0')
    return jsonify({'ok': True, **res})


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/especificaciones', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_especificaciones(equipo_id):
    equipo = st.obtener_equipo(equipo_id)
    if not equipo:
        return jsonify({'ok': False, 'error': 'El equipo no existe.'}), 404
    return jsonify({'ok': True, **st_ia.completar_caracteristicas(equipo)})


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>/aplicar-info', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def equipo_aplicar_info(equipo_id):
    import json
    campos = {c: request.form.get('valor_' + c, '') for c in request.form.getlist('aplicar')}
    try:
        sugerencias = json.loads(request.form.get('sugerencias') or 'null')
    except ValueError:
        sugerencias = None
    if sugerencias is not None and not isinstance(sugerencias, list):
        sugerencias = None
    try:
        aceptados = st.aplicar_info(
            equipo_id, campos,
            texto=request.form.get('texto') if 'texto' in request.form else None,
            resumen=request.form.get('resumen') if request.form.get('resumen') else None,
            sugerencias=[{'titulo': str(s.get('titulo', ''))[:120], 'detalle': str(s.get('detalle', ''))[:300]}
                         for s in sugerencias if isinstance(s, dict)] if sugerencias is not None else None,
            usuario_id=_usuario())
        flash(f'Ficha actualizada: {len(aceptados)} campo(s).' if aceptados else 'Información guardada en la ficha.',
              'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.equipo_ver', equipo_id=equipo_id) + '#caracteristicas')


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/prediagnostico', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_prediagnostico(orden_id):
    orden = st.obtener_orden(orden_id)
    if not orden:
        abort(404)
    texto, error = st_ia.prediagnostico(orden)
    if texto:
        st.guardar_prediagnostico(orden_id, texto, _usuario())
        flash('Pre-diagnóstico listo. Es una sugerencia: confírmalo con tus pruebas.', 'success')
    else:
        flash(error or 'La IA no respondió.', 'warning')
    return redirect(url_for('servicio_tecnico.orden_ver', orden_id=orden_id) + '#st-recep')


@servicio_tecnico_bp.route(PREFIJO + '/api/mejorar-mensaje', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def api_mejorar_mensaje():
    """Reescribe con IA la PLANTILLA del mensaje (sin datos del cliente) y la
    rellena aquí. Devuelve el texto y el enlace de WhatsApp nuevos."""
    d = _json_entrada()
    cfg = msj.config()
    if d.get('seg_id') and str(d.get('seg_id')).isdigit():
        fila = seg.obtener(int(d['seg_id']))
        if not fila:
            return jsonify({'ok': False, 'error': 'El seguimiento no existe.'}), 404
        tipo = fila['tipo']
        datos = seg._datos_mensaje(fila, msj.datos_negocio())
        telefono = fila.get('telefono')
    elif d.get('orden_id') and str(d.get('orden_id')).isdigit():
        orden = st.obtener_orden(int(d['orden_id']))
        if not orden or orden['estado'] not in seg.ESTADOS_CON_CORREO:
            return jsonify({'ok': False, 'error': 'Este estado no tiene mensaje.'}), 400
        tipo = orden['estado']
        datos = seg._datos_orden(orden, tipo)
        telefono = orden.get('cliente_whatsapp') or orden.get('cliente_telefono')
    else:
        return jsonify({'ok': False, 'error': 'Falta el mensaje a mejorar.'}), 400
    plantilla = cfg['plantillas'].get(tipo) or ''
    nueva, error = st_ia.mejorar_plantilla(msj.PLANTILLA_POR_TIPO[tipo][1], plantilla, datos.get('equipo', ''))
    if not nueva:
        return jsonify({'ok': False, 'error': error}), 200
    texto = msj.rellenar(nueva, datos)
    return jsonify({'ok': True, 'texto': texto, 'wa_url': seg.whatsapp_url(telefono, texto)})



# ── Clasificación del caso (historial consultable) ──────────────
@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/clasificar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_clasificar(orden_id):
    """Clasifica ya (reglas + IA si está disponible) y vuelve a la orden."""
    resultado = clasif.clasificar_orden(orden_id, usar_ia=True)
    if resultado is None:
        flash('Esta orden tiene una clasificación hecha a mano: corrígela abajo si hace falta.', 'warning')
    else:
        flash('Caso clasificado con IA.' if resultado['fuente'] == 'ia'
              else 'Caso clasificado con las reglas automáticas (la IA no está disponible).', 'success')
    return redirect(url_for('servicio_tecnico.orden_ver', orden_id=orden_id) + '#st-caso')


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/clasificacion', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_clasificacion_manual(orden_id):
    try:
        clasif.clasificar_manual(orden_id, request.form.get('falla_categoria'), request.form.get('componente'),
                                 request.form.get('solucion_categoria'), _usuario())
        flash('Clasificación guardada.', 'success')
    except ValueError as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.orden_ver', orden_id=orden_id) + '#st-caso')


@servicio_tecnico_bp.route(PREFIJO + '/clasificar-historial', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def clasificar_historial():
    """Órdenes viejas sin clasificar: reglas al instante (rápido). La IA las
    refina después, una por una o con el proceso de la noche."""
    hechas = clasif.clasificar_pendientes(limite=200, usar_ia=False)
    flash(f'{hechas} orden(es) clasificadas.' if hechas else 'No había órdenes sin clasificar.', 'success')
    return redirect(url_for('servicio_tecnico.configuracion'))
