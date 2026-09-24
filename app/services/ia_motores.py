"""Selector de motor: a qué máquina va cada petición de IA.

Hay tres niveles, y un solo lugar donde se decide cuál atiende:

  A · Siempre    modelo pequeño en el servidor. Hoy NO está configurado (la VPS
                 no tiene memoria: ver docs/IA_MOTORES.md). Cuando la haya,
                 basta con llenar AI_MOTOR_A_* y este módulo lo empieza a usar.
  B · Bueno      el modelo del PC de IA. Atiende el panel y el chat del sitio.
  C · Profundo   el mismo PC con contexto largo, para análisis pesados.

Reglas, en orden:

1. El nivel C **se pide a propósito** (interruptor del panel, palabra clave o
   `perfil='profundo'` desde el código) y **no degrada**: si el PC está apagado,
   se avisa. Un análisis pesado respondido por un modelo chico es peor que no
   responderlo.
2. Todo lo demás intenta B y, si no responde, cae a A.
3. Si no hay ningún motor, se devuelve None y quien llama responde con los datos
   armados en Python. El asistente nunca se queda mudo por esto.
4. El canal público **nunca** llega a C, y su uso de B está topado: si está
   ocupado, baja solo. Así un visitante no puede secuestrar la GPU.

La decisión es del sistema, no del modelo: aquí no se le pregunta a ninguna IA a
dónde mandar las cosas.
"""

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

import requests
from flask import current_app

NIVEL_A = 'A'
NIVEL_B = 'B'
NIVEL_C = 'C'

PERFIL_NORMAL = 'normal'
PERFIL_PROFUNDO = 'profundo'

CANAL_PANEL = 'panel'
CANAL_PUBLICO = 'publico'

# ── Reparto de carga por TAREA ────────────────────────────────
# El respaldo en la nube se cobra por token, así que no todas las tareas lo
# merecen. La regla es simple: **solo paga la que tiene a una persona
# esperando**. Lo demás espera a que el equipo del dueño vuelva.
#
#   chat_panel    el dueño está mirando la pantalla        → sí paga
#   chat_publico  un visitante, pero ya responde sin modelo → no paga
#   contenido     descripciones, SEO, nombres, etiquetas    → no paga, puede esperar
#   articulo      textos largos: los más caros de todos     → no paga nunca
#   resumen       corre de madrugada, sin nadie esperando   → no paga
#   profundo      exige el equipo por definición            → no paga
#
# Medido con el contador de tokens de la API: redactar una respuesta del sitio
# cuesta ~US$0,0008, mientras que un artículo de blog pasa de US$0,02. La
# diferencia entre pagar todo y pagar solo lo interactivo es de dos órdenes.
TAREAS_CON_NUBE = {'chat_panel', 'chat_publico'}
TAREA_POR_DEFECTO = 'chat_panel'

# Frases exactas con las que se pide el análisis profundo. Se comparan al inicio
# del mensaje, sin tildes y en minúsculas. Lista corta a propósito: esto lo
# decide el usuario, no una interpretación del modelo.
CLAVES_PROFUNDO = ('/profundo', 'analisis profundo', 'analiza a fondo',
                   'informe detallado', 'analisis detallado', 'estudio detallado')

_TTL_SALUD = 30           # s que se confía en el último chequeo
_salud = {}               # (BD, base_url) -> (instante, vivo)
_sondeos_local_fallidos = {}  # BD -> sondeos reales consecutivos sin respuesta
_semaforo_publico = None
_semaforo_lock = threading.Lock()
# Desde cuándo lleva caído el equipo del dueño. El respaldo que se cobra no entra
# de inmediato: primero se le da tiempo a que vuelva (un reinicio de Ollama o un
# corte de VPN no deben costar dinero).
_local_caido_desde = {}       # nombre de BD -> inicio de caída (solo este proceso)


def _reloj_clave():
    """La BD efectiva, también en el endpoint central multi-tenant de sync."""
    from database import _current_db_name
    return _current_db_name()

MSG_SIN_MOTOR = ('El redactor de IA no está disponible en este momento, así que te respondo '
                 'con los datos tal cual están.')
MSG_SIN_PROFUNDO = ('El análisis profundo corre en el equipo de IA y ahora está apagado. '
                    'Enciéndelo y vuelve a pedirlo, o pídemelo sin «a fondo» para una '
                    'respuesta normal.')
MSG_ESPERANDO_LOCAL = ('El equipo de IA no está respondiendo. Te contesto con los datos tal cual '
                       'mientras vuelve; si sigue apagado, en unos minutos entra el respaldo.')


@dataclass(frozen=True)
class Motor:
    nivel: str
    base_url: str
    modelo: str
    timeout: int
    etiqueta: str
    num_ctx: int = 0        # 0 = el que traiga el modelo
    proveedor: str = 'ollama'   # 'ollama' (una máquina propia) | 'nube' (API que se cobra)

    @property
    def es_nube(self):
        return self.proveedor == 'nube'

    @property
    def configurado(self):
        if self.proveedor == 'nube':
            return bool(self.modelo)
        return bool(self.base_url and self.modelo)


def _cfg(clave, defecto=''):
    """Ojo con el cero: `valor or defecto` convertía una espera de 0 segundos en
    los 180 por defecto, y el respaldo nunca entraba."""
    try:
        valor = current_app.config.get(clave)
        return defecto if valor in (None, '') else valor
    except Exception:
        return defecto


def motor_configurado(nivel):
    """El motor de un nivel según la configuración, sin mirar si está vivo."""
    if nivel == NIVEL_A:
        return Motor(NIVEL_A, str(_cfg('AI_MOTOR_A_BASE_URL')).rstrip('/'),
                     str(_cfg('AI_MOTOR_A_MODEL')),
                     int(_cfg('AI_MOTOR_A_TIMEOUT', 30) or 30), 'servidor')
    if nivel == NIVEL_B:
        return Motor(NIVEL_B, str(_cfg('AI_BASE_URL')).rstrip('/'), str(_cfg('AI_MODEL')),
                     int(_cfg('AI_TIMEOUT', 120) or 120), 'tu equipo de IA')
    if nivel == NIVEL_C:
        # El profundo vive en la misma máquina que B; cambia el modelo y el contexto.
        return Motor(NIVEL_C, str(_cfg('AI_BASE_URL')).rstrip('/'),
                     str(_cfg('AI_MOTOR_C_MODEL') or _cfg('AI_MODEL')),
                     int(_cfg('AI_MOTOR_C_TIMEOUT', 600) or 600), 'análisis profundo',
                     int(_cfg('AI_MOTOR_C_NUM_CTX', 0) or 0))
    return None


# ── Salud ──────────────────────────────────────────────────────
def _consultar_vivo(motor):
    """¿Responde el servidor de ese motor? Connect timeout corto: si la máquina
    está apagada tiene que fallar rápido, no dejar esperando al visitante."""
    if not motor.configurado:
        return False
    cabeceras = {}
    llave = str(_cfg('AI_API_KEY'))
    if llave:
        cabeceras['Authorization'] = f'Bearer {llave}'
    try:
        r = requests.get(f'{motor.base_url}/api/tags', headers=cabeceras, timeout=(2, 4))
        return r.status_code == 200
    except requests.RequestException:
        return False


def vivo(motor, refrescar=False):
    """Con caché corta: el chat pregunta esto en cada mensaje."""
    if not motor or not motor.configurado:
        return False
    ahora = time.time()
    clave_db = _reloj_clave()
    visto = _salud.get((clave_db, motor.base_url))
    if visto and not refrescar and ahora - visto[0] < _TTL_SALUD:
        return visto[1]
    estado = _consultar_vivo(motor)
    _salud[(clave_db, motor.base_url)] = (ahora, estado)
    if motor.nivel == NIVEL_B:
        _sondeos_local_fallidos[clave_db] = (
            0 if estado else _sondeos_local_fallidos.get(clave_db, 0) + 1)
    return estado


def modelo_cargado(motor):
    """True/False si el modelo ya está en memoria; None si no se puede saber.
    Sirve para avisar que la primera respuesta va a tardar, no para bloquear."""
    if not motor or not motor.configurado:
        return None
    try:
        r = requests.get(f'{motor.base_url}/api/ps', timeout=(2, 3))
        if r.status_code != 200:
            return None
        nombres = set()
        for m in (r.json() or {}).get('models', []):
            nombres.update({m.get('name'), m.get('model')})
        return motor.modelo in nombres or f'{motor.modelo}:latest' in nombres
    except Exception:
        return None


# ── Perfil pedido por el usuario ───────────────────────────────
def perfil_desde_texto(texto):
    """(perfil, texto_sin_la_marca). Reconoce solo las frases declaradas."""
    original = (texto or '').strip()
    from services.ia.enrutador import normalizar
    plano = normalizar(original).lstrip('¿ ')
    for clave in CLAVES_PROFUNDO:
        if plano.startswith(clave):
            limpio = original[len(original) - len(plano):] if len(plano) <= len(original) else original
            limpio = limpio[len(clave):].lstrip(' ,:;.-')
            return PERFIL_PROFUNDO, (limpio or original)
    return PERFIL_NORMAL, original


# ── Tope del canal público ─────────────────────────────────────
def _semaforo():
    global _semaforo_publico
    if _semaforo_publico is None:
        with _semaforo_lock:
            if _semaforo_publico is None:
                tope = max(1, int(_cfg('AI_PUBLIC_MAX_CONCURRENCIA', 1) or 1))
                _semaforo_publico = threading.BoundedSemaphore(tope)
    return _semaforo_publico


@contextmanager
def turno_publico():
    """Reserva un turno para generar en el canal público. Si no hay, devuelve
    False y quien llama responde con los datos armados en vez de hacer esperar."""
    sem = _semaforo()
    obtenido = sem.acquire(blocking=False)
    try:
        yield obtenido
    finally:
        if obtenido:
            try:
                sem.release()
            except ValueError:
                pass


# ── La decisión ────────────────────────────────────────────────
def motor_para(perfil=PERFIL_NORMAL, canal=CANAL_PANEL, tarea=TAREA_POR_DEFECTO):
    """(motor, motivo). motor=None significa responder sin redacción de IA."""
    if perfil == PERFIL_PROFUNDO and canal == CANAL_PUBLICO:
        perfil = PERFIL_NORMAL            # un visitante no dispara el profundo

    if perfil == PERFIL_PROFUNDO:
        c = motor_configurado(NIVEL_C)
        if vivo(c):
            return c, 'análisis profundo en tu equipo de IA'
        return None, MSG_SIN_PROFUNDO     # NO degrada: avisa

    b = motor_configurado(NIVEL_B)
    clave_reloj = _reloj_clave()
    if vivo(b):
        _local_caido_desde.pop(clave_reloj, None)  # volvió: se borra solo su reloj
        _sondeos_local_fallidos.pop(clave_reloj, None)
        return b, 'tu equipo de IA'

    # El equipo del dueño no responde. Se anota desde cuándo.
    if clave_reloj not in _local_caido_desde:
        _local_caido_desde[clave_reloj] = time.time()
    caido_hace = time.time() - _local_caido_desde[clave_reloj]

    a = motor_configurado(NIVEL_A)               # modelo propio en el servidor, si lo hubiera
    if vivo(a):
        return a, 'el modelo del servidor'

    return _respaldo_nube(canal, caido_hace, tarea)


def _respaldo_nube(canal, caido_hace, tarea=TAREA_POR_DEFECTO):
    """Último recurso, y solo si de verdad hace falta: cuesta dinero por token."""
    try:
        from services import ia_nube
    except Exception:
        return None, MSG_SIN_MOTOR
    if not ia_nube.configurada():
        return None, MSG_SIN_MOTOR
    if tarea not in TAREAS_CON_NUBE:
        # Nadie está esperando esta respuesta: que espere al equipo.
        return None, MSG_SIN_MOTOR

    # La espera cronológica por sí sola no prueba una caída continua: exigimos
    # además varios sondeos HTTP reales del PC, no varios mensajes atendidos
    # por la caché de salud de 30 segundos.
    minimo_sondeos = max(1, min(10, int(_cfg('AI_NUBE_FALLOS_LOCAL_MIN', 3))))
    if _sondeos_local_fallidos.get(_reloj_clave(), 0) < minimo_sondeos:
        return None, MSG_ESPERANDO_LOCAL

    espera = int(_cfg('AI_NUBE_ESPERA_LOCAL_S', 180))
    if caido_hace < espera:
        # Todavía no: se le da tiempo al equipo a volver.
        return None, MSG_ESPERANDO_LOCAL
    if not ia_nube.disponible(canal):
        return None, (ia_nube.motivo_bloqueo() or MSG_SIN_MOTOR)

    modelo = str(_cfg('AI_NUBE_MODEL', 'claude-haiku-4-5-20251001'))
    return (Motor(NIVEL_A, '', modelo, int(_cfg('AI_NUBE_TIMEOUT', 25) or 25),
                  'respaldo en la nube', proveedor='nube'),
            'el respaldo en la nube (se cobra por uso)')


def estado_motores():
    """Semáforo para el panel del dueño."""
    salida = {}
    for nivel, nombre in ((NIVEL_A, 'servidor'), (NIVEL_B, 'tu equipo'), (NIVEL_C, 'profundo')):
        m = motor_configurado(nivel)
        conf = bool(m and m.configurado)
        en_linea = vivo(m) if conf else False
        salida[nivel] = {
            'nombre': nombre,
            'configurado': conf,
            'en_linea': en_linea,
            'modelo': m.modelo if conf else None,
            'cargado': modelo_cargado(m) if en_linea else None,
        }
    disponible = any(v['en_linea'] for v in salida.values())
    salida['resumen'] = ('Hay redactor de IA disponible.' if disponible else
                         'Sin redactor de IA: las respuestas salen con los datos tal cual.')
    return salida
