# -*- coding: utf-8 -*-
"""¿El producto que se va a crear ya existe? (1.9.15.0)

Nace de un catálogo real de minimercado (582 productos) con duplicados que el freno de
«mismo nombre exacto» no veía: «DIANA ACEITE» dos veces a distinto precio, «TRIDENT
INDIVIDUAL» y «TRAIDENPEQUEÑO», «AROMA CAFE» y «AROMA»; y productos que se parecen pero
son de otra marca («CIELO AGUA», «BRISA AGUA»).

Compara por palabras (sin tildes, sin mayúsculas, en cualquier orden, tolerando errores
de tecleo) y por presentación (tamaños y unidades normalizados: 1 L = 1000 ML, kilo =
1000 GR, «x 12» = 12 unidades):

  duplicado   mismas palabras y misma presentación → no se crea (se dice cuál es).
  variante    mismas palabras, otra presentación → se crea, con un aviso.
  sin_tamano  mismas palabras, el nuevo sin presentación y el existente con ella → aviso.
  parecido    comparte la mayoría de las palabras (puede ser otra marca) → aviso.

No modifica nada: solo lee el catálogo para la vista previa que la persona confirma.
"""
import difflib
import re
import unicodedata

_VACIAS = {'de', 'del', 'la', 'el', 'los', 'las', 'para', 'por', 'y', 'en', 'a', 'al', 'un', 'una'}  # «con» y «sin» distinguen
_UNIDAD = {
    'ml': ('ml', 1), 'mililitros': ('ml', 1), 'cc': ('ml', 1),
    'l': ('ml', 1000), 'lt': ('ml', 1000), 'lts': ('ml', 1000), 'litro': ('ml', 1000), 'litros': ('ml', 1000),
    'g': ('g', 1), 'gr': ('g', 1), 'grs': ('g', 1), 'gramos': ('g', 1),
    'kg': ('g', 1000), 'kilo': ('g', 1000), 'kilos': ('g', 1000), 'lb': ('g', 500), 'libra': ('g', 500),
    'libras': ('g', 500), 'oz': ('ml', 30),
    'w': ('w', 1), 'gb': ('gb', 1), 'tb': ('gb', 1000), 'mm': ('mm', 1), 'cm': ('mm', 10), 'm': ('mm', 1000),
    'mts': ('mm', 1000), 'metros': ('mm', 1000),
    'und': ('u', 1), 'unds': ('u', 1), 'unidades': ('u', 1), 'unidad': ('u', 1), 'uds': ('u', 1),
}
_CANTIDAD = re.compile(r'(\d+(?:[.,]\d+)?)\s*(' + '|'.join(sorted(_UNIDAD, key=len, reverse=True)) + r')\b')
_POR = re.compile(r'\bx\s*(\d+)\b')
_SOLO = re.compile(r'\b(litro|kilo|libra)\b')


def normalizar(texto):
    t = unicodedata.normalize('NFKD', str(texto or '').lower())
    return ''.join(c for c in t if not unicodedata.combining(c))


def _numero(texto):
    return float(texto.replace(',', '.'))


def partes(nombre):
    """(palabras del producto, presentación) de un nombre: «Aceite Diana 1L» →
    ({'aceite', 'diana'}, {'1000ml'})."""
    t = normalizar(nombre)
    presentacion = set()

    def cantidad(m):
        unidad, factor = _UNIDAD[m.group(2)]
        valor = _numero(m.group(1)) * factor
        presentacion.add(f'{valor:g}{unidad}')
        return ' '
    t = _CANTIDAD.sub(cantidad, t)
    t = _POR.sub(lambda m: presentacion.add(f'x{int(m.group(1))}') or ' ', t)
    for m in _SOLO.finditer(t):
        unidad, factor = _UNIDAD[m.group(1)]
        presentacion.add(f'{factor:g}{unidad}')
    t = _SOLO.sub(' ', t)
    # Un número suelto también distingue: «ETAPA 3» ≠ «ETAPA 4», gaseosa «1.5» ≠ «2.5».
    t = re.sub(r'(?<![\w.,])(\d+(?:[.,]\d+)?)(?![\w.,])',
               lambda m: presentacion.add(f'n{_numero(m.group(1)):g}') or ' ', t)
    palabras = {w for w in re.findall(r'[a-z0-9]+', t) if w not in _VACIAS and not w.isdigit()}
    return palabras, presentacion


def _misma_palabra(a, b):
    """Igual, o el mismo con un error de tecleo («traident» = «trident», «spaguetti» =
    «spaghetti»); no «reparacion» y «restauracion»."""
    return a == b or (len(a) >= 5 and len(b) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.88)


def _comunes(a, b):
    """Palabras de `a` que también están en `b` (tolerando errores de tecleo)."""
    return sum(1 for x in a if any(_misma_palabra(x, y) for y in b))


def clasificar(nombre, existente):
    """'duplicado' | 'variante' | 'sin_tamano' | 'parecido' | None."""
    pa, ta = partes(nombre)
    pb, tb = partes(existente)
    if not pa or not pb:
        return None
    iguales = _comunes(pa, pb) == len(pa) and _comunes(pb, pa) == len(pb)
    if iguales:
        if ta == tb:
            return 'duplicado'
        if ta and tb:
            return 'variante'
        return 'sin_tamano' if tb else 'variante'
    comun = _comunes(pa, pb)
    if comun >= 2 and comun / max(len(pa), len(pb)) >= 0.6:
        return 'parecido'
    return None


def revisar(nombre, catalogo):
    """{'duplicado': producto o None, 'avisos': [textos]} frente a la lista de productos
    [{'id', 'nombre', 'precio'}]."""
    por_tipo = {'duplicado': [], 'variante': [], 'sin_tamano': [], 'parecido': []}
    for p in catalogo:
        tipo = clasificar(nombre, p.get('nombre'))
        if tipo:
            por_tipo[tipo].append(p)

    def lista(productos):
        return ', '.join(f'«{p["nombre"]}» (ID {p["id"]})' for p in productos[:3])
    avisos = []
    if por_tipo['sin_tamano']:
        avisos.append(f'⚠ Ya tienes {lista(por_tipo["sin_tamano"])}. Si este es otra presentación, agrega el '
                      'tamaño o la cantidad al nombre para no confundirlos.')
    if por_tipo['variante']:
        avisos.append(f'ℹ Ya tienes {lista(por_tipo["variante"])} en otra presentación: este queda como producto '
                      'aparte.')
    if por_tipo['parecido']:
        avisos.append(f'ℹ Parecidos en tu catálogo: {lista(por_tipo["parecido"])}. Revisa que no sea el mismo '
                      'producto (si es de otra marca, está bien).')
    return {'duplicado': (por_tipo['duplicado'] or [None])[0], 'avisos': avisos}


def catalogo(cur):
    """Los productos activos de la tienda (solo lectura)."""
    sql = 'SELECT id, nombre, precio FROM productos'
    cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'productos' AND column_name = 'active'")
    if cur.fetchone():
        sql += ' WHERE COALESCE(active, TRUE)'
    cur.execute(sql + ' ORDER BY id LIMIT 5000')
    return [dict(f) for f in cur.fetchall()]
