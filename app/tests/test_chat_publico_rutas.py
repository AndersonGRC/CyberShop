# -*- coding: utf-8 -*-
"""Pruebas HTTP de routes/chat_publico.py: las guardas de la capa API, antes
de que la pregunta llegue al motor. Qué responde el motor (y que la lista
blanca de datos se respete) ya está probado a fondo en
test_chat_publico_acceso.py — aquí lo que importa es que la ruta se comporte:
404 real con el módulo apagado (nunca la página 404.html con marca del
cliente), CSRF real, límite de tasa, payload defensivo, sin cookies nuevas,
y que nunca truene con un 500 aunque el motor falle.

Cada request a /chat/mensaje o /chat/config usa una IP única (mismo patrón
que test_ratelimit.py): el limitador de /chat/mensaje guarda sus contadores
por IP, y el test-client por defecto siempre pega desde 127.0.0.1 — sin IPs
distintas, los contadores se acumularían entre pruebas de este archivo y
harían fallar tests que no están probando el límite de tasa.
"""
import re

import pytest

from routes.chat_publico import _sanear_historial


@pytest.fixture()
def csrf_real(flask_app):
    """El resto de la suite corre con CSRF desactivado (conftest.py); solo
    aquí se prueba de verdad, y siempre se restaura al valor previo."""
    previo = flask_app.config['WTF_CSRF_ENABLED']
    flask_app.config['WTF_CSRF_ENABLED'] = True
    try:
        yield
    finally:
        flask_app.config['WTF_CSRF_ENABLED'] = previo


def _token_csrf_real(client, ip):
    """Replica lo que hace el widget: lee el <meta name="csrf-token"> de una
    página pública ya renderizada, con el mismo cliente/sesión que luego
    postea (igual que static/js/chat_publico.js hará en el navegador)."""
    html = client.get('/', environ_base={'REMOTE_ADDR': ip}).data.decode('utf-8')
    m = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
    assert m, 'la home no trae <meta name="csrf-token">; no se puede tomar un token real'
    return m.group(1)


# ── Módulo apagado: 404 minimalista, NUNCA la página 404.html con marca ──
def test_config_404_minimalista_con_modulo_apagado(client, chat_apagado, ip_unica):
    r = client.get('/chat/config', environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 404
    assert r.get_json() == {'error': 'not_found'}


def test_mensaje_404_minimalista_con_modulo_apagado(client, chat_apagado, ip_unica):
    r = client.post('/chat/mensaje', json={'pregunta': 'hola'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 404
    assert r.get_json() == {'error': 'not_found'}


# ── Módulo activo: /chat/config trae lo que el widget necesita ──
def test_config_200_con_modulo_activo(client, chat_encendido, ip_unica):
    r = client.get('/chat/config', environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 200
    datos = r.get_json()
    for campo in ('negocio', 'saludo', 'sugerencias', 'whatsapp', 'tono', 'v'):
        assert campo in datos


def test_config_trae_la_version_del_widget(client, chat_encendido, ip_unica):
    """El ?v= con que layout.js pide el CSS y el JS: cambia cuando cambia
    cualquiera de los dos, así Cloudflare nunca sirve un widget viejo."""
    import os
    from routes.chat_publico import _ARCHIVOS_WIDGET
    carpeta = client.application.static_folder
    esperado = str(int(max(os.path.getmtime(os.path.join(carpeta, ruta))
                           for ruta in _ARCHIVOS_WIDGET)))
    r = client.get('/chat/config', environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.get_json()['v'] == esperado


# ── Payload defensivo de /chat/mensaje ──
def test_mensaje_400_si_el_cuerpo_no_es_json(client, chat_encendido, ip_unica):
    r = client.post('/chat/mensaje', data=b'esto no es json',
                    content_type='application/json',
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 400
    assert r.get_json()['error'] == 'invalid_payload'


@pytest.mark.parametrize('payload', [
    {},
    {'pregunta': 123},
    {'pregunta': '   '},
    {'pregunta': None},
])
def test_mensaje_400_con_pregunta_invalida(client, chat_encendido, payload, ip_unica):
    r = client.post('/chat/mensaje', json=payload, environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 400
    assert r.get_json()['error'] == 'invalid_payload'


# ── Saneo del historial (unitario, sin pasar por HTTP) ──
def test_sanear_historial_recorta_a_8_items():
    bruto = [{'rol': 'usuario', 'texto': 'hola'}] * 20
    limpio = _sanear_historial(bruto)
    assert len(limpio) == 8


def test_sanear_historial_descarta_roles_invalidos():
    bruto = [{'rol': 'sistema', 'texto': 'no valido'}, {'rol': 'usuario', 'texto': 'hola'}]
    assert _sanear_historial(bruto) == [{'rol': 'usuario', 'texto': 'hola'}]


def test_sanear_historial_si_no_es_lista_devuelve_none():
    assert _sanear_historial('no es una lista') is None
    assert _sanear_historial(None) is None
    assert _sanear_historial([]) is None


def test_mensaje_no_falla_si_el_historial_viene_raro(client, chat_encendido, ip_unica, responder_falso):
    r = client.post('/chat/mensaje',
                    json={'pregunta': 'hola', 'historial': 'no es una lista'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 200


# ── Nunca 500, incluso si el motor explota ──
def test_mensaje_nunca_da_500_si_el_motor_falla(client, chat_encendido, monkeypatch, ip_unica):
    def _explota(pregunta, historial=None):
        raise RuntimeError('boom')
    monkeypatch.setattr('routes.chat_publico.responder', _explota)
    r = client.post('/chat/mensaje', json={'pregunta': 'hola'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 200
    datos = r.get_json()
    assert datos['via'] == 'error'
    assert datos['fuentes'] == []


# ── CSRF real: el resto de la suite lo desactiva a propósito (conftest.py) ──
def test_mensaje_sin_csrf_real_se_rechaza(client, chat_encendido, csrf_real, ip_unica):
    ip = ip_unica()
    _token_csrf_real(client, ip)  # arranca sesión real; el token no se usa
    r = client.post('/chat/mensaje', json={'pregunta': 'hola'},
                    environ_base={'REMOTE_ADDR': ip})
    assert r.status_code == 400
    datos = r.get_json()
    assert datos.get('success') is False
    assert 'CSRF' in datos.get('error', '')


def test_mensaje_con_csrf_real_pasa_la_guarda(client, chat_encendido, csrf_real, ip_unica, responder_falso):
    ip = ip_unica()
    token = _token_csrf_real(client, ip)
    r = client.post('/chat/mensaje', json={'pregunta': 'hola'},
                    headers={'X-CSRFToken': token},
                    environ_base={'REMOTE_ADDR': ip})
    assert r.status_code == 200
    assert r.get_json()['via'] == 'test'


# ── Límite de tasa real de /chat/mensaje ──
# Depende de que RATELIMIT_STORAGE_URI resuelva a un Redis realmente
# alcanzable (ver .cybershop.conf) — la misma dependencia que ya tiene
# test_ratelimit.py::test_login_rate_limit_dispara_429. Sin Redis local,
# RATELIMIT_SWALLOW_ERRORS=True dejar pasar todo (fail-open) y este test
# falla igual que el del login; no es un defecto de esta ruta.
def test_mensaje_rate_limit_dispara_429(client, chat_encendido, ip_unica, responder_falso):
    ip = ip_unica()
    codes = []
    for _ in range(12):  # limite = 8/min -> del 9 en adelante 429
        r = client.post('/chat/mensaje', json={'pregunta': 'hola'},
                        environ_base={'REMOTE_ADDR': ip})
        codes.append(r.status_code)
    assert 429 in codes, f'esperaba un 429 tras >8 intentos, vi {codes}'


# ── Sin sesión propia del chat: la única cookie es la sliding-session
# genérica que YA pone app.py en TODAS las rutas del sitio (before_request,
# session.permanent=True — ver memoria "Sesión web 5h deslizante"). Lo que
# importa no es "cero cookies" (eso lo rompería cualquier página pública),
# sino que el chat no le agrega nada propio encima de esa cookie sitewide.
def _payload_sesion(resp):
    set_cookie = next((h for h in resp.headers.getlist('Set-Cookie') if h.startswith('session=')), None)
    assert set_cookie, 'se esperaba la cookie de sesión deslizante que pone app.py en cada request'
    valor = set_cookie.split(';', 1)[0].split('=', 1)[1]
    payload_b64 = valor.split('.')[0]
    payload_b64 += '=' * (-len(payload_b64) % 4)
    import base64
    import json
    return json.loads(base64.urlsafe_b64decode(payload_b64))


def test_config_no_agrega_datos_de_sesion_propios(client, chat_encendido, ip_unica):
    r = client.get('/chat/config', environ_base={'REMOTE_ADDR': ip_unica()})
    assert _payload_sesion(r) == {'_permanent': True}


def test_mensaje_no_agrega_datos_de_sesion_propios(client, chat_encendido, ip_unica, responder_falso):
    r = client.post('/chat/mensaje', json={'pregunta': 'hola'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert _payload_sesion(r) == {'_permanent': True}
