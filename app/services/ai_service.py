"""Asistente IA del tenant — cliente compatible con OpenAI (Ollama / cloud).

AISLAMIENTO POR CLIENTE (requisito de seguridad):
- Este servicio corre dentro de la instancia del tenant; todo `get_db_cursor()`
  resuelve SOLO a la BD de ese cliente. No acepta `tenant_id` por parámetro.
- Las llamadas al modelo son stateless: cada request lleva únicamente datos del
  cliente actual; el modelo no retiene contexto entre clientes aunque la
  máquina Ollama sea compartida.
- El "agente" se aterriza en el contexto del propio cliente (`_contexto_tenant`,
  leído de SU base de datos): nombre de empresa y sus categorías.
"""

import hashlib
import re
import time

import requests
from flask import current_app

from database import get_db_cursor
from tenant_features import is_module_active, MODULE_AI, get_current_tenant_id


# ── Caché de respuestas (aislada por tenant) ───────────────────
# Misma consulta repetida (mismo tenant, misma función, mismo input) reusa la
# respuesta y libera la GPU. La CLAVE incluye el tenant_id → nunca se comparte
# una respuesta entre clientes (sin fuga). TTL corto; cache en proceso por
# instancia (cada cliente tiene su instancia, así que ya está particionada).
_CACHE = {}
_CACHE_TTL = 60 * 60          # 1 hora
_CACHE_MAX = 500             # tope de entradas por instancia


def _cache_key(funcion, *partes):
    base = '|'.join(str(p or '') for p in partes).lower().strip()
    h = hashlib.sha256(base.encode('utf-8')).hexdigest()[:24]
    return f"{get_current_tenant_id()}:{funcion}:{h}"


def _cache_get(key):
    item = _CACHE.get(key)
    if not item:
        return None
    valor, exp = item
    if time.time() > exp:
        _CACHE.pop(key, None)
        return None
    return valor


def _cache_set(key, valor):
    if len(_CACHE) >= _CACHE_MAX:
        # purga simple: elimina las expiradas; si no hay, vacía a la mitad
        ahora = time.time()
        vencidas = [k for k, (_, e) in _CACHE.items() if e < ahora]
        for k in vencidas:
            _CACHE.pop(k, None)
        if len(_CACHE) >= _CACHE_MAX:
            for k in list(_CACHE.keys())[:_CACHE_MAX // 2]:
                _CACHE.pop(k, None)
    _CACHE[key] = (valor, time.time() + _CACHE_TTL)


# ── Disponibilidad ─────────────────────────────────────────────
def ia_disponible():
    """True si el módulo IA está activo para este tenant Y hay endpoint."""
    try:
        if not is_module_active(MODULE_AI):
            return False
        return bool((current_app.config.get('AI_BASE_URL') or '').strip())
    except Exception:
        return False


def estado_ia():
    """Diagnóstico para la UI: (disponible, motivo)."""
    if not is_module_active(MODULE_AI):
        return False, 'El módulo Asistente IA no está habilitado en tu plan.'
    if not (current_app.config.get('AI_BASE_URL') or '').strip():
        return False, 'La IA no está configurada (falta el servidor de IA). Contacta a soporte.'
    return True, 'Asistente IA activo.'


def ping():
    """Verifica si el servidor de IA (Ollama) responde. Para el indicador de la
    UI. Devuelve {online, modelo, motivo}. No lanza excepciones."""
    if not is_module_active(MODULE_AI):
        return {'online': False, 'modelo': None,
                'motivo': 'El módulo Asistente IA no está habilitado.'}
    base = (current_app.config.get('AI_BASE_URL') or '').strip().rstrip('/')
    modelo = current_app.config.get('AI_MODEL') or 'qwen2.5:7b'
    if not base:
        return {'online': False, 'modelo': modelo,
                'motivo': 'La IA no está configurada (falta el servidor de IA).'}
    key = (current_app.config.get('AI_API_KEY') or '').strip()
    headers = {'Authorization': f'Bearer {key}'} if key else {}
    try:
        r = requests.get(f'{base}/api/tags', headers=headers, timeout=5)
        if r.status_code == 200:
            return {'online': True, 'modelo': modelo, 'motivo': 'IA en línea.'}
        # Algunos proveedores cloud no exponen /api/tags pero sí /v1/models
        r = requests.get(f'{base}/v1/models', headers=headers, timeout=5)
        if r.status_code == 200:
            return {'online': True, 'modelo': modelo, 'motivo': 'IA en línea.'}
        return {'online': False, 'modelo': modelo,
                'motivo': f'El servidor de IA respondió {r.status_code}.'}
    except requests.RequestException:
        return {'online': False, 'modelo': modelo,
                'motivo': 'El servidor de IA está fuera de línea (¿tu equipo está apagado o desconectado?).'}


# ── Contexto del tenant (SOLO su BD) ───────────────────────────
def _contexto_tenant():
    """Arma el contexto del agente leyendo ÚNICAMENTE la BD del tenant actual:
    nombre de la empresa y sus categorías de producto. Nunca toca otra BD."""
    nombre = 'la tienda'
    categorias = []
    try:
        from services.public_site_service import get_brand_config
        brand = get_brand_config() or {}
        nombre = brand.get('empresa_nombre') or nombre
    except Exception:
        pass
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT nombre FROM generos ORDER BY nombre LIMIT 30")
            categorias = [r['nombre'] for r in cur.fetchall()]
    except Exception:
        pass
    ctx = f"Eres el asistente de e-commerce de «{nombre}»"
    if categorias:
        ctx += f". Sus categorías de producto son: {', '.join(categorias)}"
    ctx += (". Escribe en español de Colombia, claro y persuasivo, sin inventar "
            "datos, precios ni características que no te den. No menciones otras "
            "tiendas ni marcas ajenas.")
    return ctx


# ── Cliente OpenAI-compatible (stateless) ──────────────────────
def _chat(system, user, max_tokens=400, temperature=0.7):
    """Una sola llamada stateless al endpoint /v1/chat/completions.
    Devuelve (texto, None) en éxito o (None, mensaje_amigable) en error."""
    ok, motivo = estado_ia()
    if not ok:
        return None, motivo
    base = (current_app.config.get('AI_BASE_URL') or '').strip().rstrip('/')
    model = current_app.config.get('AI_MODEL') or 'qwen2.5:7b'
    key = (current_app.config.get('AI_API_KEY') or '').strip()
    read_timeout = int(current_app.config.get('AI_TIMEOUT') or 120)
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = f'Bearer {key}'
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
        'temperature': temperature,
        'max_tokens': max_tokens,
        'stream': False,
    }
    try:
        # (connect, read): falla en 5s si el servidor de IA está apagado, pero
        # da margen amplio a la generación (cold-start del modelo puede tardar).
        r = requests.post(f'{base}/v1/chat/completions', json=payload,
                          headers=headers, timeout=(5, read_timeout))
    except requests.ConnectTimeout:
        return None, 'El servidor de IA no responde (¿tu equipo está apagado o desconectado?).'
    except requests.Timeout:
        return None, 'La IA tardó demasiado en responder. Intenta de nuevo.'
    except requests.RequestException as exc:
        try:
            current_app.logger.warning(f'IA error de red: {exc}')
        except Exception:
            pass
        return None, 'No se pudo conectar con el servidor de IA. Intenta más tarde.'
    if r.status_code != 200:
        try:
            current_app.logger.warning(f'IA HTTP {r.status_code}: {r.text[:200]}')
        except Exception:
            pass
        return None, 'El servidor de IA devolvió un error. Intenta más tarde.'
    try:
        data = r.json()
        texto = (data['choices'][0]['message']['content'] or '').strip()
    except Exception:
        return None, 'Respuesta de IA no válida.'
    if not texto:
        return None, 'La IA no devolvió contenido. Intenta de nuevo.'
    return texto, None


# ── Funciones del asistente ────────────────────────────────────
def generar_descripcion(nombre, categoria='', keywords='', precio=None):
    nombre = (nombre or '').strip()
    if not nombre:
        return None, 'Escribe primero el nombre del producto.'
    ckey = _cache_key('descripcion', nombre, categoria, keywords)
    cached = _cache_get(ckey)
    if cached:
        return cached, None
    user = (f"Escribe una descripción de venta para el producto «{nombre}»."
            f"{' Categoría: ' + categoria + '.' if categoria else ''}"
            f"{' Palabras clave: ' + keywords + '.' if keywords else ''}"
            " 2 o 3 frases, atractiva y orientada a la conversión. Solo el texto,"
            " sin títulos ni viñetas.")
    texto, err = _chat(_contexto_tenant(), user, max_tokens=300)
    if texto:
        _cache_set(ckey, texto)
    return texto, err


def reescribir_descripcion(texto):
    texto = (texto or '').strip()
    if not texto:
        return None, 'No hay descripción para mejorar.'
    user = ("Reescribe esta descripción de producto para que sea más clara y"
            " persuasiva, conservando los datos reales. Solo el texto final:\n\n"
            + texto)
    return _chat(_contexto_tenant(), user, max_tokens=320)


def generar_seo(nombre, descripcion=''):
    nombre = (nombre or '').strip()
    if not nombre:
        return None, 'Falta el nombre del producto.'
    user = (f"Para el producto «{nombre}»"
            f"{' (' + descripcion[:300] + ')' if descripcion else ''}, genera SEO."
            " Responde EXACTAMENTE en dos líneas:\nTITULO: <máx 60 caracteres>\n"
            "DESCRIPCION: <máx 155 caracteres>")
    texto, err = _chat(_contexto_tenant(), user, max_tokens=180, temperature=0.5)
    if err:
        return None, err
    meta_title, meta_desc = nombre, ''
    for linea in texto.splitlines():
        l = linea.strip()
        if l.upper().startswith('TITULO:'):
            meta_title = l.split(':', 1)[1].strip()[:60]
        elif l.upper().startswith('DESCRIPCION:'):
            meta_desc = l.split(':', 1)[1].strip()[:155]
    return {'meta_title': meta_title, 'meta_description': meta_desc}, None


def responder_chat(pregunta):
    """Asistente conversacional del negocio. Flujo seguro en 2 pasos:
      1) La IA elige UNA herramienta de solo-lectura del catálogo (JSON estricto).
      2) Ejecutamos esa herramienta (consulta REAL a la BD del tenant).
      3) La IA redacta la respuesta con esos datos reales (no inventa cifras).
    Devuelve (dict {respuesta, datos, herramienta}, None) o (None, mensaje_error)."""
    import json
    import services.ai_tools as tools

    pregunta = (pregunta or '').strip()
    if not pregunta:
        return None, 'Escribe una pregunta.'

    # Paso 1: selección de herramienta (la IA NO escribe SQL, solo elige nombre+params)
    sel_system = (
        tools.CONTEXTO_DATOS + "\n\n"
        "Eres un enrutador. Dada la pregunta de un dueño de tienda, elige UNA "
        "herramienta de esta lista para responderla:\n" + tools.catalogo_para_prompt() +
        "\nResponde SOLO un JSON válido: {\"tool\":\"<code>\",\"params\":{...}}. "
        "params puede incluir 'periodo' (hoy|semana|mes), 'limite' (número) o "
        "'umbral' (número) según aplique. Si piden datos sensibles o algo sin "
        "herramienta, usa {\"tool\":\"ninguna\"}. No expliques, solo el JSON."
    )
    raw, err = _chat(sel_system, pregunta, max_tokens=120, temperature=0)
    if err:
        return None, err
    code, params = None, {}
    try:
        m = re.search(r'\{.*\}', raw, re.S)
        data = json.loads(m.group(0)) if m else {}
        code = data.get('tool')
        params = data.get('params') or {}
    except Exception:
        code = None

    if not code or code == 'ninguna' or code not in tools.TOOLS:
        # Pregunta fuera del alcance de los datos (o dato sensible): responde
        # con honestidad y recuerda los límites del contexto.
        resp, err2 = _chat(
            _contexto_tenant() + "\n" + tools.CONTEXTO_DATOS,
            f"El dueño preguntó: «{pregunta}». No tienes una herramienta ni permiso "
            "para responder eso con datos. Responde breve y amable; si es un dato "
            "sensible niégate, y en todo caso indícale qué SÍ puedes consultar "
            "(ventas, productos más vendidos, stock bajo, inventario, clientes, "
            "pedidos por despachar, estado del catálogo).", max_tokens=220)
        if err2:
            return None, err2
        return {'respuesta': resp, 'datos': None, 'herramienta': None}, None

    # Paso 2: ejecutar la herramienta (consulta real, tenant-scoped)
    try:
        datos = tools.ejecutar(code, params)
    except Exception as exc:  # noqa: BLE001
        try:
            current_app.logger.warning(f'IA tool {code} falló: {exc}')
        except Exception:
            pass
        return None, 'No pude consultar esos datos en este momento.'

    # Paso 3: redacción con los datos reales
    red_system = (_contexto_tenant() +
                  " Responde la pregunta del dueño usando ÚNICAMENTE los datos que "
                  "te doy (son reales, de su tienda). Sé claro y breve, en español, "
                  "con las cifras exactas. No inventes nada que no esté en los datos.")
    red_user = (f"Pregunta: «{pregunta}»\nDatos reales de su tienda (JSON):\n"
                f"{json.dumps(datos, ensure_ascii=False)}\n\nRedacta la respuesta.")
    resp, err3 = _chat(red_system, red_user, max_tokens=350)
    if err3:
        return None, err3
    return {'respuesta': resp, 'datos': datos, 'herramienta': code}, None


def sugerir_nombre(descripcion, categoria=''):
    descripcion = (descripcion or '').strip()
    if not descripcion:
        return None, 'Escribe primero una descripción o detalles del producto.'
    user = (f"A partir de estos detalles{(' (categoría ' + categoria + ')') if categoria else ''}:"
            f" «{descripcion[:400]}», propón un NOMBRE comercial corto y atractivo "
            "para el producto (máx 8 palabras). Solo el nombre, sin comillas.")
    return _chat(_contexto_tenant(), user, max_tokens=40, temperature=0.8)


def generar_tags(nombre, descripcion=''):
    nombre = (nombre or '').strip()
    if not nombre:
        return None, 'Falta el nombre del producto.'
    user = (f"Genera entre 5 y 8 etiquetas (keywords) de búsqueda para el producto "
            f"«{nombre}»{(' — ' + descripcion[:200]) if descripcion else ''}. "
            "Devuélvelas separadas por comas, en minúsculas, sin numerar.")
    return _chat(_contexto_tenant(), user, max_tokens=80, temperature=0.5)


def traducir_texto(texto, idioma='inglés'):
    texto = (texto or '').strip()
    if not texto:
        return None, 'No hay texto para traducir.'
    idioma = (idioma or 'inglés').strip()
    system = ("Eres un traductor profesional de e-commerce. Traduce con naturalidad, "
              "conservando el tono de venta. Devuelve SOLO la traducción.")
    return _chat(system, f"Traduce al {idioma} este texto:\n\n{texto[:1200]}", max_tokens=500)


def sugerir_respuesta(mensaje_cliente, asunto=''):
    mensaje_cliente = (mensaje_cliente or '').strip()
    if not mensaje_cliente:
        return None, 'No hay mensaje para responder.'
    system = _contexto_tenant() + (" Redacta respuestas de servicio al cliente"
             " amables y profesionales. No prometas precios, plazos ni stock que"
             " no te den; si falta información, ofrece confirmarla.")
    user = (f"Un cliente escribió{(' sobre «' + asunto + '»') if asunto else ''}:"
            f"\n\n«{mensaje_cliente}»\n\nRedacta una respuesta breve y cordial"
            " que el negocio pueda enviar. Solo el texto de la respuesta.")
    return _chat(system, user, max_tokens=300)
