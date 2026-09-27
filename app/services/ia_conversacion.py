"""Conversación guardada del chat del panel (/admin/ia).

Antes la memoria del chat vivía solo en la pestaña del navegador: al cerrarla,
o desde otro equipo o el celular, el asistente empezaba de cero. Ahora cada
intercambio se guarda por usuario en la BD del cliente y el asistente toma los
últimos como contexto, sin importar desde dónde se escriba.

Reglas:
  - Cada usuario ve y usa solo su propia conversación (usuario_id de la sesión).
  - «Nueva conversación» la archiva: deja de usarse como contexto.
  - Lo de más de DIAS días se borra solo (es memoria del chat, no un registro
    del negocio; la auditoría de consultas sigue en ia_consultas).
  - Lo de nómina o documentos internos se guarda, pero nunca viaja a la nube:
    el filtro por herramienta (_historial_para_nube) se aplica igual.
  - Nunca rompe el chat: si la tabla no existe o la BD falla, se sigue sin memoria.

La tabla es idéntica a la migración 0017 del maestro; el código la crea si
esa migración aún no llegó al cliente.
"""
from flask import current_app, has_request_context, session

from database import _current_db_name, get_db_cursor

DIAS = 30
PARA_CONTEXTO = 6          # igual que ai_service._MAX_HISTORIAL
PARA_MOSTRAR = 20

_DDL = """
CREATE TABLE IF NOT EXISTS ia_conversacion (
    id          BIGSERIAL    PRIMARY KEY,
    usuario_id  INTEGER      NOT NULL,
    creado_en   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    pregunta    VARCHAR(300) NOT NULL,
    respuesta   VARCHAR(2000) NOT NULL,
    herramienta VARCHAR(80),
    archivada   BOOLEAN      NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_ia_conversacion_usuario
    ON ia_conversacion (usuario_id, archivada, creado_en DESC)
"""
_listas = set()             # BDs donde ya se aseguró la tabla en este proceso


def _usuario():
    if not has_request_context():
        return None
    try:
        return int(session.get('usuario_id'))
    except (TypeError, ValueError):
        return None


def _asegurar(cur):
    db = _current_db_name()
    if db not in _listas:
        cur.execute(_DDL)
        _listas.add(db)


def guardar(pregunta, respuesta, herramienta=''):
    usuario = _usuario()
    if usuario is None or not pregunta or not respuesta:
        return
    try:
        with get_db_cursor() as cur:
            _asegurar(cur)
            cur.execute("""INSERT INTO ia_conversacion (usuario_id, pregunta, respuesta, herramienta)
                           VALUES (%s, %s, %s, %s)""",
                        (usuario, str(pregunta)[:300], str(respuesta)[:2000],
                         (str(herramienta or '')[:80] or None)))
            cur.execute("DELETE FROM ia_conversacion WHERE usuario_id = %s "
                        "AND creado_en < NOW() - make_interval(days => %s)", (usuario, DIAS))
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'IA: no se pudo guardar la conversación ({exc})')


def recientes(limite=PARA_CONTEXTO):
    """Los últimos intercambios vigentes del usuario, del más viejo al más nuevo,
    con la forma del historial del chat. None si no se pudo leer (el chat usa
    entonces lo que mande el navegador)."""
    usuario = _usuario()
    if usuario is None:
        return None
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            _asegurar(cur)
            cur.execute("""SELECT pregunta, respuesta, COALESCE(herramienta, '') AS herramienta,
                                  creado_en
                           FROM ia_conversacion
                           WHERE usuario_id = %s AND NOT archivada
                             AND creado_en >= NOW() - make_interval(days => %s)
                           ORDER BY creado_en DESC, id DESC LIMIT %s""",
                        (usuario, DIAS, max(1, min(int(limite), 50))))
            filas = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'IA: no se pudo leer la conversación ({exc})')
        return None
    return [{'pregunta': f['pregunta'], 'respuesta': f['respuesta'],
             'herramienta': f['herramienta'], 'fecha': f['creado_en'].isoformat()}
            for f in reversed(filas)]


def nueva():
    """«Nueva conversación»: lo anterior deja de usarse como contexto."""
    usuario = _usuario()
    if usuario is None:
        return False
    try:
        with get_db_cursor() as cur:
            _asegurar(cur)
            cur.execute("UPDATE ia_conversacion SET archivada = TRUE "
                        "WHERE usuario_id = %s AND NOT archivada", (usuario,))
        return True
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'IA: no se pudo archivar la conversación ({exc})')
        return False
