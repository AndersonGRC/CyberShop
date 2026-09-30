"""Contrato de parámetros para las consultas de solo lectura del panel.

El modelo elige la capacidad, pero no decide por sí solo el significado de un
período omitido ni puede inventar el nombre de una persona o producto. Esta
capa no ejecuta consultas ni sustituye la comprobación de permisos del servidor.
"""

import re
from datetime import date

from services.ia.enrutador import _PERIODOS_TEXTO, normalizar
from services.ia_datos.base import PERIODOS


# Solo estos procesos consultan la ficha de UNA entidad. Los parámetros de
# búsqueda libres (p. ej. documentos_internos.texto) no son una identidad.
_IDENTIDADES = {
    'cliente_historial': ('cliente', '¿De qué cliente necesitas el historial de compras?'),
    'producto_detalle': ('producto', '¿De qué producto necesitas la ficha? Indícame su nombre.'),
    'nomina_empleado': ('empleado', '¿De qué empleado necesitas consultar la nómina?'),
}
_NOMBRES_VACIOS = {
    'cliente', 'clientes', 'producto', 'productos', 'empleado', 'empleados',
    'todos', 'todas', 'alguien', 'ninguno', 'no especificado', 'desconocido',
}
_ALIAS_PERIODO = {
    'año': 'anio', 'ano': 'anio', 'este_anio': 'anio',
    'semana_pasada': 'semana_anterior', 'mes_pasado': 'mes_anterior',
    'historico': 'todo', 'histórico': 'todo', 'siempre': 'todo',
}
_RE_SEGUIMIENTO = re.compile(
    r'^\s*[¿\s]*(?:y\b|ahora\b|tambien\b|lo mismo\b|ese\b|esa\b|esos\b|esas\b|'
    r'su\b|sus\b|de el\b|de ella\b|del mismo\b|la misma\b)'
)
_RE_TIEMPO_VAGO = re.compile(
    r'\b(?:ultimos?\s+dias|ultimas?\s+semanas|ultimos?\s+meses|'
    r'hace\s+(?:unos|varios)\s+dias|recientemente|ultimamente|'
    r'en\s+estos\s+dias|periodo\s+anterior|ese\s+periodo|mismo\s+periodo)\b'
)
_RE_FECHA_ESPECIFICA = re.compile(
    r'\b(?:19|20)\d{2}\b|\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
    r'septiembre|octubre|noviembre|diciembre|trimestre|quincena)\b|'
    r'\bultim[oa]s?\s+\d+\s+(?:dias|semanas|meses)\b|'
    r'\b(?:ano|mes|semana)\s+antepasad[oa]\b|\bano\s+(?:pasado|anterior)\b|'
    r'\bultim[oa]\s+(?:mes|semana|ano)\b|'
    r'\bhace\s+\d+\s+(?:dias|semanas|meses)\b|'
    r'\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+pasado\b|'
    r'\bdia\s+\d{1,2}\b|\b(?:desde|entre)\s+(?:el\s+)?\d{1,2}\b|'
    r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b'
)
_RE_DESGLOSE = re.compile(r'\b(?:por|cada)\s+(?:mes|semana|ano)\b')
_PERIODOS_EXTRA = (('mes', 'mes'), ('semana', 'semana'), ('ano', 'anio'))
_RE_COMPARACION = re.compile(r'\b(?:compar\w*|mas\s+que|menos\s+que|frente\s+a|contra)\b')
_PAR_ACTUAL = {'mes_anterior': 'mes', 'semana_anterior': 'semana', 'ayer': 'hoy'}


def _codigo_y_params(herramienta):
    return getattr(herramienta, 'code', ''), tuple(getattr(herramienta, 'params', ()))


def _palabras(texto):
    return ' '.join(re.findall(r'\w+', normalizar(str(texto or ''))))


def _contiene_nombre(texto, nombre):
    origen, buscado = _palabras(texto), _palabras(nombre)
    if not origen or not buscado:
        return False
    return bool(re.search(rf'(?<!\w){re.escape(buscado)}(?!\w)', origen))


def _preguntas_previas(historial):
    # Jamás se usan respuestas del asistente ni campos de herramienta aportados
    # por el navegador para completar identidades o períodos.
    if not isinstance(historial, (list, tuple)):
        return []
    return [str(t.get('pregunta') or '') for t in historial[-3:]
            if isinstance(t, dict) and t.get('pregunta')]


def _periodos(texto):
    """Períodos explícitos sin contar subcadenas solapadas dos veces."""
    plano = normalizar(str(texto or ''))
    hallados = []
    frases = sorted((*_PERIODOS_TEXTO, *_PERIODOS_EXTRA), key=lambda x: len(x[0]), reverse=True)
    for frase, periodo in frases:
        for m in re.finditer(rf'(?<!\w){re.escape(frase)}(?!\w)', plano):
            if not any(m.start() < fin and inicio < m.end() for inicio, fin, _ in hallados):
                hallados.append((m.start(), m.end(), periodo))
    return list(dict.fromkeys(p for _, _, p in sorted(hallados)))


def _periodos_contextuales(pregunta, historial):
    actuales = _periodos(pregunta)
    if actuales or not _RE_SEGUIMIENTO.match(normalizar(pregunta or '')):
        return actuales
    for anterior in reversed(_preguntas_previas(historial)):
        encontrados = _periodos(anterior)
        if encontrados:
            return encontrados
    return []


def _periodos_aceptables(pregunta, mencionados):
    """Una comparación con «mes pasado» también puede pedir «este mes»."""
    aceptables = set(mencionados)
    if _RE_COMPARACION.search(normalizar(pregunta or '')):
        aceptables.update(_PAR_ACTUAL[p] for p in mencionados if p in _PAR_ACTUAL)
    return aceptables


def _rango_suministrado(params):
    return any(params.get(k) not in (None, '') for k in ('desde', 'hasta'))


def _rango_valido(params):
    if not all(params.get(k) not in (None, '') for k in ('desde', 'hasta')):
        return False
    fechas = []
    for k in ('desde', 'hasta'):
        valor = params.get(k)
        if valor in (None, ''):
            continue
        if not isinstance(valor, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', valor):
            return False
        try:
            fechas.append(date.fromisoformat(valor))
        except ValueError:
            return False
    return not (len(fechas) == 2 and fechas[0] > fechas[1])


def _periodo_canonico(valor):
    clave = str(valor or '').strip().lower().replace(' ', '_')
    clave = _ALIAS_PERIODO.get(clave, clave)
    return clave if clave in PERIODOS else None


def normalizar_params_consulta(herramienta, params, pregunta, historial=None):
    """Copia los parámetros y fija un período inequívoco antes de ejecutar.

    Un rango explícito y una comparación de varias ventanas conservan los
    parámetros que el modelo eligió; `pregunta_faltante` los valida después.
    """
    salida = dict(params) if isinstance(params, dict) else {}
    code, permitidos = _codigo_y_params(herramienta)
    if 'periodo' not in permitidos:
        return salida
    encontrados = _periodos_contextuales(pregunta, historial)
    if _rango_suministrado(salida):
        # Un rango fabricado por el modelo no debe desplazar un período simple
        # y explícito del usuario. Con fechas concretas o varias ventanas sí se
        # conservan los rangos: son necesarios para expresar esas consultas.
        if (len(encontrados) == 1 and
                not _RE_FECHA_ESPECIFICA.search(normalizar(pregunta or '')) and
                not _RE_TIEMPO_VAGO.search(normalizar(pregunta or ''))):
            salida.pop('desde', None)
            salida.pop('hasta', None)
            salida['periodo'] = encontrados[0]
        return salida
    if len(encontrados) == 1:
        dado = _periodo_canonico(salida.get('periodo'))
        salida['periodo'] = (dado if dado in _periodos_aceptables(pregunta, encontrados)
                             else encontrados[0])
    elif len(encontrados) == 0 and not _RE_FECHA_ESPECIFICA.search(normalizar(pregunta or '')):
        # Contrato del panel: sin fecha se consulta el histórico, salvo el
        # comparativo, que requiere una ventana finita de igual duración.
        salida['periodo'] = 'mes' if code == 'comparativo_ventas' else 'todo'
    return salida


def pregunta_faltante(herramienta, params, pregunta, historial=None):
    """Pregunta puntual si falta una identidad o la ventana no es confiable.

    Retorna None si la consulta puede proseguir. El caller debe ejecutar con
    `normalizar_params_consulta(...)`, no con los parámetros crudos del modelo.
    """
    code, permitidos = _codigo_y_params(herramienta)
    params = normalizar_params_consulta(herramienta, params, pregunta, historial)
    if code in _IDENTIDADES:
        campo, aclaracion = _IDENTIDADES[code]
        nombre = str(params.get(campo) or '').strip()
        sustentado = _contiene_nombre(pregunta, nombre)
        if not sustentado and _RE_SEGUIMIENTO.match(normalizar(pregunta or '')):
            sustentado = any(_contiene_nombre(q, nombre) for q in _preguntas_previas(historial))
        if not nombre or _palabras(nombre) in _NOMBRES_VACIOS or not sustentado:
            return aclaracion

    if 'periodo' not in permitidos:
        return None
    plano = normalizar(pregunta or '')
    if _RE_TIEMPO_VAGO.search(plano):
        anterior = _periodos_contextuales(pregunta, historial)
        misma_ventana = (len(anterior) == 1 and
                         re.search(r'\b(?:ese|mismo)\s+periodo\b', plano))
        if not misma_ventana and not (code == 'comparativo_ventas' and
                                     'periodo anterior' in plano):
            return '¿Qué período exacto quieres consultar? Indícame las fechas o la cantidad de días.'
    if _RE_DESGLOSE.search(plano) and code != 'comparativo_ventas':
        return '¿Quieres un total de un período concreto o un desglose por cada período?'
    if _rango_suministrado(params):
        if not _rango_valido(params):
            return 'No pude interpretar el rango. ¿Cuáles son las fechas de inicio y fin (AAAA-MM-DD)?'
        return None
    if _RE_FECHA_ESPECIFICA.search(plano):
        return '¿Qué fechas exactas quieres consultar? Indícame el inicio y el fin (AAAA-MM-DD).'
    periodo = _periodo_canonico(params.get('periodo'))
    if periodo is None:
        return '¿Qué período quieres consultar? Puedes indicar hoy, ayer, esta semana, este mes o fechas exactas.'
    mencionados = _periodos_contextuales(pregunta, historial)
    if mencionados and periodo not in _periodos_aceptables(pregunta, mencionados):
        return '¿A cuál de los períodos mencionados te refieres para esta consulta?'
    return None


def instrucciones_para_catalogo(disponibles):
    """Guía breve, condicionada por los procesos que realmente puede usar el rol."""
    codigos = {getattr(h, 'code', '') for h in disponibles}
    partes = [
        'Cada herramienta del catálogo representa un proceso de consulta independiente. '
        'Elige solo las necesarias; si se piden varias cosas o se comparan períodos, '
        'devuelve una entrada por consulta. No inventes nombres, fechas ni filtros.',
    ]
    identidades = [f'{code} requiere «{campo}»' for code, (campo, _) in _IDENTIDADES.items()
                   if code in codigos]
    if identidades:
        partes.append('Identidad obligatoria: ' + '; '.join(identidades) + '. '
                      'Usa el nombre literal de la pregunta o de una pregunta previa clara. '
                      'Si falta o es ambiguo, elige la herramienta con params {}: '
                      'el servidor pedirá la aclaración antes de consultar.')
    if any('periodo' in getattr(h, 'params', ()) for h in disponibles):
        partes.append('Período: sin fecha explícita usa «todo» (histórico); '
                      'comparativo_ventas usa «mes» si no se indica ventana. '
                      'Para fechas concretas entrega desde/hasta en AAAA-MM-DD. '
                      'Si la expresión temporal es vaga, no adivines: el servidor '
                      'pedirá fechas. Conserva los dos períodos de una comparación.')
    return '\n'.join(partes)
