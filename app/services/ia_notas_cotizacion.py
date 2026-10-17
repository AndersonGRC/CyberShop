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
    '4. Las INDICACIONES DEL NEGOCIO mandan: usa sus valores (porcentajes, días, garantías) y convierte cada '
    'CONDICIÓN DEL NEGOCIO (qué incluye el precio, qué se cobra aparte, materiales, desplazamientos, horarios…) '
    'en una nota clara y con buena ortografía, en la sección indicada. Si contradice una cláusula de referencia, '
    'deja la del negocio y omite la otra. Lo que el negocio deba confirmar va entre corchetes, por ejemplo [15] días.\n'
    '5. Frases cortas y claras en español de Colombia, sin emojis ni markdown. Una idea por nota, de '
    'máximo 280 caracteres.\n'
    '6. Analiza las NOTAS QUE YA ESCRIBIÓ EL NEGOCIO: no las repitas ni las digas con otras palabras; sugiere solo '
    'lo que las complemente (temas que falten o detalles nuevos). Si alguna es abusiva o cita una norma dudosa, '
    'dilo en «avisos» con la alternativa justa.\n'
    '7. Responde SOLO con un JSON válido, así: {{"secciones":[{{"titulo":"Vigencia y precios","notas":["..."]}}],'
    '"avisos":[]}}. Máximo 8 secciones, 4 notas por sección y 20 notas en total, con estos títulos y en este '
    'orden cuando apliquen: ' + ', '.join(nc.SECCIONES) + '. Si no hay nada nuevo que sugerir, responde '
    '{{"secciones":[],"avisos":[]}}.'
)


def _limpio(texto, nombres=()):
    try:
        from services.servicio_tecnico_lector import sin_datos_personales
        return sin_datos_personales(texto, nombres)
    except Exception:  # noqa: BLE001
        return texto


def _notas_escritas(notas_actuales, nombres=(), maximo=1800):
    """Las notas del cuadro, línea por línea (títulos y viñetas), para que el modelo las analice."""
    lineas, total = [], 0
    for linea in str(notas_actuales or '').splitlines():
        linea = ' '.join(linea.split())
        if not linea:
            continue
        if total + len(linea) > maximo:
            lineas.append('…')
            break
        lineas.append(linea)
        total += len(linea)
    return _limpio('\n'.join(lineas), nombres)


def peticion(ctx, notas_actuales='', nombres=(), ya_vistas=()):
    """Lo que se le pide al modelo (el mismo formato del banco de entrenamiento). Solo van
    como referencia las cláusulas que el negocio aún no tiene ni se le han mostrado."""
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
    visto = nc.lo_ya_visto(notas_actuales, ya_vistas)
    condiciones = [(s, t) for s, t in ctx.get('condiciones') or [] if not nc.ya_escrita(t, visto)]
    if condiciones:
        lineas.append('CONDICIONES DEL NEGOCIO (deben quedar como notas, bien redactadas, en esta sección):')
        lineas += [f'[{s}] {_limpio(t, nombres)}' for s, t in condiciones]
    actuales = _notas_escritas(notas_actuales, nombres)
    lineas.append('NOTAS QUE YA ESCRIBIÓ EL NEGOCIO (analízalas; no las repitas ni las reformules; complementa '
                  'solo lo que falte):' + ('\n' + actuales if actuales else ' ninguna'))
    propias = set(ctx.get('condiciones') or [])
    referencias = [(s, t) for s, t in nc.clausulas_para(ctx) if (s, t) not in propias and not nc.ya_escrita(t, visto)]
    if referencias:
        lineas.append('CLÁUSULAS DE REFERENCIA (revisadas; escoge las que apliquen y adáptalas):')
        lineas += [f'[{s}] {t}' for s, t in referencias]
    else:
        lineas.append('CLÁUSULAS DE REFERENCIA: ninguna nueva (lo importante ya está escrito).')
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


def _contar(secciones):
    return sum(len(s['notas']) for s in secciones)


def asegurar_condiciones(secciones, ctx, visto=''):
    """Cada condición que escribió el negocio queda en las sugerencias: si la IA no la
    incluyó (ni con otras palabras), entra la versión del catálogo al inicio de su sección.
    Devuelve (secciones, notas que responden a sus indicaciones)."""
    faltan, de_tus = [], []
    for s, t in ctx.get('condiciones') or []:
        if nc.ya_escrita(t, visto):
            continue
        cubierta = False
        for seccion in secciones:
            if nc.cobertura(t, ' '.join(seccion['notas'])) >= 0.5:
                cubierta = True
                de_tus += [n for n in seccion['notas'] if nc.cobertura(t, n) >= 0.25]
        if not cubierta:
            faltan.append((s, t))
            de_tus.append(t)
    if faltan:
        pares = faltan + [(x['titulo'], n) for x in secciones for n in x['notas']]
        secciones = nc.agrupar(pares, propias={s for s, _ in faltan})
    return secciones, list(dict.fromkeys(de_tus))


def sugerir(items, cliente=None, indicaciones='', notas_actuales='', ya_vistas=()):
    """{'secciones', 'avisos', 'origen': 'ia' | 'base' | 'vacio', 'de_tus_indicaciones'}.
    No sugiere lo que ya está en las notas ni lo que ya se le mostró (`ya_vistas`)."""
    cliente = cliente or {}
    ctx = nc.contexto(items, cliente, indicaciones)
    if not ctx['items']:
        return {'secciones': [], 'avisos': ['Agrega primero lo que vas a cotizar.'], 'origen': 'vacio',
                'de_tus_indicaciones': []}
    base = nc.sugerencias_base(items, cliente, indicaciones, notas_actuales, ya_vistas)
    visto = nc.lo_ya_visto(notas_actuales, ya_vistas)

    def con_base(motivo):
        return {'secciones': base['secciones'], 'origen': 'base',
                'de_tus_indicaciones': base['de_tus_indicaciones'],
                'avisos': [f'{motivo} Te mostramos las sugerencias base, revisadas.'] + base['avisos']}

    from services import ai_service as ai
    ok, motivo = ai.estado_ia()
    if not ok:
        return con_base(motivo)
    if not base['secciones']:
        # Lo importante ya está escrito o ya se mostró: no hace falta despertar a la IA.
        return {'secciones': [], 'origen': 'base', 'avisos': base['avisos'], 'de_tus_indicaciones': []}
    negocio = 'el negocio'
    try:
        from services.public_site_service import get_brand_config
        negocio = (get_brand_config() or {}).get('empresa_nombre') or negocio
    except Exception:  # noqa: BLE001
        pass
    nombres = tuple(p for p in [str(cliente.get('nombre') or '').strip()] if p)
    texto, err = ai._chat(SISTEMA.format(negocio=negocio), peticion(ctx, notas_actuales, nombres, ya_vistas),
                          max_tokens=1600, temperature=0.3, espera_frio=40, tarea=TAREA)
    if err or not texto:
        return con_base(err or 'La IA no respondió.')
    respuesta = extraer_json(texto)
    if not isinstance(respuesta, dict) or not isinstance(respuesta.get('secciones'), list):
        return con_base('La respuesta de la IA no se pudo usar.')
    utiles, _ = validar(respuesta)                    # ¿dio algo usable, antes de quitar lo ya visto?
    if _contar(utiles) < min(3, _contar(base['secciones'])):
        return con_base('La respuesta de la IA no se pudo usar.')
    secciones, _descartadas = validar(respuesta, visto)
    secciones, de_tus = asegurar_condiciones(secciones, ctx, visto)
    avisos = list(dict.fromkeys(ctx['avisos'] + nc.revisar_notas(notas_actuales) + _avisos(respuesta)))
    return {'secciones': secciones, 'avisos': avisos[:5], 'origen': 'ia', 'descartadas': _descartadas,
            'de_tus_indicaciones': de_tus}
