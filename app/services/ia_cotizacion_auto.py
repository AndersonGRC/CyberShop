# -*- coding: utf-8 -*-
"""Generar una cotización con IA a partir de lo que mandó el cliente (1.9.14.0).

El negocio adjunta capturas de WhatsApp, fotos, PDF (pedidos del cliente o cotizaciones
anteriores) o pega la conversación. El análisis va por pasos y cada paso se le muestra
a quien cotiza, porque puede tardar varios minutos (prima la calidad, no la velocidad):

  1. leer      el navegador ya hizo el OCR de las imágenes y sacó el texto de los PDF.
  2. vision    el modelo de visión del equipo de IA mira cada imagen (conversación,
               documentos, fotos de equipos) y la transcribe.
  3. contexto  se busca en el catálogo y en las cotizaciones anteriores del negocio.
  4. razonar   el modelo de análisis profundo arma la propuesta: ítems, cantidades,
               condiciones y dudas, con el porqué de cada ítem.
  5. precios   Python pone los precios, nunca la IA: catálogo → cotización anterior →
               costo + margen del negocio → vacío para que lo ponga el negocio. Avisa si
               algo queda por debajo del costo o con un margen alto (no abusar).
  6. notas     las notas adicionales salen del catálogo revisado (services/notas_cotizacion.py).

Todo corre en el equipo de IA del negocio: esta tarea nunca va a la nube (las capturas
traen datos personales del cliente). Nada se guarda: el resultado llena el formulario y
el negocio revisa antes de generar el PDF.
"""
import base64
import binascii
import json
import math
import os
import re
import secrets
import tempfile
import threading
import time

import requests
from flask import copy_current_request_context, current_app

from services import notas_cotizacion as nc

TAREA = 'cotizacion_auto'
MAX_IMAGENES = 8
MAX_IMAGEN_B64 = 2_800_000            # ~2 MB por imagen ya reducida en el navegador
MAX_TEXTO_ARCHIVO = 12_000
MAX_TEXTO_TOTAL = 30_000
MAX_ITEMS = 30
MARGEN_DEFECTO = 30
MARGEN_ALTO = 60                       # por encima se avisa: ¿es justo para el cliente?

PASOS = (
    ('leer', 'Leer tus archivos (OCR en tu navegador)'),
    ('vision', 'Mirar las imágenes con la IA de visión'),
    ('contexto', 'Buscar en tu catálogo y en tus cotizaciones anteriores'),
    ('razonar', 'Razonar la cotización (análisis profundo)'),
    ('precios', 'Calcular precios: catálogo, historial y costo + margen'),
    ('mercado', 'Consultar en internet los precios que falten (nube, solo si hace falta)'),
    ('notas', 'Redactar las notas adicionales'),
)


# ── Lo que llega del navegador ──────────────────────────────────
class EntradaInvalida(ValueError):
    pass


def _texto(valor, maximo):
    """Texto recortado: conserva los saltos de línea (una conversación los necesita)."""
    t = re.sub(r'[ \t\f\v]+', ' ', str(valor or '').replace('\r', ''))
    return re.sub(r'\n{3,}', '\n\n', t)[:maximo].strip()


def leer_entrada(datos):
    """Valida y recorta lo que manda el navegador. Lanza EntradaInvalida."""
    if not isinstance(datos, dict):
        raise EntradaInvalida('Petición inválida.')
    archivos, imagenes, total = [], 0, 0
    for a in (datos.get('archivos') or [])[:20]:
        if not isinstance(a, dict):
            continue
        nombre = _texto(a.get('nombre'), 120) or 'archivo'
        tipo = a.get('tipo') if a.get('tipo') in ('imagen', 'pdf', 'texto') else 'texto'
        texto = _texto(a.get('texto'), MAX_TEXTO_ARCHIVO)
        imagen = None
        if a.get('imagen') and imagenes < MAX_IMAGENES:
            crudo = str(a['imagen']).split(',', 1)[-1]
            if len(crudo) > MAX_IMAGEN_B64:
                raise EntradaInvalida(f'La imagen «{nombre}» es muy pesada.')
            try:
                base64.b64decode(crudo[:400] + '=' * (-len(crudo[:400]) % 4), validate=True)
            except (binascii.Error, ValueError):
                raise EntradaInvalida(f'La imagen «{nombre}» no se pudo leer.')
            imagen = crudo
            imagenes += 1
        if total + len(texto) > MAX_TEXTO_TOTAL:
            texto = texto[:max(0, MAX_TEXTO_TOTAL - total)]
        total += len(texto)
        if texto or imagen:
            archivos.append({'nombre': nombre, 'tipo': tipo, 'texto': texto, 'imagen': imagen})
    conversacion = _texto(datos.get('conversacion'), MAX_TEXTO_TOTAL)
    if not archivos and len(conversacion) < 10:
        raise EntradaInvalida('Adjunta una captura, un PDF o pega la conversación con el cliente.')
    try:
        margen = float(datos.get('margen') if datos.get('margen') not in (None, '') else MARGEN_DEFECTO)
    except (TypeError, ValueError):
        margen = MARGEN_DEFECTO
    margen = max(0.0, min(200.0, margen))
    cliente = datos.get('cliente') if isinstance(datos.get('cliente'), dict) else {}
    cliente = {k: _texto(cliente.get(k), 120) for k in ('nombre', 'documento', 'ciudad', 'telefono')}
    return {'archivos': archivos, 'conversacion': conversacion, 'margen': margen, 'cliente': cliente,
            'consultar_nube': datos.get('consultar_nube') is not False}


# ── Comparar textos (catálogo, historial) ───────────────────────
_VACIAS = nc._VACIAS | {'unidad', 'unidades', 'servicio', 'producto', 'productos', 'favor', 'quiero', 'necesito',
                        'cotizar', 'cotizacion', 'precio', 'valor', 'buenas', 'tardes', 'noches', 'gracias'}


def raices(texto):
    return {w[:5] for w in re.findall(r'[a-z0-9]{3,}', nc.normalizar(texto)) if w not in _VACIAS}


def parecido(pedido, candidato):
    """Qué tanto del ítem pedido aparece en el candidato (0 a 1), con premio si el
    candidato también es corto (no un producto que solo comparte una palabra)."""
    a, b = raices(pedido), raices(candidato)
    if not a or not b:
        return 0.0
    comun = len(a & b)
    return round(0.75 * comun / len(a) + 0.25 * comun / len(b), 3)


def pesos(valor):
    """$45.000: pesos con punto de miles, como se escriben en Colombia."""
    return '$' + f'{valor or 0:,.0f}'.replace(',', '.')


def _numero(valor):
    try:
        n = float(valor)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


# ── Catálogo e historial del negocio ────────────────────────────
def catalogo():
    from database import get_db_cursor
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM productos ORDER BY nombre LIMIT 3000')
            filas = cur.fetchall()
    except Exception:  # noqa: BLE001
        return []
    salida = []
    for f in filas:
        nombre = str(f.get('nombre') or '').strip()
        if nombre:
            salida.append({'id': f.get('id'), 'nombre': nombre, 'referencia': str(f.get('referencia') or '').strip(),
                           'precio': _numero(f.get('precio')), 'costo': _numero(f.get('costo')),
                           'impuesto': str(f.get('impuesto') or ''), 'stock': f.get('stock')})
    return salida


def historial(limite=1500):
    """Líneas de las cotizaciones del negocio, de la más reciente a la más antigua."""
    from database import get_db_cursor
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT d.descripcion, d.precio_unitario, d.cantidad, d.iva_porc, c.id AS cotizacion_id,
                       c.fecha, c.cliente_nombre, c.cliente_telefono
                FROM detalle_cotizacion d JOIN cotizaciones c ON c.id = d.cotizacion_id
                ORDER BY c.fecha DESC, d.id LIMIT %s""", (limite,))
            return cur.fetchall()
    except Exception:  # noqa: BLE001
        return []


def buscar_en_catalogo(texto, productos, minimo=0.6):
    mejor, puntaje = None, 0.0
    ref = nc.normalizar(texto)
    for p in productos:
        codigo = nc.normalizar(p['referencia'])
        if len(codigo) >= 3 and re.search(r'(?<![a-z0-9])' + re.escape(codigo) + r'(?![a-z0-9])', ref):
            return p, 1.0
        s = parecido(texto, f"{p['nombre']} {p['referencia']}")
        if s > puntaje:
            mejor, puntaje = p, s
    return (mejor, puntaje) if puntaje >= minimo else (None, puntaje)


def buscar_en_historial(texto, lineas, minimo=0.7):
    for linea in lineas:                         # ya vienen de la más reciente a la más antigua
        if _numero(linea.get('precio_unitario')) and parecido(texto, linea.get('descripcion')) >= minimo:
            return linea
    return None


def iva_habitual(lineas):
    """¿El negocio suele cotizar con IVA? (la mitad o más de sus últimas líneas)."""
    recientes = lineas[:200]
    if not recientes:
        return None
    con = sum(1 for x in recientes if (_numero(x.get('iva_porc')) or 0) > 0)
    return con * 2 >= len(recientes)


def cotizaciones_del_cliente(cliente, lineas, maximo=3):
    """Las últimas cotizaciones del mismo cliente (por nombre o teléfono), con sus ítems."""
    nombre = nc.normalizar(cliente.get('nombre'))
    tel = re.sub(r'\D', '', str(cliente.get('telefono') or ''))[-10:]
    if len(nombre) < 4 and len(tel) < 7:
        return []
    por_cotizacion = {}
    for x in lineas:
        mismo = (len(nombre) >= 4 and nombre == nc.normalizar(x.get('cliente_nombre'))) or \
                (len(tel) >= 7 and tel == re.sub(r'\D', '', str(x.get('cliente_telefono') or ''))[-10:])
        if mismo:
            por_cotizacion.setdefault(x['cotizacion_id'], []).append(x)
    return list(por_cotizacion.items())[:maximo]


def productos_relacionados(texto, productos, maximo=40):
    """Los productos del catálogo que más se parecen a lo que se habló (para el modelo)."""
    palabras = raices(texto)
    puntajes = []
    for p in productos:
        comun = len(raices(p['nombre']) & palabras)
        if comun:
            puntajes.append((comun, p))
    puntajes.sort(key=lambda t: -t[0])
    return [p for _, p in puntajes[:maximo]]


# ── El modelo de visión (equipo de IA) ──────────────────────────
SISTEMA_VISION = (
    'Transcribes con exactitud imágenes que un negocio en Colombia recibió de un cliente para cotizar. '
    'Nunca inventes: si algo no se lee, escribe [ilegible].')

PEDIDO_VISION = (
    'Imagen «{nombre}». Haz esto en español:\n'
    '1. Si es una conversación (WhatsApp u otra): si arriba se ve el nombre o el número del contacto, escríbelo '
    'primero como «Contacto: …». Luego transcribe los mensajes en orden, una línea por mensaje, empezando '
    'con «Cliente:» (burbujas a la izquierda) o «Negocio:» (burbujas a la derecha, normalmente verdes).\n'
    '2. Si es un documento, lista o factura: copia lo importante (ítems, cantidades, medidas, referencias, '
    'precios, fechas).\n'
    '3. Si es una foto de un equipo o producto: describe qué es, marca, modelo y estado (daños) si se ven.\n'
    'Texto que ya leyó el OCR del navegador (puede tener errores; úsalo como ayuda):\n{ocr}')


def modelo_vision():
    return str(current_app.config.get('AI_MODEL_VISION') or 'qwen3.5:9b').strip()


def _motor_local():
    from services import ia_motores
    return ia_motores.motor_configurado(ia_motores.NIVEL_B)


def _cabeceras():
    llave = str(current_app.config.get('AI_API_KEY') or '').strip()
    return {'Authorization': f'Bearer {llave}'} if llave else {}


def vision_disponible():
    """(True, '') si el equipo de IA responde y tiene el modelo de visión; si no, el motivo."""
    motor = _motor_local()
    if not motor or not motor.configurado:
        return False, 'el equipo de IA no está configurado'
    try:
        r = requests.get(f'{motor.base_url}/api/tags', headers=_cabeceras(), timeout=(3, 8))
        nombres = {m.get('name') for m in (r.json() or {}).get('models', [])} if r.status_code == 200 else set()
    except (requests.RequestException, ValueError):
        return False, 'el equipo de IA está apagado o no responde'
    modelo = modelo_vision()
    if modelo not in nombres and f'{modelo}:latest' not in nombres:
        return False, f'el modelo de visión ({modelo}) no está instalado en el equipo de IA'
    return True, ''


def mirar_imagen(nombre, imagen_b64, ocr=''):
    """Transcripción de una imagen con el modelo de visión, o (None, motivo)."""
    motor = _motor_local()
    cuerpo = {
        'model': modelo_vision(),
        'messages': [
            {'role': 'system', 'content': SISTEMA_VISION},
            {'role': 'user', 'content': PEDIDO_VISION.format(nombre=nombre, ocr=(ocr or 'nada')[:4000]),
             'images': [imagen_b64]},
        ],
        'stream': False,
        'think': False,                      # transcribir no necesita razonar (y tardaría mucho más)
        'keep_alive': '5m',                  # no se queda 30 min ocupando la tarjeta gráfica
        'options': {'temperature': 0.1, 'num_ctx': 8192},
    }
    try:
        r = requests.post(f'{motor.base_url}/api/chat', json=cuerpo, headers=_cabeceras(), timeout=(5, 420))
    except requests.RequestException:
        return None, 'el equipo de IA no respondió'
    if r.status_code != 200:
        return None, f'el modelo de visión devolvió un error ({r.status_code})'
    try:
        texto = ((r.json().get('message') or {}).get('content') or '').strip()
    except ValueError:
        return None, 'respuesta inválida del modelo de visión'
    texto = re.sub(r'<think>.*?</think>', '', texto, flags=re.S).strip()
    return (texto, None) if texto else (None, 'el modelo de visión no devolvió texto')


def liberar_vision():
    """Saca el modelo de visión de la tarjeta gráfica apenas termina. Medido: con los dos
    cargados, el modelo del análisis tardó 6 min en cargar y luego casi no generaba."""
    motor = _motor_local()
    if not motor or not motor.configurado:
        return
    try:
        requests.post(f'{motor.base_url}/api/generate', json={'model': modelo_vision(), 'keep_alive': 0},
                      headers=_cabeceras(), timeout=(3, 30))
    except requests.RequestException:
        pass


# ── El análisis profundo ─────────────────────────────────────────
SISTEMA_PLAN = (
    'Eres el asesor comercial de «{negocio}», un negocio en Colombia. Con la conversación del cliente, sus '
    'documentos y las cotizaciones anteriores armas la propuesta de una cotización nueva: qué ítems cotizar, '
    'cuántos y qué falta confirmar. Buscas que el negocio gane, sin abusar del cliente, y todo debe ser '
    'transparente.\n'
    'Reglas:\n'
    '1. Cotiza solo lo que el cliente pidió o lo necesario para cumplirlo. Lo que agregues por tu cuenta va '
    'con "sugerido": true y su razón; nada de relleno.\n'
    '2. Usa las cantidades y especificaciones que dijo el cliente. Si falta un dato, usa lo más razonable y '
    'escribe la pregunta en "dudas". La cantidad va solo en "cantidad", nunca dentro de la descripción.\n'
    '2b. Si el cliente pide un trabajo (instalar, puntos de red, mantenimiento, reparación, montaje), cotiza el '
    'servicio con lo que incluye; no lo cambies por el puro material.\n'
    '2c. Deja siempre en "dudas" lo que haga falta confirmar para cotizar bien (dirección, fecha, marca, medidas, '
    'horario).\n'
    '3. Coherencia: si hay cotizaciones anteriores (del cliente o del mismo trabajo), usa los mismos nombres '
    'de ítems. Si el ítem está en los PRODUCTOS DEL CATÁLOGO, escribe su nombre exacto.\n'
    '4. No inventes precios. Si un documento o una cotización anterior trae el precio de ese ítem, ponlo en '
    '"precio_referencia" y di de dónde sale en "fuente_precio". Si un documento trae el costo (factura de un '
    'proveedor), ponlo en "costo". Si no hay, deja null.\n'
    '5. Cada ítem lleva "por_que": una cita breve de lo que dijo el cliente o del documento.\n'
    '6. Las condiciones que se hablaron (anticipo, plazo, entrega, garantía, materiales, transporte) van en '
    '"condiciones", una frase por condición.\n'
    '7. Los datos del cliente solo si aparecen (nombre, teléfono, ciudad, documento, dirección); si no, "". Si '
    'pide factura a nombre de una empresa, el cliente es la empresa. La ciudad es la ciudad, no el barrio '
    '(Chapinero → Bogotá).\n'
    '8. Responde SOLO con un JSON válido, así: {{"cliente":{{"nombre":"","telefono":"","ciudad":"",'
    '"documento":"","direccion":""}},"resumen":"","items":[{{"descripcion":"","cantidad":1,'
    '"tipo":"producto","iva":true,"precio_referencia":null,"fuente_precio":"","costo":null,"por_que":"",'
    '"sugerido":false}}],"condiciones":[],"dudas":[]}}. Máximo 30 ítems.'
)


def peticion_plan(lectura, relacionados=(), anteriores=(), cliente_formulario=None):
    """La petición al modelo profundo (el mismo formato del banco de entrenamiento)."""
    partes = ['LO QUE MANDÓ EL CLIENTE:']
    for i, bloque in enumerate(lectura, 1):
        partes.append(f'--- {i}. {bloque["nombre"]} ({bloque["tipo"]}) ---\n{bloque["texto"]}')
    datos = {k: v for k, v in (cliente_formulario or {}).items() if v}
    if datos:
        partes.append('DATOS DEL CLIENTE YA ESCRITOS EN EL FORMULARIO: ' + json.dumps(datos, ensure_ascii=False))
    if anteriores:
        partes.append('COTIZACIONES ANTERIORES DE ESTE CLIENTE:')
        for numero, lineas in anteriores:
            fecha = lineas[0].get('fecha')
            fecha = fecha.strftime('%d/%m/%Y') if hasattr(fecha, 'strftime') else str(fecha or '')
            partes.append(f'Cotización {numero} ({fecha}):')
            partes += [f'- {x.get("cantidad")} × {x.get("descripcion")} a {pesos(_numero(x.get("precio_unitario")))}'
                       for x in lineas[:15]]
    if relacionados:
        partes.append('PRODUCTOS DEL CATÁLOGO QUE PODRÍAN SERVIR (nombre | precio):')
        partes += [f'- {p["nombre"]} | {pesos(p["precio"])}' for p in relacionados]
    partes.append('Responde solo el JSON.')
    return '\n'.join(partes)


def extraer_json(texto):
    from services.ia_notas_cotizacion import extraer_json as _extraer
    return _extraer(texto)


def validar_plan(respuesta):
    """El JSON del modelo, limpio y con topes. None si no sirve."""
    if not isinstance(respuesta, dict) or not isinstance(respuesta.get('items'), list):
        return None
    items = []
    for it in respuesta['items'][:MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        descripcion = _texto(it.get('descripcion'), 200)
        # La cantidad va en su campo: «Punto de red (12 unidades)» → «Punto de red».
        descripcion = re.sub(r'\s*\(\s*\d+\s*(unidades|unidad|und|uds|u)\.?\s*\)\s*$', '', descripcion, flags=re.I)
        descripcion = re.sub(r'^\d+\s*[x×]\s+', '', descripcion).strip()
        if len(descripcion) < 3:
            continue
        try:
            cantidad = max(1, min(100000, int(round(float(it.get('cantidad') or 1)))))
        except (TypeError, ValueError):
            cantidad = 1
        items.append({
            'descripcion': descripcion,
            'cantidad': cantidad,
            'tipo': 'servicio' if str(it.get('tipo')).lower().startswith('serv') else 'producto',
            'iva': it.get('iva') if isinstance(it.get('iva'), bool) else None,
            'precio_referencia': _numero(it.get('precio_referencia')),
            'fuente_precio': _texto(it.get('fuente_precio'), 120),
            'costo': _numero(it.get('costo')),
            'por_que': _texto(it.get('por_que'), 240),
            'sugerido': bool(it.get('sugerido')),
        })
    if not items:
        return None
    cliente = respuesta.get('cliente') if isinstance(respuesta.get('cliente'), dict) else {}
    return {
        'cliente': {k: _texto(cliente.get(k), 120) for k in ('nombre', 'telefono', 'ciudad', 'documento', 'direccion')},
        'resumen': _texto(respuesta.get('resumen'), 600),
        'items': items,
        'condiciones': [_texto(c, 200) for c in (respuesta.get('condiciones') or []) if isinstance(c, str)][:8],
        'dudas': [_texto(d, 200) for d in (respuesta.get('dudas') or []) if isinstance(d, str)][:8],
    }


# ── Precios: los pone Python, con su fuente ─────────────────────
def redondear(valor):
    """Hacia arriba, a la centena (precios en pesos)."""
    return int(math.ceil(valor / 100.0) * 100) if valor else 0


def poner_precios(items, margen, productos, lineas, iva_defecto=None):
    """Cada ítem con precio, fuente y avisos. Nunca inventa un precio."""
    salida = []
    for it in items:
        p, _ = buscar_en_catalogo(it['descripcion'], productos)
        costo = (p or {}).get('costo') or it.get('costo')
        precio, fuente, avisos = 0, '', []
        if p and p.get('precio'):
            precio, fuente = p['precio'], f'Catálogo: {p["nombre"]}'
        elif it.get('precio_referencia'):
            precio, fuente = it['precio_referencia'], it.get('fuente_precio') or 'Documento del cliente o cotización anterior'
        else:
            previa = buscar_en_historial(it['descripcion'], lineas)
            if previa:
                fecha = previa.get('fecha')
                fecha = fecha.strftime('%d/%m/%Y') if hasattr(fecha, 'strftime') else ''
                precio = _numero(previa.get('precio_unitario'))
                fuente = f'Tu cotización {previa.get("cotizacion_id")}' + (f' del {fecha}' if fecha else '')
            elif costo:
                precio = redondear(costo * (1 + margen / 100.0))
                fuente = f'Costo {pesos(costo)} + {margen:g} % de margen'
            else:
                fuente = 'Sin precio de referencia: ponlo tú'
                avisos.append('Falta el precio')
        if costo and precio and precio < costo:
            avisos.append(f'Por debajo del costo ({pesos(costo)})')
        margen_real = round((precio - costo) / costo * 100, 1) if costo and precio else None
        if margen_real is not None and margen_real > max(MARGEN_ALTO, 2 * margen):
            avisos.append(f'Margen de {margen_real:g} %: revisa que sea justo para el cliente')
        iva = it.get('iva')
        if p and '19' in p.get('impuesto', ''):
            iva = True
        if iva is None:
            iva = bool(iva_defecto)
        salida.append({**it, 'precio': round(precio or 0),
                       'fuente': fuente, 'costo': costo, 'margen_real': margen_real, 'iva': iva,
                       'avisos': avisos, 'producto_id': (p or {}).get('id')})
    return salida


def aplicar_precio_de_mercado(item, precio, fuente):
    """Un precio de venta al público consultado en internet: se usa tal cual (ya trae la
    ganancia del mercado; sumarle margen sería cobrar de más) y se marca para verificar."""
    item['precio'] = redondear(precio)
    item['fuente'] = f'Precio de mercado en internet ({fuente})'
    item['avisos'] = [a for a in item['avisos'] if a != 'Falta el precio'] + ['Referencia de internet: verifícala']
    return item


def consultar_mercado(descripciones, ciudad):
    from services import ia_nube
    from services.servicio_tecnico_lector import sin_datos_personales
    return ia_nube.buscar_precios([sin_datos_personales(d) for d in descripciones], ciudad)


def totales(items):
    subtotal = sum(i['precio'] * i['cantidad'] for i in items)
    iva = sum(i['precio'] * i['cantidad'] * 0.19 for i in items if i['iva'])
    costo = sum((i['costo'] or 0) * i['cantidad'] for i in items if i['costo'])
    con_costo = sum(i['precio'] * i['cantidad'] for i in items if i['costo'])
    return {'subtotal': round(subtotal), 'iva': round(iva), 'total': round(subtotal + iva),
            'ganancia_estimada': round(con_costo - costo) if costo else None}


# ── Las notas ────────────────────────────────────────────────────
def notas_para(items, cliente, condiciones):
    base = nc.sugerencias_base([{'descripcion': i['descripcion'], 'cantidad': i['cantidad'],
                                 'iva': 19 if i['iva'] else 0} for i in items],
                               cliente, '. '.join(condiciones))
    return nc.a_texto(base['secciones']), base['avisos']


# ── Hilo con latidos: el análisis tarda minutos y el proxy no debe cortar ──
def _tenant_actual():
    try:
        from flask import g
        return getattr(g, 'current_tenant', None)
    except RuntimeError:
        return None


def _poner_tenant(tenant):
    """El hilo arranca con un `g` vacío: se le pasa la tienda de la petición para que la
    base de datos sea la de ese cliente y no la de otro."""
    if tenant:
        from flask import g
        g.current_tenant = tenant


def en_hilo(funcion, *args, cada=5):
    """Generador: corre `funcion` en otro hilo (con el contexto de la petición) y
    emite None cada `cada` s mientras trabaja. Con `yield from` devuelve su resultado."""
    caja = {}
    tenant = _tenant_actual()

    @copy_current_request_context
    def correr():
        _poner_tenant(tenant)
        try:
            caja['valor'] = funcion(*args)
        except Exception as exc:  # noqa: BLE001
            caja['error'] = exc
    hilo = threading.Thread(target=correr, name='ia-cotizacion', daemon=True)
    hilo.start()
    while hilo.is_alive():
        hilo.join(cada)
        if hilo.is_alive():
            yield None
    if 'error' in caja:
        raise caja['error']
    return caja.get('valor')


def _negocio():
    try:
        from services.public_site_service import get_brand_config
        return (get_brand_config() or {}).get('empresa_nombre') or 'el negocio'
    except Exception:  # noqa: BLE001
        return 'el negocio'


def _razonar(sistema, peticion):
    from services import ai_service as ai
    return ai._chat(sistema, peticion, max_tokens=3000, temperature=0.2, perfil='profundo',
                    tarea=TAREA, permitir_nube=False)


def _minutos(segundos):
    s = int(segundos)
    return f'{s // 60} min {s % 60:02d} s' if s >= 60 else f'{s} s'


# ── El recorrido completo, paso a paso ──────────────────────────
def generar(entrada):
    """Generador de eventos (tipo, dato): ('plan', pasos), ('paso', {...}), ('latido', None),
    ('resultado', propuesta) o ('error', mensaje)."""
    yield 'plan', [{'id': i, 'titulo': t} for i, t in PASOS]

    def paso(ident, estado, detalle=''):
        return 'paso', {'id': ident, 'estado': estado, 'detalle': detalle}

    archivos = entrada['archivos']
    con_imagen = [a for a in archivos if a['imagen']]
    leidos = sum(1 for a in archivos if a['texto'])
    yield paso('leer', 'listo', f'{len(archivos)} archivo(s); el OCR leyó texto en {leidos}'
               + (' y pegaste la conversación' if entrada['conversacion'] else '') + '.')

    # 2 · Visión
    lectura = []
    if entrada['conversacion']:
        lectura.append({'nombre': 'Conversación pegada', 'tipo': 'texto', 'texto': entrada['conversacion']})
    vistas = {}
    if con_imagen:
        ok, motivo = vision_disponible()
        if not ok:
            yield paso('vision', 'omitido', f'No se usó: {motivo}. Sigo con el texto del OCR.')
        else:
            for n, a in enumerate(con_imagen, 1):
                yield paso('vision', 'activo', f'Mirando «{a["nombre"]}» ({n} de {len(con_imagen)})…')
                inicio = time.time()
                trabajo = en_hilo(mirar_imagen, a['nombre'], a['imagen'], a['texto'])
                try:
                    while True:
                        next(trabajo)
                        yield 'latido', None
                        yield paso('vision', 'activo', f'Mirando «{a["nombre"]}» ({n} de {len(con_imagen)})… '
                                   f'{_minutos(time.time() - inicio)}')
                except StopIteration as fin:
                    texto, err = fin.value
                if texto:
                    vistas[a['nombre']] = texto
            liberar_vision()
            yield paso('vision', 'listo' if vistas else 'omitido',
                       f'{len(vistas)} de {len(con_imagen)} imágenes transcritas.' if vistas
                       else 'La IA de visión no pudo leerlas; sigo con el texto del OCR.')
    else:
        yield paso('vision', 'omitido', 'No hay imágenes.')
    for a in archivos:
        texto = vistas.get(a['nombre']) or a['texto']
        if vistas.get(a['nombre']) and a['texto']:
            texto = f'{vistas[a["nombre"]]}\n(OCR del navegador: {a["texto"][:1500]})'
        if texto:
            lectura.append({'nombre': a['nombre'], 'tipo': a['tipo'], 'texto': texto[:MAX_TEXTO_ARCHIVO]})
    if not lectura:
        yield 'error', 'No se pudo leer nada de los archivos. Prueba con capturas más nítidas o pega la conversación.'
        return

    # 3 · Contexto del negocio
    yield paso('contexto', 'activo', 'Buscando…')
    productos = catalogo()
    lineas = historial()
    todo = ' '.join(b['texto'] for b in lectura)
    relacionados = productos_relacionados(todo, productos)
    anteriores = cotizaciones_del_cliente(entrada['cliente'], lineas)
    yield paso('contexto', 'listo', f'{len(productos)} productos en tu catálogo ({len(relacionados)} relacionados); '
               f'{len(anteriores)} cotización(es) anterior(es) de este cliente.')

    # 4 · Análisis profundo
    yield paso('razonar', 'activo', 'Pensando la propuesta… puede tardar varios minutos.')
    inicio = time.time()
    trabajo = en_hilo(_razonar, SISTEMA_PLAN.format(negocio=_negocio()),
                      peticion_plan(lectura, relacionados, anteriores, entrada['cliente']))
    try:
        while True:
            next(trabajo)
            yield 'latido', None
            yield paso('razonar', 'activo', f'Pensando la propuesta… {_minutos(time.time() - inicio)}')
    except StopIteration as fin:
        texto, err = fin.value
    plan = validar_plan(extraer_json(texto)) if texto else None
    if not plan:
        yield paso('razonar', 'error', err or 'La respuesta de la IA no se pudo usar.')
        yield 'error', (err or 'La IA no pudo armar la propuesta.') + ' Intenta de nuevo o pega la conversación como texto.'
        return
    # El cliente del formulario manda; la IA solo llena lo vacío.
    if not anteriores and plan['cliente'].get('nombre'):
        anteriores = cotizaciones_del_cliente(plan['cliente'], lineas)
    yield paso('razonar', 'listo', f'{len(plan["items"])} ítem(s) en {_minutos(time.time() - inicio)}.')

    # 5 · Precios
    yield paso('precios', 'activo', 'Calculando…')
    items = poner_precios(plan['items'], entrada['margen'], productos, lineas, iva_habitual(lineas))
    faltan = [n for n, i in enumerate(items) if not i['precio']]
    yield paso('precios', 'listo', f'{len(items) - len(faltan)} con precio'
               + (f'; {len(faltan)} sin precio de referencia' if faltan else '') + '.')
    cliente = {**plan['cliente'], **{k: v for k, v in entrada['cliente'].items() if v}}

    # 6 · Solo lo que falte, una consulta corta a la nube (se paga): la IA local hizo el resto.
    if not faltan:
        yield paso('mercado', 'omitido', 'Todos los ítems tienen precio: no hizo falta la nube (sin costo).')
    elif not entrada['consultar_nube']:
        yield paso('mercado', 'omitido', 'Desactivaste la consulta en internet: pon tú los precios que faltan.')
    else:
        yield paso('mercado', 'activo', f'Consultando {len(faltan)} ítem(s) sin precio…')
        trabajo = en_hilo(consultar_mercado, [items[n]['descripcion'] for n in faltan], cliente.get('ciudad'))
        try:
            while True:
                next(trabajo)
                yield 'latido', None
        except StopIteration as fin:
            hallados, motivo = fin.value
        for k, (precio, fuente) in hallados.items():
            aplicar_precio_de_mercado(items[faltan[k]], precio, fuente)
        if hallados:
            yield paso('mercado', 'listo', f'{len(hallados)} de {len(faltan)} precios encontrados en internet.')
        else:
            yield paso('mercado', 'omitido', f'No se usó: {motivo}.' if motivo
                       else 'No se encontraron precios confiables: ponlos tú.')

    # 7 · Notas
    notas, avisos_notas = notas_para(items, cliente, plan['condiciones'])
    yield paso('notas', 'listo', f'{notas.count(chr(8226))} notas organizadas por sección.')

    avisos = []
    if entrada['margen'] > MARGEN_ALTO:
        avisos.append(f'Usaste un margen de {entrada["margen"]:g} %: revisa que el precio final sea justo para el cliente.')
    avisos += avisos_notas
    yield 'resultado', {
        'cliente': plan['cliente'],
        'resumen': plan['resumen'],
        'items': items,
        'totales': totales(items),
        'condiciones': plan['condiciones'],
        'dudas': plan['dudas'],
        'notas': notas,
        'avisos': avisos,
        'margen': entrada['margen'],
    }


# ── Trabajo en segundo plano ────────────────────────────────────
# Cada tienda corre con gunicorn (workers sync, --timeout 120): una petición que dure más
# de 120 s se corta aunque vaya enviando latidos, y el análisis real tarda de 5 a 8 min.
# Por eso corre en un hilo aparte y la pantalla pregunta el avance cada pocos segundos.
# El avance vive en un archivo (los dos workers de la tienda lo ven), atado a la base de
# datos de la tienda y a quien lo pidió.
CARPETA_TRABAJOS = os.path.join(tempfile.gettempdir(), 'cybershop_cotizacion_ia')
VIDA_TRABAJO_S = 3 * 3600
_ID_VALIDO = re.compile(r'^[A-Za-z0-9_-]{16,64}$')


def _base_actual():
    from database import _current_db_name
    return re.sub(r'[^A-Za-z0-9_-]', '_', str(_current_db_name() or 'base'))[:60]


def _ruta(trabajo, base=None):
    return os.path.join(CARPETA_TRABAJOS, f'{base or _base_actual()}__{trabajo}.json')


def _escribir(ruta, estado):
    temporal = f'{ruta}.{threading.get_ident()}.tmp'
    with open(temporal, 'w', encoding='utf-8') as f:
        json.dump(estado, f, ensure_ascii=False, default=str)
    for intento in range(20):
        try:
            os.replace(temporal, ruta)          # en Windows falla si alguien lo está leyendo justo ahora
            return
        except PermissionError:
            time.sleep(0.05)
    try:
        os.remove(temporal)
    except OSError:
        pass


def _limpiar_viejos():
    try:
        ahora = time.time()
        for nombre in os.listdir(CARPETA_TRABAJOS):
            ruta = os.path.join(CARPETA_TRABAJOS, nombre)
            if ahora - os.path.getmtime(ruta) > VIDA_TRABAJO_S:
                os.remove(ruta)
    except OSError:
        pass


def iniciar_trabajo(entrada, usuario_id):
    """Arranca el análisis en un hilo y devuelve el identificador del trabajo."""
    os.makedirs(CARPETA_TRABAJOS, exist_ok=True)
    _limpiar_viejos()
    trabajo = secrets.token_urlsafe(18)
    ruta = _ruta(trabajo)
    estado = {'usuario': usuario_id, 'creado': time.time(), 'eventos': [], 'fin': False}
    _escribir(ruta, estado)
    tenant = _tenant_actual()

    @copy_current_request_context
    def correr():
        _poner_tenant(tenant)
        ultimo_latido = 0.0
        try:
            for tipo, dato in generar(entrada):
                if os.path.exists(ruta + '.cancelar'):
                    estado['eventos'].append({'e': 'error', 'd': 'Análisis detenido.'})
                    break
                if tipo == 'latido':
                    if time.time() - ultimo_latido < 15:
                        continue
                    ultimo_latido = time.time()          # solo deja constancia de que sigue vivo
                else:
                    estado['eventos'].append({'e': tipo, 'd': dato})
                _escribir(ruta, estado)
        except Exception as exc:  # noqa: BLE001
            try:
                current_app.logger.exception(f'Cotización con IA: {exc}')
            except Exception:  # noqa: BLE001
                pass
            estado['eventos'].append({'e': 'error', 'd': 'Algo falló al armar la cotización. Intenta de nuevo.'})
        finally:
            estado['fin'] = True
            _escribir(ruta, estado)
            try:
                os.remove(ruta + '.cancelar')
            except OSError:
                pass

    threading.Thread(target=correr, name=f'cotizacion-ia-{trabajo[:6]}', daemon=True).start()
    return trabajo


def _cargar(trabajo, usuario_id):
    if not _ID_VALIDO.match(str(trabajo or '')):
        return None, None
    ruta = _ruta(trabajo)
    estado = None
    for intento in range(10):
        try:
            with open(ruta, encoding='utf-8') as f:
                estado = json.load(f)
            break
        except FileNotFoundError:
            return None, None
        except (PermissionError, ValueError):
            time.sleep(0.05)                    # se está reemplazando en este instante
        except OSError:
            return None, None
    if estado is None:
        return None, None
    if estado.get('usuario') != usuario_id:
        return None, None                                  # solo quien lo pidió ve su análisis
    return ruta, estado


def leer_trabajo(trabajo, usuario_id, desde=0):
    """{'eventos': los nuevos desde `desde`, 'total', 'fin'} o None si no existe."""
    _, estado = _cargar(trabajo, usuario_id)
    if estado is None:
        return None
    eventos = estado.get('eventos') or []
    desde = max(0, min(int(desde or 0), len(eventos)))
    return {'eventos': eventos[desde:], 'total': len(eventos), 'fin': bool(estado.get('fin'))}


def cancelar_trabajo(trabajo, usuario_id):
    ruta, estado = _cargar(trabajo, usuario_id)
    if estado is None:
        return False
    if not estado.get('fin'):
        open(ruta + '.cancelar', 'w').close()
    return True
