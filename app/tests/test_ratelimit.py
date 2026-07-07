# -*- coding: utf-8 -*-
"""Test del rate limiting de login (B2). Usa una IP única por corrida para ser
determinista (el contador de esa IP expira solo en Redis)."""
import uuid


def test_login_rate_limit_dispara_429(flask_app):
    ip = '10.' + '.'.join(str(b) for b in uuid.uuid4().bytes[:3])
    c = flask_app.test_client()
    codes = []
    for _ in range(14):  # limite login = 10/min -> del 11 en adelante 429
        r = c.post('/login', data={'email': 'nadie@test.com', 'password': 'malo'},
                   environ_base={'REMOTE_ADDR': ip})
        codes.append(r.status_code)
    assert 429 in codes, f"esperaba un 429 tras >10 intentos, vi {codes}"


def test_get_login_no_se_limita(flask_app):
    ip = '10.' + '.'.join(str(b) for b in uuid.uuid4().bytes[:3])
    c = flask_app.test_client()
    for _ in range(15):
        r = c.get('/login', environ_base={'REMOTE_ADDR': ip})
        assert r.status_code != 429, "el GET de la pagina de login NO debe limitarse"
