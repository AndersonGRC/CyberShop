"""routes/ia.py — Endpoints del Asistente IA (módulo ai_assistant).

Todos exigen rol staff y que el módulo esté disponible para el tenant actual.
AISLAMIENTO: estas vistas NUNCA reciben un tenant_id; toda lectura/escritura de
BD usa get_db_cursor(), que resuelve a la BD del tenant del request. El servicio
ai_service arma el contexto solo desde esa BD.
"""

import json

from flask import (Blueprint, current_app, request, jsonify, render_template, Response,
                   stream_with_context)

from security import registrar_guard_permiso, rol_requerido, ADMIN_FULL, ADMIN_STAFF
from database import get_db_cursor
from helpers import get_data_app
import services.ai_service as ai

ia_bp = Blueprint('ia', __name__, url_prefix='/admin/ia')

# Permisos dinámicos (matriz del Propietario): guard 'ver' de todo el
# blueprint. Convive con los @rol_requerido existentes (defensa doble).
registrar_guard_permiso(ia_bp, 'ai_assistant')


def _guard():
    """Devuelve None si la IA está disponible, o una respuesta JSON 403."""
    if not ai.ia_disponible():
        _ok, motivo = ai.estado_ia()
        return jsonify({'ok': False, 'error': motivo}), 403
    return None


@ia_bp.route('/')
@rol_requerido(ADMIN_STAFF)
def panel():
    """Página del Asistente IA. Solo si el cliente tiene el módulo (plan con IA)."""
    from tenant_features import is_module_active, MODULE_AI
    if not is_module_active(MODULE_AI):
        from flask import redirect, url_for, flash
        flash('El Asistente IA no está incluido en tu plan.', 'warning')
        return redirect(url_for('admin.dashboard_admin'))
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


@ia_bp.route('/contenido', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def contenido():
    """IA para secciones de Contenido Web (publicaciones, slides, servicios).
    accion='generar' (desde el título) o 'mejorar' (reescribe el texto dado)."""
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    if (d.get('accion') or '').strip() == 'mejorar':
        texto, err = ai.mejorar_contenido(d.get('texto', ''))
    else:
        texto, err = ai.generar_contenido(
            d.get('titulo', ''), d.get('tipo', 'contenido'), d.get('detalle', ''))
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
    res, err = ai.responder_chat(d.get('pregunta', ''), historial=d.get('historial'))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True, **res})


@ia_bp.route('/consultas')
@rol_requerido(ADMIN_FULL)
def consultas():
    """Uso del asistente, preguntas que aún no sabe responder y consultas
    sensibles recientes (solo dueño). Lee ia_consultas del tenant actual."""
    try:
        dias = int(request.args.get('dias', 30))
    except (TypeError, ValueError):
        dias = 30
    return jsonify({'ok': True, **ai.resumen_consultas(dias)})


@ia_bp.route('/alertas')
@rol_requerido(ADMIN_STAFF)
def alertas():
    """Alertas del negocio para el dashboard. NO usa el modelo de IA: salen
    aunque el servidor de IA esté apagado, y solo las que el cargo puede ver."""
    from services.ia_datos.alertas import alertas_negocio
    refrescar = request.args.get('refrescar') == '1'
    return jsonify({'ok': True, **alertas_negocio(refrescar=refrescar)})


@ia_bp.route('/resumen-correo', methods=['GET', 'POST'])
@rol_requerido(ADMIN_FULL)
def resumen_correo():
    """Interruptor del resumen diario por correo (solo dueño). GET devuelve la
    configuración; POST la guarda; POST con prueba=true arma el correo sin enviarlo."""
    from services.ia_resumen_correo import enviar_diario, guardar_config, leer_config
    try:
        if request.method == 'GET':
            return jsonify({'ok': True, **leer_config()})
        d = request.get_json(silent=True) or {}
        if d.get('prueba'):
            res = enviar_diario(prueba=True)
            return jsonify({'ok': True, 'asunto': res.get('asunto'), 'texto': res.get('texto'),
                            'destinos': res.get('destinos')})
        destinos = d.get('destinos')
        if isinstance(destinos, str):
            destinos = destinos.split(',')
        config = guardar_config(activo=d.get('activo'), destinos=destinos)
        return jsonify({'ok': True, **config})
    except Exception as exc:  # noqa: BLE001
        # Antes un fallo aquí daba 500 y el panel solo decía "no se pudo guardar":
        # ahora el motivo viaja al panel y queda en el log del cliente.
        current_app.logger.error(f'resumen-correo ({request.method}): {exc}', exc_info=True)
        return jsonify({'ok': False, 'error': f'{type(exc).__name__}: {exc}'}), 200


@ia_bp.route('/resumen-negocio', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def resumen_negocio():
    """Resumen ejecutivo del dashboard (4-5 líneas accionables con datos
    reales). Con caché de 1h; force=true lo regenera."""
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    res, err = ai.resumen_ejecutivo(force=bool(d.get('force')))
    if err:
        return jsonify({'ok': False, 'error': err}), 400
    return jsonify({'ok': True, **res})


@ia_bp.route('/chat-stream', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def chat_stream():
    """Chat del negocio en STREAMING (Server-Sent Events): la respuesta se
    pinta palabra a palabra en el panel. El desktop y el respaldo del panel
    siguen usando /chat (respuesta completa). Eventos: meta, delta, fin, error."""
    g = _guard()
    if g:
        return g
    d = request.get_json(silent=True) or {}
    pregunta = d.get('pregunta', '')
    historial = d.get('historial')

    def gen():
        # stream_with_context mantiene vivo el request (get_db_cursor del
        # tenant sigue resolviendo dentro del generador).
        for evento, dato in ai.responder_chat_stream(pregunta, historial=historial):
            if evento == 'latido':
                # Comentario SSE: el navegador lo ignora, pero Cloudflare y nginx ven
                # tráfico y no cortan mientras el modelo carga en frío (1-3 min).
                yield ": latido\n\n"
                continue
            yield f"data: {json.dumps({'e': evento, 'd': dato}, ensure_ascii=False)}\n\n"

    return Response(stream_with_context(gen()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache',
                             # nginx: no bufferizar el SSE (si no, llega en bloque)
                             'X-Accel-Buffering': 'no'})


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
