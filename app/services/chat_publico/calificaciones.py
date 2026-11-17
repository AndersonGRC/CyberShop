"""services/chat_publico/calificaciones.py — «¿Te sirvió?» 👍 / 👎 en el chat del sitio.

Cada respuesta del chat lleva un `calificar` firmado (con la llave de la app y
el nombre de la BD de la tienda) que trae el ID de la consulta, la pregunta y
el comienzo de la respuesta. Así:

  - nadie puede calificar respuestas que no recibió ni de otra tienda;
  - una respuesta se califica una sola vez (índice único);
  - la pregunta y la respuesta SOLO se guardan si el visitante dijo que no le
    sirvió (es lo que hay que corregir); un 👍 guarda solo que sirvió. Sin IP ni
    datos del visitante. El texto se borra a los 90 días, como las preguntas
    sin respuesta (services/chat_publico/historial.py).

Las que no sirvieron aparecen en /admin/chat-publico/conocimiento con
«Responder» (crea la pregunta frecuente) y «Descartar».
"""
from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer

from database import _current_db_name, get_db_cursor

_MAX_EDAD_S = 24 * 3600            # se puede calificar hasta un día después
_DDL = """
CREATE TABLE IF NOT EXISTS ia_calificaciones (
    id          BIGSERIAL    PRIMARY KEY,
    creado_en   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    consulta_id BIGINT       NOT NULL,
    canal       VARCHAR(20)  NOT NULL DEFAULT 'publico',
    util        BOOLEAN      NOT NULL,
    pregunta    VARCHAR(200),
    respuesta   VARCHAR(500),
    via         VARCHAR(20)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ia_calificaciones_consulta
    ON ia_calificaciones (canal, consulta_id);
CREATE INDEX IF NOT EXISTS idx_ia_calificaciones_fecha
    ON ia_calificaciones (creado_en DESC);
"""
_TABLA_LISTA = set()


def asegurar_tabla(cur):
    clave = _current_db_name()
    if clave not in _TABLA_LISTA:
        cur.execute(_DDL)
        _TABLA_LISTA.add(clave)


def _firmador():
    return URLSafeTimedSerializer(current_app.secret_key,
                                  salt=f'chat-calificar:{_current_db_name()}')


def token(consulta_id, pregunta, respuesta, via):
    """El `calificar` que viaja con la respuesta. None si no hay consulta."""
    if not consulta_id:
        return None
    try:
        return _firmador().dumps({'c': int(consulta_id), 'p': (pregunta or '')[:200],
                                  'r': (respuesta or '')[:500], 'v': (via or '')[:20]})
    except Exception:  # noqa: BLE001
        return None


def registrar(token_firmado, util):
    """Guarda la calificación. True si quedó (o ya estaba), False si el token no vale."""
    if not isinstance(token_firmado, str) or not isinstance(util, bool) or len(token_firmado) > 4000:
        return False
    try:
        datos = _firmador().loads(token_firmado, max_age=_MAX_EDAD_S)
        consulta_id = int(datos['c'])
    except (BadSignature, KeyError, TypeError, ValueError):
        return False
    try:
        with get_db_cursor() as cur:
            asegurar_tabla(cur)
            cur.execute(
                """INSERT INTO ia_calificaciones (consulta_id, canal, util, pregunta, respuesta, via)
                   VALUES (%s, 'publico', %s, %s, %s, %s)
                   ON CONFLICT (canal, consulta_id) DO NOTHING""",
                (consulta_id, util,
                 None if util else (datos.get('p') or None),
                 None if util else (datos.get('r') or None),
                 (datos.get('v') or None)))
        return True
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'chat público: no se pudo guardar la calificación ({exc})')
        return False


def resumen(dias=30):
    """{'utiles', 'no_utiles', 'porcentaje'} de los últimos días."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            asegurar_tabla(cur)
            cur.execute("""SELECT COUNT(*) FILTER (WHERE util) AS si,
                                  COUNT(*) FILTER (WHERE NOT util) AS no
                           FROM ia_calificaciones
                           WHERE creado_en > NOW() - make_interval(days => %s)""", (int(dias),))
            fila = cur.fetchone()
    except Exception:  # noqa: BLE001
        return {'utiles': 0, 'no_utiles': 0, 'porcentaje': None}
    total = (fila['si'] or 0) + (fila['no'] or 0)
    return {'utiles': fila['si'] or 0, 'no_utiles': fila['no'] or 0,
            'porcentaje': round(100 * (fila['si'] or 0) / total) if total else None}


def no_sirvieron(limite=20, excluir=()):
    """Las respuestas que no le sirvieron al visitante, de la más nueva a la más
    vieja, sin las ya atendidas (claves de services/ia_rag/bitacora.py)."""
    from services.ia_rag.bitacora import clave_pregunta
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            asegurar_tabla(cur)
            cur.execute("""UPDATE ia_calificaciones SET pregunta = NULL, respuesta = NULL
                           WHERE pregunta IS NOT NULL AND creado_en < NOW() - INTERVAL '90 days'""")
            cur.execute("""SELECT id, creado_en, pregunta, respuesta, via FROM ia_calificaciones
                           WHERE NOT util AND pregunta IS NOT NULL
                           ORDER BY creado_en DESC LIMIT 200""")
            filas = [dict(f) for f in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []
    salida, vistas = [], set()
    for f in filas:
        clave = clave_pregunta(f['pregunta'])
        if clave in excluir or clave in vistas:
            continue
        vistas.add(clave)
        salida.append(f)
        if len(salida) >= limite:
            break
    return salida
