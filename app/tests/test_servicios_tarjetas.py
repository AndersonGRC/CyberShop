# -*- coding: utf-8 -*-
"""Tarjetas de la página de Servicios (1.9.11.0, diseño A).

Cada servicio: tarjeta con foto (o la inicial), número, descripción y dos beneficios;
al tocarla se abre su detalle (<dialog>) con todo lo que incluye y el botón para
pedirlo por el WhatsApp de la tienda (o Contáctanos si no tiene). Los colores salen
de la marca; la tinta de textos se oscurece hasta leerse (4,5:1).
Contra la base de pruebas; lo que se cambia es en memoria."""
import re

import pytest

import routes.public as pub
from services import marca_service as ms
from services import public_site_service as pss
from services import servicios_publicos as sp

SERVICIOS = [
    {'titulo': 'Tortas personalizadas', 'descripcion': 'Con el sabor que quieras.', 'imagen': '/static/uploads/torta.jpg',
     'beneficios': '- Sabores a tu gusto\n• Decoración con tu tema\n\n3. Entrega a domicilio'},
    {'titulo': '«Desayunos» sorpresa', 'descripcion': 'Para fechas especiales.', 'imagen': '', 'beneficios': ''},
]


@pytest.fixture()
def tienda(flask_app, monkeypatch):
    """Una tienda (no CyberShop) con sus servicios y el WhatsApp que se pida."""
    with flask_app.test_request_context('/'):
        antes = pss.is_public_section_enabled('mostrar_modulo_software', False)
        pss.set_public_section('mostrar_modulo_software', False)
    monkeypatch.setattr(pub, 'get_home_services', lambda: SERVICIOS)
    marca = pss.get_brand_config

    def con_whatsapp(numero):
        monkeypatch.setattr(pss, 'get_brand_config', lambda: {**marca(), 'empresa_whatsapp': numero,
                                                              'empresa_telefono': '', 'color_primario': '#7a3e12'})
    yield con_whatsapp
    with flask_app.test_request_context('/'):
        pss.set_public_section('mostrar_modulo_software', antes)


def test_beneficios_como_los_escribe_la_tienda():
    assert sp.lista_beneficios('- Uno\n• Dos\n\n* Tres\n4) Cuatro\n  Cinco  ') == ['Uno', 'Dos', 'Tres', 'Cuatro', 'Cinco']
    assert sp.lista_beneficios(None) == [] and sp.lista_beneficios('  \n ') == []
    t = sp.tarjetas(SERVICIOS + [{'titulo': '  ', 'descripcion': 'sin título no sale'}])
    assert [x['numero'] for x in t] == ['01', '02'] and t[1]['inicial'] == 'D'
    assert t[0]['resumen'] == ['Sabores a tu gusto', 'Decoración con tu tema'] and len(t[0]['beneficios']) == 3


def test_tinta_legible_con_cualquier_marca():
    for color in ['#122C94', '#7a3e12', '#facc15', '#22c55e', '#ffffff'] + [c for c, _ in ms.MUESTRAS]:
        tinta = ms.tinta_legible(color)
        assert ms.contraste(tinta, ms.mezclar(color, '#ffffff', 0.92)) >= 4.5, color
        assert ms.contraste(tinta, '#ffffff') >= 4.5, color


def test_tarjetas_y_detalle_de_cada_servicio(client, tienda):
    tienda('3001234567')
    html = client.get('/servicios').get_data(as_text=True)
    assert html.count('class="sv-card"') == 2 and html.count('<dialog class="sv-dlg"') == 2
    for n in ('01', '02'):
        assert f'data-sv-abre="sv-det-{n}"' in html and f'id="sv-det-{n}"' in html
    assert 'src="/static/uploads/torta.jpg"' in html
    assert 'class="sv-card-inicial" aria-hidden="true">D</span>' in html, 'sin foto: la inicial'
    tarjeta = html.split('class="sv-card"', 2)[1]
    assert tarjeta.count('<li>') == 2, 'en la tarjeta solo dos beneficios'
    detalle = html.split('id="sv-det-01"', 1)[1].split('</dialog>', 1)[0]
    assert 'Entrega a domicilio' in detalle and 'Qué incluye' in detalle
    assert 'wa.me/573001234567?text=' in detalle and 'Tortas%20personalizadas' in detalle
    assert 'aria-label="Cerrar"' in detalle and 'id="modal"' not in html, 'ya no está la ventana vieja'
    assert re.search(r'style="--sv-tinta: #[0-9a-f]{6}"', html), 'la tinta legible de la marca'
    otro = html.split('id="sv-det-02"', 1)[1].split('</dialog>', 1)[0]
    assert 'Qué incluye' not in otro and '&#34;' not in otro and '«Desayunos» sorpresa' in otro


def test_sin_whatsapp_el_detalle_lleva_a_contactenos(client, tienda):
    tienda('')
    html = client.get('/servicios').get_data(as_text=True)
    detalle = html.split('id="sv-det-01"', 1)[1].split('</dialog>', 1)[0]
    assert 'wa.me/' not in detalle and 'href="/contactenos"' in detalle
    assert 'Ver detalles<span class="sv-sr">' in html, 'sin WhatsApp el botón no promete «pedir»'
