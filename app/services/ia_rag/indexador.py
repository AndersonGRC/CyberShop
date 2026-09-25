"""Arma el índice de textos del negocio (tabla `ia_documentos`).

El índice NO es una fuente de verdad: se puede borrar entero y reconstruir desde
las tablas reales. Por eso solo guarda lo que ya está en otra parte, y cada fila
apunta a su origen (`fuente`, `fuente_id`).

`canal_publico` es la línea que separa lo que el chat del sitio puede leer de lo
interno. Un producto archivado o no visible en la tienda entra al índice para el
panel, pero marcado como NO público: el bot del sitio no lo menciona. Los
documentos internos (services/ia_rag/internos.py) entran siempre como NO
públicos, con la visibilidad por rol en la fuente.
"""

import html
import re

from flask import current_app

from database import get_db_cursor
from services.ia_datos.base import _columnas, _existe

# Documentos internos: visibilidad por rol → fuente en el índice. Así el panel
# filtra con `fuentes=` sin tocar la búsqueda.
FUENTES_INTERNAS = {'administracion': 'interno_admin', 'equipo': 'interno_equipo'}
FUENTES = ('producto', 'servicio', 'faq', 'publicacion', 'pagina', 'blog',
           *FUENTES_INTERNAS.values())

_RE_TAG = re.compile(r'<[^>]+>')
_RE_ESPACIOS = re.compile(r'\s+')
_RE_PARRAFOS = re.compile(r'\n\s*\n')
_MAX_TEXTO = 4000          # un documento más largo que esto no aporta y sí pesa
_MAX_PARTE = 1500          # los documentos internos largos se indexan por partes


def texto_plano(valor, limite=_MAX_TEXTO):
    """HTML o texto suelto → una línea legible, recortada."""
    if not valor:
        return ''
    plano = _RE_TAG.sub(' ', str(valor))
    plano = html.unescape(plano)
    return _RE_ESPACIOS.sub(' ', plano).strip()[:limite]


def _tiene_unaccent(cur):
    try:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'unaccent'")
        return cur.fetchone() is not None
    except Exception:
        return False


def _sql_tsv(cur):
    """Expresión que arma el tsvector, con o sin unaccent según haya."""
    if _tiene_unaccent(cur):
        return "to_tsvector('spanish', unaccent(%s))"
    return "to_tsvector('spanish', %s)"


def indice_disponible(cur=None):
    """True si este cliente ya tiene la tabla (migración 0012 aplicada)."""
    if cur is not None:
        return _existe(cur, 'ia_documentos')
    try:
        with get_db_cursor() as c:
            return _existe(c, 'ia_documentos')
    except Exception:
        return False


def _upsert(cur, tsv_sql, fuente, fuente_id, titulo, texto, url, publico):
    """Una fila por origen: `(fuente, fuente_id)` es única, así que reindexar no
    duplica, actualiza."""
    titulo = (titulo or '').strip()[:300]
    if not titulo:
        return False
    texto = texto_plano(texto)
    completo = f'{titulo}. {texto}'.strip()
    cur.execute(f"""
        INSERT INTO ia_documentos (fuente, fuente_id, titulo, texto, url, canal_publico,
                                   actualizado_en, tsv)
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), {tsv_sql})
        ON CONFLICT (fuente, fuente_id) DO UPDATE SET
            titulo = EXCLUDED.titulo, texto = EXCLUDED.texto, url = EXCLUDED.url,
            canal_publico = EXCLUDED.canal_publico, actualizado_en = NOW(), tsv = EXCLUDED.tsv
    """, (fuente, str(fuente_id)[:60], titulo, texto, (url or '')[:400] or None,
          bool(publico), completo))
    return True


# ── Fuentes ────────────────────────────────────────────────────
def _productos(cur, tsv_sql):
    if not _existe(cur, 'productos'):
        return 0
    cols = _columnas(cur, 'productos')
    # Mismas reglas que el catálogo público: si no se ve en la tienda, no es público.
    publico = ['TRUE']
    if 'active' in cols:
        publico.append('COALESCE(p.active, TRUE)')
    if 'visible_en_ecommerce' in cols:
        publico.append('COALESCE(p.visible_en_ecommerce, TRUE)')
    slug = 'p.slug' if 'slug' in cols else 'NULL'
    cur.execute(f"""
        SELECT p.id, p.nombre, COALESCE(p.descripcion, '') AS descripcion,
               COALESCE(g.nombre, '') AS categoria, {slug} AS slug,
               ({' AND '.join(publico)}) AS publico
        FROM productos p LEFT JOIN generos g ON g.id = p.genero_id
    """)
    n = 0
    for r in cur.fetchall():
        url = f"/producto/{r['id']}-{r['slug']}" if r['slug'] else f"/producto/{r['id']}"
        texto = r['descripcion']
        if r['categoria']:
            texto = f"Categoría: {r['categoria']}. {texto}"
        n += _upsert(cur, tsv_sql, 'producto', r['id'], r['nombre'], texto, url, r['publico'])
    return n


_ITEMS = (('service', 'servicio', '/servicios'),
          ('faq', 'faq', None),
          ('publication', 'publicacion', '/'))


def _items_del_sitio(cur, tsv_sql):
    if not _existe(cur, 'public_site_items'):
        return 0
    n = 0
    for item_type, fuente, url in _ITEMS:
        cur.execute("""SELECT id, title, COALESCE(subtitle, '') AS subtitle,
                              COALESCE(description, '') AS description,
                              COALESCE(extra_text, '') AS extra_text,
                              COALESCE(cta_url, '') AS cta_url, is_active
                       FROM public_site_items WHERE item_type = %s""", (item_type,))
        for r in cur.fetchall():
            texto = ' '.join(x for x in (r['subtitle'], r['description'], r['extra_text']) if x)
            n += _upsert(cur, tsv_sql, fuente, r['id'], r['title'], texto,
                         r['cta_url'] or url, bool(r['is_active']))
    return n


# Textos del sitio que describen al negocio. Clave en public_site_settings → título.
_PAGINAS = (
    ('home_about_title', 'home_about_intro', 'home_about_body', 'Quiénes somos', '/quienes_somos'),
    ('home_mision_titulo', 'home_mision_texto', None, 'Nuestra misión', '/quienes_somos'),
    ('home_vision_titulo', 'home_vision_texto', None, 'Nuestra visión', '/quienes_somos'),
)


def _paginas(cur, tsv_sql):
    if not _existe(cur, 'public_site_settings'):
        return 0
    cur.execute('SELECT key, value FROM public_site_settings')
    valores = {r['key']: r['value'] for r in cur.fetchall()}
    n = 0
    for clave_titulo, clave_a, clave_b, titulo_defecto, url in _PAGINAS:
        texto = ' '.join(x for x in (valores.get(clave_a), valores.get(clave_b)) if x)
        if not texto_plano(texto):
            continue
        titulo = (valores.get(clave_titulo) or '').strip() or titulo_defecto
        n += _upsert(cur, tsv_sql, 'pagina', clave_titulo, titulo, texto, url, True)
    return n


def _blog(cur, tsv_sql):
    if not _existe(cur, 'blog_posts'):
        return 0
    cols = _columnas(cur, 'blog_posts')
    cuerpo = 'cuerpo_html' if 'cuerpo_html' in cols else "''"
    cur.execute(f"""SELECT slug, titulo, COALESCE(extracto, '') AS extracto,
                           COALESCE({cuerpo}, '') AS cuerpo, estado
                    FROM blog_posts""")
    n = 0
    for r in cur.fetchall():
        texto = f"{r['extracto']} {r['cuerpo']}".strip()
        n += _upsert(cur, tsv_sql, 'blog', r['slug'], r['titulo'], texto,
                     f"/blog/{r['slug']}", r['estado'] == 'publicado')
    return n


def partir(texto, maximo=_MAX_PARTE):
    """Un documento largo en partes que se encuentran y se citan por separado.
    Corta por párrafos y, si un párrafo solo no cabe, por la última frase."""
    partes, actual = [], ''
    for parrafo in (p.strip() for p in _RE_PARRAFOS.split(texto or '')):
        while len(parrafo) > maximo:
            corte = parrafo.rfind('. ', 0, maximo)
            corte = corte + 1 if corte > maximo // 2 else maximo
            if actual:
                partes.append(actual)
                actual = ''
            partes.append(parrafo[:corte].strip())
            parrafo = parrafo[corte:].strip()
        if not parrafo:
            continue
        if actual and len(actual) + 2 + len(parrafo) > maximo:
            partes.append(actual)
            actual = parrafo
        else:
            actual = f'{actual}\n\n{parrafo}' if actual else parrafo
    if actual:
        partes.append(actual)
    return partes


def _internos(cur, tsv_sql):
    """Documentos internos activos: NUNCA públicos. Se rehace el grupo entero,
    así lo archivado o lo que cambió de visibilidad no deja restos."""
    cur.execute('DELETE FROM ia_documentos WHERE fuente = ANY(%s)',
                (list(FUENTES_INTERNAS.values()),))
    if not _existe(cur, 'ia_documentos_internos'):
        return 0
    cur.execute("""SELECT id, titulo, texto, visibilidad FROM ia_documentos_internos
                   WHERE activo""")
    n = 0
    for r in cur.fetchall():
        fuente = FUENTES_INTERNAS.get(r['visibilidad'])
        if not fuente:
            continue
        for i, parte in enumerate(partir(r['texto']), 1):
            n += _upsert(cur, tsv_sql, fuente, f"{r['id']}-{i}", r['titulo'], parte, None, False)
    return n


_INDEXADORES = {
    'producto': _productos,
    'sitio': _items_del_sitio,       # servicios + faq + publicaciones
    'pagina': _paginas,
    'blog': _blog,
    'interno': _internos,            # documentos internos (solo el panel)
}


def reindexar(fuentes=None, limpiar=True):
    """Reconstruye el índice del cliente actual. Devuelve {fuente: filas}.

    `limpiar` borra lo que ya no existe en el origen (un producto eliminado no
    puede seguir apareciendo en las respuestas).
    """
    pedidas = tuple(fuentes) if fuentes else tuple(_INDEXADORES)
    resultado = {}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if not indice_disponible(cur):
                return {'error': 'sin_indice'}
            tsv_sql = _sql_tsv(cur)
            if limpiar and not fuentes:
                cur.execute('DELETE FROM ia_documentos')
            for nombre in pedidas:
                fn = _INDEXADORES.get(nombre)
                if fn:
                    resultado[nombre] = fn(cur, tsv_sql)
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(f'rag: no se pudo reindexar: {exc}')
        return {'error': str(exc)[:200]}
    return resultado


def reindexar_uno(fuente, fuente_id):
    """Actualiza un solo documento (al guardar un producto, una FAQ, etc.).
    Silencioso a propósito: nunca debe tumbar el guardado que lo llamó."""
    mapa = {'producto': 'producto', 'servicio': 'sitio', 'faq': 'sitio',
            'publicacion': 'sitio', 'pagina': 'pagina', 'blog': 'blog', 'interno': 'interno'}
    grupo = mapa.get(fuente)
    if not grupo:
        return False
    try:
        return bool(reindexar([grupo], limpiar=False))
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'rag: no se pudo reindexar {fuente}/{fuente_id}: {exc}')
        return False


def estado():
    """Cuántos documentos hay por fuente y cuándo se actualizó el índice."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if not indice_disponible(cur):
                return {'disponible': False, 'documentos': 0, 'por_fuente': {}}
            cur.execute("""SELECT fuente, COUNT(*) AS n,
                                  COUNT(*) FILTER (WHERE canal_publico) AS publicos,
                                  MAX(actualizado_en) AS ultima
                           FROM ia_documentos GROUP BY fuente ORDER BY fuente""")
            filas = cur.fetchall()
    except Exception:
        return {'disponible': False, 'documentos': 0, 'por_fuente': {}}
    return {
        'disponible': True,
        'documentos': sum(int(r['n']) for r in filas),
        'publicos': sum(int(r['publicos']) for r in filas),
        'por_fuente': {r['fuente']: {'total': int(r['n']), 'publicos': int(r['publicos']),
                                     'ultima': r['ultima']} for r in filas},
    }
