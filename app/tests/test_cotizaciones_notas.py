# -*- coding: utf-8 -*-
"""Cotizaciones: notas adicionales, renglón de descuento y firma (1.9.10.0).

- Notas adicionales (impuestos, condiciones, entrega…): campo nuevo del formulario;
  salen al final del PDF, antes de la firma. Vacías no salen.
- Sin descuento no sale el renglón «Descuentos» (el cliente no lee «Descuentos $0»).
- Las cotizaciones ya hechas no cambian: sus notas quedan vacías y su PDF guardado
  sigue igual.
Contra la base de pruebas; lo que se crea se borra al final."""
import os
import uuid

import pytest
from flask import render_template

import routes.quotes as rq

MARCA = uuid.uuid4().hex[:8]


# ── Las notas tal como se escriben ──────────────────────────────
def test_limpiar_notas():
    assert rq._limpiar_notas(None) == '' and rq._limpiar_notas('  \r\n  ') == ''
    escrito = 'Precios con IVA incluido.   \r\n\r\n\r\n\r\nEntrega: 5 días hábiles.\r\n'
    assert rq._limpiar_notas(escrito) == 'Precios con IVA incluido.\n\nEntrega: 5 días hábiles.'
    assert len(rq._limpiar_notas('x' * 5000)) == rq.NOTAS_MAX


# ── El PDF ──────────────────────────────────────────────────────
def _pdf(flask_app, **extra):
    datos = dict(id='COT 0000000001', fecha='1 de enero de 2026', cliente={'nombre': 'Cliente QA'},
                 items=[], total='$119.000', subtotal='$100.000', descuento='$0', iva='$19.000',
                 logo='', colores=rq._get_brand_colors())
    datos.update(extra)
    with flask_app.test_request_context('/'):
        return render_template('pdf_quote.html', **datos)


def test_sin_descuento_ni_notas_no_salen(flask_app):
    html = _pdf(flask_app, mostrar_descuento=False, notas='', firma_empresa='Panadería QA')
    assert '>Descuentos<' not in html and 'class="notas-titulo"' not in html
    assert '>Subtotal<' in html and '>TOTAL<' in html and '>IVA (19%)<' in html
    assert '>Firma autorizada<' in html and '<b>Panadería QA</b>' in html


def test_con_descuento_y_notas_antes_de_la_firma(flask_app):
    html = _pdf(flask_app, mostrar_descuento=True, descuento='$10.000', firma_empresa='',
                notas='Precios con IVA incluido.\nEntrega <5 días>.')
    assert '>Descuentos<' in html and '$10.000' in html
    assert 'Precios con IVA incluido.<br>Entrega &lt;5 días&gt;.' in html, 'saltos de línea y texto escapado'
    assert html.index('>TOTAL<') < html.index('>Notas adicionales<') < html.index('>Firma autorizada<')
    assert '<b>' not in html.split('firma-linea">', 1)[1].split('</td>', 1)[0], 'sin nombre propio, sin nombre'


def test_quien_no_manda_las_banderas_lo_ve_como_antes(flask_app):
    """La app de escritorio usa una copia de esta plantilla y no manda las banderas."""
    html = _pdf(flask_app)
    assert '>Descuentos<' in html and 'class="notas-titulo"' not in html and 'class="firma-tabla"' not in html


def test_la_firma_nunca_dice_cybershop_en_un_cliente(flask_app, monkeypatch):
    from services import public_site_service as pss
    marca = pss.get_brand_config
    monkeypatch.setattr(pss, 'get_brand_config', lambda: {**marca(), 'empresa_nombre': 'CyberShop'})
    monkeypatch.setattr(pss, 'is_public_section_enabled', lambda clave, default=True: False)
    with flask_app.test_request_context('/'):
        assert rq._firma_empresa() == ''
    monkeypatch.setattr(pss, 'is_public_section_enabled', lambda clave, default=True: True)
    with flask_app.test_request_context('/'):
        assert rq._firma_empresa() == 'CyberShop', 'en la página de CyberShop sí'


# ── De punta a punta: crear, editar y quitar las notas ──────────
@pytest.fixture()
def generar(as_propietario, cursor, monkeypatch, flask_app):
    """POST al generador como el dueño. Sin CRM (no deja contactos de prueba) y
    guardando lo que recibe la plantilla del PDF. Borra al final lo que creó."""
    import services.crm_service as crm
    monkeypatch.setattr(crm, 'upsert_contacto', lambda **kw: None)
    contexto = {}
    real = rq.render_template

    def capturar(plantilla, **kw):
        if plantilla == 'pdf_quote.html':
            contexto.clear()
            contexto.update(kw)
        return real(plantilla, **kw)
    monkeypatch.setattr(rq, 'render_template', capturar)
    creadas = []

    def enviar(descuento='0', notas=None, cotizacion_id=None):
        datos = {'cliente_nombre': f'Cliente QA {MARCA}', 'cliente_documento': '900123456',
                 'descripcion[]': ['Mantenimiento de equipo'], 'cantidad[]': ['2'],
                 'precio[]': ['50000'], 'descuento[]': [descuento], 'iva[]': ['19']}
        if notas is not None:
            datos['notas_adicionales'] = notas
        if cotizacion_id:
            datos['cotizacion_id'] = str(cotizacion_id)
        r = as_propietario.post('/admin/cotizar/generar', data=datos)
        assert r.status_code == 200 and r.mimetype == 'application/pdf', r.get_data(as_text=True)[:300]
        with cursor() as cur:
            cur.execute("SELECT * FROM cotizaciones WHERE cliente_nombre = %s ORDER BY id DESC LIMIT 1",
                        (f'Cliente QA {MARCA}',))
            fila = dict(cur.fetchone())
        if fila['id'] not in creadas:
            creadas.append(fila['id'])
        return fila, dict(contexto)
    yield enviar
    with cursor() as cur:
        cur.execute('DELETE FROM detalle_cotizacion WHERE cotizacion_id = ANY(%s)', (creadas,))
        cur.execute('DELETE FROM cotizaciones WHERE id = ANY(%s)', (creadas,))
    carpeta = os.path.join(flask_app.root_path, 'static', 'cotizaciones', 'pdf')
    for cid in creadas:
        archivo = os.path.join(carpeta, f'Cotizacion_{cid}.pdf')
        if os.path.isfile(archivo):
            os.remove(archivo)


def test_crear_con_notas_y_sin_descuento(generar, as_propietario):
    fila, pdf = generar(notas='Precios con IVA incluido.\r\nVigencia: 15 días.')
    assert fila['notas_adicionales'] == 'Precios con IVA incluido.\nVigencia: 15 días.'
    assert pdf['mostrar_descuento'] is False and pdf['notas'] == fila['notas_adicionales']
    assert float(fila['total']) == 119000.0, 'el total no cambia: 2 × 50.000 + IVA'

    html = as_propietario.get(f"/admin/cotizar/editar/{fila['id']}").get_data(as_text=True)
    assert 'name="notas_adicionales"' in html and 'Vigencia: 15 días.</textarea>' in html


def test_editar_con_descuento_y_quitar_las_notas(generar):
    fila, _ = generar(notas='Entrega en 5 días.')
    fila, pdf = generar(descuento='10', notas='', cotizacion_id=fila['id'])
    assert fila['notas_adicionales'] is None and pdf['notas'] == ''
    assert pdf['mostrar_descuento'] is True and float(fila['total']) == 107100.0


def test_sin_el_campo_no_se_tocan_las_notas_al_crear(generar):
    """Quien envía el formulario viejo (sin el campo) crea la cotización igual."""
    fila, pdf = generar(notas=None)
    assert fila['notas_adicionales'] is None and pdf['notas'] == ''


# ── «Visítanos en…»: el sitio de la tienda, nunca el de CyberShop en un cliente ──
def test_visitanos_en_el_sitio_de_la_tienda(flask_app, monkeypatch):
    from services import public_site_service as pss
    marca = pss.get_brand_config
    monkeypatch.setattr(pss, 'get_brand_config', lambda: {**marca(), 'empresa_website': ''})
    monkeypatch.setattr(pss, 'is_public_section_enabled', lambda clave, default=True: False)
    with flask_app.test_request_context('/admin/cotizar', base_url='https://panaderia.cybershopcol.com'):
        assert rq._sitio_de_la_tienda() == 'https://panaderia.cybershopcol.com'
    monkeypatch.setattr(pss, 'is_public_section_enabled', lambda clave, default=True: True)
    with flask_app.test_request_context('/admin/cotizar', base_url='https://cybershopcol.com'):
        assert rq._sitio_de_la_tienda() == 'https://cybershopcol.com'
    monkeypatch.setattr(pss, 'get_brand_config', lambda: {**marca(), 'empresa_website': 'https://mipanaderia.co'})
    with flask_app.test_request_context('/admin/cotizar'):
        assert rq._sitio_de_la_tienda() == 'https://mipanaderia.co', 'el que escribió la tienda manda'
