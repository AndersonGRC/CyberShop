"""
routes/servicio_tecnico.py — Módulo «Servicio Técnico».

Equipos de los clientes (computadores, celulares, tablets, televisores, UPS…),
órdenes de servicio de la recepción a la entrega, garantía y bitácora. La
lógica vive en services/servicio_tecnico_service.py; aquí solo HTTP.

  /admin/servicio-tecnico/...   panel (módulo activo + permiso 'servicio_tecnico')
  /servicio/<token>             estado de la orden para el cliente (sin sesión,
                                sin datos sensibles, con límite de peticiones)
"""

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)

from extensions import limiter
from helpers import get_common_data, get_data_app
from security import ADMIN_STAFF, permiso_requerido, registrar_guard_permiso, rol_requerido
from services import servicio_tecnico_mensajes as msj
from services import servicio_tecnico_seguimiento as seg
from services import servicio_tecnico_service as st
from services import servicio_tecnico_tipos as tipos
from tenant_features import MODULE_SERVICIO_TECNICO, is_module_active, module_required

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
    base = dict(datosApp=get_data_app(), estados=st.ESTADOS, estado_info=st.ESTADO_POR_CODIGO,
                pasos=st.PASOS, tipos_lista=tipos.TIPOS, tipo_nombre=tipos.nombre,
                tipo_icono=tipos.icono, etiquetas=tipos.ETIQUETAS_COMUNES)
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
        aviso=seg.aviso_estado(orden), seguimientos=seg.de_orden(orden_id),
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
        flash(f"Estado actualizado: {st.ESTADO_POR_CODIGO[nuevo][1]}.{aviso}", 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.orden_ver', orden_id=orden_id))


@servicio_tecnico_bp.route(PREFIJO + '/orden/<int:orden_id>/editar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
@permiso_requerido('servicio_tecnico', 'operar')
def orden_actualizar(orden_id):
    permitidos = ('diagnostico', 'estado_fisico', 'accesorios', 'valor_estimado', 'valor_final',
                  'fecha_promesa', 'tecnico_id', 'garantia_dias', 'clave')
    datos = {k: request.form.get(k) for k in permitidos if k in request.form}
    try:
        st.actualizar_orden(orden_id, datos, _usuario())
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
    q = request.args.get('q', '')
    tipo = request.args.get('tipo', '')
    return render_template('servicio_tecnico/equipos.html', **_ctx(
        equipos=st.listar_equipos(q=q, tipo=tipo), q=q, filtro_tipo=tipo, st_activo='equipos'))


@servicio_tecnico_bp.route(PREFIJO + '/equipo/<int:equipo_id>')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_SERVICIO_TECNICO)
def equipo_ver(equipo_id):
    equipo = st.obtener_equipo(equipo_id)
    if not equipo:
        abort(404)
    return render_template('servicio_tecnico/equipo.html', **_ctx(
        equipo=equipo, campos_extra=tipos.campos_extra(equipo['tipo']),
        columnas=tipos.columnas(equipo['tipo']), cambios=st.cambios_de_equipo(equipo_id),
        ordenes_equipo=st.ordenes_de_equipo(equipo_id), eventos=st.eventos(equipo_id=equipo_id),
        st_activo='equipos'))


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
        flash('Pieza registrada en la ficha del equipo.', 'success')
    except st.ErrorServicio as exc:
        flash(str(exc), 'warning')
    return redirect(url_for('servicio_tecnico.equipo_ver', equipo_id=equipo_id) + '#piezas')


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
        grupos=grupos, total=sum(len(v) for v in grupos.values()), st_activo='hoy'))


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
