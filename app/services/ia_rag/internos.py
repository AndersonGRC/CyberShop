"""Documentos internos del negocio: procedimientos, políticas, manuales.

Los escribe el dueño desde el panel (/admin/ia/documentos) y SOLO los lee el
asistente privado, según el rol de quien pregunta:

  administracion  dueño y superadministrador (rol base 1 o 2)
  equipo          todo el que puede usar el asistente del panel

Nunca son públicos: el indexador los guarda con canal_publico=FALSE y el chat
del sitio solo busca filas públicas. Tampoco salen hacia el respaldo en la
nube: la capacidad que los consulta está declarada solo local
(services/ia_datos/__init__.py).

La tabla de origen es esta; el índice (ia_documentos) se reconstruye desde
aquí. Archivar no borra nada: el documento deja de consultarse y se puede
restaurar.
"""

from database import _current_db_name, get_db_cursor
from services.ia_rag.indexador import FUENTES_INTERNAS, reindexar

VISIBILIDADES = tuple(FUENTES_INTERNAS)          # ('administracion', 'equipo')
_ROLES_ADMINISTRACION = {1, 2}
MAX_TITULO = 200
MAX_TEXTO = 20000                                # ~10 páginas; se indexa por partes

_DDL = """
CREATE TABLE IF NOT EXISTS ia_documentos_internos (
    id              SERIAL PRIMARY KEY,
    titulo          VARCHAR(200) NOT NULL,
    texto           TEXT         NOT NULL,
    visibilidad     VARCHAR(20)  NOT NULL DEFAULT 'administracion',
    activo          BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_por      INTEGER,
    creado_en       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    actualizado_por INTEGER,
    actualizado_en  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
"""
_TABLA_LISTA = set()      # BDs con la tabla ya verificada (por proceso)


def asegurar_tabla(cur):
    """La misma tabla que crea la migración 0016 del maestro, por si este
    cliente todavía no la tiene. Aditiva e idempotente."""
    clave = _current_db_name()
    if clave not in _TABLA_LISTA:
        cur.execute(_DDL)
        _TABLA_LISTA.add(clave)


def listar():
    with get_db_cursor(dict_cursor=True) as cur:
        asegurar_tabla(cur)
        cur.execute("""SELECT id, titulo, texto, visibilidad, activo, actualizado_en
                       FROM ia_documentos_internos
                       ORDER BY activo DESC, actualizado_en DESC""")
        return cur.fetchall()


def obtener(doc_id):
    with get_db_cursor(dict_cursor=True) as cur:
        asegurar_tabla(cur)
        cur.execute("""SELECT id, titulo, texto, visibilidad, activo
                       FROM ia_documentos_internos WHERE id = %s""", (doc_id,))
        return cur.fetchone()


def guardar(titulo, texto, visibilidad, doc_id=None, usuario_id=None):
    """Crea o actualiza un documento y lo deja buscable. Devuelve su id.
    ValueError con un mensaje para el dueño si algo no cuadra."""
    titulo = (titulo or '').strip()
    texto = (texto or '').strip()
    if not titulo:
        raise ValueError('Escribe un título para el documento.')
    if not texto:
        raise ValueError('El documento no tiene contenido.')
    if len(titulo) > MAX_TITULO:
        raise ValueError(f'El título admite hasta {MAX_TITULO} caracteres.')
    if len(texto) > MAX_TEXTO:
        raise ValueError('El documento admite hasta 20.000 caracteres; divídelo en varios.')
    if visibilidad not in VISIBILIDADES:
        raise ValueError('Elige quién puede consultarlo.')
    with get_db_cursor(dict_cursor=True) as cur:
        asegurar_tabla(cur)
        if doc_id:
            cur.execute("""UPDATE ia_documentos_internos
                           SET titulo = %s, texto = %s, visibilidad = %s,
                               actualizado_por = %s, actualizado_en = NOW()
                           WHERE id = %s RETURNING id""",
                        (titulo, texto, visibilidad, usuario_id, doc_id))
            fila = cur.fetchone()
            if not fila:
                raise ValueError('Ese documento ya no existe.')
        else:
            cur.execute("""INSERT INTO ia_documentos_internos
                               (titulo, texto, visibilidad, creado_por, actualizado_por)
                           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                        (titulo, texto, visibilidad, usuario_id, usuario_id))
            fila = cur.fetchone()
    reindexar(['interno'], limpiar=False)
    return fila['id']


def cambiar_estado(doc_id, activo, usuario_id=None):
    """Archiva (activo=False) o restaura un documento. Nunca lo borra."""
    with get_db_cursor() as cur:
        asegurar_tabla(cur)
        cur.execute("""UPDATE ia_documentos_internos
                       SET activo = %s, actualizado_por = %s, actualizado_en = NOW()
                       WHERE id = %s""", (bool(activo), usuario_id, doc_id))
        cambiado = cur.rowcount > 0
    if cambiado:
        reindexar(['interno'], limpiar=False)
    return cambiado


def visibilidades_de(rol_id):
    """Qué documentos puede leer un rol. Se mira el rol BASE: un rol
    personalizado derivado de Empleado no ve los de administración."""
    if rol_id is None:
        return ()
    try:
        from services.permisos_service import rol_base_efectivo
        base = rol_base_efectivo(rol_id)
    except Exception:  # noqa: BLE001
        base = rol_id
    return VISIBILIDADES if base in _ROLES_ADMINISTRACION else ('equipo',)


def buscar_para_rol(consulta, rol_id, limite=3):
    """Partes de documentos activos que responden la consulta y que ese rol
    puede leer. Sin el índice (cliente sin la migración 0012), busca directo
    en la tabla de origen: peor, pero nunca deja de responder."""
    visibles = visibilidades_de(rol_id)
    texto = (consulta or '').strip()
    if not visibles or len(texto) < 3:
        return []
    from services.ia_rag.buscar import buscar
    from services.ia_rag.indexador import indice_disponible
    if indice_disponible():
        return buscar(texto, solo_publico=False, limite=limite,
                      fuentes=[FUENTES_INTERNAS[v] for v in visibles])
    with get_db_cursor(dict_cursor=True) as cur:
        asegurar_tabla(cur)
        cur.execute("""SELECT id, titulo, texto FROM ia_documentos_internos
                       WHERE activo AND visibilidad = ANY(%s)
                         AND (titulo ILIKE %s OR texto ILIKE %s)
                       ORDER BY actualizado_en DESC LIMIT %s""",
                    (list(visibles), f'%{texto}%', f'%{texto}%', limite))
        return [{'fuente': 'interno', 'fuente_id': str(r['id']), 'titulo': r['titulo'],
                 'texto': r['texto'], 'url': None, 'score': 0, 'via': 'contiene'}
                for r in cur.fetchall()]
