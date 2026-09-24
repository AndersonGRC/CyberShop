"""Respaldo en la nube (Anthropic) para cuando el equipo de IA está apagado.

Es el ÚLTIMO recurso, a propósito, y con tres frenos:

  1. **Tiempo**: no entra apenas el equipo deja de responder. Solo después de
     `AI_NUBE_ESPERA_LOCAL_S` (3 minutos por defecto) de caída continua. Un
     reinicio de Ollama o un corte de VPN no debe costar dinero.
  2. **Presupuesto**: un tope mensual en dólares. Al llegar, se apaga sola y
     el sistema sigue respondiendo con los datos armados en Python.
  3. **Alcance**: por defecto NO atiende al chat del sitio público. Ese chat ya
     responde bien sin modelo, y dejarlo abierto a internet con una API que se
     cobra por token es la forma más rápida de gastar sin darse cuenta.

Cada llamada queda contada (tokens y costo estimado) en `ia_uso_nube`, y la
primera de cada mes dispara un correo avisando que empezó el cobro.

La clave vive en `.cybershop.conf` del servidor (fuera de git). Nunca en código.
"""

import time
from datetime import date

import requests
from flask import current_app

from database import get_db_cursor
from services.ia_datos.base import _existe

API_URL = 'https://api.anthropic.com/v1/messages'
VERSION_API = '2023-06-01'

# Errores por los que NO tiene sentido reintentar en un rato largo: falta saldo,
# clave mala o cuenta bloqueada. Se guarda el motivo y se deja de llamar.
_PAUSA_TRAS_FALLO_S = 1800          # 30 min
_bloqueo = {'hasta': 0, 'motivo': None}

_DDL_USO = """
CREATE TABLE IF NOT EXISTS ia_uso_nube (
    periodo         VARCHAR(7) PRIMARY KEY,
    llamadas        INTEGER NOT NULL DEFAULT 0,
    tokens_entrada  BIGINT  NOT NULL DEFAULT 0,
    tokens_salida   BIGINT  NOT NULL DEFAULT 0,
    costo_usd       NUMERIC(10,4) NOT NULL DEFAULT 0,
    aviso_enviado   BOOLEAN NOT NULL DEFAULT FALSE,
    actualizado_en  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _cfg(clave, defecto=None):
    try:
        v = current_app.config.get(clave)
        return defecto if v in (None, '') else v
    except Exception:
        return defecto


def _periodo():
    hoy = date.today()
    return f'{hoy.year:04d}-{hoy.month:02d}'


def configurada():
    return bool(str(_cfg('AI_NUBE_API_KEY', '')).strip())


# ── Contabilidad del gasto ─────────────────────────────────────
def uso_del_mes():
    """{llamadas, tokens, costo_usd, tope_usd, restante_usd, aviso_enviado}."""
    tope = float(_cfg('AI_NUBE_PRESUPUESTO_USD', 5) or 0)
    base = {'periodo': _periodo(), 'llamadas': 0, 'tokens_entrada': 0, 'tokens_salida': 0,
            'costo_usd': 0.0, 'tope_usd': tope, 'restante_usd': tope, 'aviso_enviado': False}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if not _existe(cur, 'ia_uso_nube'):
                return base
            cur.execute('SELECT * FROM ia_uso_nube WHERE periodo = %s', (_periodo(),))
            r = cur.fetchone()
            if not r:
                return base
            base.update(llamadas=int(r['llamadas']), tokens_entrada=int(r['tokens_entrada']),
                        tokens_salida=int(r['tokens_salida']), costo_usd=float(r['costo_usd']),
                        aviso_enviado=bool(r['aviso_enviado']))
            base['restante_usd'] = round(max(0.0, tope - base['costo_usd']), 4)
    except Exception:
        pass
    return base


def _costo(entrada, salida):
    """Costo estimado en dólares. Los precios son configurables porque cambian:
    revisar la página de precios de Anthropic y ajustar si hace falta."""
    p_in = float(_cfg('AI_NUBE_PRECIO_ENTRADA_USD_MTOK', 1.0))
    p_out = float(_cfg('AI_NUBE_PRECIO_SALIDA_USD_MTOK', 5.0))
    return round((entrada / 1_000_000) * p_in + (salida / 1_000_000) * p_out, 6)


def _sumar_uso(entrada, salida):
    costo = _costo(entrada, salida)
    primera_del_mes = False
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(_DDL_USO)
            cur.execute("""
                INSERT INTO ia_uso_nube (periodo, llamadas, tokens_entrada, tokens_salida, costo_usd)
                VALUES (%s, 1, %s, %s, %s)
                ON CONFLICT (periodo) DO UPDATE SET
                    llamadas = ia_uso_nube.llamadas + 1,
                    tokens_entrada = ia_uso_nube.tokens_entrada + EXCLUDED.tokens_entrada,
                    tokens_salida = ia_uso_nube.tokens_salida + EXCLUDED.tokens_salida,
                    costo_usd = ia_uso_nube.costo_usd + EXCLUDED.costo_usd,
                    actualizado_en = NOW()
                RETURNING llamadas, costo_usd, aviso_enviado
            """, (_periodo(), entrada, salida, costo))
            r = cur.fetchone()
            primera_del_mes = bool(r and int(r['llamadas']) == 1 and not r['aviso_enviado'])
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'IA nube: no se pudo contar el uso ({exc})')
    if primera_del_mes:
        _avisar_cobro_iniciado()
    return costo


def hay_presupuesto():
    tope = float(_cfg('AI_NUBE_PRESUPUESTO_USD', 5) or 0)
    if tope <= 0:
        return False
    return uso_del_mes()['costo_usd'] < tope


# ── Aviso por correo ───────────────────────────────────────────
def _avisar_cobro_iniciado():
    """Un correo, una vez por mes: desde aquí el uso de la nube cuesta dinero."""
    try:
        from services.ia_resumen_correo import _destinatarios, leer_config
        destinos = _destinatarios(leer_config())
    except Exception:
        destinos = []
    if not destinos:
        return
    uso = uso_del_mes()
    negocio = 'tu negocio'
    try:
        from services.public_site_service import get_brand_config
        negocio = (get_brand_config() or {}).get('empresa_nombre') or negocio
    except Exception:
        pass
    asunto = f'Aviso: el asistente de {negocio} empezó a usar la IA en la nube'
    texto = (
        f"El equipo de IA no respondió durante varios minutos, así que el asistente pasó al "
        f"respaldo en la nube para no dejar de atender.\n\n"
        f"Desde este momento el uso se cobra por token.\n\n"
        f"  Tope de este mes: US$ {uso['tope_usd']:.2f}\n"
        f"  Gastado hasta ahora: US$ {uso['costo_usd']:.4f}\n\n"
        f"Si enciendes el equipo de IA, el asistente vuelve solo a usarlo y el cobro se detiene.\n"
        f"Al llegar al tope, el respaldo se apaga y el asistente sigue respondiendo con los "
        f"datos del negocio, sin redacción de IA.")
    try:
        from helpers_gmail import enviar_email_gmail
        for correo in destinos[:3]:
            enviar_email_gmail(correo, asunto, texto)
        with get_db_cursor() as cur:
            cur.execute('UPDATE ia_uso_nube SET aviso_enviado = TRUE WHERE periodo = %s',
                        (_periodo(),))
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning(f'IA nube: no se pudo avisar del cobro ({exc})')


# ── Disponibilidad y llamada ───────────────────────────────────
def _bloqueada():
    return _bloqueo['hasta'] > time.time()


def motivo_bloqueo():
    return _bloqueo['motivo'] if _bloqueada() else None


def _bloquear(motivo):
    _bloqueo['hasta'] = time.time() + _PAUSA_TRAS_FALLO_S
    _bloqueo['motivo'] = motivo
    try:
        current_app.logger.warning(f'IA nube: pausada 30 min — {motivo}')
    except Exception:
        pass


def disponible(canal='panel'):
    """¿Se puede usar el respaldo AHORA? No mira si el equipo local está caído:
    de eso se encarga el selector de motores."""
    if not configurada() or _bloqueada():
        return False
    if canal == 'publico' and not bool(_cfg('AI_NUBE_PARA_PUBLICO', False)):
        return False
    return hay_presupuesto()


def responder(sistema, usuario, max_tokens=None, temperature=0.4, timeout=25):
    """(texto, None) o (None, motivo). Nunca lanza."""
    if not configurada():
        return None, 'El respaldo en la nube no está configurado.'
    if _bloqueada():
        return None, _bloqueo['motivo']
    if not hay_presupuesto():
        return None, ('Se alcanzó el tope de gasto de IA de este mes. El asistente sigue '
                      'respondiendo con los datos del negocio.')

    modelo = str(_cfg('AI_NUBE_MODEL', 'claude-haiku-4-5-20251001'))
    tope_tokens = int(max_tokens or _cfg('AI_NUBE_MAX_TOKENS', 300))
    try:
        r = requests.post(
            API_URL,
            headers={'x-api-key': str(_cfg('AI_NUBE_API_KEY', '')),
                     'anthropic-version': VERSION_API, 'content-type': 'application/json'},
            json={'model': modelo, 'max_tokens': tope_tokens, 'temperature': temperature,
                  'system': sistema, 'messages': [{'role': 'user', 'content': usuario}]},
            timeout=(5, timeout))
    except requests.RequestException as exc:
        return None, f'No se pudo alcanzar el respaldo en la nube ({type(exc).__name__}).'

    if r.status_code == 200:
        d = r.json()
        uso = d.get('usage') or {}
        _sumar_uso(int(uso.get('input_tokens') or 0), int(uso.get('output_tokens') or 0))
        texto = ' '.join(b.get('text', '') for b in d.get('content', []) if b.get('type') == 'text')
        return (texto.strip() or None), (None if texto.strip() else 'La nube respondió vacío.')

    detalle = ''
    try:
        detalle = ((r.json() or {}).get('error') or {}).get('message', '')[:200]
    except Exception:
        detalle = r.text[:200]

    # Sin saldo o clave inválida: no sirve reintentar en cada mensaje.
    if r.status_code in (400, 401, 403) and ('credit' in detalle.lower()
                                             or 'balance' in detalle.lower()
                                             or r.status_code in (401, 403)):
        _bloquear('El respaldo en la nube no está disponible: revisa el saldo o la clave '
                  f'de la API ({detalle}).')
        return None, _bloqueo['motivo']
    if r.status_code == 429:
        _bloquear('El respaldo en la nube está saturado; se reintenta más tarde.')
        return None, _bloqueo['motivo']
    return None, f'El respaldo en la nube respondió {r.status_code}.'


def estado():
    """Para el panel: configurada, disponible, gasto del mes y por qué no se usa."""
    uso = uso_del_mes()
    return {
        'configurada': configurada(),
        'disponible': disponible(),
        'bloqueo': motivo_bloqueo(),
        'modelo': str(_cfg('AI_NUBE_MODEL', 'claude-haiku-4-5-20251001')),
        'para_publico': bool(_cfg('AI_NUBE_PARA_PUBLICO', False)),
        'espera_local_s': int(_cfg('AI_NUBE_ESPERA_LOCAL_S', 180)),
        **uso,
    }
