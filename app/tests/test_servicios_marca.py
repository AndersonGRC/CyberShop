# -*- coding: utf-8 -*-
"""Página pública de Servicios con la marca de cada tienda (1.9.9.1).

El encabezado ya no lleva la foto de CyberShop (Fondo.jpg, la misma en todas las
tiendas): sale de los colores y el nombre de la tienda. Lo de CyberShop —su frase,
sus servicios de siempre y su WhatsApp— solo aparece en la página del operador;
una tienda que aún no carga los suyos ve un aviso con su propio contacto.
Contra la base de pruebas; lo que se cambia se restaura."""
import pytest

import routes.public as pub
from services import public_site_service as pss

SERVICIOS_DE_CYBERSHOP = 'Desarrollo web empresarial'
FRASE_DE_CYBERSHOP = pss.PUBLIC_FIELD_BY_KEY['servicios_hero_subtitulo']['default']
WHATSAPP_DE_CYBERSHOP = pss.PUBLIC_FIELD_BY_KEY['empresa_whatsapp']['default']


@pytest.fixture()
def operador(flask_app):
    """Pone la tienda como la del operador (CyberShop) o como la de un cliente."""
    with flask_app.test_request_context('/'):
        antes = pss.is_public_section_enabled('mostrar_modulo_software', False)

    def poner(valor):
        with flask_app.test_request_context('/'):
            pss.set_public_section('mostrar_modulo_software', valor)
    yield poner
    poner(antes)


@pytest.fixture()
def sin_cambios_de_marca(monkeypatch):
    """La frase y el WhatsApp como vienen por defecto (los de CyberShop) y sin
    servicios cargados: el caso de un cliente que no ha tocado nada."""
    monkeypatch.setattr(pub, 'get_home_services', lambda: [])
    original = pub.get_public_home_content
    monkeypatch.setattr(pub, 'get_public_home_content',
                        lambda: {**original(), 'services_hero_title': 'Servicios',
                                 'services_hero_subtitle': FRASE_DE_CYBERSHOP})
    marca = pss.get_brand_config
    monkeypatch.setattr(pss, 'get_brand_config',
                        lambda: {**marca(), 'empresa_whatsapp': WHATSAPP_DE_CYBERSHOP, 'empresa_nombre': 'Panadería QA'})


def test_un_cliente_no_ve_nada_de_cybershop(client, operador, sin_cambios_de_marca):
    operador(False)
    html = client.get('/servicios').get_data(as_text=True)
    assert 'img/Fondo.jpg' not in html and 'class="sv-hero"' in html
    assert '<h1 id="sv-titulo">Nuestros servicios</h1>' in html
    assert FRASE_DE_CYBERSHOP not in html and 'Conoce lo que ofrecemos.' in html
    assert SERVICIOS_DE_CYBERSHOP not in html and 'Muy pronto verás aquí nuestros servicios' in html
    assert f'wa.me/{WHATSAPP_DE_CYBERSHOP}' not in html.split('sv-vacio', 1)[1].split('</section>', 1)[0]
    assert 'href="/contactenos"' in html


def test_cybershop_conserva_su_frase_y_sus_servicios(client, operador, sin_cambios_de_marca):
    operador(True)
    html = client.get('/servicios').get_data(as_text=True)
    assert 'img/Fondo.jpg' not in html and FRASE_DE_CYBERSHOP in html
    assert SERVICIOS_DE_CYBERSHOP in html and 'Muy pronto verás' not in html


def test_los_servicios_de_la_tienda_y_su_whatsapp(client, operador, monkeypatch):
    operador(False)
    monkeypatch.setattr(pub, 'get_home_services', lambda: [
        {'titulo': 'Tortas personalizadas', 'descripcion': 'Con el sabor que quieras.', 'imagen': '', 'beneficios': ''}])
    html = client.get('/servicios').get_data(as_text=True)
    assert 'Tortas personalizadas' in html and 'Muy pronto verás' not in html and SERVICIOS_DE_CYBERSHOP not in html
    monkeypatch.setattr(pub, 'get_home_services', lambda: [])
    marca = pss.get_brand_config
    monkeypatch.setattr(pss, 'get_brand_config', lambda: {**marca(), 'empresa_whatsapp': '+57 300 123 4567'})
    html = client.get('/servicios').get_data(as_text=True)
    assert 'wa.me/573001234567' in html, 'el WhatsApp propio de la tienda sí se ofrece'


def test_capa_oscura_segun_el_color_de_la_marca():
    from services import marca_service as ms
    assert ms.capa_para_texto_blanco('#122C94', '#091C5A', '#0e1b33') == 10, 'CyberShop queda igual'
    for color, _ in ms.MUESTRAS:                       # los colores de la prueba gratis tampoco cambian
        p = ms.paleta_desde(color)
        assert ms.capa_para_texto_blanco(p['color_primario'], p['color_primario_oscuro'], p['color_secundario']) == 10, color
    assert ms.capa_para_texto_blanco('#facc15') > 10, 'un amarillo se oscurece para poder leer'
    assert ms.capa_para_texto_blanco('#ffffff') == ms.CAPAS_OSCURAS[-1]
    assert ms.capa_para_texto_blanco(None, '', 'no-es-color') == 10


def test_marca_clara_lleva_capa_mas_fuerte(client, operador, monkeypatch):
    operador(False)
    marca = pss.get_brand_config
    monkeypatch.setattr(pss, 'get_brand_config', lambda: {**marca(), 'color_primario': '#facc15'})
    html = client.get('/servicios').get_data(as_text=True)
    assert 'class="sv-hero sv-capa-' in html
    monkeypatch.setattr(pss, 'get_brand_config', lambda: {**marca(), 'color_primario': '#122C94',
                                                          'color_primario_oscuro': '#091C5A', 'color_secundario': '#0e1b33'})
    html = client.get('/servicios').get_data(as_text=True)
    assert 'class="sv-hero"' in html


def test_titulo_propio(client, operador, monkeypatch):
    operador(False)
    original = pub.get_public_home_content
    monkeypatch.setattr(pub, 'get_public_home_content',
                        lambda: {**original(), 'services_hero_title': 'Lo que hacemos por ti',
                                 'services_hero_subtitle': 'Pan del día.'})
    html = client.get('/servicios').get_data(as_text=True)
    assert '<h1 id="sv-titulo">Lo que hacemos por ti</h1>' in html and 'Pan del día.' in html


def test_sin_ruta_que_repita_el_menu(client, operador):
    """«Inicio › Servicios» en el encabezado repetía el menú de arriba (1.9.10.1)."""
    operador(True)
    html = client.get('/servicios').get_data(as_text=True)
    encabezado = html.split('class="sv-hero', 1)[1].split('</section>', 1)[0]
    assert 'sv-ruta' not in encabezado and 'aria-label="Ruta"' not in encabezado
    assert '<h1 id="sv-titulo">' in encabezado
