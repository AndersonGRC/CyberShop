# -*- coding: utf-8 -*-
"""La tienda y el panel se instalan como una app (PWA, 1.9.20.0).

Qué se cuida: cada tienda sale con SU nombre/color/logo, el service worker no guarda
nada del negocio (solo el aviso de «sin conexión»), nada queda detrás del inicio de
sesión, se puede apagar por tienda y una tienda con el código anterior no se rompe.
"""
import io
import json

import pytest
from PIL import Image

from services import pwa


@pytest.fixture(autouse=True)
def _iconos_limpios():
    pwa._iconos.clear()
    yield
    pwa._iconos.clear()


def _marca(monkeypatch, **valores):
    base = {'empresa_nombre': 'Panadería Nicol', 'color_primario': '#8a4b12',
            'empresa_tagline': 'Pan caliente todo el día', 'empresa_logo_url': ''}
    base.update(valores)
    monkeypatch.setattr(pwa, '_marca', lambda: dict(base))
    return base


def _logo(tmp_path, monkeypatch, flask_app, color=(200, 30, 30, 255), tamano=(300, 120)):
    """Un logo propio en la carpeta de la tienda (como los que sube el dueño)."""
    carpeta = tmp_path / 'static' / 'media' / 'public_site'
    carpeta.mkdir(parents=True)
    lienzo = Image.new('RGBA', (tamano[0] + 80, tamano[1] + 80), (0, 0, 0, 0))
    lienzo.paste(Image.new('RGBA', tamano, color), (40, 40))
    lienzo.save(carpeta / 'logo_publico_prueba.png')
    monkeypatch.setitem(flask_app.config, 'INSTANCE_OVERRIDES_DIR', str(tmp_path))
    return '/static/media/public_site/logo_publico_prueba.png'


def _png(respuesta):
    return Image.open(io.BytesIO(respuesta.data))


# ── Manifiestos ─────────────────────────────────────────────────────────────

def test_manifiesto_de_la_tienda_usa_su_nombre_y_su_color(client, monkeypatch):
    _marca(monkeypatch)
    r = client.get('/manifest.webmanifest')
    assert r.status_code == 200
    assert r.mimetype == 'application/manifest+json'
    assert 'no-store' in r.headers['Cache-Control']
    m = json.loads(r.data.decode('utf-8'))
    assert m['name'] == 'Panadería Nicol'
    assert m['short_name'] == 'Panadería'
    assert m['description'] == 'Pan caliente todo el día'
    assert m['theme_color'] == '#8a4b12'
    assert (m['id'], m['start_url'], m['scope'], m['display']) == ('/', '/', '/', 'standalone')


def test_manifiesto_del_panel_es_otra_app_con_la_paleta_del_panel(client, monkeypatch):
    _marca(monkeypatch)
    m = json.loads(client.get('/manifest-panel.webmanifest').data.decode('utf-8'))
    assert m['name'] == 'Panel Panadería Nicol'
    assert m['short_name'] == 'Panel Panadería'
    assert m['theme_color'] == '#122C94'
    assert m['id'] == '/pwa/panel' and m['start_url'] == '/pwa/panel'
    tienda = json.loads(client.get('/manifest.webmanifest').data.decode('utf-8'))
    assert m['id'] != tienda['id']


def test_los_iconos_del_manifiesto_existen_y_miden_lo_que_dicen(client, monkeypatch):
    _marca(monkeypatch)
    m = json.loads(client.get('/manifest.webmanifest').data.decode('utf-8'))
    assert {i['purpose'] for i in m['icons']} == {'any', 'maskable'}
    assert {i['sizes'] for i in m['icons']} == {'192x192', '512x512'}
    for icono in m['icons']:
        r = client.get(icono['src'])
        assert r.status_code == 200 and r.mimetype == 'image/png'
        lado = int(icono['sizes'].split('x')[0])
        assert _png(r).size == (lado, lado)


def test_color_raro_o_nombre_vacio_no_rompen_el_manifiesto(client, monkeypatch):
    _marca(monkeypatch, empresa_nombre='  ', color_primario='rojo"; }', empresa_tagline='')
    m = json.loads(client.get('/manifest.webmanifest').data.decode('utf-8'))
    assert m['name'] == 'Mi tienda'
    assert m['theme_color'] == '#122C94'
    assert m['description'] == 'Tienda en línea de Mi tienda.'


def test_nombre_corto():
    assert pwa.nombre_corto('CyberShop') == 'CyberShop'
    assert pwa.nombre_corto('Panadería Nicol de la Esquina') == 'Panadería'
    assert pwa.nombre_corto('Supercalifragilístico') == 'Supercalifra'
    assert pwa.nombre_corto('') == ''


# ── Íconos ──────────────────────────────────────────────────────────────────

def test_icono_con_el_logo_de_la_tienda(client, monkeypatch, tmp_path, flask_app):
    url = _logo(tmp_path, monkeypatch, flask_app)
    _marca(monkeypatch, empresa_logo_url=url)
    normal = _png(client.get('/pwa/icono-512.png')).convert('RGB')
    assert normal.size == (512, 512)
    assert normal.getpixel((4, 4)) == (255, 255, 255)            # fondo blanco, sin transparencia
    assert normal.getpixel((256, 256)) == (200, 30, 30)          # el logo, al centro
    # «maskable»: el logo más pequeño, dentro de la zona que el sistema no recorta
    mask = _png(client.get('/pwa/icono-maskable-512.png')).convert('RGB')
    assert mask.getpixel((256, 256)) == (200, 30, 30)
    assert mask.getpixel((80, 256)) == (255, 255, 255)
    assert normal.getpixel((80, 256)) == (200, 30, 30)


def test_logo_claro_va_sobre_el_color_de_la_tienda(client, monkeypatch, tmp_path, flask_app):
    url = _logo(tmp_path, monkeypatch, flask_app, color=(255, 255, 255, 255))
    _marca(monkeypatch, empresa_logo_url=url)
    icono = _png(client.get('/pwa/icono-192.png')).convert('RGB')
    assert icono.getpixel((3, 3)) == (0x8a, 0x4b, 0x12)
    assert icono.getpixel((96, 96)) == (255, 255, 255)


def test_sin_logo_propio_sale_la_inicial_y_no_el_logo_de_cybershop(client, monkeypatch):
    """Una tienda que no ha subido logo tiene por defecto el de CyberShop: su app no
    puede salir con ese logo."""
    _marca(monkeypatch, empresa_logo_url='/static/img/Logo.png')
    monkeypatch.setattr(pwa, '_es_operador', lambda: False)
    icono = _png(client.get('/pwa/icono-192.png')).convert('RGB')
    assert icono.getpixel((3, 3)) == (0x8a, 0x4b, 0x12)          # su color
    colores = {icono.getpixel((x, y)) for x in range(60, 132, 4) for y in range(50, 142, 4)}
    assert (255, 255, 255) in colores                            # la inicial, en blanco


def test_el_operador_si_usa_el_logo_de_cybershop(client, monkeypatch):
    _marca(monkeypatch, empresa_nombre='CyberShop', empresa_logo_url='/static/img/Logo.png')
    monkeypatch.setattr(pwa, '_es_operador', lambda: True)
    icono = _png(client.get('/pwa/icono-192.png')).convert('RGB')
    assert len(icono.getcolors(maxcolors=100000)) > 20           # un logo, no un cuadro liso


def test_logo_que_no_se_puede_dibujar_no_da_error(client, monkeypatch, tmp_path, flask_app):
    carpeta = tmp_path / 'static' / 'media' / 'public_site'
    carpeta.mkdir(parents=True)
    (carpeta / 'logo.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding='utf-8')
    (carpeta / 'roto.png').write_bytes(b'esto no es una imagen')
    monkeypatch.setitem(flask_app.config, 'INSTANCE_OVERRIDES_DIR', str(tmp_path))
    for nombre in ('logo.svg', 'roto.png', 'no_existe.png', '../../../config.py'):
        pwa._iconos.clear()
        _marca(monkeypatch, empresa_logo_url=f'/static/media/public_site/{nombre}')
        r = client.get('/pwa/icono-192.png')
        assert r.status_code == 200 and _png(r).size == (192, 192)


def test_icono_solo_en_los_tamanos_previstos(client, monkeypatch):
    _marca(monkeypatch)
    assert client.get('/pwa/icono-180.png').status_code == 200
    assert client.get('/pwa/icono-9000.png').status_code == 404
    assert client.get('/pwa/icono-otra-192.png').status_code == 404


def test_cambiar_el_logo_cambia_la_huella_del_icono(client, monkeypatch, tmp_path, flask_app):
    _marca(monkeypatch)
    antes = pwa_version(flask_app)
    url = _logo(tmp_path, monkeypatch, flask_app)
    _marca(monkeypatch, empresa_logo_url=url)
    despues = pwa_version(flask_app)
    assert antes != despues
    m = json.loads(client.get('/manifest.webmanifest').data.decode('utf-8'))
    assert all(i['src'].endswith('?v=' + despues) for i in m['icons'])


def pwa_version(flask_app):
    with flask_app.test_request_context('/'):
        return pwa.version_icono()


# ── Service worker y aviso de «sin conexión» ────────────────────────────────

def test_service_worker_sin_cache_y_sin_guardar_nada_del_negocio(client, flask_app):
    r = client.get('/sw.js')
    assert r.status_code == 200
    assert r.mimetype in ('application/javascript', 'text/javascript')
    assert 'no-store' in r.headers['Cache-Control']
    js = r.data.decode('utf-8')
    assert "cs-pwa-" + flask_app.config['APP_VERSION'] in js
    # Lo único que entra a la memoria del equipo: el aviso y el ícono.
    assert "/pwa/sin-conexion" in js and "/pwa/icono-192.png" in js
    assert js.count('addAll(') == 1
    assert '.put(' not in js                                     # nunca guarda respuestas
    assert '/admin' not in js
    assert "r.method !== 'GET'" in js                            # los envíos no se tocan
    assert "r.mode === 'navigate'" in js


def test_aviso_sin_conexion_lleva_el_nombre_de_la_tienda(client, monkeypatch):
    _marca(monkeypatch, empresa_nombre='Nicol <b>&</b> Hijos')
    r = client.get('/pwa/sin-conexion')
    assert r.status_code == 200 and r.mimetype == 'text/html'
    html = r.data.decode('utf-8')
    assert 'No hay conexión a internet' in html and 'Reintentar' in html
    assert 'Nicol &lt;b&gt;&amp;&lt;/b&gt; Hijos' in html         # el nombre no inyecta HTML
    assert 'noindex' in r.headers['X-Robots-Tag']


# ── Apagado por tienda ──────────────────────────────────────────────────────

def test_apagada_no_se_ofrece_y_el_service_worker_se_retira(client, as_propietario, monkeypatch):
    monkeypatch.setenv('PWA_ACTIVA', '0')
    assert client.get('/manifest.webmanifest').status_code == 404
    assert client.get('/manifest-panel.webmanifest').status_code == 404
    js = client.get('/sw.js').data.decode('utf-8')
    assert 'unregister()' in js and 'addAll(' not in js
    assert 'rel="manifest"' not in client.get('/').data.decode('utf-8')
    panel = as_propietario.get('/admin').data.decode('utf-8')
    assert 'rel="manifest"' not in panel and 'btn-instalar-app' not in panel


# ── Las páginas ─────────────────────────────────────────────────────────────

def test_la_tienda_enlaza_su_manifiesto(client):
    html = client.get('/').data.decode('utf-8')
    assert '<link rel="manifest" href="/manifest.webmanifest">' in html
    assert '<link rel="apple-touch-icon" href="/pwa/icono-180.png">' in html
    assert "serviceWorker.register('/sw.js')" in html
    assert 'btn-instalar-app' not in html                        # el botón es solo del panel


def test_el_panel_enlaza_el_suyo_y_trae_el_boton_instalar(as_propietario):
    r = as_propietario.get('/admin')
    assert r.status_code == 200
    html = r.data.decode('utf-8')
    assert '<link rel="manifest" href="/manifest-panel.webmanifest">' in html
    assert 'id="btn-instalar-app"' in html and 'beforeinstallprompt' in html
    assert "serviceWorker.register('/sw.js')" in html


def test_con_el_codigo_anterior_las_plantillas_no_ofrecen_nada(flask_app):
    """Las plantillas son compartidas: una tienda que aún no se reinicia las lee con el
    código viejo (sin `pwa_activa`). No debe fallar ni enlazar rutas que no tiene."""
    fuente = flask_app.jinja_env.loader.get_source(flask_app.jinja_env, 'plantillaindex.html')[0]
    panel = flask_app.jinja_env.loader.get_source(flask_app.jinja_env, 'plantillaapp.html')[0]
    for texto in (fuente, panel):
        assert "url_for('pwa." not in texto and 'url_for("pwa.' not in texto
        inicio = texto.index('rel="manifest"')
        assert '{% if pwa_activa %}' in texto[:inicio]


def test_nada_exige_sesion(client):
    for ruta in ('/manifest.webmanifest', '/manifest-panel.webmanifest', '/sw.js',
                 '/pwa/sin-conexion', '/pwa/icono-192.png', '/pwa/icono-maskable-512.png'):
        assert client.get(ruta).status_code == 200, ruta


# ── Entrada de la app del panel ─────────────────────────────────────────────

@pytest.mark.parametrize('rol, destino', [
    (None, '/login?acceso=1'),
    (1, '/admin'), (2, '/admin'), (4, '/admin'),
])
def test_la_app_del_panel_abre_donde_trabaja_cada_quien(client, rol, destino):
    if rol is not None:
        with client.session_transaction() as s:
            s['usuario_id'], s['rol_id'], s['username'] = 1, rol, 'PytestUser'
    r = client.get('/pwa/panel')
    assert r.status_code == 302
    assert r.headers['Location'].endswith(destino)
    assert 'no-store' in r.headers['Cache-Control']


def test_la_app_del_panel_lleva_a_contador_mesero_y_cliente_a_lo_suyo(client, flask_app):
    with flask_app.test_request_context('/'):
        from flask import url_for
        esperado = {5: url_for('contabilidad.dashboard'),
                    6: url_for('restaurant_tables.waiter_panel'),
                    7: url_for('restaurant_tables.waiter_panel'),
                    3: url_for('auth.dashboard_cliente')}
    for rol, destino in esperado.items():
        with client.session_transaction() as s:
            s['usuario_id'], s['rol_id'], s['username'] = 1, rol, 'PytestUser'
        r = client.get('/pwa/panel')
        assert r.status_code == 302 and r.headers['Location'].endswith(destino), rol
