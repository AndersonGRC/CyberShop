"""
Meta Conversions API (CAPI) — envío server-to-server de eventos a Facebook.

Complementa al Pixel del browser: lo que el pixel pierde (ad blockers,
iOS 14+ tracking limits, browser privacy) lo recupera CAPI desde el server.

La deduplicación se hace con event_id: el pixel y CAPI envían el mismo
event_id para el mismo evento, Meta elimina duplicados automáticamente.

Uso típico:
    from services.meta_capi import send_event_async, build_user_data
    send_event_async(
        event_name='Purchase',
        event_id=str(uuid.uuid4()),
        user_data=build_user_data(request, email=user_email, phone=user_phone),
        custom_data={'currency': 'COP', 'value': 150000.0,
                     'content_ids': ['SKU-123'], 'content_type': 'product'},
        event_source_url=request.url,
    )

Docs Meta:
    https://developers.facebook.com/docs/marketing-api/conversions-api
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests
from flask import current_app

from config import Config


GRAPH_API_VERSION = 'v18.0'

# Campos de user_data que Meta exige hashear con SHA-256 (lowercase, trim).
# Los demás campos (client_ip_address, client_user_agent, fbp, fbc) van en claro.
_HASH_FIELDS = {
    'em', 'ph', 'fn', 'ln', 'ge', 'db',
    'ct', 'st', 'zp', 'country', 'external_id',
}


def is_enabled() -> bool:
    """True si CAPI está configurado y debe enviar eventos."""
    return bool(Config.META_CAPI_ACCESS_TOKEN and Config.META_PIXEL_ID)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode('utf-8')).hexdigest()


def _hash_user_data(data: dict[str, Any]) -> dict[str, Any]:
    """Hashea PII según especificación de Meta. No modifica el dict original."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        if v is None or v == '':
            continue
        if k in _HASH_FIELDS:
            # Algunos campos pueden ser lista (ej. múltiples emails)
            if isinstance(v, list):
                out[k] = [_sha256_hex(str(item)) for item in v if item]
            else:
                out[k] = _sha256_hex(str(v))
        else:
            out[k] = v
    return out


def build_user_data(req, *, email: str | None = None, phone: str | None = None,
                    first_name: str | None = None, last_name: str | None = None,
                    external_id: str | None = None) -> dict[str, Any]:
    """Construye user_data combinando datos de la request + datos conocidos.

    Toma del request: IP, user-agent, cookies _fbp y _fbc (puestas por el pixel).
    Acepta PII opcional (email, phone, etc.) que se hashea automáticamente.
    """
    ip = req.headers.get('X-Forwarded-For', req.remote_addr or '')
    ip = ip.split(',')[0].strip() if ip else None

    return {
        'em': email,
        'ph': phone,
        'fn': first_name,
        'ln': last_name,
        'external_id': external_id,
        'client_ip_address': ip,
        'client_user_agent': req.headers.get('User-Agent'),
        'fbp': req.cookies.get('_fbp'),
        'fbc': req.cookies.get('_fbc'),
    }


def _build_payload(*, event_name: str, event_id: str,
                   user_data: dict, custom_data: dict | None,
                   event_source_url: str | None,
                   action_source: str) -> dict:
    event: dict[str, Any] = {
        'event_name':    event_name,
        'event_time':    int(time.time()),
        'event_id':      event_id,
        'action_source': action_source,
        'user_data':     _hash_user_data(user_data or {}),
    }
    if event_source_url:
        event['event_source_url'] = event_source_url
    if custom_data:
        event['custom_data'] = custom_data

    payload: dict[str, Any] = {
        'data': [event],
        'access_token': Config.META_CAPI_ACCESS_TOKEN,
    }
    if Config.META_CAPI_TEST_EVENT_CODE:
        payload['test_event_code'] = Config.META_CAPI_TEST_EVENT_CODE
    return payload


def _send_sync(payload: dict, logger):
    """Envía un evento sincrónicamente. Usar via send_event_async para no bloquear."""
    url = f'https://graph.facebook.com/{GRAPH_API_VERSION}/{Config.META_PIXEL_ID}/events'
    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code >= 400:
            logger.warning(f"CAPI {resp.status_code}: {resp.text[:300]}")
        else:
            logger.info(
                f"CAPI sent {payload['data'][0]['event_name']} "
                f"id={payload['data'][0]['event_id'][:8]}…"
            )
    except requests.RequestException as exc:
        logger.warning(f"CAPI request failed: {exc}")


def send_event_async(event_name: str, event_id: str, user_data: dict,
                     custom_data: dict | None = None,
                     event_source_url: str | None = None,
                     action_source: str = 'website'):
    """Envía un evento a Meta CAPI sin bloquear el request actual.

    No falla nunca: si CAPI no está configurado o Meta responde mal,
    se loguea pero NO se levanta excepción al caller. CAPI nunca debe
    romper el flujo de checkout/navegación del cliente.
    """
    if not is_enabled():
        return

    payload = _build_payload(
        event_name=event_name, event_id=event_id,
        user_data=user_data, custom_data=custom_data,
        event_source_url=event_source_url, action_source=action_source,
    )
    # Capturamos el logger ANTES del thread (current_app no funciona fuera del request).
    logger = current_app.logger
    threading.Thread(
        target=_send_sync, args=(payload, logger), daemon=True
    ).start()


def should_track_pageview(req) -> bool:
    """Filtro para decidir si una request es candidata a PageView CAPI.

    Excluye: admin, api, assets, AJAX, métodos no-GET, healthchecks.
    """
    if req.method != 'GET':
        return False
    path = req.path or ''
    if path.startswith(('/admin', '/api', '/static', '/.well-known', '/favicon')):
        return False
    if req.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return False
    accept = req.headers.get('Accept', '')
    if 'text/html' not in accept and accept != '*/*' and accept != '':
        return False
    return True
