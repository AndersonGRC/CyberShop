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
import threading
import time
from datetime import datetime

import requests
from flask import current_app

from database import _current_db_name, get_db_cursor
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
    return f"{_current_db_name()}:{get_current_tenant_id()}:{funcion}:{h}"


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
def _hay_algun_motor():
    """¿Hay al menos un motor CONFIGURADO? (encendido o no: eso se mira al usarlo)"""
    cfg = current_app.config
    return bool((cfg.get('AI_BASE_URL') or '').strip() or
                (cfg.get('AI_MOTOR_A_BASE_URL') or '').strip())


def ia_disponible():
    """True si el módulo IA está activo para este tenant Y hay algún motor."""
    try:
        if not is_module_active(MODULE_AI):
            return False
        return _hay_algun_motor()
    except Exception:
        return False


def estado_ia():
    """Diagnóstico para la UI: (disponible, motivo)."""
    if not is_module_active(MODULE_AI):
        return False, 'El módulo Asistente IA no está habilitado en tu plan.'
    if not _hay_algun_motor():
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
def _chat_una_vez(model, system, user, max_tokens, temperature, base_url=None, timeout=None):
    """Una llamada a /v1/chat/completions con UN modelo concreto.
    Devuelve (texto, None) o (None, (codigo, mensaje_amigable)) donde codigo
    distingue errores REINTENTABLES con otro modelo ('modelo') de los que no
    ('red' = servidor apagado: cambiar de modelo no ayuda).

    `base_url` y `timeout` los pone el selector de motores cuando la petición no
    va al equipo de siempre; sin ellos se usa la configuración de toda la vida."""
    base = (base_url or current_app.config.get('AI_BASE_URL') or '').strip().rstrip('/')
    key = (current_app.config.get('AI_API_KEY') or '').strip()
    read_timeout = int(timeout or current_app.config.get('AI_TIMEOUT') or 120)
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
    r = None
    for intento in range(_INTENTOS_CONEXION):
        try:
            # (connect, read): falla en 5s si el servidor de IA está apagado, pero
            # da margen amplio a la generación (cold-start del modelo puede tardar).
            r = requests.post(f'{base}/v1/chat/completions', json=payload,
                              headers=headers, timeout=(5, read_timeout))
            break
        except requests.ConnectTimeout:
            # Sin respuesta de red: el PC está apagado o el túnel caído. Reintentar no ayuda.
            return None, ('red', 'El servidor de IA no responde (¿tu equipo está apagado o desconectado?).')
        except requests.Timeout:
            return None, ('modelo', 'La IA tardó demasiado en responder. Intenta de nuevo.')
        except requests.ConnectionError as exc:
            # Conexión rechazada o cortada sin respuesta: el PC está encendido pero
            # Ollama se está (re)iniciando —su vigilancia lo relanza en ~25 s—.
            # Antes se rendía al primer intento ("No se pudo conectar…").
            try:
                current_app.logger.warning(f'IA error de conexión (intento {intento + 1}): {exc}')
            except Exception:
                pass
            if intento < _INTENTOS_CONEXION - 1:
                time.sleep(_PAUSA_CONEXION_S)
                continue
            return None, ('red', 'El servidor de IA se está reiniciando. Intenta de nuevo en un minuto.')
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


def _chat_stream_una_vez(model, system, user, max_tokens, temperature,
                         base_url=None, timeout=None):
    """Generador: fragmentos de texto de /v1/chat/completions con stream=True.
    Si falla ANTES del primer fragmento lanza _ErrorIA (el caller decide si
    reintenta con el fallback). Si el stream se corta a MITAD, termina en
    silencio: el texto ya emitido se conserva en pantalla. Los deltas de
    razonamiento (gpt-oss emite 'reasoning' antes del contenido) se descartan.

    `base_url` y `timeout` los pone el selector de motores; sin ellos, el equipo
    de siempre."""
    base = (base_url or current_app.config.get('AI_BASE_URL') or '').strip().rstrip('/')
    key = (current_app.config.get('AI_API_KEY') or '').strip()
    read_timeout = int(timeout or current_app.config.get('AI_TIMEOUT') or 120)
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
    r = None
    for intento in range(_INTENTOS_CONEXION):
        try:
            r = requests.post(f'{base}/v1/chat/completions', json=payload,
                              headers=headers, stream=True, timeout=(5, read_timeout))
            break
        except requests.ConnectTimeout:
            raise _ErrorIA('red', 'El servidor de IA no responde (¿tu equipo está apagado o desconectado?).')
        except requests.Timeout:
            raise _ErrorIA('modelo', 'La IA tardó demasiado en responder. Intenta de nuevo.')
        except requests.ConnectionError as exc:
            # Mismo criterio que _chat_una_vez: Ollama reiniciándose → reintentar un poco.
            try:
                current_app.logger.warning(f'IA error de conexión (stream, intento {intento + 1}): {exc}')
            except Exception:
                pass
            if intento < _INTENTOS_CONEXION - 1:
                time.sleep(_PAUSA_CONEXION_S)
                continue
            raise _ErrorIA('red', 'El servidor de IA se está reiniciando. Intenta de nuevo en un minuto.')
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
    # Ollama responde `text/event-stream` SIN charset y requests asume ISO-8859-1
    # para text/*: "¡Hola! Sí, información" llegaba como "Â¡Hola! SÃ­, informaciÃ³n".
    # El JSON de la variante sin streaming no tenía el problema (r.json() usa UTF-8).
    r.encoding = 'utf-8'
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


def chat_con_motor(motor, system, user, max_tokens=400, temperature=0.7, canal='panel',
                   permitir_puente=True, esperar_carga=True):
    """Le habla al motor que sea: una máquina propia (Ollama) o el respaldo en la
    nube. Devuelve (texto, None) o (None, motivo). Quien llama no tiene que saber
    con cuál de los dos está hablando. permitir_puente=False: nunca desvía a la
    nube aunque el modelo local esté frío. esperar_carga=False: con el modelo
    frío no se espera la carga (1-3 min); queda pedida y se devuelve
    (None, motivo) para que quien llama conteste sin modelo."""
    if motor is None:
        return None, 'Sin motor de IA disponible.'
    if getattr(motor, 'es_nube', False):
        from services import ia_nube
        return ia_nube.responder(system, user, max_tokens=max_tokens,
                                 temperature=temperature, timeout=motor.timeout)

    from services.ia_motores import NIVEL_B
    if motor.nivel == NIVEL_B and _modelo_en_memoria(motor.modelo) is False:
        # Frío: la carga se pide YA, en segundo plano, pase lo que pase después
        # (puente a la nube, espera o respuesta sin modelo).
        _pedir_carga(motor.modelo)
        if permitir_puente:
            puente = _intentar_puente_frio(motor, system, user, max_tokens, temperature, canal)
            if puente is not None:
                return puente, None
        if not esperar_carga:
            return None, MSG_MOTOR_PREPARANDO

    texto, err = _chat_una_vez(motor.modelo, system, user, max_tokens, temperature,
                               base_url=motor.base_url, timeout=motor.timeout)
    return (texto, None) if texto is not None else (None, err[1])


def _chat(system, user, max_tokens=400, temperature=0.7, espera_frio=45,
          perfil='normal', canal='panel', tarea='chat_panel', user_nube=None,
          permitir_nube=True):
    """Llamada de chat con FALLBACK automático de modelo: si el primario
    (AI_MODEL, p.ej. gpt-oss:20b) falla por memoria/timeout/error del server,
    reintenta UNA vez con AI_MODEL_FALLBACK (p.ej. qwen2.5:7b) — el usuario
    recibe respuesta en vez de un error. Devuelve (texto, None) o (None, msg).

    espera_frio: segundos máximos a esperar si el modelo está sin cargar. Quien
    llama mientras se arma una página (p. ej. "Tu día" del CRM) pasa 0: se pide
    la carga y se responde al instante, sin colgar la página.

    Si atiende el respaldo en la nube: se le manda `user_nube` (la misma
    petición sin la conversación que no puede salir del equipo) y, con
    permitir_nube=False, no se le manda nada."""
    ok, motivo = estado_ia()
    if not ok:
        return None, motivo

    # Quién atiende esta petición (ver services/ia_motores.py): el equipo de IA
    # si está encendido, el modelo del servidor si no, y nada si no hay ninguno
    # —en ese caso quien llama responde con los datos tal cual.
    from services import ia_motores as motores
    motor, motivo_motor = motores.motor_para(perfil, canal, tarea)
    if motor is None:
        return None, motivo_motor
    if motor.es_nube:
        if not permitir_nube:
            return None, MSG_SOLO_LOCAL
        # La nube no se precalienta ni tiene modelo de respaldo: se llama y ya.
        return chat_con_motor(motor, system, user if user_nube is None else user_nube,
                              max_tokens, temperature)

    primario = motor.modelo or 'qwen2.5:7b'
    # El respaldo de modelo es de la máquina del dueño: no aplica a los demás.
    fallback = ((current_app.config.get('AI_MODEL_FALLBACK') or '').strip()
                if motor.nivel == motores.NIVEL_B else '')

    # Motor en frío: espera acotada. Estas respuestas no envían nada hasta el final
    # y nginx corta a los 60 s (Cloudflare a los 100 s); pasados 45 s se contesta que
    # el motor se está preparando —ya quedó cargando— en vez de morir con un 504.
    # No se salta al modelo de respaldo: cargarlo a la vez peleaba por el disco y
    # alargaba las dos cargas.
    # Solo aplica al equipo del dueño: el del servidor se deja siempre cargado.
    if motor.nivel == motores.NIVEL_B and not _esperar_motor_bloqueando(primario, espera_max=espera_frio):
        return None, MSG_MOTOR_PREPARANDO

    texto, err = _chat_una_vez(primario, system, user, max_tokens, temperature,
                               base_url=motor.base_url, timeout=motor.timeout)
    if texto is not None:
        return texto, None
    codigo, mensaje = err
    if codigo == 'modelo' and fallback and fallback != primario:
        try:
            current_app.logger.warning(
                f"IA fallback: {primario} falló ({mensaje[:60]}) → intentando {fallback}")
        except Exception:
            pass
        texto, err2 = _chat_una_vez(fallback, system, user, max_tokens, temperature,
                                    base_url=motor.base_url, timeout=motor.timeout)
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
    texto, err = _chat(_contexto_tenant(), user, max_tokens=300, tarea='contenido')
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
    texto, err = _chat(system, user, max_tokens=2600, temperature=0.6, tarea='articulo')
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
    texto, err = _chat(_contexto_tenant(), user, max_tokens=180, temperature=0.5, tarea='contenido')
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


def _modelo_en_memoria(modelo):
    """True/False si Ollama ya tiene el modelo cargado; None si no se puede
    saber (proveedor cloud sin /api/ps, red lenta). Solo sirve para AVISARLE al
    usuario que la primera respuesta tardará: nunca bloquea la consulta."""
    base = (current_app.config.get('AI_BASE_URL') or '').strip().rstrip('/')
    if not base:
        return None
    key = (current_app.config.get('AI_API_KEY') or '').strip()
    headers = {'Authorization': f'Bearer {key}'} if key else {}
    try:
        r = requests.get(f'{base}/api/ps', headers=headers, timeout=(2, 2))
        if r.status_code != 200:
            return None
        nombres = set()
        for m in (r.json() or {}).get('models', []):
            nombres.update({m.get('name'), m.get('model')})
        return modelo in nombres or f'{modelo}:latest' in nombres
    except Exception:
        return None


# ── Motor en frío ──────────────────────────────────────────────
# Tras encender el PC de IA, o tras 30 min sin uso, el modelo no está en memoria y
# cargarlo tarda de 1 a 3 minutos. Cloudflare corta a los 100 s y nginx a los 60 s
# si la respuesta no envía nada, así que una consulta que solo esperara la carga
# moría con 504/524 y el cliente veía "No se pudo conectar con el servidor de IA".
# Ahora se pide la carga apenas se detecta el frío y se espera en tramos cortos.
_INTENTOS_CONEXION = 3       # conexión rechazada/cortada: Ollama reiniciándose
_PAUSA_CONEXION_S = 5
_CALENTANDO = {}             # modelo -> instante del último pedido de carga (por proceso)
_CALENTAR_CADA_S = 120
MSG_MOTOR_PREPARANDO = ('El motor de IA se está preparando: la primera consulta después de encender '
                        'el equipo, o de un rato sin uso, tarda de 1 a 3 minutos. Intenta de nuevo en un momento.')
MSG_SOLO_LOCAL = ('Estos datos no salen del equipo del negocio y el equipo de IA no está disponible '
                  'ahora mismo.')

# Puente a la nube mientras el modelo del equipo no está listo. vivo()/api/tags
# (ia_motores.py) no distingue "Ollama arriba pero modelo sin cargar" de "modelo
# caliente"; _modelo_en_memoria (/api/ps) sí, y Ollama no lista un modelo hasta
# que terminó de cargar (medido con 0.31.1). Regla del dueño: mientras el modelo
# no esté listo, cada pregunta que necesita modelo la responde la nube (Claude
# Haiku, sin pensamiento extendido) y la carga queda pedida; cada pregunta vuelve
# a mirar y, en cuanto está listo, responde el local. Sin tope de preguntas: el
# gasto lo frena el presupuesto mensual de ia_nube, y lo solo local (nómina,
# documentos internos) nunca sale.
def _puente_disponible(canal):
    """¿Puede la nube responder esta pregunta mientras el modelo local carga?
    Llave válida, presupuesto y, en el chat del sitio, su permiso. Nunca lanza."""
    try:
        from services import ia_nube
        return bool(ia_nube.disponible(canal))
    except Exception:  # noqa: BLE001
        return False


def _responder_nube(system, user, max_tokens, temperature):
    """Una llamada directa al respaldo en la nube. (texto, None) o (None, motivo);
    nunca lanza. Presupuesto y conteo de tokens los lleva ia_nube."""
    try:
        from services import ia_nube
        timeout = int(current_app.config.get('AI_NUBE_TIMEOUT') or 25)
        return ia_nube.responder(system, user, max_tokens=max_tokens,
                                 temperature=temperature, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        try:
            current_app.logger.warning(f'IA: el respaldo en la nube falló ({exc})')
        except Exception:
            pass
        return None, 'El respaldo en la nube no respondió.'


def _intentar_puente_frio(motor, system, user, max_tokens, temperature, canal):
    """Solo con el modelo ya confirmado frío. None si no aplica (sigue el camino
    local de siempre); el texto de la nube si el puente respondió."""
    if not _puente_disponible(canal):
        return None
    texto, _motivo = _responder_nube(system, user, max_tokens, temperature)
    return texto or None


def _pedir_carga(modelo):
    """Pide a Ollama cargar el modelo sin bloquear (hilo aparte). No fija
    keep_alive: rige el del servidor (30 min), así no queda cargado para siempre."""
    ahora = time.time()
    if ahora - _CALENTANDO.get(modelo, 0) < _CALENTAR_CADA_S:
        return
    _CALENTANDO[modelo] = ahora
    base = (current_app.config.get('AI_BASE_URL') or '').strip().rstrip('/')
    key = (current_app.config.get('AI_API_KEY') or '').strip()
    headers = {'Authorization': f'Bearer {key}'} if key else {}

    def _cargar():
        try:
            requests.post(f'{base}/api/generate', json={'model': modelo},
                          headers=headers, timeout=(5, 600))
        except Exception:
            pass

    threading.Thread(target=_cargar, name=f'ia-calentar-{modelo}', daemon=True).start()


def precalentar(motor):
    """Deja el modelo del equipo del dueño cargándose para la PRÓXIMA pregunta,
    aunque esta la haya contestado Python. Si ya está en memoria, el pedido solo
    renueva el keep_alive del servidor (30 min): nunca lo deja cargado para
    siempre. No espera ni lanza; el freno de _pedir_carga evita repetirlo."""
    try:
        from services.ia_motores import NIVEL_B
        if motor is None or motor.es_nube or motor.nivel != NIVEL_B or not motor.configurado:
            return
        _pedir_carga(motor.modelo)
    except Exception:  # noqa: BLE001
        pass


def _esperar_motor(modelo, espera_max, intervalo=5):
    """Generador que espera a que el modelo esté en memoria. Mientras carga emite
    None cada `intervalo` s (el chat lo convierte en latido para que el proxy no
    corte) y al terminar devuelve True si quedó listo o False si se agotó la
    espera. Si el estado no se puede saber (proveedor sin /api/ps), sale True."""
    if _modelo_en_memoria(modelo) is not False:
        return True
    _pedir_carga(modelo)
    fin = time.time() + espera_max
    while time.time() < fin:
        yield None
        time.sleep(intervalo)
        if _modelo_en_memoria(modelo) is not False:
            return True
        _pedir_carga(modelo)   # si Ollama se reinició a mitad, vuelve a pedir la carga
    return False


def _esperar_motor_bloqueando(modelo, espera_max):
    """Variante sin latidos para las respuestas completas (sin streaming)."""
    gen = _esperar_motor(modelo, espera_max)
    try:
        while True:
            next(gen)
    except StopIteration as fin:
        return fin.value


def _latidos(espera):
    """La espera de _esperar_motor convertida en eventos ('latido', None) para
    el chat en streaming. Con `yield from` devuelve si el modelo quedó listo."""
    try:
        while True:
            next(espera)
            yield ('latido', None)
    except StopIteration as fin:
        return fin.value


# ── Chat del negocio ───────────────────────────────────────────
_MAX_HERRAMIENTAS = 3        # por pregunta (p. ej. "ventas del mes y qué reponer")
_MAX_HISTORIAL = 4           # intercambios previos que se tienen en cuenta
_DIAS_SEMANA = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']


def _sanear_historial(historial):
    """Últimos intercambios que manda el panel, para entender preguntas de
    seguimiento («¿y el mes pasado?»). Vienen del navegador: se recortan y solo se
    usan como texto de contexto; no dan acceso a nada (los permisos se revisan
    igual en cada herramienta)."""
    if not isinstance(historial, list):
        return []
    limpio = []
    for turno in historial[-_MAX_HISTORIAL:]:
        if not isinstance(turno, dict):
            continue
        pregunta = str(turno.get('pregunta') or '').strip()[:300]
        if pregunta:
            limpio.append({'pregunta': pregunta,
                           'respuesta': str(turno.get('respuesta') or '').strip()[:300],
                           'herramienta': str(turno.get('herramienta') or '').strip()[:80]})
    return limpio


def _texto_historial(historial):
    if not historial:
        return ''
    lineas = ['CONVERSACIÓN RECIENTE (úsala solo para entender preguntas de seguimiento):']
    for turno in historial:
        usada = f" [herramienta: {turno['herramienta']}]" if turno['herramienta'] else ''
        lineas.append(f"- Dueño: «{turno['pregunta']}»{usada}")
        if turno['respuesta']:
            lineas.append(f"  Asistente: «{turno['respuesta']}»")
    return '\n'.join(lineas)


def _previo(historial):
    """La conversación reciente lista para anteponer a la petición, o ''."""
    conversacion = _texto_historial(historial)
    return f'{conversacion}\n\n' if conversacion else ''


def _solo_local(h):
    """True si lo que devuelve esta capacidad nunca puede ir a la nube: los datos
    sensibles (nómina) y las que se declaran así (documentos internos)."""
    return h is not None and (h.sensible is not None or h.extra.get('nube') is False)


def _historial_para_nube(historial):
    """La conversación sin los turnos que usaron capacidades solo locales: sus
    respuestas pueden traer esas cifras, y la nube no debe verlas aunque la
    pregunta nueva no sea sensible."""
    import services.ai_tools as tools
    limpio = []
    for turno in historial:
        codigos = [c.strip() for c in (turno.get('herramienta') or '').split(',') if c.strip()]
        if not any(_solo_local(tools.REGISTRO.get(c)) for c in codigos):
            limpio.append(turno)
    return limpio


_RE_CODE = re.compile(r'"tool"\s*:\s*"([a-z_]+)"|"([a-z_]+)"\s*:\s*\{\s*"params"')
_RE_PARAM = re.compile(r'"(periodo|desde|hasta|limite|umbral|producto|cliente|empleado)"\s*:\s*"?([\w-]+)"?')


def _reparar_herramientas(raw):
    """Rescata las herramientas cuando el modelo devuelve un JSON inválido
    (p. ej. mezcla una clave dentro de la lista). Sin esto se perdía la consulta
    entera. Los nombres se validan igual contra el catálogo más adelante."""
    texto = raw or ''
    encontrados = []
    for m in _RE_CODE.finditer(texto):
        code = m.group(1) or m.group(2)
        # Los parámetros de ese bloque: hasta donde empieza la siguiente herramienta
        siguiente = _RE_CODE.search(texto, m.end())
        trozo = texto[m.end():siguiente.start() if siguiente else len(texto)]
        params = {}
        for k, v in _RE_PARAM.findall(trozo):
            params[k] = int(v) if v.isdigit() else v
        encontrados.append((code, params))
    return encontrados


def _parsear_herramientas(raw):
    """[(code, params)] de la respuesta del enrutador. Acepta el formato nuevo
    {"tools":[{tool, params}]} y el anterior {"tool":..., "params":...}."""
    try:
        m = re.search(r'\{.*\}', raw or '', re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        data = None
    if data is None:
        items = [{'tool': c, 'params': p} for c, p in _reparar_herramientas(raw)]
        data = {'tools': items} if items else {}
    if not isinstance(data, dict):
        return []
    if isinstance(data.get('tools'), list):
        items = data['tools']
    elif data.get('tool'):
        items = [{'tool': data.get('tool'), 'params': data.get('params')}]
    else:
        items = []
    elegidas, vistas = [], set()
    for item in items:
        if isinstance(item, str):
            item = {'tool': item}
        if not isinstance(item, dict):
            continue
        code = str(item.get('tool') or '').strip()
        params = item.get('params') if isinstance(item.get('params'), dict) else {}
        firma = (code, json.dumps(params, sort_keys=True, default=str))
        if not code or code == 'ninguna' or firma in vistas:
            continue
        vistas.add(firma)
        elegidas.append((code, params))
    return elegidas[:_MAX_HERRAMIENTAS]


def _resolver_codigo(code, permitidos):
    """El modelo a veces escribe el nombre casi bien ('restaurant_ahora' por
    'restaurante_ahora') y se perdía la consulta entera. Se corrige SOLO contra
    las herramientas que este usuario puede usar, así que la corrección nunca
    sirve de atajo para saltarse un permiso."""
    import difflib
    limpio = lambda c: re.sub(r'[^a-z]', '', (c or '').lower())  # noqa: E731
    equivalentes = {limpio(c): c for c in permitidos}
    clave = limpio(code)
    if clave in equivalentes:
        return equivalentes[clave]
    cercanos = difflib.get_close_matches(clave, list(equivalentes), n=1, cutoff=0.85)
    return equivalentes[cercanos[0]] if cercanos else None


def _fecha_hoy():
    """Fecha de la BD (la misma que usan los filtros de período), no la del
    servidor web, que puede ir en UTC y adelantarse un día por la noche."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT CURRENT_DATE AS hoy, LOCALTIMESTAMP AS ahora")
            r = cur.fetchone()
            return r['hoy'], r['ahora']
    except Exception:
        ahora = datetime.now()
        return ahora.date(), ahora


def _plan_chat(pregunta, historial=None, contexto=None):
    """Pasos 1 y 2 del chat del negocio sin anuncios de progreso (la usa la
    respuesta completa, p. ej. el POS de escritorio). Devuelve (plan, None) o
    (None, err); ver _plan_chat_pasos."""
    for evento, dato in _plan_chat_pasos(pregunta, anunciar=False, historial=historial,
                                         contexto=contexto):
        if evento == 'plan':
            return dato, None
        if evento == 'error':
            return None, dato
    return None, 'No pude preparar la respuesta.'


def _plan_chat_pasos(pregunta, anunciar=True, historial=None, contexto=None):
    """Pasos 1 y 2 del chat del negocio (comunes a la variante normal y a la
    streaming): la IA elige de 1 a 3 herramientas de solo-lectura (JSON
    estricto) entre las que quien pregunta puede usar, y las ejecutamos contra
    la BD del tenant.

    Es un generador para poder contarle al usuario en qué va mientras espera:
    en frío la primera respuesta puede tardar más de un minuto y, sin avisos,
    el chat parecía colgado. Emite:
      ('estado', texto) — fase en curso (solo si anunciar=True)
      ('plan', plan)    — {system, user, max_tokens, datos, herramienta,
                           herramientas, sensible, objetivo}
      ('error', texto)  — fin sin plan
    """
    import services.ai_tools as tools

    pregunta = (pregunta or '').strip()
    if not pregunta:
        yield ('error', 'Escribe una pregunta.')
        return

    if anunciar:
        yield ('estado', 'Estamos procesando tu pregunta…')

    ctx = contexto or tools.contexto_actual()
    disponibles = tools.permitidas(ctx)
    from services.ia.enrutador import enrutar_panel_seguro
    ruta_segura = enrutar_panel_seguro(pregunta, disponibles, historial=historial)

    # La conversación va en dos versiones: completa para el modelo del equipo del
    # dueño, y sin los turnos solo locales (nómina, documentos internos) para el
    # respaldo en la nube.
    historial = _sanear_historial(historial)
    previo = _previo(historial)
    previo_nube = _previo(_historial_para_nube(historial))

    # Las consultas inequívocas van directo a funciones fijas: no esperan a que
    # cargue Ollama ni pagan un modelo en la nube solo para elegir herramienta.
    # Las demás necesitan el modelo para elegir: si está frío, la carga se pide ya
    # y, mientras tanto, la pregunta va por la nube (si está configurada); si no,
    # se espera la carga como siempre.
    puente = None                     # None = no se decidió: lo decide la redacción si hace falta
    if not ruta_segura:
        primario = current_app.config.get('AI_MODEL') or 'qwen2.5:7b'
        if _modelo_en_memoria(primario) is False:
            _pedir_carga(primario)
            puente = _puente_disponible('panel')
            if puente:
                if anunciar:
                    yield ('estado', 'Tu equipo de IA se está preparando: mientras carga, te '
                                     'respondo con el respaldo en la nube…')
            elif anunciar:
                yield ('estado', 'Estamos preparando el motor de análisis. '
                                 'La primera consulta tarda un poco más; enseguida seguimos…')
                # Se espera la carga ANTES de preguntarle al modelo, con latidos cada 5 s:
                # sin ellos Cloudflare/nginx cortaban la conexión a los 60-100 s de silencio.
                listo = yield from _latidos(_esperar_motor(primario, espera_max=300))
                if not listo:
                    yield ('error', MSG_MOTOR_PREPARANDO)
                    return
                yield ('estado', 'El motor de análisis está listo. Seguimos con tu pregunta…')

    hoy, ahora = _fecha_hoy()

    # Paso 1: selección de herramientas (la IA NO escribe SQL, solo elige nombres+params).
    # Solo ve las que este usuario puede usar: lo demás ni aparece en su lista.
    sel_system = (
        tools.CONTEXTO_DATOS + "\n\n"
        f"Hoy es {_DIAS_SEMANA[hoy.weekday()]} {hoy.isoformat()}.\n"
        "Eres un enrutador. Dada la pregunta de un dueño de negocio, elige las "
        f"herramientas MÍNIMAS (de 1 a {_MAX_HERRAMIENTAS}) de esta lista para responderla:\n" +
        tools.catalogo_para_prompt(disponibles) +
        "\nResponde SOLO un JSON válido: {\"tools\":[{\"tool\":\"<code>\",\"params\":{...}}]}. "
        "params puede incluir 'periodo' (hoy|ayer|semana|semana_anterior|mes|mes_anterior|anio|todo), "
        "'desde' y 'hasta' (AAAA-MM-DD, para fechas concretas como «en agosto»), 'limite' "
        "(número), 'umbral' (número) y los parámetros propios que cada herramienta pide entre "
        "paréntesis (por ejemplo «cliente» con el nombre tal como lo dijo el usuario). "
        "Si el usuario NO menciona un período "
        "concreto, usa 'todo' (histórico). Usa más de una herramienta solo si la pregunta pide "
        "cosas distintas o una comparación (este mes contra el anterior = la misma herramienta "
        "dos veces con períodos distintos). Si es una pregunta de seguimiento, completa lo que "
        "falta con la conversación reciente. Si piden datos sensibles o algo sin herramienta, "
        "responde {\"tools\":[]}. Solo el JSON."
    )
    sel_user = f"{previo}Pregunta actual: «{pregunta}»" if previo else pregunta
    sel_user_nube = f"{previo_nube}Pregunta actual: «{pregunta}»" if previo_nube else pregunta

    def _seleccionar(extra=''):
        """Elegir herramientas no manda datos del negocio, solo la pregunta y el
        catálogo; aun así la nube recibe la conversación ya filtrada."""
        if puente:
            texto, _motivo = _responder_nube(sel_system, sel_user_nube + extra, 220, 0)
            if texto:
                return texto, None
            # La nube falló: se sigue con el equipo del dueño (espera acotada).
        return _chat(sel_system, sel_user + extra, max_tokens=220, temperature=0,
                     user_nube=sel_user_nube + extra)

    if ruta_segura:
        elegidas = ruta_segura
        via = 'keyword'
    else:
        raw, err = _seleccionar()
        if err:
            yield ('error', err)
            return
        if not _parsear_herramientas(raw):
            # A veces el modelo contesta "ninguna" a preguntas que sí puede resolver
            # (medido con el modelo real). Se insiste UNA vez, sin aflojar la regla de
            # los datos sensibles: si de verdad no aplica, vuelve a responder vacío.
            reintento, err2 = _seleccionar(
                "\n\nAntes respondiste sin herramientas. Si la pregunta se puede responder con "
                "alguna de la lista, elígela ahora. Si pide datos sensibles o algo que no está en la lista, "
                "responde {\"tools\":[]} otra vez.")
            if not err2 and _parsear_herramientas(reintento):
                raw = reintento
        permitidos = [h.code for h in disponibles]
        elegidas = []
        for code, params in _parsear_herramientas(raw):
            if code in tools.REGISTRO:
                elegidas.append((code, params))      # existe: el permiso se revisa al ejecutar
                continue
            real = _resolver_codigo(code, permitidos)
            if real:
                elegidas.append((real, params))
        via = 'modelo'

    if not elegidas:
        # Pregunta fuera del alcance de los datos (o dato sensible): responde
        # con honestidad y recuerda los límites del contexto.
        puede = '; '.join(h.etiqueta for h in disponibles) or 'la información general de tu negocio'
        cuerpo = (f"El dueño preguntó: «{pregunta}». No tienes una herramienta ni permiso "
                  "para responder eso con datos. Responde breve y amable; si es un dato "
                  "sensible niégate, y en todo caso indícale qué SÍ puedes consultar: "
                  f"{puede}.")
        yield ('plan', {
            'system': _contexto_tenant() + "\n" + tools.CONTEXTO_DATOS,
            'user': previo + cuerpo, 'user_nube': previo_nube + cuerpo,
            'max_tokens': 220, 'datos': None, 'herramienta': None,
            'herramientas': [], 'sensible': None, 'objetivo': None,
            'via': via, 'intencion': None, 'puente': puente, 'solo_local': False,
        })
        return

    # Paso 2: ejecutar las herramientas (consultas reales, tenant-scoped). ejecutar()
    # vuelve a revisar el permiso por si el modelo nombró una que no estaba en su lista.
    resultados, usadas, fallidas, sensibles, objetivos = {}, [], 0, set(), []
    solo_local = False
    for code, params in elegidas:
        h = tools.REGISTRO[code]
        if anunciar:
            yield ('estado', f"Consultando {h.etiqueta}…")
        try:
            datos = tools.ejecutar(code, params, ctx)
        except Exception as exc:  # noqa: BLE001
            try:
                current_app.logger.warning(f'IA tool {code} falló: {exc}')
            except Exception:
                pass
            fallidas += 1
            datos = {'error': 'No se pudo consultar este dato en este momento.'}
        clave = code if code not in resultados else f'{code}_{usadas.count(code) + 1}'
        resultados[clave] = datos
        usadas.append(code)
        denegado = isinstance(datos, dict) and datos.get('denegado')
        if h.sensible and not denegado:
            sensibles.add(h.sensible)
            objetivos.extend(str(v) for k, v in params.items() if k in ('empleado', 'cliente') and v)
        if _solo_local(h) and not denegado:
            solo_local = True
    if fallidas == len(elegidas):
        yield ('error', 'No pude consultar esos datos en este momento.')
        return

    if anunciar:
        yield ('estado', 'Iniciamos el análisis de los datos…')

    # Paso 3 (preparado): redacción con los datos reales
    unica = len(resultados) == 1
    datos = next(iter(resultados.values())) if unica else resultados
    agrupados = '' if unica else ', agrupados por herramienta'
    cuerpo = (f"Pregunta: «{pregunta}»\n"
              f"Datos reales de su tienda, consultados el {ahora:%Y-%m-%d %H:%M}{agrupados} (JSON):\n"
              f"{json.dumps(datos, ensure_ascii=False, default=str)}\n\nRedacta la respuesta.")
    yield ('plan', {
        'system': (_contexto_tenant() +
                   " Responde la pregunta del dueño usando ÚNICAMENTE los datos que "
                   "te doy (son reales, de su tienda). Sé claro y breve, en español, "
                   "con las cifras exactas. No inventes nada que no esté en los datos."),
        'user': previo + cuerpo,
        # solo_local: la redacción nunca va a la nube (ni puente ni respaldo).
        'user_nube': previo_nube + cuerpo,
        'max_tokens': 350 if unica else 550,
        'datos': datos,
        'herramienta': ','.join(dict.fromkeys(usadas)),
        'herramientas': usadas,
        'sensible': ','.join(sorted(sensibles)) or None,
        'objetivo': '; '.join(dict.fromkeys(objetivos))[:120] or None,
        'via': via, 'intencion': usadas[0] if len(set(usadas)) == 1 else 'multiple',
        'puente': puente, 'solo_local': solo_local,
    })


# ── Registro de consultas del chat ─────────────────────────────
# Solo datos técnicos (qué herramientas, si salió bien, cuánto tardó), nunca la
# respuesta ni las cifras. La pregunta se guarda únicamente cuando la IA no tenía
# herramienta para contestarla, para saber qué datos faltan conectar; ese texto
# se borra a los 90 días. Las filas no se borran: también son la auditoría de las
# consultas sensibles (quién consultó nómina y de quién).
_DDL_IA_CONSULTAS = """
CREATE TABLE IF NOT EXISTS ia_consultas (
    id BIGSERIAL PRIMARY KEY,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    usuario_id INTEGER,
    rol_id INTEGER,
    canal VARCHAR(20) NOT NULL DEFAULT 'web',
    herramientas TEXT[] NOT NULL DEFAULT '{}',
    ok BOOLEAN NOT NULL DEFAULT TRUE,
    error VARCHAR(300),
    ms INTEGER,
    sensible VARCHAR(40),
    objetivo VARCHAR(120),
    pregunta_sin_herramienta VARCHAR(200),
    intencion VARCHAR(40),
    via VARCHAR(20),
    motor VARCHAR(4),
    documentos BIGINT[]
);
CREATE INDEX IF NOT EXISTS idx_ia_consultas_creado_en ON ia_consultas (creado_en);
"""
_IA_CONSULTAS_LISTA = set()   # tenants con la tabla ya verificada (por proceso)
_IA_CONSULTAS_PURGA = {}      # tenant -> día de la última limpieza de preguntas


def _registrar_consulta(ctx, pregunta, plan, error, inicio):
    """Nunca rompe el chat: si la BD no deja registrar, solo queda en el log."""
    try:
        tenant = (_current_db_name(), get_current_tenant_id())
        herramientas = list((plan or {}).get('herramientas') or [])
        sin_herramienta = None
        if plan is not None and not herramientas and not error:
            sin_herramienta = (pregunta or '').strip()[:200] or None
        try:
            usuario = int(ctx.usuario_id) if ctx.usuario_id is not None else None
        except (TypeError, ValueError):
            usuario = None
        with get_db_cursor() as cur:
            if tenant not in _IA_CONSULTAS_LISTA:
                cur.execute(_DDL_IA_CONSULTAS)
                _IA_CONSULTAS_LISTA.add(tenant)
            cur.execute(
                """INSERT INTO ia_consultas (usuario_id, rol_id, canal, herramientas, ok, error, ms,
                                             sensible, objetivo, pregunta_sin_herramienta,
                                             intencion, via, motor, documentos)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (usuario, ctx.rol_id, ctx.canal, herramientas, not error,
                 (str(error)[:300] if error else None), int((time.time() - inicio) * 1000),
                 (plan or {}).get('sensible'), (plan or {}).get('objetivo'), sin_herramienta,
                 (plan or {}).get('intencion'), (plan or {}).get('via'),
                 (plan or {}).get('motor'), list((plan or {}).get('documentos') or []) or None))
            hoy = datetime.now().date()
            if _IA_CONSULTAS_PURGA.get(tenant) != hoy:
                cur.execute("""UPDATE ia_consultas SET pregunta_sin_herramienta = NULL
                               WHERE pregunta_sin_herramienta IS NOT NULL
                                 AND creado_en < NOW() - INTERVAL '90 days'""")
                _IA_CONSULTAS_PURGA[tenant] = hoy
    except Exception as exc:  # noqa: BLE001
        try:
            current_app.logger.warning(f'IA: no se pudo registrar la consulta: {exc}')
        except Exception:
            pass


def resumen_consultas(dias=30):
    """Uso del asistente en los últimos `dias`, preguntas que aún no sabe
    responder y consultas sensibles recientes. Para el dueño (panel IA)."""
    import services.ai_tools as tools
    dias = max(1, min(int(dias or 30), 365))
    vacio = {'dias': dias, 'total': 0, 'correctas': 0, 'ms_mediana': None, 'sin_herramienta': 0,
             'herramientas': [], 'preguntas_sin_respuesta': [], 'sensibles': []}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT to_regclass('public.ia_consultas') AS t")
            if cur.fetchone()['t'] is None:
                return vacio
            cur.execute("""SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE ok) AS correctas,
                                  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ms) AS ms_mediana,
                                  COUNT(*) FILTER (WHERE ok AND cardinality(herramientas) = 0) AS sin_herramienta
                           FROM ia_consultas WHERE creado_en >= NOW() - make_interval(days => %s)""", (dias,))
            r = cur.fetchone()
            cur.execute("""SELECT h, COUNT(*) AS n FROM ia_consultas, unnest(herramientas) AS h
                           WHERE creado_en >= NOW() - make_interval(days => %s)
                           GROUP BY h ORDER BY n DESC LIMIT 10""", (dias,))
            usos = [{'herramienta': x['h'],
                     'etiqueta': (tools.REGISTRO[x['h']].etiqueta if x['h'] in tools.REGISTRO else x['h']),
                     'veces': int(x['n'])} for x in cur.fetchall()]
            cur.execute("""SELECT creado_en, pregunta_sin_herramienta FROM ia_consultas
                           WHERE pregunta_sin_herramienta IS NOT NULL
                           ORDER BY creado_en DESC LIMIT 30""")
            preguntas = [{'fecha': x['creado_en'].isoformat(timespec='minutes'),
                          'pregunta': x['pregunta_sin_herramienta']} for x in cur.fetchall()]
            cur.execute("""SELECT c.creado_en, c.sensible, c.objetivo, COALESCE(u.nombre, 'Usuario ' || c.usuario_id::text) AS usuario
                           FROM ia_consultas c LEFT JOIN usuarios u ON u.id = c.usuario_id
                           WHERE c.sensible IS NOT NULL ORDER BY c.creado_en DESC LIMIT 30""")
            sensibles = [{'fecha': x['creado_en'].isoformat(timespec='minutes'), 'tipo': x['sensible'],
                          'objetivo': x['objetivo'], 'usuario': x['usuario']} for x in cur.fetchall()]
    except Exception as exc:  # noqa: BLE001
        try:
            current_app.logger.warning(f'IA: resumen de consultas falló: {exc}')
        except Exception:
            pass
        return vacio
    return {'dias': dias, 'total': int(r['total']), 'correctas': int(r['correctas']),
            'ms_mediana': int(r['ms_mediana']) if r['ms_mediana'] is not None else None,
            'sin_herramienta': int(r['sin_herramienta']), 'herramientas': usos,
            'preguntas_sin_respuesta': preguntas, 'sensibles': sensibles}


def _respuesta_datos_sin_modelo(plan):
    """Entrega el resultado autorizado sin inventar una explicación con IA.

    La salida se acota explícitamente para no volcar tablas enormes al chat;
    los valores originales siguen en ``plan['datos']`` para el cliente interno.
    """
    datos = plan.get('datos')
    if datos is None:
        return None
    documentos = _texto_de_documentos(datos)
    if documentos:
        return documentos

    def acotar(valor, profundidad=0):
        if profundidad >= 5:
            return '[detalle anidado omitido]'
        if isinstance(valor, dict):
            pares = list(valor.items())
            salida = {str(k): acotar(v, profundidad + 1) for k, v in pares[:30]}
            if len(pares) > 30:
                salida['registros_adicionales_omitidos'] = len(pares) - 30
            return salida
        if isinstance(valor, (list, tuple)):
            salida = [acotar(v, profundidad + 1) for v in valor[:12]]
            if len(valor) > 12:
                salida.append({'registros_adicionales_omitidos': len(valor) - 12})
            return salida
        if isinstance(valor, str) and len(valor) > 500:
            return valor[:500] + '… [texto abreviado]'
        return valor

    codigos = plan.get('herramientas') or []
    titulo = ', '.join(dict.fromkeys(c.replace('_', ' ') for c in codigos)) or 'la consulta'
    cuerpo = json.dumps(acotar(datos), ensure_ascii=False, indent=2, default=str)
    return f'Datos verificados de {titulo} (sin redacción de IA):\n{cuerpo}'


def _texto_de_documentos(datos):
    """Los documentos internos como texto legible (título y contenido), no como
    JSON: son textos que el dueño escribió para leerse. None si no es eso."""
    if not isinstance(datos, dict) or not set(datos) <= {'buscado', 'encontrados',
                                                         'documentos', 'conclusion'}:
        return None
    docs = datos.get('documentos')
    if isinstance(docs, list) and docs and all(
            isinstance(d, dict) and d.get('titulo') and d.get('texto') for d in docs):
        partes = [f"«{d['titulo']}»\n{d['texto']}" for d in docs]
        return 'Esto dicen tus documentos internos (sin redacción de IA):\n\n' + '\n\n'.join(partes)
    return datos.get('conclusion') or None


def _datos_solo_locales_hacia_nube(plan, motor):
    """True si el único motor disponible es la nube y la respuesta no puede ir
    allá: o trae datos solo locales, o es una consulta directa (keyword) que ya
    se entiende sin redactar. Entonces se entregan los datos tal cual."""
    return (plan['datos'] is not None and motor is not None and motor.es_nube
            and (plan.get('via') == 'keyword' or plan.get('solo_local')))


def _redactar_en_frio(plan, motor):
    """(texto_de_la_nube, frio). Si el modelo del equipo del dueño está sin
    cargar: pide la carga y, si la nube está disponible (o ya eligió las
    herramientas de esta pregunta) y sus datos pueden salir, la redacta la nube.
    `frio` le dice a quien llama que, si no hubo texto, hay que esperar la carga."""
    from services.ia_motores import NIVEL_B
    if motor is None or motor.es_nube or motor.nivel != NIVEL_B:
        return None, False
    primario = motor.modelo or 'qwen2.5:7b'
    if _modelo_en_memoria(primario) is not False:
        return None, False
    _pedir_carga(primario)
    if plan.get('solo_local'):
        return None, True
    usar = plan['puente'] if plan.get('puente') is not None else _puente_disponible('panel')
    if not usar:
        return None, True
    texto, _motivo = _responder_nube(plan['system'], plan['user_nube'], plan['max_tokens'], 0.7)
    return (texto or None), True


def responder_chat(pregunta, historial=None, contexto=None):
    """Asistente conversacional del negocio (respuesta completa, sin streaming
    — la usa el desktop y queda de respaldo para el panel web).
    Devuelve (dict {respuesta, datos, herramienta, herramientas}, None) o
    (None, mensaje_error)."""
    import services.ai_tools as tools
    inicio = time.time()
    ctx = contexto or tools.contexto_actual()
    plan, err = _plan_chat(pregunta, historial, ctx)
    if err:
        _registrar_consulta(ctx, pregunta, None, err, inicio)
        return None, err
    from services import ia_motores as motores
    motor, _ = motores.motor_para(plan.get('perfil', 'normal'),
                                 plan.get('canal_motor', 'panel'))
    directo = plan['datos'] is not None and (
        motor is None or _datos_solo_locales_hacia_nube(plan, motor))
    if directo:
        resp, err3 = _respuesta_datos_sin_modelo(plan), None
        plan['motor'] = 'SQL'
    else:
        resp, _frio = _redactar_en_frio(plan, motor)
        err3 = None
        if resp:
            plan['motor'] = 'nube'
        else:
            resp, err3 = _chat(plan['system'], plan['user'], max_tokens=plan['max_tokens'],
                               user_nube=plan.get('user_nube'),
                               permitir_nube=not plan.get('solo_local'))
            if err3 and plan['datos'] is not None:
                resp, err3 = _respuesta_datos_sin_modelo(plan), None
                plan['motor'] = 'SQL'
            elif not err3 and motor is not None:
                plan['motor'] = 'nube' if motor.es_nube else motor.nivel
    _registrar_consulta(ctx, pregunta, plan, err3, inicio)
    if err3:
        return None, err3
    return {'respuesta': resp, 'datos': plan['datos'], 'herramienta': plan['herramienta'],
            'herramientas': plan['herramientas']}, None


def responder_chat_stream(pregunta, historial=None, contexto=None):
    """Variante STREAMING del chat del negocio. Los pasos 1-2 (elegir
    herramientas + consulta real) no se pueden streamear; solo la redacción
    final se emite palabra a palabra. Generador de eventos (tuplas):
      ('estado', texto)                — fase en curso, para que la espera no
                                         parezca un cuelgue (puede repetirse)
      ('meta',  {herramienta, datos})  — una vez, antes del texto
      ('delta', fragmento)             — texto incremental
      ('fin',   texto_completo)        — cierre normal
      ('error', mensaje)               — cierre con error (puede llegar sin deltas)
    Mantiene el fallback de modelo: si el primario falla ANTES de emitir texto,
    reintenta con AI_MODEL_FALLBACK. Si falla a mitad, lo emitido se conserva."""
    import services.ai_tools as tools
    inicio = time.time()
    ctx = contexto or tools.contexto_actual()
    resultado = {'plan': None, 'error': 'La consulta se interrumpió antes de terminar.'}
    try:
        for evento in _responder_chat_stream(pregunta, historial, ctx, resultado):
            yield evento
    finally:
        # También si el navegador cierra a mitad (GeneratorExit): queda registrada.
        _registrar_consulta(ctx, pregunta, resultado['plan'], resultado['error'], inicio)


def _responder_chat_stream(pregunta, historial, ctx, resultado):
    plan = None
    for evento, dato in _plan_chat_pasos(pregunta, historial=historial, contexto=ctx):
        if evento in ('estado', 'latido'):
            yield (evento, dato)
        elif evento == 'error':
            resultado['error'] = dato
            yield ('error', dato)
            return
        elif evento == 'plan':
            plan = dato
    if plan is None:
        resultado['error'] = 'No pude preparar la respuesta.'
        yield ('error', resultado['error'])
        return
    resultado['plan'] = plan
    yield ('meta', {'herramienta': plan['herramienta'], 'herramientas': plan['herramientas'],
                    'datos': plan['datos']})
    yield ('estado', 'Pronto te entregaremos el resultado…')

    from services import ia_motores as motores
    motor, motivo_motor = motores.motor_para(plan.get('perfil', 'normal'),
                                             plan.get('canal_motor', 'panel'))
    if plan['datos'] is not None and (
            motor is None or _datos_solo_locales_hacia_nube(plan, motor)):
        texto = _respuesta_datos_sin_modelo(plan)
        plan['motor'] = 'SQL'
        resultado['error'] = None
        yield ('delta', texto)
        yield ('fin', texto)
        return
    if motor is None:
        resultado['error'] = motivo_motor
        yield ('error', motivo_motor)
        return
    if motor.es_nube:
        yield ('estado', 'Respondiendo con el respaldo en la nube…')
        texto, motivo = chat_con_motor(motor, plan['system'], plan['user_nube'],
                                       plan['max_tokens'], 0.7)
        if not texto:
            if plan['datos'] is not None:
                directo = _respuesta_datos_sin_modelo(plan)
                plan['motor'] = 'SQL'
                resultado['error'] = None
                yield ('delta', directo)
                yield ('fin', directo)
                return
            resultado['error'] = motivo
            yield ('error', motivo)
            return
        resultado['texto'] = texto
        resultado['error'] = None
        plan['motor'] = 'nube'
        yield ('delta', texto)
        yield ('fin', {'herramienta': plan['herramienta'], 'motor': 'nube'})
        return

    # Modelo del equipo del dueño sin cargar: el puente (si toca y los datos
    # pueden salir) o esperar la carga con latidos. Sin esto, el stream quedaba
    # mudo 1-3 min mientras Ollama cargaba y nginx lo cortaba a los 60 s.
    texto_nube, frio = _redactar_en_frio(plan, motor)
    if texto_nube:
        resultado['texto'] = texto_nube
        resultado['error'] = None
        plan['motor'] = 'nube'
        yield ('delta', texto_nube)
        yield ('fin', {'herramienta': plan['herramienta'], 'motor': 'nube'})
        return
    if frio:
        yield ('estado', 'Estamos preparando el motor de análisis. Enseguida seguimos…')
        listo = yield from _latidos(_esperar_motor(motor.modelo or 'qwen2.5:7b', espera_max=300))
        if not listo:
            if plan['datos'] is not None:
                directo = _respuesta_datos_sin_modelo(plan)
                plan['motor'] = 'SQL'
                resultado['error'] = None
                yield ('delta', directo)
                yield ('fin', directo)
                return
            resultado['error'] = MSG_MOTOR_PREPARANDO
            yield ('error', MSG_MOTOR_PREPARANDO)
            return

    primario = motor.modelo or 'qwen2.5:7b'
    plan['motor'] = motor.nivel
    fallback = ((current_app.config.get('AI_MODEL_FALLBACK') or '').strip()
                if motor.nivel == motores.NIVEL_B else '')
    partes = []
    try:
        for frag in _chat_stream_una_vez(primario, plan['system'], plan['user'],
                                         plan['max_tokens'], 0.7,
                                         base_url=motor.base_url, timeout=motor.timeout):
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
            yield ('estado', 'Seguimos con el motor de respaldo para no hacerte esperar más…')
            try:
                for frag in _chat_stream_una_vez(fallback, plan['system'], plan['user'],
                                                 plan['max_tokens'], 0.7,
                                                 base_url=motor.base_url,
                                                 timeout=motor.timeout):
                    partes.append(frag)
                    yield ('delta', frag)
            except _ErrorIA as e2:
                if plan['datos'] is not None and not partes:
                    directo = _respuesta_datos_sin_modelo(plan)
                    plan['motor'] = 'SQL'
                    resultado['error'] = None
                    yield ('delta', directo)
                    yield ('fin', directo)
                    return
                resultado['error'] = e2.mensaje
                yield ('error', e2.mensaje)
                return
        else:
            if plan['datos'] is not None and not partes:
                directo = _respuesta_datos_sin_modelo(plan)
                plan['motor'] = 'SQL'
                resultado['error'] = None
                yield ('delta', directo)
                yield ('fin', directo)
                return
            resultado['error'] = e.mensaje
            yield ('error', e.mensaje)
            return
    resultado['error'] = None
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
    texto, err = _chat(_contexto_tenant(), user, max_tokens=380, temperature=0.5, tarea='contenido')
    if err:
        return None, err

    ahora = datetime.now().isoformat(timespec='seconds')
    try:
        from services.config_tenant import set_cliente_config
        with get_db_cursor() as cur:
            for clave, valor in (('ia_resumen_negocio', texto),
                                 ('ia_resumen_negocio_ts', ahora)):
                set_cliente_config(cur, clave, valor,
                                   descripcion='Resumen IA del dashboard (auto)')
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
    return _chat(system, f"Traduce al {idioma} este texto:\n\n{texto[:1200]}", max_tokens=500,
                 tarea='contenido')


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
    return _chat(system, user, max_tokens=300, tarea='contenido')


def narrar_tu_dia(senales):
    """CRM · panel 'Tu día'. Recibe una lista de señales (strings) y devuelve UNA
    frase corta priorizando qué atender hoy. Fail-open: '' si la IA no responde."""
    senales = [str(s).strip() for s in (senales or []) if str(s).strip()]
    if not senales:
        return ''
    try:
        if not ia_disponible():
            return ''
        system = ("Eres el asistente comercial de un CRM. En UNA sola frase breve "
                  "(máx 20 palabras), en español, con tono cercano y accionable, di qué "
                  "conviene atender primero hoy. No saludes ni uses listas ni comillas.")
        # espera_frio=0: se llama mientras se arma la página del CRM. Con el motor
        # en frío, antes la colgaba hasta que el proxy cortaba; ahora pide la carga
        # y la página sale al instante (la frase aparece en la siguiente visita).
        texto, err = _chat(system, "Señales de hoy:\n" + '\n'.join('- ' + s for s in senales),
                           max_tokens=80, temperature=0.5, espera_frio=0, tarea='contenido')
        if err or not texto:
            return ''
        return texto.strip().strip('"').strip()[:200]
    except Exception:
        return ''
