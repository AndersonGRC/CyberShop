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
import json
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
    fallback = (current_app.config.get('AI_MODEL_FALLBACK') or '').strip()
    fallback = fallback if fallback and fallback != modelo else None
    if not base:
        return {'online': False, 'modelo': modelo, 'fallback': fallback,
                'motivo': 'La IA no está configurada (falta el servidor de IA).'}
    key = (current_app.config.get('AI_API_KEY') or '').strip()
    headers = {'Authorization': f'Bearer {key}'} if key else {}
    try:
        r = requests.get(f'{base}/api/tags', headers=headers, timeout=5)
        if r.status_code != 200:
            # Algunos proveedores cloud no exponen /api/tags pero sí /v1/models
            r = requests.get(f'{base}/v1/models', headers=headers, timeout=5)
        if r.status_code == 200:
            motivo = 'IA en línea.'
            if fallback:
                motivo = f'IA en línea (respaldo: {fallback}).'
            return {'online': True, 'modelo': modelo, 'fallback': fallback,
                    'motivo': motivo}
        return {'online': False, 'modelo': modelo, 'fallback': fallback,
                'motivo': f'El servidor de IA respondió {r.status_code}.'}
    except requests.RequestException:
        return {'online': False, 'modelo': modelo, 'fallback': fallback,
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
def _chat_una_vez(model, system, user, max_tokens, temperature):
    """Una llamada a /v1/chat/completions con UN modelo concreto.
    Devuelve (texto, None) o (None, (codigo, mensaje_amigable)) donde codigo
    distingue errores REINTENTABLES con otro modelo ('modelo') de los que no
    ('red' = servidor apagado: cambiar de modelo no ayuda)."""
    base = (current_app.config.get('AI_BASE_URL') or '').strip().rstrip('/')
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
        # Margen para modelos razonadores (gpt-oss gasta tokens en su canal de
        # razonamiento ANTES del contenido; medido: hasta ~700-900 en tareas
        # con datos JSON — sin margen devuelve vacío). max_tokens es solo un
        # TECHO: el modelo para en EOS, así que el margen amplio no cuesta.
        'max_tokens': int(max_tokens) + 1200,
        'stream': False,
    }
    try:
        # (connect, read): falla en 5s si el servidor de IA está apagado, pero
        # da margen amplio a la generación (cold-start del modelo puede tardar).
        r = requests.post(f'{base}/v1/chat/completions', json=payload,
                          headers=headers, timeout=(5, read_timeout))
    except requests.ConnectTimeout:
        return None, ('red', 'El servidor de IA no responde (¿tu equipo está apagado o desconectado?).')
    except requests.Timeout:
        return None, ('modelo', 'La IA tardó demasiado en responder. Intenta de nuevo.')
    except requests.RequestException as exc:
        try:
            current_app.logger.warning(f'IA error de red: {exc}')
        except Exception:
            pass
        return None, ('red', 'No se pudo conectar con el servidor de IA. Intenta más tarde.')
    if r.status_code != 200:
        try:
            current_app.logger.warning(f'IA HTTP {r.status_code} ({model}): {r.text[:200]}')
        except Exception:
            pass
        # 500 típico: el modelo no cupo en memoria → REINTENTABLE con fallback
        return None, ('modelo', 'El servidor de IA devolvió un error. Intenta más tarde.')
    try:
        data = r.json()
        texto = (data['choices'][0]['message']['content'] or '').strip()
    except Exception:
        return None, ('modelo', 'Respuesta de IA no válida.')
    if not texto:
        return None, ('modelo', 'La IA no devolvió contenido. Intenta de nuevo.')
    return texto, None


class _ErrorIA(Exception):
    """Fallo de una llamada streaming ANTES de producir contenido.
    codigo: 'modelo' (reintentable con el fallback) o 'red' (no reintentar)."""

    def __init__(self, codigo, mensaje):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


def _chat_stream_una_vez(model, system, user, max_tokens, temperature):
    """Generador: fragmentos de texto de /v1/chat/completions con stream=True.
    Si falla ANTES del primer fragmento lanza _ErrorIA (el caller decide si
    reintenta con el fallback). Si el stream se corta a MITAD, termina en
    silencio: el texto ya emitido se conserva en pantalla. Los deltas de
    razonamiento (gpt-oss emite 'reasoning' antes del contenido) se descartan."""
    base = (current_app.config.get('AI_BASE_URL') or '').strip().rstrip('/')
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
        # Mismo margen razonador que _chat_una_vez.
        'max_tokens': int(max_tokens) + 1200,
        'stream': True,
    }
    try:
        r = requests.post(f'{base}/v1/chat/completions', json=payload,
                          headers=headers, stream=True, timeout=(5, read_timeout))
    except requests.ConnectTimeout:
        raise _ErrorIA('red', 'El servidor de IA no responde (¿tu equipo está apagado o desconectado?).')
    except requests.Timeout:
        raise _ErrorIA('modelo', 'La IA tardó demasiado en responder. Intenta de nuevo.')
    except requests.RequestException as exc:
        try:
            current_app.logger.warning(f'IA error de red (stream): {exc}')
        except Exception:
            pass
        raise _ErrorIA('red', 'No se pudo conectar con el servidor de IA. Intenta más tarde.')
    if r.status_code != 200:
        try:
            current_app.logger.warning(f'IA HTTP {r.status_code} stream ({model}): {r.text[:200]}')
        except Exception:
            pass
        raise _ErrorIA('modelo', 'El servidor de IA devolvió un error. Intenta más tarde.')
    emitio = False
    try:
        for linea in r.iter_lines(decode_unicode=True):
            if not linea or not linea.startswith('data:'):
                continue
            cuerpo = linea[5:].strip()
            if cuerpo == '[DONE]':
                break
            try:
                delta = json.loads(cuerpo)['choices'][0].get('delta') or {}
            except Exception:
                continue
            frag = delta.get('content') or ''
            if frag:
                emitio = True
                yield frag
    except requests.RequestException:
        if not emitio:
            raise _ErrorIA('modelo', 'La IA tardó demasiado en responder. Intenta de nuevo.')
        return
    finally:
        try:
            r.close()
        except Exception:
            pass
    if not emitio:
        raise _ErrorIA('modelo', 'La IA no devolvió contenido. Intenta de nuevo.')


def _chat(system, user, max_tokens=400, temperature=0.7):
    """Llamada de chat con FALLBACK automático de modelo: si el primario
    (AI_MODEL, p.ej. gpt-oss:20b) falla por memoria/timeout/error del server,
    reintenta UNA vez con AI_MODEL_FALLBACK (p.ej. qwen2.5:7b) — el usuario
    recibe respuesta en vez de un error. Devuelve (texto, None) o (None, msg)."""
    ok, motivo = estado_ia()
    if not ok:
        return None, motivo
    primario = current_app.config.get('AI_MODEL') or 'qwen2.5:7b'
    fallback = (current_app.config.get('AI_MODEL_FALLBACK') or '').strip()

    texto, err = _chat_una_vez(primario, system, user, max_tokens, temperature)
    if texto is not None:
        return texto, None
    codigo, mensaje = err
    if codigo == 'modelo' and fallback and fallback != primario:
        try:
            current_app.logger.warning(
                f"IA fallback: {primario} falló ({mensaje[:60]}) → intentando {fallback}")
        except Exception:
            pass
        texto, err2 = _chat_una_vez(fallback, system, user, max_tokens, temperature)
        if texto is not None:
            return texto, None
        mensaje = err2[1]
    return None, mensaje


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


# ── Contenido web (publicaciones, slides, servicios) ───────────
def generar_contenido(titulo, tipo='contenido', detalle=''):
    """Redacta un texto breve para una sección de contenido web del tenant
    (publicación, slide/banner o servicio). Genérico, no específico de producto."""
    titulo = (titulo or '').strip()
    if not titulo:
        return None, 'Escribe primero el título.'
    detalle = (detalle or '').strip()
    tipo = (tipo or 'contenido').strip()
    user = (f"Escribe un texto breve y atractivo para {tipo} titulado «{titulo}» "
            "de una tienda online."
            f"{' Ten en cuenta estos detalles: ' + detalle[:300] + '.' if detalle else ''}"
            " 2 o 3 frases, claro y orientado a interesar al lector. Solo el texto, "
            "sin títulos ni viñetas.")
    return _chat(_contexto_tenant(), user, max_tokens=300)


def generar_articulo_blog(tema, keyword='', publico=''):
    """Redacta un ARTÍCULO DE BLOG completo optimizado para SEO (borrador que
    el dueño revisa y publica). Devuelve (dict, None) o (None, error). El dict:
    titulo (≤60), meta_descripcion (≤155), slug_sugerido, extracto, cuerpo_html.
    """
    import re as _re
    tema = (tema or '').strip()
    if not tema:
        return None, 'Escribe primero el tema del artículo.'
    keyword = (keyword or '').strip()
    publico = (publico or '').strip() or 'dueños de pequeños negocios en Colombia'

    system = ("Eres un redactor SEO senior colombiano. Escribes artículos útiles, "
              "concretos y cercanos (tuteo), sin relleno ni promesas exageradas. "
              "Respondes EXACTAMENTE en el formato pedido, sin comentarios extra.")
    kw = (f"Palabra clave objetivo: «{keyword}» (úsala en el título, el primer "
          "párrafo y un subtítulo, con naturalidad). ") if keyword else ''
    user = (f"Escribe un artículo de blog sobre: «{tema}». {kw}"
            f"Público: {publico}. "
            "Extensión OBLIGATORIA: mínimo 900 palabras (desarrolla cada "
            "sección con 120-180 palabras; ejemplos concretos de negocios "
            "colombianos: tiendas de barrio, restaurantes, panaderías). "
            "Estructura: introducción que enganche (80-120 palabras), 4 o 5 "
            "secciones con subtítulos <h2> (y <h3> si aplica), una lista <ul> "
            "donde aporte, y cierra con una sección "
            "<h2>Preguntas frecuentes</h2> con 3 preguntas <h3> y su respuesta "
            "de 40-70 palabras cada una. "
            "FORMATO DE RESPUESTA (respeta los marcadores; cuerpo en HTML "
            "simple usando solo <h2> <h3> <p> <ul> <li> <strong>): "
            "primera línea 'TITULO: ...' (máx 60 caracteres, con la palabra "
            "clave); segunda línea 'META: ...' (máx 155, invita al clic); "
            "tercera línea 'EXTRACTO: ...' (2 frases); luego una línea "
            "'CUERPO:' y a continuación el HTML del artículo.")
    texto, err = _chat(system, user, max_tokens=2600, temperature=0.6)
    if err:
        return None, err

    out = {'titulo': '', 'meta_descripcion': '', 'extracto': '', 'cuerpo_html': ''}
    m = _re.search(r'TITULO:\s*(.+)', texto)
    if m:
        out['titulo'] = m.group(1).strip().strip('«»"')[:120]
    m = _re.search(r'META:\s*(.+)', texto)
    if m:
        out['meta_descripcion'] = m.group(1).strip()[:160]
    m = _re.search(r'EXTRACTO:\s*(.+)', texto)
    if m:
        out['extracto'] = m.group(1).strip()[:390]
    m = _re.search(r'CUERPO:\s*(.*)', texto, _re.S)
    if m:
        out['cuerpo_html'] = m.group(1).strip()
    if not out['titulo'] or not out['cuerpo_html']:
        return None, 'La IA no devolvió el formato esperado. Intenta de nuevo.'

    # Los modelos pequeños tienden a quedarse cortos: si el cuerpo no llega a
    # ~550 palabras, una segunda pasada lo amplía sección por sección.
    palabras = len(_re.sub(r'<[^>]+>', ' ', out['cuerpo_html']).split())
    if palabras < 550:
        ampliado, err2 = _chat(
            system,
            "Amplía este artículo hasta MÍNIMO 900 palabras. Conserva los "
            "mismos subtítulos y estructura; desarrolla cada sección con más "
            "detalle, ejemplos concretos de negocios colombianos (tienda de "
            "barrio, restaurante, panadería) y consejos accionables. Devuelve "
            "SOLO el HTML del cuerpo (h2, h3, p, ul, li, strong), sin "
            "marcadores:\n\n" + out['cuerpo_html'],
            max_tokens=3200, temperature=0.6)
        if not err2 and ampliado:
            nuevo = ampliado.strip()
            if len(_re.sub(r'<[^>]+>', ' ', nuevo).split()) > palabras:
                out['cuerpo_html'] = nuevo

    s = out['titulo'].lower().translate(str.maketrans('áéíóúüñ', 'aeiouun'))
    out['slug_sugerido'] = _re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:170]
    return out, None


def mejorar_contenido(texto):
    """Reescribe cualquier texto de contenido para que sea más claro y atractivo."""
    texto = (texto or '').strip()
    if not texto:
        return None, 'No hay texto para mejorar.'
    user = ("Reescribe este texto para que sea más claro, atractivo y bien "
            "redactado, conservando la información real. Solo el texto final:\n\n"
            + texto[:1500])
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


def _plan_chat(pregunta):
    """Pasos 1 y 2 del chat del negocio (comunes a la variante normal y a la
    streaming): la IA elige UNA herramienta de solo-lectura (JSON estricto) y
    la ejecutamos contra la BD del tenant. Devuelve (plan, None) o (None, err),
    donde plan = {system, user, max_tokens, datos, herramienta} deja lista la
    redacción final (paso 3)."""
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
        "params puede incluir 'periodo' (hoy|semana|mes|todo), 'limite' (número) o "
        "'umbral' (número) según aplique. Si el usuario NO menciona un período "
        "concreto (hoy/semana/mes), usa 'todo' (histórico). Si piden datos "
        "sensibles o algo sin herramienta, usa {\"tool\":\"ninguna\"}. Solo el JSON."
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
        return {
            'system': _contexto_tenant() + "\n" + tools.CONTEXTO_DATOS,
            'user': (
                f"El dueño preguntó: «{pregunta}». No tienes una herramienta ni permiso "
                "para responder eso con datos. Responde breve y amable; si es un dato "
                "sensible niégate, y en todo caso indícale qué SÍ puedes consultar "
                "(ventas, productos más vendidos, stock bajo, inventario, clientes, "
                "pedidos por despachar, estado del catálogo)."),
            'max_tokens': 220, 'datos': None, 'herramienta': None,
        }, None

    # Paso 2: ejecutar la herramienta (consulta real, tenant-scoped)
    try:
        datos = tools.ejecutar(code, params)
    except Exception as exc:  # noqa: BLE001
        try:
            current_app.logger.warning(f'IA tool {code} falló: {exc}')
        except Exception:
            pass
        return None, 'No pude consultar esos datos en este momento.'

    # Paso 3 (preparado): redacción con los datos reales
    return {
        'system': (_contexto_tenant() +
                   " Responde la pregunta del dueño usando ÚNICAMENTE los datos que "
                   "te doy (son reales, de su tienda). Sé claro y breve, en español, "
                   "con las cifras exactas. No inventes nada que no esté en los datos."),
        'user': (f"Pregunta: «{pregunta}»\nDatos reales de su tienda (JSON):\n"
                 f"{json.dumps(datos, ensure_ascii=False)}\n\nRedacta la respuesta."),
        'max_tokens': 350, 'datos': datos, 'herramienta': code,
    }, None


def responder_chat(pregunta):
    """Asistente conversacional del negocio (respuesta completa, sin streaming
    — la usa el desktop y queda de respaldo para el panel web).
    Devuelve (dict {respuesta, datos, herramienta}, None) o (None, mensaje_error)."""
    plan, err = _plan_chat(pregunta)
    if err:
        return None, err
    resp, err3 = _chat(plan['system'], plan['user'], max_tokens=plan['max_tokens'])
    if err3:
        return None, err3
    return {'respuesta': resp, 'datos': plan['datos'],
            'herramienta': plan['herramienta']}, None


def responder_chat_stream(pregunta):
    """Variante STREAMING del chat del negocio. Los pasos 1-2 (elegir
    herramienta + consulta real) no se pueden streamear; solo la redacción
    final se emite palabra a palabra. Generador de eventos (tuplas):
      ('meta',  {herramienta, datos})  — una vez, antes del texto
      ('delta', fragmento)             — texto incremental
      ('fin',   texto_completo)        — cierre normal
      ('error', mensaje)               — cierre con error (puede llegar sin deltas)
    Mantiene el fallback de modelo: si el primario falla ANTES de emitir texto,
    reintenta con AI_MODEL_FALLBACK. Si falla a mitad, lo emitido se conserva."""
    plan, err = _plan_chat(pregunta)
    if err:
        yield ('error', err)
        return
    yield ('meta', {'herramienta': plan['herramienta'], 'datos': plan['datos']})

    primario = current_app.config.get('AI_MODEL') or 'qwen2.5:7b'
    fallback = (current_app.config.get('AI_MODEL_FALLBACK') or '').strip()
    partes = []
    try:
        for frag in _chat_stream_una_vez(primario, plan['system'], plan['user'],
                                         plan['max_tokens'], 0.7):
            partes.append(frag)
            yield ('delta', frag)
    except _ErrorIA as e:
        if e.codigo == 'modelo' and fallback and fallback != primario and not partes:
            try:
                current_app.logger.warning(
                    f"IA fallback (stream): {primario} falló ({e.mensaje[:60]}) "
                    f"→ intentando {fallback}")
            except Exception:
                pass
            try:
                for frag in _chat_stream_una_vez(fallback, plan['system'], plan['user'],
                                                 plan['max_tokens'], 0.7):
                    partes.append(frag)
                    yield ('delta', frag)
            except _ErrorIA as e2:
                yield ('error', e2.mensaje)
                return
        else:
            yield ('error', e.mensaje)
            return
    yield ('fin', ''.join(partes).strip())


def resumen_cacheado():
    """Último resumen ejecutivo guardado en cliente_config (BD del tenant),
    si tiene menos de 1 hora. None si no hay o venció. No usa el LLM."""
    from datetime import datetime, timedelta
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT clave, valor FROM cliente_config WHERE clave IN "
                        "('ia_resumen_negocio','ia_resumen_negocio_ts')")
            filas = {r['clave']: r['valor'] for r in cur.fetchall()}
        texto, ts = filas.get('ia_resumen_negocio'), filas.get('ia_resumen_negocio_ts')
        if not texto or not ts:
            return None
        if datetime.now() - datetime.fromisoformat(ts) > timedelta(hours=1):
            return None
        return {'resumen': texto, 'generado': ts}
    except Exception:
        return None


def resumen_ejecutivo(force=False):
    """Resumen ejecutivo del negocio: 4-5 líneas accionables redactadas por la
    IA a partir de las herramientas de datos REALES del tenant. Caché de 1 hora
    en cliente_config (no gastar GPU en cada carga del dashboard; el botón
    «Actualizar» pasa force=True). Devuelve
    ({'resumen', 'generado', 'cache'}, None) o (None, mensaje_error)."""
    from datetime import datetime
    import services.ai_tools as tools

    if not force:
        cached = resumen_cacheado()
        if cached:
            return {**cached, 'cache': True}, None

    datos = {}
    for nombre, fn, kw in (
            ('ventas_semana', tools.ventas_periodo, {'periodo': 'semana'}),
            ('top_productos_mes', tools.top_productos, {'periodo': 'mes', 'limite': 5}),
            ('stock_bajo', tools.productos_bajo_stock, {'umbral': 5}),
            ('pedidos_por_despachar', tools.pedidos_por_despachar, {}),
            ('compras_sugeridas', tools.sugerencia_reorden, {}),
    ):
        try:
            datos[nombre] = fn(**kw)
        except Exception:
            pass
    if not datos:
        return None, 'No pude consultar los datos del negocio.'

    user = ("Con estos datos REALES de la tienda (JSON), escribe un resumen "
            "ejecutivo para el dueño: 4 o 5 líneas, cada una en un renglón "
            "empezando con «• », concretas y accionables (qué va bien, qué "
            "atender hoy, qué comprar o despachar). Usa las cifras exactas, no "
            "inventes nada y no saludes:\n\n" + json.dumps(datos, ensure_ascii=False))
    texto, err = _chat(_contexto_tenant(), user, max_tokens=380, temperature=0.5)
    if err:
        return None, err

    ahora = datetime.now().isoformat(timespec='seconds')
    try:
        with get_db_cursor() as cur:
            for clave, valor in (('ia_resumen_negocio', texto),
                                 ('ia_resumen_negocio_ts', ahora)):
                cur.execute(
                    """INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion)
                       VALUES (%s, %s, 'texto', 'sistema', 'Resumen IA del dashboard (auto)')
                       ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor""",
                    (clave, valor))
    except Exception:
        pass  # el caché es cosmético: si no se pudo guardar, igual respondemos
    return {'resumen': texto, 'generado': ahora, 'cache': False}, None


def sugerir_categoria_movimiento(descripcion, tipo='egreso', monto=None):
    """Clasifica un movimiento contable en UNA categoría de la lista REAL del
    módulo (lista cerrada — nunca inventa categorías). Solo SUGIERE: el humano
    siempre confirma en el formulario. Devuelve
    ({'categoria': code, 'etiqueta': label}, None) o (None, mensaje_error)."""
    # Import diferido: routes importa services, no al revés (evita ciclo).
    from routes.contabilidad import CATEGORIAS_INGRESO, CATEGORIAS_EGRESO

    descripcion = (descripcion or '').strip()
    if not descripcion:
        return None, 'Escribe primero la descripción del movimiento.'
    tipo = 'ingreso' if (tipo or '').strip().lower() == 'ingreso' else 'egreso'
    cats = CATEGORIAS_INGRESO if tipo == 'ingreso' else CATEGORIAS_EGRESO

    ckey = _cache_key('cat_mov', tipo, descripcion)
    cached = _cache_get(ckey)
    if cached:
        return cached, None

    try:
        monto_txt = f" por ${float(monto):,.0f} COP" if monto else ''
    except (TypeError, ValueError):
        monto_txt = ''
    lista = '\n'.join(f"- {c}: {l}" for c, l in cats)
    user = (f"Clasifica este {tipo} de la contabilidad de una tienda en UNA "
            f"categoría de esta lista. Responde SOLO el código (lo que va antes "
            f"de los dos puntos), nada más:\n{lista}\n\n"
            f"Movimiento: «{descripcion[:200]}»{monto_txt}\nCódigo:")
    texto, err = _chat(
        "Eres el contador de una tienda en Colombia. Respondes únicamente con "
        "el código de categoría pedido, sin explicaciones.",
        user, max_tokens=20, temperature=0)
    if err:
        return None, err

    # El modelo puede envolver el código ("Código: venta_pos.") → buscar el
    # código válido más largo dentro del texto; si no hay, cae a otro_*.
    t = texto.strip().lower().replace('-', '_')
    validos = [c for c, _ in cats]
    code = next((c for c in sorted(validos, key=len, reverse=True) if c in t), '')
    if not code:
        code = 'otro_ingreso' if tipo == 'ingreso' else 'otro_egreso'
    res = {'categoria': code, 'etiqueta': dict(cats).get(code, code)}
    _cache_set(ckey, res)
    return res, None


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
