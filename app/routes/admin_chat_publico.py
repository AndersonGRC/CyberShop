"""routes/admin_chat_publico.py — Configuración del chat público (módulo
ai_public) + sus preguntas frecuentes.

Blueprint propio, separado de routes/admin.py a propósito: routes/admin.py
queda con CERO líneas tocadas. Reusa el mismo patrón que ya existe ahí —
mi_negocio() para la pantalla de configuración, gestion_servicios() para el
CRUD — pero las FAQ se guardan con las funciones genéricas de
services/public_site_service.py (item_type='faq'), sin tabla propia.
"""
from flask import (Blueprint, current_app, flash, redirect, render_template, request,
                   session, url_for)

from database import get_db_cursor
from helpers import get_data_app
from security import ADMIN_FULL, ADMIN_STAFF, rol_requerido
from services.chat_publico.historial import preguntas_sin_responder
from services.config_tenant import set_cliente_config
from services.ia_rag import conocimiento as kb
from services.ia_rag import sinonimos
from services.ia_rag.buscar import SINONIMOS
from services.chat_publico import calificaciones
from services.public_site_service import get_public_site_items
from tenant_features import MODULE_AI_PUBLIC, MODULE_AI_PUBLIC_COMPAT, is_module_active

admin_chat_publico_bp = Blueprint('admin_chat_publico', __name__, url_prefix='/admin/chat-publico')

# Lo único configurable desde aquí: textos del propio chat. Nada de colores,
# módulos ni nada que ya se gestione desde el panel maestro o "Mi Negocio".
_CAMPOS_CONFIG = ('chat_publico_saludo', 'chat_publico_sugerencias', 'chat_publico_tono')


def _reindexar_faq(item_id=None):
    try:
        from services.ia_rag.indexador import reindexar_uno
        if reindexar_uno('faq', item_id):
            return True
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'admin_chat_publico: reindexado de FAQ falló ({exc})')
    current_app.logger.warning(f'admin_chat_publico: FAQ {item_id} no se actualizó en el índice')
    return False


def _avisar_resultado_faq(mensaje, item_id=None):
    if _reindexar_faq(item_id):
        flash(mensaje, 'success')
    else:
        flash(mensaje + ' El índice del chat no se pudo actualizar; verifica el chat público.',
              'warning')


@admin_chat_publico_bp.route('/', methods=['GET', 'POST'])
@rol_requerido(ADMIN_FULL)  # como "Mi Negocio": super admin + propietario
def config():
    """Textos del chat (saludo, sugerencias, tono) + estado del módulo de
    solo lectura (se activa/desactiva desde el panel maestro) + preguntas
    que nadie supo responder."""
    if request.method == 'POST':
        try:
            with get_db_cursor() as cur:
                for clave in _CAMPOS_CONFIG:
                    valor = (request.form.get(clave) or '').strip()
                    set_cliente_config(cur, clave, valor, descripcion='Chat del sitio')
            flash('Configuración del chat guardada.', 'success')
        except Exception as exc:  # noqa: BLE001
            current_app.logger.error(f'admin_chat_publico: error guardando config ({exc})')
            flash('No fue posible guardar los cambios.', 'error')
        return redirect(url_for('admin_chat_publico.config'))

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT clave, valor FROM cliente_config WHERE clave = ANY(%s)",
                       (list(_CAMPOS_CONFIG),))
            valores = {r['clave']: r['valor'] for r in cur.fetchall()}
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'admin_chat_publico: no se pudo leer config ({exc})')
        valores = {}

    return render_template(
        'admin/chat_publico_config.html',
        datosApp=get_data_app(),
        activo=is_module_active(MODULE_AI_PUBLIC),
        valores=valores,
        sin_responder=preguntas_sin_responder(limite=20),
        activo_compat=is_module_active(MODULE_AI_PUBLIC_COMPAT),
    )


@admin_chat_publico_bp.route('/faq')
@rol_requerido(ADMIN_STAFF)  # como gestion_servicios
def faq_lista():
    faqs = get_public_site_items('faq', include_inactive=True)
    return render_template('admin/chat_publico_faq.html', datosApp=get_data_app(),
                          faqs=faqs, modo='lista')


def _volver(defecto='admin_chat_publico.faq_lista'):
    """Vuelve a la pantalla desde la que se hizo el cambio rápido (la base de
    conocimiento o la lista de preguntas frecuentes)."""
    if request.form.get('volver') == 'conocimiento':
        return redirect(url_for('admin_chat_publico.conocimiento'))
    return redirect(url_for(defecto))


@admin_chat_publico_bp.route('/faq/crear', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def faq_crear():
    if request.method == 'POST':
        try:
            item_id = kb.faq_guardar(
                request.form, archivo=request.files.get('imagen'),
                root_path=current_app.root_path,
                pregunta=(request.form.get('pregunta_origen') or '').strip() or None)
            _avisar_resultado_faq('Pregunta frecuente creada.', item_id)
        except ValueError as exc:
            flash(str(exc), 'error')
        except Exception as exc:  # noqa: BLE001
            current_app.logger.error(f'admin_chat_publico: error creando FAQ ({exc})')
            flash('No fue posible guardar la pregunta.', 'error')
        return _volver()
    # «Responder» desde lo que el chat no supo contestar: la pregunta llega escrita.
    pregunta = (request.args.get('pregunta') or '').strip()[:200]
    return render_template('admin/chat_publico_faq.html', datosApp=get_data_app(),
                          faqs=[], modo='crear', pregunta_origen=pregunta)


@admin_chat_publico_bp.route('/faq/editar/<int:item_id>', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def faq_editar(item_id):
    if request.method == 'POST':
        try:
            kb.faq_guardar(request.form, item_id=item_id,
                                     archivo=request.files.get('imagen'),
                                     root_path=current_app.root_path)
            _avisar_resultado_faq('Pregunta frecuente actualizada.', item_id)
        except ValueError as exc:
            flash(str(exc), 'error')
        except Exception as exc:  # noqa: BLE001
            current_app.logger.error(f'admin_chat_publico: error editando FAQ ({exc})')
            flash('No fue posible guardar los cambios.', 'error')
        return _volver()

    item = next((f for f in get_public_site_items('faq', include_inactive=True)
                if f['id'] == item_id), None)
    if not item:
        flash('Pregunta frecuente no encontrada.', 'error')
        return redirect(url_for('admin_chat_publico.faq_lista'))
    return render_template('admin/chat_publico_faq.html', datosApp=get_data_app(),
                          faqs=[], modo='editar', item=item)


@admin_chat_publico_bp.route('/faq/eliminar/<int:item_id>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def faq_eliminar(item_id):
    try:
        if kb.faq_eliminar(item_id):
            _avisar_resultado_faq('Pregunta frecuente eliminada. Si fue un error, la puedes '
                                  'restaurar desde «Base de conocimiento → Historial».', item_id)
        else:
            flash('Esa pregunta frecuente ya no existe.', 'error')
    except Exception:
        flash('Error eliminando la pregunta.', 'error')
    return _volver()


@admin_chat_publico_bp.route('/faq/toggle/<int:item_id>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def faq_toggle(item_id):
    try:
        if kb.faq_cambiar_estado(item_id):
            _avisar_resultado_faq('Estado actualizado.', item_id)
        else:
            flash('Esa pregunta frecuente ya no existe.', 'error')
    except Exception:
        flash('Error cambiando el estado.', 'error')
    return _volver()


# ── Base de conocimiento: todo lo que sabe la IA, con historial ──────────────

def _ve_documentos():
    """Los documentos internos (y su historial) son del dueño y del asistente
    del panel: ADMIN_FULL y el módulo ai_assistant."""
    from tenant_features import MODULE_AI
    try:
        from services.permisos_service import rol_base_efectivo
        base = rol_base_efectivo(session.get('rol_id'))
    except Exception:  # noqa: BLE001
        base = session.get('rol_id')
    return base in ADMIN_FULL and is_module_active(MODULE_AI)


@admin_chat_publico_bp.route('/conocimiento')
@rol_requerido(ADMIN_STAFF)
def conocimiento():
    """Una sola pantalla para lo que sabe la IA: qué tiene guardado, probar una
    pregunta, lo que no supo responder (con botón para responderlo) y el
    historial de cambios con «Restaurar»."""
    from services.ia_rag import bitacora
    from services.ia_rag.indexador import estado
    ve_docs = _ve_documentos()
    pregunta = (request.args.get('probar') or '').strip()[:300]
    prueba = (kb.probar(pregunta, rol_id=session.get('rol_id'), con_internos=ve_docs)
              if pregunta else None)
    tipos = ('faq', 'documento', 'pregunta', 'sinonimos') if ve_docs else ('faq', 'pregunta', 'sinonimos')
    historial = bitacora.listar(tipos=tipos, limite=60)
    for fila in historial:
        fila['restaurable'] = kb.puede_restaurar(fila)
    return render_template(
        'admin/ia_conocimiento.html', datosApp=get_data_app(),
        indice=estado(), pendientes=kb.preguntas_pendientes(limite=20),
        faqs=get_public_site_items('faq', include_inactive=True),
        historial=historial, pregunta=pregunta, prueba=prueba, ve_documentos=ve_docs,
        chat_activo=is_module_active(MODULE_AI_PUBLIC),
        sinonimos_texto=sinonimos.leer_texto(), sinonimos_comunes=SINONIMOS,
        calificacion=calificaciones.resumen(30),
        para_revisar=kb.faqs_para_revisar(), parecidas=kb.faqs_parecidas(),
        no_sirvieron=calificaciones.no_sirvieron(limite=15, excluir=bitacora.preguntas_atendidas()))


@admin_chat_publico_bp.route('/conocimiento/sinonimos', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def conocimiento_sinonimos():
    """Palabras que en ESTA tienda significan lo mismo (p. ej. «pola = cerveza»)."""
    try:
        tabla = sinonimos.guardar(request.form.get('sinonimos', ''))
        flash(f'Sinónimos guardados ({len(tabla)}). El chat ya los usa al buscar.', 'success')
    except ValueError as exc:
        flash(f'No se guardaron los sinónimos: {exc}', 'error')
    return redirect(url_for('admin_chat_publico.conocimiento') + '#kbx-sinonimos')


@admin_chat_publico_bp.route('/conocimiento/faq/<int:item_id>/vigente', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def conocimiento_faq_vigente(item_id):
    """La revisó y sigue bien: deja de aparecer en «Para revisar»."""
    if kb.faq_sigue_vigente(item_id):
        flash('Listo: queda marcada como revisada.', 'success')
    else:
        flash('Esa pregunta frecuente ya no existe.', 'error')
    return redirect(url_for('admin_chat_publico.conocimiento') + '#kbx-revisar')


@admin_chat_publico_bp.route('/conocimiento/descartar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def conocimiento_descartar():
    if kb.descartar_pregunta(request.form.get('pregunta')):
        flash('Pregunta descartada: ya no aparece como pendiente.', 'success')
    else:
        flash('No se pudo descartar la pregunta.', 'error')
    return redirect(url_for('admin_chat_publico.conocimiento'))


@admin_chat_publico_bp.route('/conocimiento/restaurar/<int:log_id>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def conocimiento_restaurar(log_id):
    from services.ia_rag import bitacora
    fila = bitacora.obtener(log_id)
    if fila and fila['tipo'] == 'documento' and not _ve_documentos():
        flash('No tienes permiso para cambiar documentos internos.', 'error')
        return redirect(url_for('admin_chat_publico.conocimiento'))
    try:
        ok, mensaje, tipo, objeto_id = kb.restaurar(log_id)
    except ValueError as exc:
        ok, mensaje, tipo, objeto_id = False, str(exc), None, None
    if ok and tipo == 'faq':
        _avisar_resultado_faq(mensaje, objeto_id)
    else:
        flash(mensaje, 'success' if ok else 'error')
    return redirect(url_for('admin_chat_publico.conocimiento'))


@admin_chat_publico_bp.route('/conocimiento/reindexar', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def conocimiento_reindexar():
    """Rehace el índice ya, sin esperar la revisión diaria (p. ej. después de
    cargar muchos productos)."""
    from services.ia_rag.indexador import reindexar
    resultado = reindexar()
    if 'error' in resultado:
        flash('No se pudo actualizar el índice: ' + str(resultado['error'])[:150], 'error')
    else:
        flash(f'Índice actualizado: {sum(resultado.values())} textos.', 'success')
    return redirect(url_for('admin_chat_publico.conocimiento'))
