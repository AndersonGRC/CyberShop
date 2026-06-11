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
    timeout = int(current_app.config.get('AI_TIMEOUT') or 60)
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
        r = requests.post(f'{base}/v1/chat/completions', json=payload,
                          headers=headers, timeout=timeout)
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
