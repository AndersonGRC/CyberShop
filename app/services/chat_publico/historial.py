"""services/chat_publico/historial.py — Preguntas del canal público que nadie
supo responder (lo que falta agregar a las preguntas frecuentes).

Lee la misma tabla ia_consultas que ya llena services/chat_publico/motor.py
en cada respuesta (motor.py::_registrar(), sin IP ni datos del visitante).

Purga propia de 90 días: la de services/ai_service.py solo corre cuando el
PANEL registra una consulta, y ai_public puede estar activo sin
ai_assistant — sin esto, esas preguntas nunca se limpiarían para un cliente
que solo usa el chat público. Como a esta función solo la llama la pantalla
de configuración (un dueño mirándola de vez en cuando, no cada mensaje del
chat), la purga corre en cada llamada sin necesitar la caché de "ya purgué
hoy" que sí tiene ai_service.py para su volumen mucho mayor.
"""
from database import get_db_cursor
from services.ia_datos.acceso import CANAL_PUBLICO


def preguntas_sin_responder(limite=30):
    """Las últimas preguntas del chat público que no encontraron capacidad
    para responder — la lista de qué agregar a las preguntas frecuentes."""
    limite = max(1, min(int(limite or 30), 100))
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT to_regclass('public.ia_consultas') AS t")
            if cur.fetchone()['t'] is None:
                return []
            cur.execute(
                """UPDATE ia_consultas SET pregunta_sin_herramienta = NULL
                   WHERE canal = %s AND pregunta_sin_herramienta IS NOT NULL
                     AND creado_en < NOW() - INTERVAL '90 days'""",
                (CANAL_PUBLICO,))
            cur.execute(
                """SELECT creado_en, pregunta_sin_herramienta FROM ia_consultas
                   WHERE canal = %s AND pregunta_sin_herramienta IS NOT NULL
                   ORDER BY creado_en DESC LIMIT %s""",
                (CANAL_PUBLICO, limite))
            return [{'fecha': r['creado_en'].isoformat(timespec='minutes'),
                     'pregunta': r['pregunta_sin_herramienta']} for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        try:
            from flask import current_app
            current_app.logger.warning(f'chat público: preguntas_sin_responder falló ({exc})')
        except Exception:
            pass
        return []
