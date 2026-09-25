# -*- coding: utf-8 -*-
"""Anti-bot del chat público: señuelo (honeypot) + verificación humana
(reCAPTCHA) por token firmado, sin sesión ni cookies. Confirmado explícitamente
que el chat interno (tras login) NO necesita ninguno de los dos — esta prueba
es exclusiva de routes/chat_publico.py.
"""

import pytest

from routes.chat_publico import _CAMPO_SENUELO, _emitir_token_verificacion


def _llaves(monkeypatch, flask_app, site, secret):
    monkeypatch.setitem(flask_app.config, 'RECAPTCHA_SITE_KEY', site)
    monkeypatch.setitem(flask_app.config, 'RECAPTCHA_SECRET_KEY', secret)


@pytest.fixture()
def sin_recaptcha(flask_app, monkeypatch):
    """La mayoría de instancias no tienen reCAPTCHA configurado: el chat debe
    seguir funcionando solo con señuelo + límite de tasa."""
    _llaves(monkeypatch, flask_app, '', '')


@pytest.fixture()
def con_recaptcha(flask_app, monkeypatch):
    _llaves(monkeypatch, flask_app, 'clave-publica-de-prueba', 'secreto-de-prueba')


def test_solo_la_llave_secreta_no_bloquea_el_chat(client, flask_app, monkeypatch, chat_encendido,
                                                   ip_unica, responder_falso):
    """Sin site key el widget no puede mostrar la verificación: exigirla dejaría
    el chat bloqueado. Con una sola llave, la verificación queda apagada."""
    _llaves(monkeypatch, flask_app, '', 'secreto-de-prueba')
    r = client.post('/chat/mensaje', json={'pregunta': 'hola'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 200
    cfg = client.get('/chat/config', environ_base={'REMOTE_ADDR': ip_unica()}).get_json()
    assert 'recaptcha_site_key' not in cfg


# ── Señuelo (honeypot): siempre activo, con o sin reCAPTCHA ─────
def test_senuelo_lleno_da_404_minimalista(client, chat_encendido, sin_recaptcha, ip_unica, responder_falso):
    r = client.post('/chat/mensaje', json={'pregunta': 'hola', _CAMPO_SENUELO: 'soy un bot'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 404
    assert r.get_json() == {'error': 'not_found'}


def test_senuelo_vacio_no_afecta_nada(client, chat_encendido, sin_recaptcha, ip_unica, responder_falso):
    r = client.post('/chat/mensaje', json={'pregunta': 'hola', _CAMPO_SENUELO: ''},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 200


def test_senuelo_ausente_no_afecta_nada(client, chat_encendido, sin_recaptcha, ip_unica, responder_falso):
    r = client.post('/chat/mensaje', json={'pregunta': 'hola'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 200


# ── Sin reCAPTCHA configurado: el chat funciona sin pedir nada extra ──
def test_sin_recaptcha_configurado_no_pide_verificacion(client, chat_encendido, sin_recaptcha, ip_unica, responder_falso):
    r = client.post('/chat/mensaje', json={'pregunta': 'hola'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 200
    assert 'verificacion' not in r.get_json()


# ── Con reCAPTCHA configurado ─────────────────────────────────
def test_con_recaptcha_sin_token_ni_respuesta_pide_verificacion(client, chat_encendido, con_recaptcha, ip_unica, responder_falso):
    r = client.post('/chat/mensaje', json={'pregunta': 'hola'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 400
    assert r.get_json()['error'] == 'verificacion_requerida'


def test_con_recaptcha_valido_pasa_y_devuelve_token_nuevo(client, chat_encendido, con_recaptcha, monkeypatch, ip_unica, responder_falso):
    llamadas = []

    class _Resp:
        def json(self):
            return {'success': True}

    def _post_falso(url, data=None, timeout=None):
        llamadas.append((url, data))
        return _Resp()

    monkeypatch.setattr('routes.chat_publico.requests.post', _post_falso)
    r = client.post('/chat/mensaje',
                    json={'pregunta': 'hola', 'recaptcha': 'token-de-google-valido'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 200
    datos = r.get_json()
    assert 'verificacion' in datos and datos['verificacion']
    assert len(llamadas) == 1
    assert llamadas[0][0] == 'https://www.google.com/recaptcha/api/siteverify'
    assert llamadas[0][1]['response'] == 'token-de-google-valido'


def test_con_recaptcha_invalido_sigue_pidiendo_verificacion(client, chat_encendido, con_recaptcha, monkeypatch, ip_unica, responder_falso):

    class _Resp:
        def json(self):
            return {'success': False}

    monkeypatch.setattr('routes.chat_publico.requests.post', lambda *a, **k: _Resp())
    r = client.post('/chat/mensaje', json={'pregunta': 'hola', 'recaptcha': 'token-malo'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 400
    assert r.get_json()['error'] == 'verificacion_requerida'


def test_con_token_de_verificacion_previo_no_llama_a_google_de_nuevo(client, chat_encendido, con_recaptcha, monkeypatch, ip_unica, responder_falso):
    llamadas = []
    monkeypatch.setattr('routes.chat_publico.requests.post', lambda *a, **k: llamadas.append(1))

    with client.application.test_request_context('/'):
        token = _emitir_token_verificacion()

    r = client.post('/chat/mensaje', json={'pregunta': 'hola', 'verificacion': token},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 200
    assert llamadas == [], 'con un token de verificacion ya valido, no debe volver a golpear a Google'
    assert 'verificacion' not in r.get_json(), 'no hace falta reemitir un token que ya era valido'


def test_token_de_verificacion_invalido_o_ajeno_no_sirve(client, chat_encendido, con_recaptcha, ip_unica, responder_falso):
    r = client.post('/chat/mensaje', json={'pregunta': 'hola', 'verificacion': 'esto-no-es-un-token-real'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 400
    assert r.get_json()['error'] == 'verificacion_requerida'


def test_token_firmado_con_otra_llave_no_sirve(client, chat_encendido, con_recaptcha, ip_unica, responder_falso):
    """Un token viejo/ajeno no debe colarse solo por tener forma de token."""
    from itsdangerous import URLSafeTimedSerializer
    otro = URLSafeTimedSerializer('otra-llave-distinta', salt='chat-publico-verificacion-humana')
    token_ajeno = otro.dumps({'ok': True})
    r = client.post('/chat/mensaje', json={'pregunta': 'hola', 'verificacion': token_ajeno},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 400
    assert r.get_json()['error'] == 'verificacion_requerida'


# ── /chat/config expone la site key SOLO si la verificación está activa ──
def test_config_expone_site_key_cuando_esta_configurada(client, chat_encendido, con_recaptcha, ip_unica):
    r = client.get('/chat/config', environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.get_json().get('recaptcha_site_key') == 'clave-publica-de-prueba'


def test_config_no_expone_site_key_cuando_no_esta(client, chat_encendido, sin_recaptcha, ip_unica):
    r = client.get('/chat/config', environ_base={'REMOTE_ADDR': ip_unica()})
    assert 'recaptcha_site_key' not in r.get_json()
