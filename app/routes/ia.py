"""routes/ia.py — Endpoints del Asistente IA (módulo ai_assistant).

Todos exigen rol staff y que el módulo esté disponible para el tenant actual.
AISLAMIENTO: estas vistas NUNCA reciben un tenant_id; toda lectura/escritura de
BD usa get_db_cursor(), que resuelve a la BD del tenant del request. El servicio
ai_service arma el contexto solo desde esa BD.
"""

from flask import Blueprint, request, jsonify, render_template

from security import rol_requerido, ADMIN_STAFF
from database import get_db_cursor
from helpers import get_data_app
import services.ai_service as ai

ia_bp = Blueprint('ia', __name__, url_prefix='/admin/ia')


def _guard():
    """Devuelve None si la IA está disponible, o una respuesta JSON 403."""
    if not ai.ia_disponible():
        _ok, motivo = ai.estado_ia()
        return jsonify({'ok': False, 'error': motivo}), 403
    return None


@ia_bp.route('/')
@rol_requerido(ADMIN_STAFF)
def panel():
    """Página de estado del Asistente IA + acciones masivas."""
    datosApp = get_data_app()
    estado = ai.ping()
    faltan = 0
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT COUNT(*) AS n FROM productos "
                        "WHERE descripcion IS NULL OR TRIM(descripcion) = ''")
            faltan = cur.fetchone()['n']
    except Exception:
        faltan = 0
    return render_template('admin/ia_panel.html', datosApp=datosApp,
                           estado=estado, faltan=faltan)


@ia_bp.route('/estado')
@rol_requerido(ADMIN_STAFF)
def estado():
    return jsonify(ai.ping())


@ia_bp.route('/descripcion', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def descripcion():
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    texto, err = ai.generar_descripcion(
        d.get('nombre', ''), d.get('categoria', ''),
        d.get('keywords', ''), d.get('precio'))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True, 'descripcion': texto})


@ia_bp.route('/reescribir', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def reescribir():
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    texto, err = ai.reescribir_descripcion(d.get('texto', ''))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True, 'texto': texto})


@ia_bp.route('/seo', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def seo():
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    res, err = ai.generar_seo(d.get('nombre', ''), d.get('descripcion', ''))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True, **res})


@ia_bp.route('/respuesta-sugerida', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def respuesta_sugerida():
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    texto, err = ai.sugerir_respuesta(d.get('mensaje', ''), d.get('asunto', ''))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True, 'respuesta': texto})


@ia_bp.route('/chat', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def chat():
    """Asistente conversacional: responde con datos reales del tenant actual."""
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    res, err = ai.responder_chat(d.get('pregunta', ''))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True, **res})


@ia_bp.route('/nombre', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def nombre():
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    texto, err = ai.sugerir_nombre(d.get('descripcion', ''), d.get('categoria', ''))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True, 'nombre': texto})


@ia_bp.route('/tags', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def tags():
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    texto, err = ai.generar_tags(d.get('nombre', ''), d.get('descripcion', ''))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True, 'tags': texto})


@ia_bp.route('/traducir', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def traducir():
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    texto, err = ai.traducir_texto(d.get('texto', ''), d.get('idioma', 'inglés'))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True, 'texto': texto})


@ia_bp.route('/descripciones-masivas', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def descripciones_masivas():
    """Genera descripciones para un LOTE pequeño de productos del tenant actual
    que no tengan descripción. El frontend repite hasta restantes=0 (evita el
    worker timeout). Secuencial (una sola GPU)."""
    g = _guard()
    if g:
        return g
    LOTE = 4
    procesados, errores = 0, 0
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT p.id, p.nombre, COALESCE(g.nombre,'') AS categoria "
                "FROM productos p LEFT JOIN generos g ON g.id = p.genero_id "
                "WHERE p.descripcion IS NULL OR TRIM(p.descripcion) = '' "
                "ORDER BY p.id LIMIT %s", (LOTE,))
            pendientes = cur.fetchall()
        for prod in pendientes:
            texto, err = ai.generar_descripcion(prod['nombre'], prod['categoria'])
            if err or not texto:
                errores += 1
                continue
            with get_db_cursor() as cur:
                cur.execute("UPDATE productos SET descripcion = %s WHERE id = %s",
                            (texto, prod['id']))
            procesados += 1
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT COUNT(*) AS n FROM productos "
                        "WHERE descripcion IS NULL OR TRIM(descripcion) = ''")
            restantes = cur.fetchone()['n']
    except Exception as exc:
        return jsonify({'ok': False, 'error': f'Error en lote: {exc}'}), 500
    return jsonify({'ok': True, 'procesados': procesados, 'errores': errores,
                    'restantes': restantes})
