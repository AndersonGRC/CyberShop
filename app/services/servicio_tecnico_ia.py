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
  - Importador: la IA lee documentos viejos y columnas de Excel con títulos
    raros; cada valor, fecha y mantenimiento que propone se busca en el
    documento y lo que no aparece se descarta.
"""

import json
import re
from datetime import date, timedelta

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


def recortar_relevante(texto, limite=MAX_PARA_IA, patron=None):
    """Si el texto no cabe, se quedan las líneas con datos técnicos (en su
    orden y sin repetidas) en vez de cortarlo a la mitad: un `systeminfo` con
    200 parches de Windows ya no esconde la RAM ni el disco al final.
    `patron`: qué líneas sirven (por defecto, las técnicas).
    Devuelve (texto, {'lineas_totales', 'lineas_usadas'} o None)."""
    if len(texto) <= limite:
        return texto, None
    patron = patron or _LINEA_TECNICA
    lineas = [l.rstrip() for l in texto.split('\n')]
    vistas, elegidas = set(), []
    for i, linea in enumerate(lineas):
        clave = linea.strip().lower()
        if not clave or clave in vistas:
            continue
        if i < 15 or patron.search(linea) or re.search(r'[:\t].*\d', linea):
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


# ── 5. Importador: documentos viejos y columnas de Excel ────────
# Líneas útiles de una hoja de vida o un historial: las técnicas, las que
# traen fecha y las que hablan de mantenimientos.
_LINEA_DOCUMENTO = re.compile(
    _LINEA_TECNICA.pattern + r'|\d{1,4}[/\-.]\d{1,2}[/\-.]\d{2,4}|mantenimiento|mtto|limpieza|preventiv|correctiv|'
    r'repar|cambio|instal|formate|revisi|diagn|actualiz|servicio|tipo de equipo|frecuencia|pr[oó]xim', re.I)
# Campos extra que se le piden a la IA en un documento (los del tipo se filtran después).
_EXTRAS_DOCUMENTO = ('tipo_disco', 'ram_ranuras_total', 'ram_ranuras_libres', 'tarjeta_video', 'bateria_desgaste',
                     'bateria_salud', 'version_sistema', 'imei2', 'capacidad_va', 'capacidad_w', 'autonomia_min',
                     'baterias_cantidad', 'baterias_voltaje', 'baterias_ultimo_cambio', 'pulgadas', 'tecnologia',
                     'contador_paginas', 'licencia_windows')
_FRECUENCIA_PALABRAS = {1: ('mensual',), 2: ('bimestral',), 3: ('trimestral',), 4: ('cuatrimestral',),
                        6: ('semestral', 'dos veces al ano'), 12: ('anual', 'una vez al ano', 'cada ano')}
_MESES = ('ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic')


def _campos_para_documento():
    lineas = [f'- {c}: {tipos.ETIQUETAS_COMUNES[c]}' for c in _COLUMNAS]
    vistos = set()
    for codigo in tipos.CODIGOS:
        for clave, etiqueta, tipo_input, opciones in tipos.campos_extra(codigo):
            if clave not in _EXTRAS_DOCUMENTO or clave in vistos:
                continue
            vistos.add(clave)
            extra = f" (una de: {', '.join(opciones)})" if opciones else (' (sí/no)' if tipo_input == 'si_no' else '')
            extra += ' (AAAA-MM-DD)' if tipo_input == 'fecha' else ''
            extra += ' (solo el número)' if tipo_input == 'numero' else ''
            lineas.append(f'- extra.{clave}: {etiqueta}{extra}')
    return '\n'.join(lineas)


def _fecha_doc(valor, hoy):
    try:
        f = date.fromisoformat(str(valor or '').strip()[:10])
    except ValueError:
        return None
    return f if date(1990, 1, 1) <= f <= hoy + timedelta(days=3 * 366) else None


def fecha_en_texto(f, plano):
    """¿La fecha aparece en el documento? (15/03/2025, 15-3-25, 2025-03-15,
    03/15/2025 o «15 de marzo de 2025»). `plano`: texto en minúscula y sin tildes."""
    d, m, a = f.day, f.month, f.year
    variantes = set()
    for dd in {str(d), f'{d:02d}'}:
        for mm in {str(m), f'{m:02d}'}:
            for sep in '/-.':
                for aa in {str(a), f'{a % 100:02d}'}:
                    variantes.add(f'{dd}{sep}{mm}{sep}{aa}')
                    variantes.add(f'{mm}{sep}{dd}{sep}{aa}')
                variantes.add(f'{a}{sep}{mm}{sep}{dd}')
    if re.search(r'(?<!\d)(?:' + '|'.join(re.escape(v) for v in variantes) + r')(?!\d)', plano):
        return True
    return bool(re.search(rf'(?<!\d){d}\s*(?:de\s+)?{_MESES[m - 1]}\w*\.?\s*(?:de\s+|del\s+)?{a}(?!\d)', plano))


def _meses_ok(meses, plano):
    if not isinstance(meses, int) or not 1 <= meses <= 36:
        return False
    if re.search(rf'(?<!\d){meses}\s*mes', plano):
        return True
    return any(p in plano for p in _FRECUENCIA_PALABRAS.get(meses, ()))


def _palabras_presentes(texto, plano, minimo):
    palabras = [w for w in re.findall(r'[a-z]{3,}', _plano(texto)) if w not in ('del', 'los', 'las', 'con', 'por', 'para')]
    if not palabras:
        return True
    return sum(1 for w in palabras if w in plano) / len(palabras) >= minimo


def _motor_preparando(err):
    try:
        return bool(err) and err == _ia().MSG_MOTOR_PREPARANDO
    except Exception:  # noqa: BLE001
        return False


def interpretar_documento(texto, tipo_sugerido=None, nombres=(), hoy=None):
    """Equipos que describe un documento viejo (ficha técnica, hoja de vida,
    historial de mantenimientos): ficha, mantenimientos con fecha y el próximo.

    El texto pasa antes por `limpiar_personales` y `sin_datos_personales` (con
    los nombres que el importador encontró con reglas fijas): a la IA no le
    llegan nombre, teléfono, correo ni documento del cliente. Cada valor, fecha
    y mantenimiento que propone se busca en el documento; lo que no aparece se
    descarta. Devuelve {'equipos': [...], 'ia': bool, 'aviso': str|None,
    'reintentar': bool, 'descartados': int}."""
    hoy = hoy or date.today()
    salida = {'equipos': [], 'ia': False, 'aviso': None, 'reintentar': False, 'descartados': 0}
    limpio = lector.sin_datos_personales(lector.limpiar_personales(texto), nombres)
    if len(re.sub(r'\s', '', limpio)) < 20:
        salida['aviso'] = 'El documento casi no tiene texto para leer.'
        return salida
    ok, motivo = estado()
    if not ok:
        salida['aviso'] = motivo
        return salida
    para_ia, recorte = recortar_relevante(limpio, patron=_LINEA_DOCUMENTO)
    sugerido = (f'Por las reglas parece: {tipos.nombre(tipo_sugerido)}.\n'
                if tipo_sugerido and tipo_sugerido != 'otro' else '')
    user = ('Documento de un taller de reparación (ficha técnica, hoja de vida o historial de mantenimiento)'
            f'{" — solo las líneas útiles, porque era muy largo" if recorte else ""}:\n<<<\n{para_ia}\n>>>\n\n'
            f'{sugerido}'
            'Tipos de equipo (usa el código): ' + ', '.join(f'{c} = {tipos.nombre(c)}' for c in tipos.CODIGOS) + '.\n'
            f'Campos del equipo (usa exactamente estas claves):\n{_campos_para_documento()}\n\n'
            'Reglas: copia cada valor TAL CUAL aparece en el documento (no conviertas ni completes). Si un dato no '
            'está, NO lo pongas. Fechas en AAAA-MM-DD. Un equipo por cada equipo distinto que describa el documento '
            '(máximo 8); el monitor, el teclado y el mouse de un computador NO son equipos aparte. En «mantenimientos» '
            'van solo los que tienen fecha en el documento (máximo 15 por equipo).\n'
            'Responde SOLO un JSON así: {"equipos": [{"tipo": "portatil", "campos": {"marca": "...", '
            '"extra.tipo_disco": "..."}, "mantenimientos": [{"fecha": "AAAA-MM-DD", "tipo": "preventivo o correctivo", '
            '"que_se_hizo": "..."}], "proximo_mantenimiento": "AAAA-MM-DD o vacío", "cada_meses": número o null, '
            '"resumen": "1 o 2 frases sobre el equipo"}]}')
    texto_ia, err = _ia()._chat(SISTEMA, user, max_tokens=1600, temperature=0.1, espera_frio=25, tarea='contenido')
    datos = _json_de(texto_ia) if texto_ia else None
    if not isinstance(datos, dict):
        salida['reintentar'] = not texto_ia and _motor_preparando(err)
        salida['aviso'] = ('La respuesta de la IA llegó incompleta.' if texto_ia
                           else (err or 'La IA no respondió a tiempo.'))
        return salida
    lista = datos.get('equipos')
    if not isinstance(lista, list):
        lista = [datos] if isinstance(datos.get('campos'), dict) else []
    plano = _plano(limpio)
    descartados = 0
    for e in lista[:8]:
        if not isinstance(e, dict):
            continue
        tipo = str(e.get('tipo') or '').strip().lower()
        if not tipos.es_valido(tipo):
            tipo = tipos.tipo_desde_texto(tipo) or tipo_sugerido or 'otro'
        leido = _validar(tipo, e.get('campos') if isinstance(e.get('campos'), dict) else {})
        columnas, extras = {}, {}
        for clave, valor in leido['columnas'].items():
            if verificado(valor, plano):
                columnas[clave] = valor
            else:
                descartados += 1
        for clave, valor in leido['extras'].items():
            if verificado(valor, plano) or str(valor).lower() in ('si', 'no') or any(
                    w in plano for w in _plano(valor).split() if len(w) > 2):
                extras[clave] = valor
            else:
                descartados += 1
        historial = []
        for m in (e.get('mantenimientos') or [])[:30]:
            if not isinstance(m, dict):
                continue
            f = _fecha_doc(m.get('fecha'), hoy)
            que = ' '.join(str(m.get('que_se_hizo') or m.get('descripcion') or '').split())[:500]
            if not f or f > hoy or not fecha_en_texto(f, plano) or not _palabras_presentes(que, plano, 0.5):
                descartados += 1
                continue
            historial.append({'fecha': f.isoformat(),
                              'tipo': 'correctivo' if 'correct' in str(m.get('tipo') or '').lower() else 'preventivo',
                              'descripcion': que})
        proximo = _fecha_doc(e.get('proximo_mantenimiento'), hoy)
        if proximo and not fecha_en_texto(proximo, plano):
            proximo, descartados = None, descartados + 1
        try:
            cada = int(e.get('cada_meses')) if e.get('cada_meses') not in (None, '') else None
        except (TypeError, ValueError):
            cada = None
        if cada is not None and not _meses_ok(cada, plano):
            cada = None
        if not columnas and not extras and not historial:
            continue
        salida['equipos'].append({'tipo': tipo, 'columnas': columnas, 'extras': extras, 'historial': historial,
                                  'proximo': proximo.isoformat() if proximo else None, 'cada_meses': cada,
                                  'resumen': str(e.get('resumen') or '').strip()[:400]})
    salida.update(ia=True, descartados=descartados)
    if descartados:
        salida['aviso'] = (f'La IA propuso {descartados} dato(s) que no aparecen tal cual en el documento: '
                           'no se usaron.')
    return salida


def mapear_columnas(columnas, destinos):
    """Columnas de un Excel con un título que las reglas no entienden → campo.

    `columnas`: [{'col': n, 'encabezado': str, 'ejemplos': [str]}]; los ejemplos
    ya vienen sin datos personales. `destinos`: {clave: descripción}. Devuelve
    {'mapeo': {col: clave}, 'ia': bool, 'aviso': str|None, 'reintentar': bool}."""
    salida = {'mapeo': {}, 'ia': False, 'aviso': None, 'reintentar': False}
    if not columnas:
        return salida
    ok, motivo = estado()
    if not ok:
        salida['aviso'] = motivo
        return salida
    lineas = [f'- columna {c["col"]}: «{c["encabezado"] or "(sin título)"}» → ejemplos: '
              + ' | '.join(f'«{e}»' for e in (c.get('ejemplos') or [])[:4]) for c in columnas[:40]]
    user = ('Estas columnas de un Excel de equipos de un taller tienen un título que no reconocimos:\n'
            + '\n'.join(lineas)
            + '\n\nCampos posibles (usa exactamente la clave):\n'
            + '\n'.join(f'- {k}: {v}' for k, v in destinos.items())
            + '\n\nPara cada columna di a qué campo corresponde por su título y sus ejemplos. Si es un dato que no '
              'está en la lista, «notas»; si no sirve (números de fila, vacía), «ignorar». '
              'Responde SOLO un JSON: {"columnas": {"<número de columna>": "clave"}}')
    texto_ia, err = _ia()._chat(SISTEMA, user, max_tokens=500, temperature=0.1, espera_frio=25, tarea='contenido')
    datos = _json_de(texto_ia) if texto_ia else None
    if not isinstance(datos, dict):
        salida['reintentar'] = not texto_ia and _motor_preparando(err)
        salida['aviso'] = ('La respuesta de la IA llegó incompleta.' if texto_ia
                           else (err or 'La IA no respondió a tiempo.'))
        return salida
    validas = {str(c['col']) for c in columnas}
    crudo = datos.get('columnas') if isinstance(datos.get('columnas'), dict) else {}
    for col, clave in crudo.items():
        clave = str(clave or '').strip()
        if str(col) in validas and clave in destinos:
            salida['mapeo'][int(col)] = clave
    salida['ia'] = True
    return salida


# ── 6. Ficha técnica: redactar los textos con el estilo del taller ──
# Dos fichas reales del taller, sin nombres ni usuarios: la IA aprende el tono,
# el largo y el orden (descripción, vida útil, recomendaciones, problema y
# requerimientos). Ficha roja = presenta inconvenientes; azul = buen estado.
_EJEMPLOS_FICHA = (
    'Ejemplo 1. Datos: portátil HP Laptop 15-gw0; AMD Ryzen 3 3250U (2 núcleos / 4 hilos); 8 GB DDR4, 1 de 2 '
    'ranuras en uso; memoria disponible 1,01 GB; SSD NVMe 239 GB; Windows 11 Home.\n'
    '{"estado": "inconveniente", "descripcion": "Este equipo de cómputo es un portátil HP Laptop 15-gw0 con procesador '
    'AMD Ryzen 3 3250U (2 núcleos / 4 hilos), gráficos Radeon integrados y 8 GB de RAM. Es un equipo de gama básica apto '
    'para ofimática, navegación en internet, videoconferencias y tareas de productividad ligera.", "vida_util": "La vida '
    'útil estimada de un portátil como este (AMD Ryzen 3 3250U, 8 GB de RAM) es de 4 a 6 años desde su fabricación, '
    'dependiendo del uso, el mantenimiento y las actualizaciones realizadas. Actualmente presenta muy poca memoria '
    'disponible (1,01 GB), lo que afecta el rendimiento; se recomienda ampliar la RAM. Recomendaciones:", '
    '"recomendaciones": ["Conectarlo a un regulador de voltaje o UPS.", "Realizar mantenimiento periódico al sistema de '
    'enfriamiento y cambio de pasta térmica.", "Ampliar la memoria RAM para mejorar el rendimiento.", "Desinstalar '
    'programas innecesarios y mantener Windows 11 actualizado.", "Mantenerlo limpio y libre de polvo (teclado, rejillas y '
    'ventilador)."], "problema": "Memoria RAM insuficiente: 8 GB instalados con solo 1,01 GB disponibles, lo que afecta '
    'el rendimiento.", "requerimientos": "Ampliación de memoria RAM a 16 GB (mínimo recomendado) aprovechando el slot '
    'SO-DIMM libre: agregar un módulo de 8 GB DDR4. Incluye mantenimiento preventivo: limpieza interna y cambio de pasta '
    'térmica.", "destacar": ["Memoria RAM"]}\n\n'
    'Ejemplo 2. Datos: portátil Lenovo IdeaPad Slim 3 15ABR8; AMD Ryzen 7 5825U (8 núcleos / 16 hilos); 16 GB DDR4 '
    'soldada, sin ranuras libres; SSD 512 GB; Windows 11 Home.\n'
    '{"estado": "bueno", "descripcion": "Este equipo de cómputo es un portátil Lenovo IdeaPad Slim 3 15ABR8 con '
    'procesador AMD Ryzen 7 5825U (8 núcleos / 16 hilos), gráficos Radeon integrados y 16 GB de RAM, apto para '
    'ofimática, navegación en internet, videoconferencias, multimedia y aplicaciones de productividad de exigencia '
    'media-alta.", "vida_util": "La vida útil estimada de un portátil como este (AMD Ryzen 7 5825U, 16 GB de RAM) es de '
    '5 a 7 años desde su fabricación, dependiendo del uso, el mantenimiento y las actualizaciones realizadas. Al contar '
    'con 16 GB de RAM tiene buen margen de rendimiento para ofimática, navegación y videoconferencia. Recomendaciones:", '
    '"recomendaciones": ["Conectarlo a un regulador de voltaje o UPS.", "Realizar mantenimiento periódico al sistema de '
    'enfriamiento y cambio de pasta térmica.", "Cuidar el ciclo de carga de la batería y evitar descargas totales.", '
    '"Desinstalar programas innecesarios y mantener Windows 11 actualizado.", "Mantenerlo limpio y libre de polvo '
    '(teclado, rejillas y ventilador)."], "problema": "N/A - El equipo no presenta fallas.", "requerimientos": '
    '"Mantenimiento preventivo. El equipo cumple el mínimo recomendado de 16 GB de RAM DDR4 (memoria soldada, sin slots '
    'disponibles para ampliación). Se recomienda limpieza interna, cambio de pasta térmica y verificación de la unidad '
    'de almacenamiento.", "destacar": []}')
# Filas de la ficha que NO van a la IA (identifican a la persona o al equipo en su red).
_FILAS_PRIVADAS = ('nombre de usuario', 'usuario', 'directorios del sistema', 'zona horaria')
_DATO_TECNICO = re.compile(r'(\d+(?:[.,]\d+)?)\s*(gb|mb|tb|ghz|nucleos|hilos|anos|ranuras?|slots?|modulos?)\b')


def _datos_para_ficha(equipo, filas):
    """Solo lo técnico del equipo, en una línea por dato (nada de la persona)."""
    lineas = [f'Tipo de equipo: {tipos.nombre(equipo.get("tipo"))}']
    for c in _COLUMNAS:
        if equipo.get(c) and c not in ('serial', 'imei'):
            lineas.append(f'{tipos.ETIQUETAS_COMUNES[c]}: {equipo[c]}')
    etiquetas = {c[0]: c[1] for c in tipos.campos_extra(equipo.get('tipo'))}
    for clave, valor in (equipo.get('extras') or {}).items():
        if clave in etiquetas and valor:
            lineas.append(f'{etiquetas[clave]}: {valor}')
    for etiqueta, valor in filas:
        if valor and _plano(etiqueta) not in _FILAS_PRIVADAS:
            lineas.append(f'{etiqueta}: {valor}')
    vistos, salida = set(), []
    for linea in lineas:
        if linea not in vistos:
            vistos.add(linea)
            salida.append(lector.sin_datos_personales(linea))
    return '\n'.join(salida)


_TAMANOS_ESTANDAR = {'1', '2', '4', '8', '16', '32', '64', '128', '256', '512'}


def _sin_datos_inventados(texto, datos_plano, permitidos=()):
    """¿Cada cantidad técnica del texto (GB, GHz, núcleos…) está en los datos?
    `permitidos`: cantidades que se aceptan aunque no estén (p. ej. «ampliar a
    16 GB» en los requerimientos)."""
    for numero, unidad in _DATO_TECNICO.findall(_plano(texto)):
        if unidad in ('anos', 'ranura', 'ranuras', 'slot', 'slots', 'modulo', 'modulos') or numero in permitidos:
            continue                                # años de vida útil y cantidades de piezas a cambiar
        variantes = {numero, numero.replace(',', '.'), numero.replace('.', ','), numero.split(',')[0].split('.')[0]}
        if not any(re.search(r'(?<![\d.,])' + re.escape(v) + r'(?![\d])', datos_plano) for v in variantes):
            return False
    return True


def redactar_ficha(equipo, filas, borrador):
    """Textos de la ficha técnica redactados por la IA con el estilo del taller.

    `filas`: [(etiqueta, valor)] de las características; `borrador`: lo que
    proponen las reglas (la IA lo mejora). A la IA solo le llegan datos
    técnicos. Un texto que menciona una cantidad que no está en los datos se
    cambia por el de las reglas. Devuelve {'propuesta', 'ia', 'aviso'}."""
    salida = {'propuesta': dict(borrador), 'ia': False, 'aviso': None}
    ok, motivo = estado()
    if not ok:
        salida['aviso'] = f'{motivo} Se propusieron los textos con las reglas.'
        return salida
    datos = _datos_para_ficha(equipo, filas)
    etiquetas = [e for e, v in filas if v]
    user = ('Redacta la ficha técnica de un equipo con el MISMO estilo, tono y largo de estos ejemplos del taller:\n\n'
            f'{_EJEMPLOS_FICHA}\n\n'
            f'Datos del equipo (usa SOLO estos; no inventes cantidades ni piezas):\n<<<\n{datos}\n>>>\n\n'
            f'Borrador hecho con reglas (corrígelo y mejóralo): {json.dumps(borrador, ensure_ascii=False)}\n\n'
            '«estado» es «inconveniente» si el equipo necesita algo además del mantenimiento preventivo (memoria '
            'insuficiente, disco mecánico, batería gastada, arranque seguro desactivado, sistema sin soporte…); si no, '
            '«bueno» y el problema es «N/A - El equipo no presenta fallas.». En «destacar» van las filas que muestran el '
            f'problema, escogidas de: {", ".join(etiquetas) or "ninguna"}.\n'
            'Responde SOLO un JSON con las claves estado, descripcion, vida_util, recomendaciones (lista de 4 a 7 frases '
            'cortas), problema, requerimientos y destacar.')
    texto_ia, err = _ia()._chat(SISTEMA, user, max_tokens=1100, temperature=0.3, espera_frio=30, tarea='contenido')
    respuesta = _json_de(texto_ia) if texto_ia else None
    if not isinstance(respuesta, dict):
        salida['aviso'] = (('La respuesta de la IA llegó incompleta.' if texto_ia else (err or 'La IA no respondió a '
                                                                                                'tiempo.'))
                           + ' Se propusieron los textos con las reglas.')
        return salida
    plano = _plano(datos)
    metas = _TAMANOS_ESTANDAR | {n for n, _u in _DATO_TECNICO.findall(_plano(json.dumps(borrador, ensure_ascii=False)))}
    propuesta, cambiados, tomados = dict(borrador), [], 0
    for clave, largo in (('descripcion', 1500), ('vida_util', 2500), ('problema', 1500), ('requerimientos', 2500)):
        valor = ' '.join(str(respuesta.get(clave) or '').split())[:largo]
        if not valor:
            continue
        if _sin_datos_inventados(valor, plano, metas if clave in ('problema', 'requerimientos') else ()):
            propuesta[clave] = valor
            tomados += 1
        else:
            cambiados.append(clave)
    recomendaciones = [' '.join(str(r).split())[:300] for r in (respuesta.get('recomendaciones') or [])
                       if isinstance(r, str) and r.strip()][:8]
    if recomendaciones:
        if all(_sin_datos_inventados(r, plano, metas) for r in recomendaciones):
            propuesta['recomendaciones'] = recomendaciones
            tomados += 1
        else:
            cambiados.append('recomendaciones')
    if not tomados:
        # Nada de la respuesta sirvió: se queda TODO lo de las reglas (también el color y lo resaltado).
        salida['aviso'] = ('La IA no devolvió textos utilizables'
                           + (' (mencionó datos que no están en el equipo)' if cambiados else '')
                           + '. Se propusieron los textos con las reglas.')
        return salida
    if respuesta.get('estado') in ('bueno', 'inconveniente'):
        propuesta['estado'] = respuesta['estado']
    destacar = [d for d in (respuesta.get('destacar') or []) if isinstance(d, str) and d in etiquetas]
    if propuesta['estado'] == 'bueno':
        destacar = []
    propuesta['destacar'] = destacar if 'destacar' in respuesta else borrador.get('destacar', [])
    salida.update(propuesta=propuesta, ia=True)
    if cambiados:
        salida['aviso'] = ('La IA mencionó datos que no están en el equipo; en ' + ', '.join(cambiados)
                           + ' quedó el texto de las reglas.')
    return salida
