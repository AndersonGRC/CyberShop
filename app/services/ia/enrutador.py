"""Enrutador determinista: resuelve las preguntas típicas SIN gastar modelo.

Por qué existe: elegir la herramienta correcta es justo lo que peor hace un
modelo chico, y es también lo más lento (una llamada al modelo solo para decidir
a dónde ir). Las preguntas de todos los días —«¿cuánto vendí hoy?», «¿qué está
agotado?»— se reconocen por palabras y se contestan de inmediato. Lo que no
reconoce se le deja al modelo, con el mismo JSON estricto de siempre.

Las palabras de cada capacidad se declaran en `services/ia/intenciones.py`.
Aquí solo está la mecánica de reconocerlas.
"""

import re
import unicodedata

_CONECTORES = ('de ', 'del ', 'la ', 'el ', 'los ', 'las ', 'a ', 'mi ', 'mis ', 'un ', 'una ')
# Parámetros que se recortan de lo que viene DESPUÉS de la frase disparadora:
# «¿qué ha comprado Ana Pérez?» → cliente='Ana Pérez'; «¿tienen gaseosa?» → texto='gaseosa'.
_PARAMS_NOMBRE = ('cliente', 'producto', 'empleado', 'texto')

# Más específico primero: «semana pasada» antes que «semana».
_PERIODOS_TEXTO = (
    ('semana pasada', 'semana_anterior'), ('semana anterior', 'semana_anterior'),
    ('mes pasado', 'mes_anterior'), ('mes anterior', 'mes_anterior'),
    ('anteayer', 'ayer'),
    ('hoy', 'hoy'), ('ayer', 'ayer'),
    ('esta semana', 'semana'), ('la semana', 'semana'),
    ('este mes', 'mes'), ('del mes', 'mes'), ('en el mes', 'mes'),
    ('este ano', 'anio'), ('del ano', 'anio'), ('anual', 'anio'),
    ('historico', 'todo'), ('en total', 'todo'), ('siempre', 'todo'), ('desde que abri', 'todo'),
)

_RE_LIMITE = (
    re.compile(r'\btop\s*(\d{1,2})\b'),
    re.compile(r'\b(?:los|las)\s+(\d{1,2})\b'),
    re.compile(r'\b(\d{1,2})\s+(?:mas|mejores|principales|primeros)\b'),
)


def normalizar(texto):
    """Minúsculas y sin tildes, **conservando las posiciones**: así se puede
    recortar el nombre propio del texto ORIGINAL (con sus tildes) a partir de
    dónde terminó la frase que disparó la herramienta."""
    plano = unicodedata.normalize('NFD', (texto or '').lower())
    return ''.join(c for c in plano if unicodedata.category(c) != 'Mn')


def periodo_de(texto):
    """Período mencionado en la pregunta, o None si no menciona ninguno."""
    t = normalizar(texto)
    for frase, periodo in _PERIODOS_TEXTO:
        if frase in t:
            return periodo
    return None


def limite_de(texto):
    """Cuántos pidió («top 5», «los 10 mejores»). None si no lo dice."""
    t = normalizar(texto)
    for rx in _RE_LIMITE:
        m = rx.search(t)
        if m:
            return max(1, min(20, int(m.group(1))))
    return None


def _nombre_tras(original, normal, fin):
    """Lo que viene después de la frase disparadora, como nombre propio.

    Se recorta del texto ORIGINAL para no perder tildes: las consultas buscan
    con LIKE y «Ana Pérez» no casa con «ana perez».
    """
    if len(original) != len(normal):
        return None                      # la normalización movió posiciones: no arriesgar
    resto_norm = normal[fin:].lstrip()
    desplazado = fin + (len(normal[fin:]) - len(resto_norm))
    for con in _CONECTORES:
        if resto_norm.startswith(con):
            resto_norm = resto_norm[len(con):]
            desplazado += len(con)
            break
    nombre = original[desplazado:].strip(' ?¿!¡.,;:"\'')
    return nombre if len(nombre) >= 3 else None


def enrutar(texto, capacidades):
    """Devuelve [(code, params)] si reconoce la intención, o [] si no.

    Nunca devuelve más de una capacidad: si hace falta combinar varias, que
    decida el modelo. `capacidades` ya viene filtrada por permisos y canal, así
    que el enrutador no puede llegar a algo que quien pregunta no podría usar.
    """
    original = (texto or '').strip()
    if not original:
        return []
    normal = normalizar(original)

    mejor = None                         # (largo_del_disparador, capacidad, fin)
    for h in capacidades:
        for disparador in h.disparadores:
            d = normalizar(disparador)
            pos = normal.find(d)
            if pos < 0:
                continue
            if mejor is None or len(d) > mejor[0]:
                mejor = (len(d), h, pos + len(d))
    if mejor is None:
        return []

    _, h, fin = mejor
    params = {}
    for p in h.params:
        if p == 'periodo':
            periodo = periodo_de(original)
            if periodo:
                params['periodo'] = periodo
        elif p == 'limite':
            limite = limite_de(original)
            if limite:
                params['limite'] = limite
        elif p in _PARAMS_NOMBRE:
            nombre = _nombre_tras(original, normal, fin)
            if not nombre:
                return []                # sin el nombre la consulta no sirve: que decida el modelo
            params[p] = nombre
    return [(h.code, params)]
