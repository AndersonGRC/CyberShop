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
    ('anteayer', 'anteayer'),
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


# Errores de escritura comunes que no cambian el sentido: b/v, s/z, s/c (ce, ci).
# Se cambia letra por letra (misma longitud) para no perder las posiciones con
# las que se recorta el nombre del texto original.
_FONETICA = str.maketrans({'v': 'b', 'z': 's'})


def fonetico(texto_normalizado):
    """«cuanto bendi» = «cuanto vendi»; «cotisaciones» = «cotizaciones»."""
    t = texto_normalizado.translate(_FONETICA)
    return re.sub(r'c(?=[ei])', 's', t)


# Abreviaturas de chat: se expanden ANTES de todo (en el texto original), así
# las posiciones del original y del normalizado siguen cuadrando.
_ABREVIATURAS = (
    (r'\bq\b', 'que'), (r'\bk\b', 'que'), (r'\bke\b', 'que'), (r'\bxq\b', 'por que'), (r'\bpq\b', 'por que'),
    (r'\bx\b', 'por'), (r'\bpa\b', 'para'), (r'\btb\b', 'tambien'), (r'\btmb\b', 'tambien'),
    (r'\bmsj\b', 'mensaje'), (r'\bcel\b', 'celular'), (r'\bcompu\b', 'computador'),
)


def expandir(texto):
    t = texto or ''
    for patron, reemplazo in _ABREVIATURAS:
        t = re.sub(patron, reemplazo, t, flags=re.I)
    return t


# «Qué día de la semana se vende más» habla del día, no de «esta semana».
_NO_ES_PERIODO = re.compile(r'\bdias? de (?:la|una) semana\b')


# Cada frase de período como palabra completa: «anual» no está en «manual».
_RE_PERIODO = {frase: re.compile(r'\b' + re.escape(frase) + r'\b') for frase, _ in _PERIODOS_TEXTO}


def periodo_de(texto):
    """Período mencionado en la pregunta, o None si no menciona ninguno."""
    t = _NO_ES_PERIODO.sub(' ', normalizar(texto))
    for frase, periodo in _PERIODOS_TEXTO:
        if _RE_PERIODO[frase].search(t):
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
    # Un número de documento («la cotización 15») también sirve, aunque sea corto.
    return nombre if len(nombre) >= 3 or nombre.isdigit() else None


def enrutar(texto, capacidades):
    """Devuelve [(code, params)] si reconoce la intención, o [] si no.

    Nunca devuelve más de una capacidad: si hace falta combinar varias, que
    decida el modelo. `capacidades` ya viene filtrada por permisos y canal, así
    que el enrutador no puede llegar a algo que quien pregunta no podría usar.
    """
    original = expandir((texto or '').strip())
    if not original:
        return []
    normal = normalizar(original)
    buscable = fonetico(normal)

    mejor = None                         # (largo_del_disparador, capacidad, fin)
    for h in capacidades:
        for disparador in h.disparadores:
            d = fonetico(normalizar(disparador))
            pos = buscable.find(d)
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
                if (getattr(h, 'extra', None) or {}).get('texto_opcional'):
                    continue             # la consulta sirve sin nombre (p. ej. «los últimos casos»)
                return []                # sin el nombre la consulta no sirve: que decida el modelo
            params[p] = nombre
    return [(h.code, params)]


# Palabras que acompañan a un seguimiento de período sin cambiar su sentido:
# «¿y el mes pasado?», «¿lo mismo pero de ayer?», «¿ahora la semana pasada?».
_RELLENO_SEGUIMIENTO = set('y e en el la los las de del para con ahora lo mismo pero que tal como fue fueron '
                           'va vamos ese esa eso por favor porfa dame muestrame y ya'.split())


def seguimiento_de_periodo(texto, historial, capacidades):
    """«¿Y el mes pasado?» justo después de una consulta con período → la MISMA
    consulta con el período nuevo, sin modelo. Solo si el último turno usó una
    sola capacidad que admite período y la pregunta no dice nada más que el
    período (un nombre, otro tema o dos períodos van al modelo)."""
    if not historial or not isinstance(historial, list) or not isinstance(historial[-1], dict):
        return []
    codigo = str(historial[-1].get('herramienta') or '').strip()
    if not codigo or ',' in codigo or ':' in codigo:
        return []
    h = next((c for c in capacidades if c.code == codigo), None)
    if h is None or 'periodo' not in h.params:
        return []
    normal = normalizar(expandir(texto))
    resto, periodos = normal, set()
    for frase, periodo in sorted(_PERIODOS_TEXTO, key=lambda x: len(x[0]), reverse=True):
        if _RE_PERIODO[frase].search(resto):
            periodos.add(periodo)
            resto = _RE_PERIODO[frase].sub(' ', resto)
    if len(periodos) != 1:
        return []
    if any(w not in _RELLENO_SEGUIMIENTO for w in re.findall(r'[a-z0-9]+', resto)):
        return []
    return [(codigo, {'periodo': periodos.pop()})]


def enrutar_panel_seguro(texto, capacidades, historial=None):
    """Ruta rápida solo para preguntas inequívocas del panel.

    El enrutador general sirve también al chat público y elige una coincidencia
    por longitud. En el panel, responder sin modelo exige más cautela: una
    comparación, una fecha que no sabemos interpretar o dos intenciones nunca
    deben convertirse silenciosamente en una consulta distinta.
    """
    texto = expandir((texto or '').strip())
    normal = normalizar(texto)
    if not normal:
        return []
    if historial and re.match(r'^[¿\s]*(?:y\b|ahora\b|tambien\b|lo mismo\b|ese\b|esa\b|esos\b|esas\b)', normal):
        # Un cambio de período sobre la consulta anterior se resuelve aquí;
        # cualquier otro seguimiento necesita al modelo con la conversación.
        return seguimiento_de_periodo(texto, historial, capacidades)
    if re.search(r'\b(?:19|20)\d{2}\b|\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b', normal):
        return []                         # fechas concretas: las interpreta el planificador
    if re.search(r'\b(?:trimestre|quincena|ultimos?\s+\d+\s+dias?|entre\s+el\s+\d+|del\s+\d+\s+al\s+\d+)\b', normal):
        return []
    filtro_desconocido = re.search(
        r'\b(?:en efectivo|con tarjeta|por vendedor|por sucursal|por canal|en linea|en la web|por empleado)\b', normal)

    # Dos intenciones diferentes no se pueden reducir a la frase más larga.
    # Pero si dos frases se pisan sobre las MISMAS palabras («la cotización» y
    # «la cotización más grande»), es una sola lectura: vale la más larga.
    tramos = []
    buscable = fonetico(normal)
    for h in capacidades:
        for disparador in h.disparadores:
            d = fonetico(normalizar(disparador))
            for m in re.finditer(re.escape(d), buscable):
                tramos.append((m.end() - m.start(), m.start(), m.end(), h.code))
    aceptados = []
    for largo, ini, fin, code in sorted(tramos, reverse=True):
        # Solo choca con lo aceptado de OTRA capacidad: dos frases de la misma
        # que se encadenan («cómo vamos frente al» + «frente al mes pasado»)
        # cubren juntas el tramo y dejan fuera a la más corta de otra.
        if not any(ini < f and i < fin and c != code for _, i, f, c in aceptados):
            aceptados.append((largo, ini, fin, code))
    coincidencias = {code for _, _, _, code in aceptados}
    if len(coincidencias) != 1:
        return []
    # «En efectivo», «con tarjeta»… son filtros que las ventas no saben aplicar,
    # pero son justo el tema de medios de pago y de la caja.
    if filtro_desconocido and not coincidencias & {'metodos_pago', 'caja_estado'}:
        return []

    # Detecta dos períodos independientes, respetando que «mes pasado» contiene
    # «mes» y «semana pasada» puede contener «la semana».
    menciones = []
    sin_dias = _NO_ES_PERIODO.sub(lambda m: ' ' * len(m.group(0)), normal)
    for frase, periodo in sorted(_PERIODOS_TEXTO, key=lambda x: len(x[0]), reverse=True):
        for match in _RE_PERIODO[frase].finditer(sin_dias):
            tramo = (match.start(), match.end())
            if not any(tramo[0] < fin and inicio < tramo[1] for inicio, fin, _ in menciones):
                menciones.append((*tramo, periodo))
    if len({p for _, _, p in menciones}) > 1:
        return []

    elegidas = enrutar(texto, capacidades)
    if len(elegidas) != 1 or elegidas[0][0] not in coincidencias:
        return []
    code, params = elegidas[0]
    h = next(c for c in capacidades if c.code == code)
    if any(p in _PARAMS_NOMBRE for p in h.params) and menciones:
        return []                         # evita incluir «este mes» en el nombre
    if 'periodo' in h.params and 'periodo' not in params:
        # El comparativo necesita una ventana finita; el resto sigue la regla
        # del panel: sin fecha explícita, histórico completo.
        params['periodo'] = 'mes' if code == 'comparativo_ventas' else 'todo'
    return [(code, params)]
