"""Bitácora de lo que sabe la IA: quién cambió qué y cuándo.

Cada alta, edición, borrado o archivo de una pregunta frecuente o de un
documento interno queda aquí con una foto de ANTES y de DESPUÉS. Con esa foto
se puede ver el cambio y deshacerlo (services/ia_rag/conocimiento.py →
restaurar): borrar una pregunta frecuente ya no la pierde para siempre.

Solo se agregan filas: nada de este módulo actualiza ni borra la bitácora.
La tabla es la misma de la migración 0028 del maestro; si el cliente aún no la
tiene, se crea aquí (aditivo e idempotente).

También anota lo que se hizo con las preguntas que el chat no supo responder
(tipo «pregunta»: respondida con una pregunta frecuente o descartada), para no
volver a mostrarlas como pendientes.
"""

import hashlib
import re
import unicodedata

from flask import current_app, has_request_context, session
from psycopg2.extras import Json

from database import _current_db_name, get_db_cursor

TIPOS = ('faq', 'documento', 'pregunta')
ACCIONES = ('crear', 'editar', 'publicar', 'despublicar', 'eliminar', 'archivar',
            'restaurar', 'responder', 'descartar')

_DDL = """
CREATE TABLE IF NOT EXISTS ia_conocimiento_log (
    id             BIGSERIAL    PRIMARY KEY,
    creado_en      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    usuario_id     INTEGER,
    usuario_nombre VARCHAR(150),
    tipo           VARCHAR(20)  NOT NULL,
    accion         VARCHAR(20)  NOT NULL,
    objeto_id      VARCHAR(64),
    titulo         VARCHAR(300) NOT NULL DEFAULT '',
    antes          JSONB,
    despues        JSONB,
    origen         VARCHAR(20)  NOT NULL DEFAULT 'panel'
);
CREATE INDEX IF NOT EXISTS idx_ia_conocimiento_log_fecha
    ON ia_conocimiento_log (creado_en DESC);
CREATE INDEX IF NOT EXISTS idx_ia_conocimiento_log_objeto
    ON ia_conocimiento_log (tipo, objeto_id);
"""
_TABLA_LISTA = set()      # BDs con la tabla ya verificada (por proceso)


def asegurar_tabla(cur):
    clave = _current_db_name()
    if clave not in _TABLA_LISTA:
        cur.execute(_DDL)
        _TABLA_LISTA.add(clave)


def _usuario():
    if not has_request_context():
        return None, None
    return session.get('usuario_id'), (session.get('username') or '')[:150] or None


def _limpiar(valor):
    """La foto que se guarda: solo tipos simples (fechas como texto)."""
    if valor is None:
        return None
    return {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in dict(valor).items()}


def registrar(tipo, accion, objeto_id=None, titulo='', antes=None, despues=None,
              origen='panel'):
    """Agrega una fila. Nunca lanza: si la bitácora falla, el cambio ya hecho
    no se deshace, pero queda la advertencia en el log del servidor."""
    usuario_id, usuario_nombre = _usuario()
    try:
        with get_db_cursor() as cur:
            asegurar_tabla(cur)
            cur.execute(
                """INSERT INTO ia_conocimiento_log
                       (usuario_id, usuario_nombre, tipo, accion, objeto_id, titulo,
                        antes, despues, origen)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (usuario_id, usuario_nombre, tipo, accion,
                 None if objeto_id is None else str(objeto_id)[:64],
                 (titulo or '').strip()[:300],
                 Json(_limpiar(antes)) if antes is not None else None,
                 Json(_limpiar(despues)) if despues is not None else None,
                 (origen or 'panel')[:20]))
        return True
    except Exception as exc:  # noqa: BLE001
        try:
            current_app.logger.warning(f'bitácora IA: no se pudo registrar {tipo}/{accion} ({exc})')
        except Exception:
            pass
        return False


def listar(tipos=None, limite=100, objeto_id=None):
    """Últimos cambios, del más reciente al más viejo."""
    limite = max(1, min(int(limite or 100), 500))
    where, params = ['TRUE'], []
    if tipos:
        where.append('tipo = ANY(%s)')
        params.append(list(tipos))
    if objeto_id is not None:
        where.append('objeto_id = %s')
        params.append(str(objeto_id))
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            asegurar_tabla(cur)
            cur.execute(f"""SELECT id, creado_en, usuario_id, usuario_nombre, tipo, accion,
                                   objeto_id, titulo, antes, despues, origen
                            FROM ia_conocimiento_log WHERE {' AND '.join(where)}
                            ORDER BY creado_en DESC, id DESC LIMIT %s""", params + [limite])
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'bitácora IA: no se pudo leer ({exc})')
        return []


def obtener(log_id):
    with get_db_cursor(dict_cursor=True) as cur:
        asegurar_tabla(cur)
        cur.execute("""SELECT id, creado_en, usuario_id, usuario_nombre, tipo, accion,
                              objeto_id, titulo, antes, despues, origen
                       FROM ia_conocimiento_log WHERE id = %s""", (log_id,))
        fila = cur.fetchone()
        return dict(fila) if fila else None


# ── Preguntas sin responder ────────────────────────────────────

def normalizar_pregunta(texto):
    """Misma pregunta escrita distinto → misma clave («¿Hacen domicilios?» y
    «hacen domicilios» son una sola)."""
    plano = unicodedata.normalize('NFKD', str(texto or '').lower())
    plano = ''.join(c for c in plano if not unicodedata.combining(c))
    plano = re.sub(r'[^a-z0-9ñ ]+', ' ', plano)
    return ' '.join(plano.split())


def clave_pregunta(texto):
    return hashlib.md5(normalizar_pregunta(texto).encode('utf-8')).hexdigest()


def preguntas_atendidas():
    """Claves de las preguntas ya respondidas o descartadas."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            asegurar_tabla(cur)
            cur.execute("""SELECT DISTINCT objeto_id FROM ia_conocimiento_log
                           WHERE tipo = 'pregunta' AND accion IN ('responder', 'descartar')""")
            return {r['objeto_id'] for r in cur.fetchall()}
    except Exception:  # noqa: BLE001
        return set()
