"""routes/admin_chat_publico.py — Configuración del chat público (módulo
ai_public) + sus preguntas frecuentes.

Blueprint propio, separado de routes/admin.py a propósito: routes/admin.py
queda con CERO líneas tocadas. Reusa el mismo patrón que ya existe ahí —
mi_negocio() para la pantalla de configuración, gestion_servicios() para el
CRUD — pero las FAQ se guardan con las funciones genéricas de
services/public_site_service.py (item_type='faq'), sin tabla propia.
"""
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from database import get_db_cursor
from helpers import get_data_app
from security import ADMIN_FULL, ADMIN_STAFF, rol_requerido
from services.chat_publico.historial import preguntas_sin_responder
from services.config_tenant import set_cliente_config
from services.public_site_service import (
    delete_public_site_item,
    get_public_site_items,
    save_public_site_item,
    toggle_public_site_item,
)
from tenant_features import MODULE_AI_PUBLIC, MODULE_AI_PUBLIC_COMPAT, is_module_active

admin_chat_publico_bp = Blueprint('admin_chat_publico', __name__, url_prefix='/admin/chat-publico')

# Lo único configurable desde aquí: textos del propio chat. Nada de colores,
# módulos ni nada que ya se gestione desde el panel maestro o "Mi Negocio".
_CAMPOS_CONFIG = ('chat_publico_saludo', 'chat_publico_sugerencias', 'chat_publico_tono')


def _reindexar_faq():
    try:
        from services.ia_rag.indexador import reindexar_uno
        reindexar_uno('faq', None)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'admin_chat_publico: reindexado de FAQ falló ({exc})')


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


@admin_chat_publico_bp.route('/faq/crear', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def faq_crear():
    if request.method == 'POST':
        datos = request.form.copy()
        datos['item_type'] = 'faq'
        try:
            save_public_site_item(datos, request.files.get('imagen'), current_app.root_path)
            _reindexar_faq()
            flash('Pregunta frecuente creada.', 'success')
        except Exception as exc:  # noqa: BLE001
            current_app.logger.error(f'admin_chat_publico: error creando FAQ ({exc})')
            flash('No fue posible guardar la pregunta.', 'error')
        return redirect(url_for('admin_chat_publico.faq_lista'))
    return render_template('admin/chat_publico_faq.html', datosApp=get_data_app(),
                          faqs=[], modo='crear')


@admin_chat_publico_bp.route('/faq/editar/<int:item_id>', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def faq_editar(item_id):
    if request.method == 'POST':
        datos = request.form.copy()
        datos['item_type'] = 'faq'
        datos['item_id'] = str(item_id)
        try:
            save_public_site_item(datos, request.files.get('imagen'), current_app.root_path)
            _reindexar_faq()
            flash('Pregunta frecuente actualizada.', 'success')
        except Exception as exc:  # noqa: BLE001
            current_app.logger.error(f'admin_chat_publico: error editando FAQ ({exc})')
            flash('No fue posible guardar los cambios.', 'error')
        return redirect(url_for('admin_chat_publico.faq_lista'))

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
        delete_public_site_item(item_id, item_type='faq')
        _reindexar_faq()
        flash('Pregunta frecuente eliminada.', 'success')
    except Exception:
        flash('Error eliminando la pregunta.', 'error')
    return redirect(url_for('admin_chat_publico.faq_lista'))


@admin_chat_publico_bp.route('/faq/toggle/<int:item_id>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def faq_toggle(item_id):
    try:
        toggle_public_site_item(item_id, item_type='faq')
        _reindexar_faq()
        flash('Estado actualizado.', 'success')
    except Exception:
        flash('Error cambiando el estado.', 'error')
    return redirect(url_for('admin_chat_publico.faq_lista'))
