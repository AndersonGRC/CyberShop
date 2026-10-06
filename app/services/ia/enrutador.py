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


_APERTURA_SEGUIMIENTO = re.compile(r'^[¿\s]*(?:y\b|ahora\b|tambien\b|lo mismo\b|ese\b|esa\b|esos\b|esas\b)')
# Lo que se quita al inicio de «¿Y de Laura?», «¿y qué tal el de Juan?»,
# «¿lo mismo pero para Ana?» para quedarse con el nombre.
_RELLENO_NOMBRE = re.compile(
    r'^(?:\s|[¿?¡!,.;:]|\b(?:y|e|ahora|tambi[eé]n|lo|mismo|pero|de|del|el|la|los|las|para|con|sobre|a|al|'
    r'qu[eé]|tal|c[oó]mo|va|ese|esa|eso|esos|esas)\b)+', re.I)
_FECHAS_CONCRETAS = re.compile(
    r'\b(?:19|20)\d{2}\b|\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b')
# Ventanas que no tienen código de período: van al planificador. «El año
# pasado» no es «este año» (antes se leía «del año» dentro de la frase).
_VENTANAS_RARAS = re.compile(r'\b(?:trimestre|quincena|ultimos?\s+\d+\s+dias?|entre\s+el\s+\d+|del\s+\d+\s+al\s+\d+|'
                             r'ano\s+(?:pasado|anterior)|semestre)\b')
# Palabras que no cuentan como «contenido extra» al revisar una comparación de períodos.
_RELLENO_COMPARACION = {'cuanto', 'cuanta', 'cuantos', 'cuantas', 'fueron', 'como', 'esta', 'este', 'tambien',
                        'ademas', 'entre', 'comparado', 'comparar', 'frente', 'contra', 'versus', 'pasado',
                        'pasada', 'anterior', 'semana', 'tuve', 'tuvimos', 'hubo'}


def _sobra_contenido(normal, capacidades, codigo):
    """¿Queda algo en la pregunta además de las frases de `codigo`, los períodos
    y el relleno? («¿cuánto vendí hoy y qué tal el clima del mes?» → «clima»)."""
    buscable = fonetico(normal)
    h = next(c for c in capacidades if c.code == codigo)
    for d in h.disparadores:
        buscable = buscable.replace(fonetico(normalizar(d)), ' ' * len(d))
    for frase, _ in _PERIODOS_TEXTO:
        buscable = _RE_PERIODO[frase].sub(lambda m: ' ' * len(m.group(0)), buscable)
    vocabulario = _vocabulario(capacidades)
    return any(w not in vocabulario and w not in _RELLENO_COMPARACION
               for w in re.findall(r'[a-z0-9]{4,}', buscable))
_FILTROS = re.compile(
    r'\b(?:en efectivo|con tarjeta|por vendedor|por sucursal|por canal|en linea|en la web|por empleado)\b')
# Partes de una pregunta compuesta: «…hoy y qué está agotado», «…, además…».
_SEPARADOR = re.compile(r'\s*(?:[,;]|\by\b|\be\b|\btambi[eé]n\b|\badem[aá]s\b)\s*', re.I)
_MAX_PARTES = 3
# Pares «actual / anterior» para el comparativo: «este mes y el mes pasado» = mes.
_ACTUAL_DE = {'mes_anterior': 'mes', 'semana_anterior': 'semana', 'ayer': 'hoy'}


def seguimiento_de_nombre(texto, historial, capacidades):
    """«¿Y de Laura?» justo después de una consulta que pide un nombre (cliente,
    producto, empleado o texto) → la MISMA consulta con el nombre nuevo. Si lo
    que queda menciona un período u otro tema, va al modelo."""
    if not historial or not isinstance(historial, list) or not isinstance(historial[-1], dict):
        return []
    codigo = str(historial[-1].get('herramienta') or '').strip()
    if not codigo or ',' in codigo or ':' in codigo:
        return []
    h = next((c for c in capacidades if c.code == codigo), None)
    if h is None:
        return []
    campos = [p for p in h.params if p in _PARAMS_NOMBRE]
    if len(campos) != 1:
        return []
    nombre = _RELLENO_NOMBRE.sub('', texto or '').strip(' ?¿!¡.,;:"\'')
    if len(nombre) < 3 and not nombre.isdigit():
        return []
    plano = normalizar(nombre)
    if periodo_de(plano) or _FECHAS_CONCRETAS.search(plano):
        return []
    buscable = fonetico(plano)
    for c in capacidades:
        if c.code != codigo and any(fonetico(normalizar(d)) in buscable for d in c.disparadores):
            return []                     # otro tema, no un nombre
    # «¿Y los gastos?» no nombra a nadie: si alguna palabra es del vocabulario
    # del negocio (la que usan las frases de las capacidades), no es un nombre.
    vocabulario = _vocabulario(capacidades)
    if any(fonetico(w) in vocabulario for w in re.findall(r'[a-z0-9]{4,}', plano)):
        return []
    return [(codigo, {campos[0]: nombre})]


def _vocabulario(capacidades):
    """Palabras de 4+ letras de las frases de todas las capacidades («gastos»,
    «ventas», «stock»…), sin tildes y en su forma fonética."""
    clave = tuple(c.code for c in capacidades)
    if _VOCABULARIO_CACHE.get('clave') != clave:
        palabras = set()
        for c in capacidades:
            for d in c.disparadores:
                palabras.update(fonetico(w) for w in re.findall(r'[a-z0-9]{4,}', normalizar(d)))
        _VOCABULARIO_CACHE.update(clave=clave, palabras=palabras - _NO_VOCABULARIO)
    return _VOCABULARIO_CACHE['palabras']


_VOCABULARIO_CACHE = {}
# Palabras de las frases que también aparecen en nombres propios o productos.
_NO_VOCABULARIO = {'para', 'como', 'cual', 'cuanto', 'cuanta', 'cuantos', 'cuantas', 'esta', 'este', 'tengo',
                   'tiene', 'tienen', 'donde', 'quien', 'quienes'}


def _periodos_en(normal):
    """[(inicio, fin, periodo)] sin solapes, en orden del texto."""
    menciones = []
    sin_dias = _NO_ES_PERIODO.sub(lambda m: ' ' * len(m.group(0)), normal)
    for frase, periodo in sorted(_PERIODOS_TEXTO, key=lambda x: len(x[0]), reverse=True):
        for match in _RE_PERIODO[frase].finditer(sin_dias):
            tramo = (match.start(), match.end())
            if not any(tramo[0] < fin and inicio < tramo[1] for inicio, fin, _ in menciones):
                menciones.append((*tramo, periodo))
    return sorted(menciones)


def _coincidencias(normal, capacidades):
    """Capacidades cuyas frases aparecen. Si dos frases se pisan sobre las
    MISMAS palabras («la cotización» y «la cotización más grande»), es una sola
    lectura: vale la más larga. Dos frases encadenadas de la misma capacidad
    («cómo vamos frente al» + «frente al mes pasado») cubren juntas el tramo y
    dejan fuera a la más corta de otra («cómo vamos»)."""
    tramos = []
    buscable = fonetico(normal)
    for h in capacidades:
        for disparador in h.disparadores:
            d = fonetico(normalizar(disparador))
            for m in re.finditer(re.escape(d), buscable):
                tramos.append((m.end() - m.start(), m.start(), m.end(), h.code))
    aceptados = []
    for largo, ini, fin, code in sorted(tramos, reverse=True):
        if not any(ini < f and i < fin and c != code for _, i, f, c in aceptados):
            aceptados.append((largo, ini, fin, code))
    return {code for _, _, _, code in aceptados}


def _ruta_unica(texto, capacidades):
    """Una sola capacidad reconocida sin dudas → [(code, params)]; una sola
    capacidad con dos o tres períodos → la misma consulta por cada período.
    Cualquier otra cosa → []."""
    normal = normalizar(texto)
    if not normal:
        return []
    coincidencias = _coincidencias(normal, capacidades)
    if len(coincidencias) != 1:
        return []
    # «En efectivo», «con tarjeta»… son filtros que las ventas no saben aplicar,
    # pero son justo el tema de medios de pago y de la caja.
    if _FILTROS.search(normal) and not coincidencias & {'metodos_pago', 'caja_estado'}:
        return []

    menciones = _periodos_en(normal)
    periodos = list(dict.fromkeys(p for _, _, p in menciones))
    if len(periodos) > 1:
        code = next(iter(coincidencias))
        h = next(c for c in capacidades if c.code == code)
        if 'periodo' not in h.params or any(p in _PARAMS_NOMBRE for p in h.params) or len(periodos) > _MAX_PARTES:
            return []
        if _sobra_contenido(normal, capacidades, code):
            return []                     # un período puede ser de otra cosa: que decida el modelo
        if code == 'comparativo_ventas':
            # El comparativo ya compara con el período anterior: «este mes y el
            # mes pasado» es una sola consulta del mes actual.
            if len(periodos) == 2 and _ACTUAL_DE.get(periodos[1]) == periodos[0]:
                return [(code, {'periodo': periodos[0]})]
            if len(periodos) == 2 and _ACTUAL_DE.get(periodos[0]) == periodos[1]:
                return [(code, {'periodo': periodos[1]})]
            return []
        return [(code, {'periodo': p}) for p in periodos]

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


def _ruta_compuesta(texto, capacidades):
    """«¿Cuánto vendí hoy y qué está agotado?» → una consulta por parte, si
    CADA parte se reconoce sola y sin dudas (máximo tres). Un único período
    dicho en una parte vale para las demás que lo admitan («cuánto vendí y
    cuánto gasté este mes»). Si alguna parte no se entiende, va al modelo."""
    partes = [p.strip(' ¿?¡!.') for p in _SEPARADOR.split(texto) if p and p.strip(' ¿?¡!.')]
    if not 2 <= len(partes) <= _MAX_PARTES:
        return []
    rutas = []
    for parte in partes:
        r = _ruta_unica(parte, capacidades)
        if len(r) != 1:
            return []
        rutas.append(r[0])
    if len({(c, tuple(sorted(p.items()))) for c, p in rutas}) != len(rutas):
        return []                         # la misma consulta dos veces: algo se entendió mal
    periodos = {p for _, _, p in _periodos_en(normalizar(texto))}
    if len(periodos) == 1:
        unico = periodos.pop()
        sin_fecha = [i for i, parte in enumerate(partes) if not _periodos_en(normalizar(parte))]
        for i in sin_fecha:
            code, params = rutas[i]
            h = next(c for c in capacidades if c.code == code)
            if 'periodo' in h.params:
                rutas[i] = (code, {**params, 'periodo': unico})
    return rutas


def enrutar_panel_seguro(texto, capacidades, historial=None):
    """Ruta rápida del panel: resuelve sin modelo solo lo inequívoco.

    - Una pregunta de una sola capacidad → esa consulta.
    - Una capacidad con dos o tres períodos → la misma consulta por período.
    - Una pregunta compuesta («¿cuánto vendí hoy y qué está agotado?») → una
      consulta por parte, si cada parte se entiende sola.
    - Un seguimiento («¿y el mes pasado?», «¿y de Laura?») → la consulta del
      turno anterior con el período o el nombre nuevo.
    Lo demás (fechas concretas, filtros que no sabemos aplicar, partes que no
    se entienden) va al modelo: nunca se convierte en silencio en otra consulta.
    """
    texto = expandir((texto or '').strip())
    normal = normalizar(texto)
    if not normal:
        return []
    if historial and _APERTURA_SEGUIMIENTO.match(normal):
        return (seguimiento_de_periodo(texto, historial, capacidades)
                or seguimiento_de_nombre(texto, historial, capacidades))
    anio_pasado = _ANIO_PASADO.search(normal)
    if anio_pasado:
        return _con_anio_pasado(texto, anio_pasado, capacidades)
    if _FECHAS_CONCRETAS.search(normal) or _VENTANAS_RARAS.search(normal):
        return []                         # fechas concretas: las interpreta el planificador
    return _ruta_unica(texto, capacidades) or _ruta_compuesta(texto, capacidades)


_ANIO_PASADO = re.compile(r'\b(?:en\s+el\s+|el\s+|del\s+)?ano\s+(?:pasado|anterior)\b')


def _con_anio_pasado(texto, coincidencia, capacidades):
    """«¿Cuánto vendí el año pasado?» → la consulta con el rango exacto del año
    anterior (1-ene a 31-dic). Si la pregunta trae otra fecha, o ninguna de sus
    consultas admite período, va al modelo."""
    from datetime import date
    ini, fin = coincidencia.span()
    limpio = texto[:ini] + ' ' * (fin - ini) + texto[fin:]
    plano = normalizar(limpio)
    if _FECHAS_CONCRETAS.search(plano) or _VENTANAS_RARAS.search(plano) or _periodos_en(plano):
        return []
    rutas = _ruta_unica(limpio, capacidades) or _ruta_compuesta(limpio, capacidades)
    anio = date.today().year - 1
    salida, alguna = [], False
    for code, params in rutas:
        if 'periodo' in params:
            alguna = True
            params = {k: v for k, v in params.items() if k != 'periodo'}
            params.update(desde=f'{anio}-01-01', hasta=f'{anio}-12-31')
        salida.append((code, params))
    return salida if alguna else []
