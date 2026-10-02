# -*- coding: utf-8 -*-
"""Recuperar la contraseña por correo y vista previa de tiendas nuevas.

Contra la base de pruebas: el usuario creado se borra al final."""
import uuid

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import app as app_mod
from services import recuperar_clave_service as rc

MARCA = uuid.uuid4().hex[:6]
EMAIL = f'pytest-clave-{MARCA}@ejemplo.com'


@pytest.fixture()
def usuario(cursor):
    with cursor() as cur:
        cur.execute('INSERT INTO usuarios (nombre, email, "contraseña", rol_id) '
                    'VALUES (%s, %s, %s, 2) RETURNING id',
                    ('Pytest Clave', EMAIL, generate_password_hash('vieja-clave-123')))
        uid = cur.fetchone()['id']
    yield uid
    with cursor() as cur:
        cur.execute('DELETE FROM usuarios WHERE id = %s', (uid,))


@pytest.fixture()
def correos(monkeypatch):
    enviados = []
    monkeypatch.setattr(rc, 'enviar_correo', lambda u, url, negocio: enviados.append((u['email'], url)) or True)
    return enviados


def _hash(cursor, uid):
    with cursor() as cur:
        cur.execute('SELECT "contraseña" AS h FROM usuarios WHERE id = %s', (uid,))
        return cur.fetchone()['h']


def test_login_tiene_enlace_para_recuperar(client):
    assert '/recuperar-contrasena' in client.get('/login').get_data(as_text=True)


def test_respuesta_igual_exista_o_no_el_correo(client, usuario, correos):
    r1 = client.post('/recuperar-contrasena', data={'email': EMAIL.upper()}, follow_redirects=True)
    r2 = client.post('/recuperar-contrasena', data={'email': f'nadie-{MARCA}@ejemplo.com'}, follow_redirects=True)
    assert r1.status_code == r2.status_code == 200
    assert 'Si ese correo tiene una cuenta' in r1.get_data(as_text=True)
    assert 'Si ese correo tiene una cuenta' in r2.get_data(as_text=True)
    assert len(correos) == 1 and correos[0][0] == EMAIL


def test_enlace_cambia_la_clave_y_sirve_una_sola_vez(client, cursor, usuario, correos, flask_app):
    client.post('/recuperar-contrasena', data={'email': EMAIL})
    ruta = '/' + correos[0][1].split('/', 3)[3]
    assert client.get(ruta).status_code == 200

    malo = client.post(ruta, data={'password': 'corta', 'confirmacion': 'corta'})
    assert malo.status_code == 200 and check_password_hash(_hash(cursor, usuario), 'vieja-clave-123')

    ok = client.post(ruta, data={'password': 'nueva-clave-456', 'confirmacion': 'nueva-clave-456'})
    assert ok.status_code == 302 and '/login' in ok.headers['Location']
    assert check_password_hash(_hash(cursor, usuario), 'nueva-clave-456')

    otra_vez = client.get(ruta)
    assert otra_vez.status_code == 302 and 'recuperar-contrasena' in otra_vez.headers['Location']


def test_enlace_alterado_o_vencido_no_sirve(flask_app, usuario, monkeypatch):
    with flask_app.app_context():
        u = rc.usuario_por_email(EMAIL)
        token = rc.crear_token(u)
        assert rc.usuario_del_token(token)['id'] == usuario
        assert rc.usuario_del_token(token + 'x') is None
        monkeypatch.setattr(rc, 'VIGENCIA_S', -1)
        assert rc.usuario_del_token(token) is None


def test_next_solo_acepta_rutas_internas(client):
    for malo in ('https://otro.com', '//otro.com', '/\\otro.com'):
        client.get('/login', query_string={'next': malo})
        with client.session_transaction() as s:
            assert 'login_next' not in s
    client.get('/login', query_string={'next': '/admin/mi-negocio'})
    with client.session_transaction() as s:
        assert s['login_next'] == '/admin/mi-negocio'


@pytest.fixture()
def modo_demo(monkeypatch):
    """Simula una tienda nueva sin escribir en la BD."""
    monkeypatch.setitem(app_mod._DEMO_CACHE, 'ts', 0)
    monkeypatch.setattr('services.marca_service.es_autoservicio', lambda: True)
    yield
    app_mod._DEMO_CACHE['ts'] = 0


def test_tienda_nueva_muestra_imagenes_de_muestra(client, modo_demo, monkeypatch):
    import services.public_site_service as pss
    if hasattr(pss, 'get_slides'):
        monkeypatch.setattr(pss, 'get_slides', lambda *a, **k: [])
    html = client.get('/').get_data(as_text=True)
    assert 'demo_placeholders.js' in html and 'demo-barra' in html
    assert 'Iniciar sesión y personalizar' in html

    serv = client.get('/servicios').get_data(as_text=True)
    assert 'data-demo-img' in serv


def test_tienda_normal_no_carga_la_vista_previa(client, monkeypatch):
    monkeypatch.setitem(app_mod._DEMO_CACHE, 'ts', 0)
    monkeypatch.setattr('services.marca_service.es_autoservicio', lambda: False)
    html = client.get('/').get_data(as_text=True)
    app_mod._DEMO_CACHE['ts'] = 0
    assert 'demo_placeholders.js' not in html and 'demo-barra' not in html
