"""routes/chat_publico.py — Endpoints del chat público (módulo ai_public).

Expone el motor de `services/chat_publico/` a visitantes anónimos del sitio.
AISLAMIENTO: estas vistas nunca reciben ni fijan un tenant_id — usan
get_current_tenant_id()/get_db_cursor() como el resto de la app, resueltos por
el before_request de tenant_resolver. Sin sesión, sin cookies nuevas.

Defensa en capas, en este orden en cada vista:
  1. CSRF real (CSRFProtect global; el widget manda X-CSRFToken, ver
     static/js/chat_publico.js). Nada de @_csrf_exempt: ese atributo no lo lee
     Flask-WTF en este repo (solo csrf.exempt() explícito en app.py).
  2. Rate limit (ver decoradores de cada ruta).
  3. Gate de módulo: is_module_active(MODULE_AI_PUBLIC) → 404 minimalista si
     está apagado (NO abort(404): eso renderiza la página 404.html completa
     con marca del cliente, pensada para navegación, no para una API).
  4. Validación defensiva del payload + señuelo anti-bot (honeypot).
  5. Verificación humana (reCAPTCHA una vez por carga de página, por token
     firmado), solo si la instancia tiene configuradas AMBAS llaves.
  6. Todo el cuerpo en try/except amplio: esta ruta nunca debe dar 500.

Esta capa es independiente de la lista blanca del motor
(services/ia_datos/acceso.py::puede_usar): aunque algo aquí fallara, el motor
igual se niega a servir cualquier capacidad no declarada pública.
"""

import requests
from flask import Blueprint, current_app, jsonify, request
from itsdangerous import URLSafeTimedSerializer

from extensions import limiter
from security import controlar_tasa_solicitudes
from services.chat_publico import config_publica, responder
from tenant_features import MODULE_AI_PUBLIC, is_module_active

chat_publico_bp = Blueprint('chat_publico', __name__, url_prefix='/chat')

# Límites de la capa HTTP (además de los que ya aplica el motor internamente:
# MAX_PREGUNTA=300, MAX_HISTORIAL=4 en services/chat_publico/motor.py).
_MAX_BYTES_REQUEST = 8 * 1024        # un mensaje de chat no necesita más
_MAX_PREGUNTA_HTTP = 1000            # tope antes de que el motor la recorte a 300
_MAX_HISTORIAL_ITEMS = 8
_MAX_TEXTO_HISTORIAL = 500

_MSG_NO_DISPONIBLE = 'El chat no está disponible en este momento.'

# Campo señuelo: mismo patrón que 'website'/'website2' ya usan /enviar-mensaje
# y /prueba-gratis (routes/public.py) — un nombre propio para no chocar.
_CAMPO_SENUELO = 'asunto_web'

# Verificación humana SIN sesión ni cookies: reCAPTCHA se resuelve una sola vez
# por carga de página, y esa prueba se lleva en un token firmado que el propio
# cliente reenvía en los mensajes siguientes — nada que guardar en el servidor.
_SALT_VERIFICACION = 'chat-publico-verificacion-humana'
_VERIFICACION_MAX_EDAD_S = 3600


def _verificacion_activa():
    """Las dos llaves o ninguna: con solo la secreta el servidor exigiría una
    verificación que el widget no sabe mostrar (sin site key) y el chat
    quedaría bloqueado."""
    return bool(current_app.config.get('RECAPTCHA_SITE_KEY')
                and current_app.config.get('RECAPTCHA_SECRET_KEY'))


def _serializador_verificacion():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=_SALT_VERIFICACION)


def _emitir_token_verificacion():
    return _serializador_verificacion().dumps({'ok': True})


def _token_verificacion_valido(token):
    if not token or not isinstance(token, str):
        return False
    try:
        _serializador_verificacion().loads(token, max_age=_VERIFICACION_MAX_EDAD_S)
        return True
    except Exception:  # noqa: BLE001 — firma inválida, vencida o malformada
        return False


def _verificar_recaptcha(respuesta_token, ip):
    """Mismo patrón que routes/public.py::enviar_mensaje. False ante
    cualquier problema — nunca deja pasar por un error de red."""
    secret = current_app.config.get('RECAPTCHA_SECRET_KEY')
    if not secret or not respuesta_token:
        return False
    try:
        r = requests.post('https://www.google.com/recaptcha/api/siteverify', data={
            'secret': secret, 'response': respuesta_token, 'remoteip': ip,
        }, timeout=5)
        return bool(r.json().get('success'))
    except Exception:  # noqa: BLE001
        return False


def _modulo_apagado():
    """404 minimalista: nunca la página 404.html con marca del cliente."""
    return jsonify({'error': 'not_found'}), 404


def _sanear_historial(bruto):
    """Recorta el historial ANTES de que llegue al motor. Defensivo: hoy el
    motor ni siquiera lee su contenido, pero el contrato de la API lo acepta
    para no tener que rediseñarlo si algún día se usa."""
    if not isinstance(bruto, list):
        return None
    limpio = []
    for item in bruto[-_MAX_HISTORIAL_ITEMS:]:
        if not isinstance(item, dict):
            continue
        rol = item.get('rol')
        texto = item.get('texto')
        if rol not in ('usuario', 'asistente') or not isinstance(texto, str):
            continue
        limpio.append({'rol': rol, 'texto': texto.strip()[:_MAX_TEXTO_HISTORIAL]})
    return limpio or None


@chat_publico_bp.route('/config', methods=['GET'])
def config():
    """Lo que el widget necesita para pintar su estado inicial."""
    if not controlar_tasa_solicitudes(request.remote_addr, max_requests=30, interval=60):
        return jsonify({'error': 'rate_limited'}), 429
    if not is_module_active(MODULE_AI_PUBLIC):
        return _modulo_apagado()
    try:
        salida = config_publica()
        # Ausente por completo si no está configurada: el widget no debe ni
        # intentar cargar el script de reCAPTCHA cuando no hace falta.
        if _verificacion_activa():
            salida['recaptcha_site_key'] = current_app.config['RECAPTCHA_SITE_KEY']
        return jsonify(salida)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'chat público: /config falló ({exc})')
        return jsonify({'error': 'internal'}), 200  # el widget no debe romperse por esto


@chat_publico_bp.route('/mensaje', methods=['POST'])
@limiter.limit('8 per minute; 60 per hour')
def mensaje():
    """Respuesta completa a una pregunta del visitante."""
    if not is_module_active(MODULE_AI_PUBLIC):
        return _modulo_apagado()

    try:
        if request.content_length and request.content_length > _MAX_BYTES_REQUEST:
            return jsonify({'error': 'payload_too_large'}), 413

        datos = request.get_json(silent=True)
        if not isinstance(datos, dict):
            return jsonify({'error': 'invalid_payload'}), 400

        # Señuelo: un visitante real nunca lo llena (está fuera de pantalla).
        # Mismo 404 minimalista que el módulo apagado — nunca un mensaje que
        # le confirme al bot que fue detectado.
        if (datos.get(_CAMPO_SENUELO) or '').strip():
            return _modulo_apagado()

        pregunta = datos.get('pregunta')
        if not isinstance(pregunta, str) or not pregunta.strip():
            return jsonify({'error': 'invalid_payload'}), 400
        pregunta = pregunta.strip()[:_MAX_PREGUNTA_HTTP]

        # Verificación humana: solo si el servidor tiene reCAPTCHA configurado
        # (si no, el chat sigue con honeypot + límite de tasa solamente). Una
        # vez validado el checkbox, el token firmado que se devuelve sirve
        # para el resto de la conversación — sin sesión ni cookies.
        token_nuevo = None
        if _verificacion_activa():
            if not _token_verificacion_valido(datos.get('verificacion')):
                if not _verificar_recaptcha(datos.get('recaptcha'), request.remote_addr):
                    return jsonify({'error': 'verificacion_requerida'}), 400
                token_nuevo = _emitir_token_verificacion()

        historial = _sanear_historial(datos.get('historial'))

        salida = responder(pregunta, historial=historial)
        if token_nuevo:
            salida['verificacion'] = token_nuevo
        return jsonify(salida)
    except Exception as exc:  # noqa: BLE001
        # Nunca 500: la filosofía de motor.py ("nunca lanza") se sostiene también
        # en la capa HTTP. Se responde con lo mismo que el motor daría sin modelo.
        current_app.logger.error(f'chat público: /mensaje falló ({exc})')
        try:
            whatsapp = config_publica().get('whatsapp')
        except Exception:
            whatsapp = None
        return jsonify({'respuesta': _MSG_NO_DISPONIBLE, 'via': 'error',
                        'fuentes': [], 'escalar': bool(whatsapp), 'whatsapp': whatsapp,
                        'ms': 0})
