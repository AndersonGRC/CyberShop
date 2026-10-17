# -*- coding: utf-8 -*-
"""Notas adicionales de la cotización sugeridas por la IA del negocio (1.9.13.0).

La IA lee lo que se cotiza (productos y servicios), el tipo de cliente y las
indicaciones del negocio, y propone notas organizadas por sección, legales en
Colombia y justas para las dos partes. Solo con el módulo Asistente IA activo.

Cómo se cuida el resultado:
  - La IA recibe como referencia las cláusulas revisadas de services/notas_cotizacion.py
    y solo puede citar esas normas: una nota que cite otra ley se descarta.
  - Una nota abusiva (sin garantía, anticipo que nunca se devuelve…) se descarta.
  - Al modelo no llegan el nombre, el documento ni el teléfono del cliente: solo si es
    empresa o persona natural y su ciudad; el texto libre pasa por sin_datos_personales.
  - Si la IA no responde (equipo apagado o cargando) o su respuesta no sirve, se
    devuelven las sugerencias base del catálogo, con un aviso.
"""
import json
import re

from services import notas_cotizacion as nc

TAREA = 'cotizacion_notas'

SISTEMA = (
    'Eres el asistente de cotizaciones de «{negocio}», un negocio en Colombia. Redactas las NOTAS '
    'ADICIONALES que van al final de una cotización: condiciones claras, legales en Colombia y justas para '
    'el cliente y para el negocio.\n'
    'Reglas:\n'
    '1. Parte de las CLÁUSULAS DE REFERENCIA (están revisadas): escoge solo las que apliquen a lo que se '
    'cotiza y adáptalas a esos productos o servicios. Puedes unir dos parecidas en una sola nota y agregar '
    'notas propias del servicio (alcance, entregables, tiempos) sin citar normas.\n'
    '2. Cita solo las normas que aparecen en las cláusulas de referencia, igual que allí. Nunca inventes '
    'leyes, artículos, decretos ni resoluciones.\n'
    '3. Nada de cláusulas abusivas (art. 43 de la Ley 1480 de 2011): no quites ni limites la garantía legal, '
    'no digas que el anticipo nunca se devuelve, no niegues devoluciones o reclamos, no hagas renunciar al '
    'cliente a sus derechos. Si las indicaciones del negocio piden algo así, no lo incluyas: deja la '
    'alternativa justa y explícalo en «avisos».\n'
    '4. Usa los valores de las INDICACIONES DEL NEGOCIO (porcentajes, días, garantías). Lo que el negocio '
    'deba confirmar va entre corchetes, por ejemplo [15] días.\n'
    '5. Frases cortas y claras en español de Colombia, sin emojis ni markdown. Una idea por nota, de '
    'máximo 280 caracteres.\n'
    '6. No repitas las notas que el negocio ya escribió.\n'
    '7. Responde SOLO con un JSON válido, así: {{"secciones":[{{"titulo":"Vigencia y precios","notas":["..."]}}],'
    '"avisos":[]}}. Usa de 4 a 8 secciones, máximo 4 notas por sección y máximo 20 notas en total, con estos '
    'títulos y en este orden cuando apliquen: ' + ', '.join(nc.SECCIONES) + '.'
)


def _limpio(texto, nombres=()):
    try:
        from services.servicio_tecnico_lector import sin_datos_personales
        return sin_datos_personales(texto, nombres)
    except Exception:  # noqa: BLE001
        return texto


def peticion(ctx, notas_actuales='', nombres=()):
    """Lo que se le pide al modelo (el mismo formato del banco de entrenamiento)."""
    lineas = [f"CLIENTE: {ctx['cliente']}" + (f", en {ctx['ciudad']}" if ctx['ciudad'] else '')]
    lineas.append('LO QUE SE COTIZA:')
    for item in ctx['items'][:25]:
        try:
            cantidad = int(float(item.get('cantidad') or 1))
        except (TypeError, ValueError):
            cantidad = 1
        tipo = 'servicio' if nc.es_servicio(item.get('descripcion')) else 'producto'
        iva = 'con IVA 19 %' if float(item.get('iva') or 0) > 0 else 'sin IVA'
        descripcion = _limpio(' '.join(str(item.get('descripcion')).split())[:160], nombres)
        lineas.append(f'- {cantidad} × {descripcion} ({tipo}, {iva})')
    tipos = [nc.CATEGORIAS[c]['nombre'] for c in ctx['categorias']]
    lineas.append('TIPO: ' + ('; '.join(tipos) if tipos else 'venta general'))
    lineas.append('INDICACIONES DEL NEGOCIO: ' + (_limpio(ctx['indicaciones'], nombres) or 'ninguna'))
    actuales = _limpio(' '.join(str(notas_actuales or '').split())[:600], nombres)
    lineas.append('NOTAS QUE YA ESCRIBIÓ EL NEGOCIO (no las repitas): ' + (actuales or 'ninguna'))
    lineas.append('CLÁUSULAS DE REFERENCIA (revisadas; escoge las que apliquen y adáptalas):')
    lineas += [f'[{s}] {t}' for s, t in nc.clausulas_para(ctx)]
    lineas.append('Responde solo el JSON.')
    return '\n'.join(lineas)


def extraer_json(texto):
    """El primer objeto JSON del texto (el modelo a veces escribe algo antes o después)."""
    texto = str(texto or '')
    inicio = texto.find('{')
    while inicio != -1:
        nivel, dentro, escape = 0, False, False
        for i in range(inicio, len(texto)):
            ch = texto[i]
            if dentro:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    dentro = False
                continue
            if ch == '"':
                dentro = True
            elif ch == '{':
                nivel += 1
            elif ch == '}':
                nivel -= 1
                if nivel == 0:
                    try:
                        valor = json.loads(texto[inicio:i + 1])
                        return valor if isinstance(valor, dict) else None
                    except ValueError:
                        break
        inicio = texto.find('{', inicio + 1)
    return None


_TITULOS = (('vigencia', 'Vigencia y precios'), ('precio', 'Vigencia y precios'), ('alcance', 'Alcance del servicio'),
            ('incluye', 'Alcance del servicio'), ('entrega', 'Tiempos de entrega'), ('plazo', 'Tiempos de entrega'),
            ('tiempo', 'Tiempos de entrega'), ('pago', 'Forma de pago'), ('garant', 'Garantía'),
            ('responsab', 'Responsabilidades del cliente'), ('cliente', 'Responsabilidades del cliente'),
            ('propiedad', 'Propiedad intelectual'), ('autor', 'Propiedad intelectual'),
            ('cancel', 'Cancelaciones'), ('retracto', 'Cancelaciones'), ('impuest', 'Impuestos y facturación'),
            ('factur', 'Impuestos y facturación'), ('iva', 'Impuestos y facturación'),
            ('dato', 'Datos personales'), ('privacidad', 'Datos personales'))


def titulo_canonico(titulo):
    n = nc.normalizar(titulo)
    for s in nc.SECCIONES:
        if n == nc.normalizar(s):
            return s
    for clave, s in _TITULOS:
        if clave in n:
            return s
    return 'Alcance del servicio'


def _nota_limpia(nota):
    t = re.sub(r'[*_`#]+', '', str(nota or ''))               # sin markdown
    t = re.sub(r'^\s*([•\-–·]|\d+[.)])\s*', '', t)              # sin viñeta ni numeración
    t = ' '.join(t.split())
    if len(t) > nc.MAX_LARGO_NOTA:
        corte = t.rfind('. ', 0, nc.MAX_LARGO_NOTA)
        t = t[:corte + 1] if corte > 80 else t[:nc.MAX_LARGO_NOTA].rsplit(' ', 1)[0] + '…'
    return t


def validar(respuesta, notas_actuales=''):
    """Secciones de la IA ya revisadas: títulos conocidos, notas limpias, sin citas
    inventadas, sin cláusulas abusivas, sin repetir lo escrito, con los topes."""
    pares, descartadas = [], 0
    for seccion in (respuesta or {}).get('secciones') or []:
        if not isinstance(seccion, dict):
            continue
        titulo = titulo_canonico(seccion.get('titulo'))
        for nota in seccion.get('notas') or []:
            if not isinstance(nota, str):
                continue
            t = _nota_limpia(nota)
            if len(t) < 15:
                continue
            if nc.es_abusiva(t) or nc.cita_norma_no_permitida(t) or nc.ya_escrita(t, notas_actuales):
                descartadas += 1
                continue
            pares.append((titulo, t))
    return nc.agrupar(pares), descartadas


def _avisos(respuesta):
    salida = []
    for a in (respuesta or {}).get('avisos') or []:
        if isinstance(a, str) and a.strip() and not nc.cita_norma_no_permitida(a):
            salida.append(' '.join(a.split())[:300])
    return salida[:3]


def sugerir(items, cliente=None, indicaciones='', notas_actuales=''):
    """{'secciones', 'avisos', 'origen': 'ia' | 'base' | 'vacio'}."""
    cliente = cliente or {}
    ctx = nc.contexto(items, cliente, indicaciones)
    if not ctx['items']:
        return {'secciones': [], 'avisos': ['Agrega primero lo que vas a cotizar.'], 'origen': 'vacio'}
    base = nc.sugerencias_base(items, cliente, indicaciones, notas_actuales)

    def con_base(motivo):
        return {'secciones': base['secciones'], 'origen': 'base',
                'avisos': [f'{motivo} Te mostramos las sugerencias base, revisadas.'] + base['avisos']}

    from services import ai_service as ai
    ok, motivo = ai.estado_ia()
    if not ok:
        return con_base(motivo)
    negocio = 'el negocio'
    try:
        from services.public_site_service import get_brand_config
        negocio = (get_brand_config() or {}).get('empresa_nombre') or negocio
    except Exception:  # noqa: BLE001
        pass
    nombres = tuple(p for p in [str(cliente.get('nombre') or '').strip()] if p)
    texto, err = ai._chat(SISTEMA.format(negocio=negocio), peticion(ctx, notas_actuales, nombres),
                          max_tokens=1600, temperature=0.3, espera_frio=40, tarea=TAREA)
    if err or not texto:
        return con_base(err or 'La IA no respondió.')
    respuesta = extraer_json(texto)
    secciones, _descartadas = validar(respuesta, notas_actuales)
    if sum(len(s['notas']) for s in secciones) < 3:
        return con_base('La respuesta de la IA no se pudo usar.')
    avisos = list(dict.fromkeys(ctx['avisos'] + _avisos(respuesta)))
    return {'secciones': secciones, 'avisos': avisos, 'origen': 'ia', 'descartadas': _descartadas}
