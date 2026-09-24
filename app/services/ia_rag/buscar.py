"""Búsqueda en el índice de textos del negocio.

Dos pasadas, de más a menos precisa:

  1. **Por palabras** (`to_tsvector`/`plainto_tsquery` en español): entiende
     plurales y conjugaciones, así que «hacen envíos» encuentra «enviamos».
  2. **Por parecido** (pg_trgm), solo si la primera no encontró nada: rescata
     preguntas con errores de escritura («domisilios»).

Si el cliente no tiene las extensiones, ambas degradan a un ILIKE simple: peor,
pero nunca deja de funcionar.

`solo_publico=True` es el candado del chat del sitio: una fila que no esté
marcada como pública no sale, sin importar lo que pregunten ni cómo.
"""

from flask import current_app

from database import get_db_cursor
from services.ia_datos.base import _existe

LIMITE_DEFECTO = 4
_MIN_RANK = 0.01          # por debajo de esto el "resultado" es ruido
_MIN_RANK_OR = 0.02       # la pasada permisiva exige un poco más para no traer ruido
_MIN_PARECIDO = 0.3       # similitud de trigramas

# Sinónimos del día a día: la gente pregunta «¿a qué hora abren?» y el negocio
# escribió «horario de atención». El buscador entiende plurales y conjugaciones,
# pero no que dos palabras distintas signifiquen lo mismo.
#
# Es una lista corta y explícita a propósito, para poder leerla y discutirla. Se
# aplica SOLO a la pregunta (nunca al texto del negocio) y solo en las pasadas
# permisivas, así no ensucia la búsqueda exacta. Cuando el servidor tenga el
# modelo de embeddings, esto se vuelve innecesario.
SINONIMOS = {
    'abren': 'horario atencion abrimos', 'abre': 'horario atencion abrimos',
    'cierran': 'horario atencion', 'atienden': 'horario atencion',
    'hora': 'horario', 'horas': 'horario', 'festivos': 'horario domingos',
    'mandan': 'envio domicilio', 'envian': 'envio domicilio',
    'llevan': 'domicilio envio', 'traen': 'domicilio envio',
    'nequi': 'pago transferencia', 'daviplata': 'pago transferencia',
    'datafono': 'pago tarjeta', 'contraentrega': 'pago contra entrega',
    'ustedes': 'nosotros empresa', 'quienes': 'nosotros empresa',
    'empresa': 'nosotros', 'tienda': 'nosotros negocio',
    'devolver': 'devolucion cambio', 'cambiar': 'cambio devolucion',
    'reparan': 'reparacion servicio mantenimiento', 'arreglan': 'reparacion mantenimiento',
    'vale': 'precio', 'cuesta': 'precio', 'valen': 'precio',
    'ubicados': 'direccion ubicacion', 'queda': 'direccion ubicacion',
    'factura': 'facturacion garantia',
}


def expandir(consulta):
    """La pregunta más los sinónimos de las palabras que usó."""
    from services.ia.enrutador import normalizar
    palabras = normalizar(consulta).replace('¿', ' ').replace('?', ' ').split()
    extra = [SINONIMOS[p] for p in palabras if p in SINONIMOS]
    return f"{consulta} {' '.join(extra)}".strip() if extra else consulta


def _tiene(cur, extension):
    try:
        cur.execute('SELECT 1 FROM pg_extension WHERE extname = %s', (extension,))
        return cur.fetchone() is not None
    except Exception:
        return False


def _fila(r, via):
    return {
        'fuente': r['fuente'],
        'fuente_id': r['fuente_id'],
        'titulo': r['titulo'],
        'texto': r['texto'],
        'url': r['url'],
        'score': round(float(r['score'] or 0), 4),
        'via': via,
    }


def buscar(consulta, solo_publico=True, limite=LIMITE_DEFECTO, fuentes=None):
    """Documentos que responden la pregunta. Lista vacía si no hay nada decente."""
    texto = (consulta or '').strip()
    if len(texto) < 3:
        return []
    limite = max(1, min(10, int(limite or LIMITE_DEFECTO)))

    where = ['TRUE']
    params_base = []
    if solo_publico:
        where.append('canal_publico')
    if fuentes:
        where.append('fuente = ANY(%s)')
        params_base.append(list(fuentes))
    filtro = ' AND '.join(where)

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if not _existe(cur, 'ia_documentos'):
                return []
            normaliza = 'unaccent(%s)' if _tiene(cur, 'unaccent') else '%s'
            expandido = expandir(texto)

            # 1) por palabras
            cur.execute(f"""
                SELECT fuente, fuente_id, titulo, texto, url,
                       ts_rank(tsv, plainto_tsquery('spanish', {normaliza})) AS score
                FROM ia_documentos
                WHERE {filtro} AND tsv @@ plainto_tsquery('spanish', {normaliza})
                ORDER BY score DESC, actualizado_en DESC
                LIMIT %s
            """, [texto] + params_base + [texto, limite])
            filas = [_fila(r, 'palabras') for r in cur.fetchall()
                     if float(r['score'] or 0) >= _MIN_RANK]
            if filas:
                return filas

            # 2) las mismas palabras, pero con que aparezca ALGUNA.
            # plainto_tsquery exige TODAS, y así «¿puedo pagar con Nequi?» no
            # encontraba la respuesta de formas de pago solo porque el texto no
            # dice «puedo». Se ordena por ts_rank, que premia al que trae más.
            cur.execute(f"""
                WITH q AS (
                    SELECT array_to_string(
                               tsvector_to_array(to_tsvector('spanish', {normaliza})), ' | '
                           )::tsquery AS tq
                )
                SELECT d.fuente, d.fuente_id, d.titulo, d.texto, d.url,
                       ts_rank(d.tsv, q.tq) AS score
                FROM ia_documentos d, q
                WHERE {filtro.replace('canal_publico', 'd.canal_publico').replace('fuente =', 'd.fuente =')}
                  AND q.tq IS NOT NULL AND d.tsv @@ q.tq
                ORDER BY score DESC, d.actualizado_en DESC
                LIMIT %s
            """, [expandido] + params_base + [limite])
            filas = [_fila(r, 'alguna_palabra') for r in cur.fetchall()
                     if float(r['score'] or 0) >= _MIN_RANK_OR]
            if filas:
                return filas

            # 3) por parecido (errores de escritura)
            if _tiene(cur, 'pg_trgm'):
                cur.execute(f"""
                    SELECT fuente, fuente_id, titulo, texto, url,
                           GREATEST(similarity(titulo, %s), similarity(LEFT(texto, 1000), %s)) AS score
                    FROM ia_documentos
                    WHERE {filtro}
                      AND (titulo %% %s OR LEFT(texto, 1000) %% %s)
                    ORDER BY score DESC
                    LIMIT %s
                """, [texto, texto] + params_base + [texto, texto, limite])
                filas = [_fila(r, 'parecido') for r in cur.fetchall()
                         if float(r['score'] or 0) >= _MIN_PARECIDO]
                if filas:
                    return filas

            # 4) último recurso: contiene el texto
            cur.execute(f"""
                SELECT fuente, fuente_id, titulo, texto, url, 0 AS score
                FROM ia_documentos
                WHERE {filtro} AND (titulo ILIKE %s OR texto ILIKE %s)
                ORDER BY actualizado_en DESC LIMIT %s
            """, params_base + [f'%{texto}%', f'%{texto}%', limite])
            return [_fila(r, 'contiene') for r in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'rag: falló la búsqueda ({exc})')
        return []


def contexto_para_modelo(documentos, max_caracteres=1800):
    """Los documentos encontrados, listos para meterlos en el prompt.

    Van numerados y con su origen para que la respuesta pueda citar de dónde
    salió cada cosa, y recortados para no inflar el contexto.
    """
    partes, total = [], 0
    for i, d in enumerate(documentos, 1):
        trozo = f"[{i}] {d['titulo']}: {d['texto']}".strip()
        if total + len(trozo) > max_caracteres:
            trozo = trozo[:max(0, max_caracteres - total)]
        if not trozo:
            break
        partes.append(trozo)
        total += len(trozo)
    return '\n'.join(partes)
