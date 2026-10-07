"""Servicio Técnico F3: IA para la ficha del equipo, el diagnóstico y los mensajes.

Reglas:
  - Al modelo SOLO le llega información del equipo (tipo, marca, modelo,
    características, síntomas). Nunca nombre, teléfono, correo, clave ni
    dirección del cliente: el texto pegado pasa antes por
    `lector.limpiar_personales`, lo que escribe el técnico (falla,
    diagnóstico) por `lector.sin_datos_personales`, y los mensajes se
    reescriben como plantilla con {cliente}, {negocio}… sin rellenar.
  - La IA PROPONE; el usuario acepta campo por campo. Nada se guarda solo.
  - Sin IA (apagada, fría o sin plan) todo funciona: el lector fijo y las
    sugerencias por reglas siguen respondiendo.
  - Usa el motor del propio cliente (`ai_service._chat`, aislado por tenant).
"""

import json
import re

from services import servicio_tecnico_lector as lector
from services import servicio_tecnico_tipos as tipos

_COLUMNAS = ('marca', 'modelo', 'serial', 'imei', 'color', 'sistema_operativo', 'procesador', 'ram',
             'almacenamiento', 'pantalla')
SISTEMA = ('Eres el asistente del técnico de un taller de reparación de equipos electrónicos en Colombia. '
           'Respondes en español, breve y concreto. Nunca inventas datos: si algo no está en la información '
           'que te dan, lo dejas vacío.')


def _ia():
    import services.ai_service as ai
    return ai


def estado():
    """(disponible, motivo) para mostrar en la pantalla."""
    try:
        return _ia().estado_ia()
    except Exception:  # noqa: BLE001
        return False, 'La IA no está disponible.'


def _json_de(texto):
    """Primer objeto JSON del texto del modelo (tolera ```json y texto alrededor)."""
    if not texto:
        return None
    texto = re.sub(r'```(?:json)?', '', texto)
    inicio = texto.find('{')
    while inicio != -1:
        profundidad = 0
        for i in range(inicio, len(texto)):
            if texto[i] == '{':
                profundidad += 1
            elif texto[i] == '}':
                profundidad -= 1
                if profundidad == 0:
                    try:
                        return json.loads(texto[inicio:i + 1])
                    except ValueError:
                        break
        inicio = texto.find('{', inicio + 1)
    return None


def _campos_del_tipo(tipo):
    """Descripción de los campos para el prompt: clave → etiqueta (+ opciones)."""
    lineas = [f'- {c}: {tipos.ETIQUETAS_COMUNES[c]}' for c in tipos.columnas(tipo)]
    for clave, etiqueta, tipo_input, opciones in tipos.campos_extra(tipo):
        extra = f" (una de: {', '.join(opciones)})" if opciones else (' (sí/no)' if tipo_input == 'si_no' else '')
        extra += ' (AAAA-MM-DD)' if tipo_input == 'fecha' else ''
        extra += ' (solo el número)' if tipo_input == 'numero' else ''
        lineas.append(f'- extra.{clave}: {etiqueta}{extra}')
    return '\n'.join(lineas)


# ── Texto largo: qué líneas leer y cómo verificar lo que dice la IA ──
_LINEA_TECNICA = re.compile(
    r'(procesador|processor|cpu|core|ryzen|intel|amd|apple|snapdragon|exynos|mediatek|memoria|memory|ram|ddr|'
    r'disco|disk|drive|ssd|hdd|nvme|almacenamiento|storage|capacidad|capacity|serial|serie|s/n|imei|modelo|model|'
    r'marca|fabricante|manufacturer|vendor|sistema|system|windows|android|ios|version|versión|bios|board|placa|'
    r'grafic|graphic|gpu|video|pantalla|display|resoluci|pulgad|inch|bateria|batería|battery|design capacity|'
    r'full charge|ranura|slot|bank|dimm|va\b|watts?\b|\bw\b|ah\b|voltaje|voltage|color|operador|carrier)', re.I)
MAX_PARA_IA = 6000


def recortar_relevante(texto, limite=MAX_PARA_IA):
    """Si el texto no cabe, se quedan las líneas con datos técnicos (en su
    orden y sin repetidas) en vez de cortarlo a la mitad: un `systeminfo` con
    200 parches de Windows ya no esconde la RAM ni el disco al final.
    Devuelve (texto, {'lineas_totales', 'lineas_usadas'} o None)."""
    if len(texto) <= limite:
        return texto, None
    lineas = [l.rstrip() for l in texto.split('\n')]
    vistas, elegidas = set(), []
    for i, linea in enumerate(lineas):
        clave = linea.strip().lower()
        if not clave or clave in vistas:
            continue
        if i < 15 or _LINEA_TECNICA.search(linea) or re.search(r'[:\t].*\d', linea):
            if re.match(r'^\s*\[\d+\]:\s*KB\d+', linea):   # lista de parches de Windows
                continue
            vistas.add(clave)
            elegidas.append(linea)
    salida, largo = [], 0
    for linea in elegidas:
        if largo + len(linea) + 1 > limite:
            break
        salida.append(linea)
        largo += len(linea) + 1
    return '\n'.join(salida), {'lineas_totales': len([l for l in lineas if l.strip()]), 'lineas_usadas': len(salida)}


def _plano(texto):
    import unicodedata
    t = unicodedata.normalize('NFD', str(texto or '').lower())
    return ''.join(ch for ch in t if unicodedata.category(ch) != 'Mn')


def verificado(valor, texto_plano):
    """¿El valor que propone la IA aparece de verdad en el texto pegado?
    Todos sus números deben estar, y al menos 6 de cada 10 de sus palabras."""
    v = _plano(valor)
    numeros = re.findall(r'\d+(?:[.,]\d+)?', v)
    for n in numeros:
        variantes = {n, n.replace(',', '.'), n.replace('.', ',')}
        if not any(x in texto_plano for x in variantes):
            return False
    palabras = [w for w in re.findall(r'[a-z][a-z0-9\-]{1,}', v) if w not in ('gb', 'mb', 'tb', 'de', 'con')]
    if not palabras:
        return bool(numeros)
    presentes = sum(1 for w in palabras if w in texto_plano)
    return presentes / len(palabras) >= 0.6


def _validar(tipo, crudo):
    """Solo claves conocidas y valores razonables → {'columnas':{}, 'extras':{}}.
    Acepta «clave: valor» o «clave: {valor, linea}» (la línea es la evidencia)."""
    columnas, extras = {}, {}
    if not isinstance(crudo, dict):
        return {'columnas': columnas, 'extras': extras}
    permitidas = set(tipos.columnas(tipo))
    for clave, valor in crudo.items():
        if isinstance(valor, dict):
            valor = valor.get('valor')
        if valor in (None, '', [], {}):
            continue
        valor = str(valor).strip()
        if not valor or valor.lower() in ('null', 'none', 'n/a', 'no disponible', 'desconocido', '-'):
            continue
        if clave.startswith('extra.'):
            extras[clave[6:]] = valor
        elif clave in permitidas:
            columnas[clave] = valor[:160]
    extras = tipos.limpiar_extras(tipo, extras)
    if 'imei' in columnas and not lector.imei_luhn(columnas['imei']):
        columnas.pop('imei')                      # un IMEI inventado no pasa
    if 'serial' in columnas and not re.fullmatch(r'[\w\-./]{4,40}', columnas['serial']):
        columnas.pop('serial')
    return {'columnas': columnas, 'extras': extras}


def _propuestas(equipo, leido, fuente_por_campo, texto_plano=None):
    """Lista «actual → sugerido» solo de los campos que cambian. Con
    `texto_plano`, lo que propone la IA y no aparece en el texto queda como
    no verificado (no se marca solo para guardar)."""
    actuales_extras = equipo.get('extras') or {}
    salida = []
    for clave, valor in leido['columnas'].items():
        actual = equipo.get(clave) or ''
        if str(valor).strip() and str(valor).strip() != str(actual).strip():
            fuente = fuente_por_campo.get(clave, 'ia')
            salida.append({'campo': clave, 'etiqueta': tipos.ETIQUETAS_COMUNES.get(clave, clave),
                           'actual': actual, 'sugerido': valor, 'extra': False, 'fuente': fuente,
                           'verificado': fuente == 'lector' or texto_plano is None or verificado(valor, texto_plano)})
    etiquetas = {c[0]: c[1] for c in tipos.campos_extra(equipo['tipo'])}
    for clave, valor in leido['extras'].items():
        actual = actuales_extras.get(clave) or ''
        if str(valor).strip() != str(actual).strip():
            fuente = fuente_por_campo.get('extra_' + clave, 'ia')
            # Los campos de opción (tipo de disco, sí/no…) son una lectura del texto, no una copia:
            # basta con que algo de su valor aparezca.
            ok = fuente == 'lector' or texto_plano is None or verificado(valor, texto_plano) or (
                str(valor).lower() in ('si', 'no') or any(w in texto_plano for w in _plano(valor).split() if len(w) > 2))
            salida.append({'campo': 'extra_' + clave, 'etiqueta': etiquetas.get(clave, clave),
                           'actual': actual, 'sugerido': valor, 'extra': True, 'fuente': fuente,
                           'verificado': ok})
    return salida


# ── 1. Leer la información del sistema pegada ───────────────────
def leer_informacion(equipo, texto, usar_ia=True):
    """Propuestas para la ficha a partir de un texto largo pegado.

    `equipo`: dict con al menos 'tipo' (y los valores actuales si ya existe).
    Devuelve {'propuestas': [...], 'resumen': str, 'sugerencias': [...],
              'texto_limpio': str, 'ia': bool, 'aviso': str|None}."""
    tipo = equipo.get('tipo') or 'otro'
    limpio = lector.limpiar_personales(texto)
    if len(limpio) < 10:
        return {'propuestas': [], 'resumen': '', 'sugerencias': [], 'texto_limpio': limpio, 'ia': False,
                'aviso': 'Pega la información del equipo (por ejemplo, el resultado de «systeminfo» o la '
                         'pantalla «Acerca del teléfono»).'}

    fijo = lector.leer(limpio, tipo)
    para_ia, recorte = recortar_relevante(limpio)
    fuente = {k: 'lector' for k in fijo['columnas']}
    fuente.update({'extra_' + k: 'lector' for k in fijo['extras']})
    combinado = {'columnas': dict(fijo['columnas']), 'extras': dict(fijo['extras'])}
    resumen, sugerencias_ia, aviso, uso_ia = '', [], None, False

    if usar_ia:
        ok, motivo = estado()
        if ok:
            user = (f'Tipo de equipo: {tipos.nombre(tipo)}.\n'
                    f'Esta es la información técnica que pegó el técnico (puede venir de systeminfo, '
                    f'CPU-Z, la pantalla de información del teléfono o una etiqueta)'
                    f'{" — solo las líneas con datos técnicos, porque era muy largo" if recorte else ""}:\n'
                    f'<<<\n{para_ia}\n>>>\n\n'
                    f'Ubica cada dato en estos campos (usa exactamente estas claves):\n{_campos_del_tipo(tipo)}\n\n'
                    'Reglas: copia cada valor TAL CUAL aparece en el texto (no conviertas ni completes). Si un '
                    'dato no está en el texto, NO lo pongas. En «linea» copia solo el pedazo del texto donde lo '
                    'viste (máximo 60 caracteres).\n'
                    'Responde SOLO un JSON así: {"campos": {"clave": {"valor": "...", "linea": "..."}, '
                    '"extra.clave": {"valor": "...", "linea": "..."}}, '
                    '"resumen": "2 o 3 frases con lo importante del equipo para el técnico", '
                    '"sugerencias": [{"titulo": "...", "detalle": "..."}]}. '
                    'En sugerencias pon mejoras reales que el dato justifique (ranura de RAM libre, disco '
                    'mecánico, batería gastada, sistema sin soporte); si no hay, lista vacía. '
                    'Valores cortos, sin unidades repetidas, sin inventar.')
            # Un portátil tiene ~17 campos con su evidencia: con menos tokens el JSON se corta.
            texto_ia, err = _ia()._chat(SISTEMA, user, max_tokens=1100, temperature=0.1, espera_frio=40,
                                        tarea='contenido')
            datos = _json_de(texto_ia) if texto_ia else None
            if isinstance(datos, dict):
                uso_ia = True
                ia_val = _validar(tipo, datos.get('campos') or {})
                for k, v in ia_val['columnas'].items():
                    combinado['columnas'].setdefault(k, v)      # el lector fijo manda
                for k, v in ia_val['extras'].items():
                    combinado['extras'].setdefault(k, v)
                resumen = str(datos.get('resumen') or '').strip()[:800]
                for s in (datos.get('sugerencias') or [])[:5]:
                    if isinstance(s, dict) and s.get('titulo'):
                        sugerencias_ia.append({'titulo': str(s['titulo'])[:120],
                                               'detalle': str(s.get('detalle') or '')[:300]})
            elif texto_ia:
                aviso = 'La respuesta de la IA llegó incompleta. Se usó el lector automático.'
            else:
                aviso = (err or 'La IA no respondió a tiempo.') + ' Se usó el lector automático.'
        else:
            aviso = f'{motivo} Se usó el lector automático.'

    combinado['extras'] = tipos.limpiar_extras(tipo, combinado['extras'])
    reglas = lector.sugerencias(tipo, {**{c: equipo.get(c) for c in _COLUMNAS}, **combinado['columnas']},
                                {**(equipo.get('extras') or {}), **combinado['extras']})
    titulos = {s['titulo'].lower() for s in reglas}
    sugerencias = reglas + [s for s in sugerencias_ia if s['titulo'].lower() not in titulos]
    propuestas = _propuestas({**equipo, 'tipo': tipo}, combinado, fuente, _plano(limpio))
    sin_verificar = sum(1 for x in propuestas if not x['verificado'])
    avisos = [a for a in (aviso,
                          (f"El texto era largo: se leyeron {recorte['lineas_usadas']} de {recorte['lineas_totales']} "
                           'líneas, las que traen datos técnicos.') if recorte else None,
                          (f'{sin_verificar} dato(s) de la IA no aparecen tal cual en el texto: quedan sin marcar '
                           'para que los revises.') if sin_verificar else None) if a]
    return {'propuestas': propuestas, 'resumen': resumen, 'sugerencias': sugerencias, 'texto_limpio': limpio,
            'ia': uso_ia, 'aviso': ' '.join(avisos) or None, 'recorte': recorte}


# ── 2. Completar características con referencias de internet ────
def completar_caracteristicas(equipo):
    """Busca «marca modelo especificaciones» (SearXNG propio) y propone campos."""
    tipo = equipo.get('tipo') or 'otro'
    nombre = ' '.join(p for p in (equipo.get('marca'), equipo.get('modelo')) if p)
    if not equipo.get('modelo'):
        return {'propuestas': [], 'fuentes': [], 'aviso': 'Escribe primero la marca y el modelo del equipo.'}
    ok, motivo = estado()
    if not ok:
        return {'propuestas': [], 'fuentes': [], 'aviso': motivo}
    from services.chat_publico import busqueda_web
    refs = busqueda_web.buscar(nombre, tipos.nombre(tipo))
    if not refs:
        return {'propuestas': [], 'fuentes': [],
                'aviso': 'No se encontraron referencias en internet para ese modelo (o la búsqueda no está instalada).'}
    user = (f'Equipo: {tipos.nombre(tipo)} {nombre}.\n'
            f'Referencias de internet (de terceros, sin verificar):\n{busqueda_web.bloque_para_modelo(refs)}\n\n'
            f'Con SOLO lo que digan las referencias sobre ESTE modelo, llena estos campos:\n{_campos_del_tipo(tipo)}\n'
            'No llenes serial, IMEI ni color. Si una referencia habla de otro modelo, ignórala. '
            'Responde SOLO un JSON: {"campos": {"clave": "valor"}}.')
    texto, err = _ia()._chat(SISTEMA, user, max_tokens=500, temperature=0.1, espera_frio=40, tarea='contenido')
    datos = _json_de(texto) if texto else None
    if not isinstance(datos, dict):
        return {'propuestas': [], 'fuentes': refs, 'aviso': err or 'La IA no respondió a tiempo.'}
    leido = _validar(tipo, datos.get('campos') or {})
    for k in ('serial', 'imei', 'color'):
        leido['columnas'].pop(k, None)
    # Solo completa: no propone cambiar lo que el técnico ya escribió.
    leido['columnas'] = {k: v for k, v in leido['columnas'].items() if not equipo.get(k)}
    actuales = equipo.get('extras') or {}
    leido['extras'] = {k: v for k, v in leido['extras'].items() if not actuales.get(k)}
    referencias = _plano(' '.join(r.get('texto', '') + ' ' + r.get('titulo', '') for r in refs))
    return {'propuestas': _propuestas(equipo, leido, {}, referencias), 'fuentes': refs, 'aviso': None}


# ── 3. Pre-diagnóstico ──────────────────────────────────────────
def prediagnostico(orden):
    ok, motivo = estado()
    if not ok:
        return None, motivo
    # Lo escribe el técnico a mano: puede traer el nombre o el celular del cliente.
    def limpio(texto):
        return lector.sin_datos_personales(texto, (orden.get('cliente_nombre'),))
    datos = [f'Equipo: {tipos.nombre(orden.get("tipo"))} {orden.get("marca") or ""} {orden.get("modelo") or ""}'.strip(),
             f'Falla que reporta el cliente: {limpio(orden.get("falla_reportada") or "")}']
    if orden.get('estado_fisico'):
        datos.append(f'Estado físico al recibir: {limpio(orden["estado_fisico"])}')
    if orden.get('diagnostico'):
        datos.append(f'Notas del técnico: {limpio(orden["diagnostico"])}')
    user = ('\n'.join(datos) + '\n\nEscribe un pre-diagnóstico para el técnico con tres partes cortas:\n'
            'Causas probables: (de la más a la menos probable, máximo 4)\n'
            'Pruebas a hacer: (en orden, máximo 5)\n'
            'Repuestos posibles: (máximo 4)\n'
            'Texto plano, con viñetas «- ». Sin saludo ni conclusión.')
    texto, err = _ia()._chat(SISTEMA, user, max_tokens=600, temperature=0.3, espera_frio=40, tarea='contenido')
    if not texto:
        return None, err or 'La IA no respondió a tiempo.'
    return texto.strip()[:3000], None


# ── 4. Redactar mensajes ────────────────────────────────────────
_VARIABLES = re.compile(r'\{(cliente|negocio|numero|equipo|enlace|valor|garantia|pieza|telefono|motivo)\}')


def mejorar_plantilla(tipo_mensaje, plantilla, equipo_desc=''):
    """Reescribe la PLANTILLA (con {cliente}, {enlace}…) sin rellenar: así el
    modelo nunca ve datos del cliente. Debe conservar las mismas variables."""
    ok, motivo = estado()
    if not ok:
        return None, motivo
    variables = sorted(set(_VARIABLES.findall(plantilla)))
    user = (f'Mensaje de WhatsApp de un taller para un cliente («{tipo_mensaje}»'
            f'{", equipo: " + equipo_desc if equipo_desc else ""}):\n«{plantilla}»\n\n'
            'Reescríbelo más cálido y cercano, en español de Colombia, máximo 3 frases, con un emoji como mucho. '
            f'Conserva EXACTAMENTE estas variables entre llaves: {", ".join("{" + v + "}" for v in variables) or "ninguna"}. '
            'No agregues otras variables ni datos. Responde solo el mensaje.')
    texto, err = _ia()._chat(SISTEMA, user, max_tokens=250, temperature=0.6, espera_frio=30, tarea='contenido')
    if not texto:
        return None, err or 'La IA no respondió a tiempo.'
    texto = ' '.join(texto.strip().strip('«»"').split())[:700]
    if sorted(set(_VARIABLES.findall(texto))) != variables or re.search(r'\{(?!(?:' + '|'.join(variables or ['x']) + r')\})', texto):
        return None, 'La IA cambió los datos del mensaje; se deja el original.'
    return texto, None
