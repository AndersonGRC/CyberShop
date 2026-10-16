# -*- coding: utf-8 -*-
"""Datos de CyberShop en la tienda de un cliente (1.9.11.1).

Los valores por defecto del lema, el ©, el mapa, el correo, el teléfono y el
WhatsApp son los de CyberShop: una tienda que no ha puesto los suyos mostraba los
de CyberShop en el pie de página, Contáctanos y el mapa del inicio. Ahora no se
muestran (el © pasa a ser el nombre de la tienda). La página de CyberShop sigue
igual, y si no se puede saber qué tienda es, no se esconde nada.
Contra la base de pruebas; lo que se cambia es en memoria o se restaura."""
import pytest

from services import public_site_service as pss

DEF = {k: pss.PUBLIC_FIELD_BY_KEY[k]['default'] for k in pss._DATOS_DE_CYBERSHOP}
MAPA = DEF['empresa_maps_embed'][:70]
LEMA = DEF['empresa_tagline']


@pytest.fixture()
def tienda(flask_app, monkeypatch):
    """La tienda sin sus datos de contacto (salen los de por defecto), llamada
    «Panadería QA»; `poner(operador)` la vuelve la de CyberShop o la de un cliente."""
    estructurados, legado = pss._structured_settings_values, pss._legacy_cliente_config_values

    def sin_contacto(valores):
        return {k: v for k, v in valores.items() if k not in pss._DATOS_DE_CYBERSHOP}
    monkeypatch.setattr(pss, '_structured_settings_values',
                        lambda: {**sin_contacto(estructurados()), 'empresa_nombre': 'Panadería QA'})
    monkeypatch.setattr(pss, '_legacy_cliente_config_values', lambda: sin_contacto(legado()))
    with flask_app.test_request_context('/'):
        antes = pss.is_public_section_enabled('mostrar_modulo_software', False)

    def poner(operador):
        with flask_app.test_request_context('/'):
            pss.set_public_section('mostrar_modulo_software', operador)
    yield poner
    poner(antes)


def test_un_cliente_no_muestra_los_datos_de_cybershop(client, flask_app, tienda):
    tienda(False)
    with flask_app.test_request_context('/'):
        marca = pss.get_brand_config()
    assert all(marca[k] == '' for k in pss._DATOS_DE_CYBERSHOP), marca
    for ruta in ('/', '/contactenos', '/servicios'):
        html = client.get(ruta).get_data(as_text=True)
        assert DEF['empresa_email'] not in html and LEMA not in html and MAPA not in html, ruta
        assert '3015963776' not in html and '573027974969' not in html, ruta
        assert 'Panadería QA.</p>' in html, f'{ruta}: el © lleva el nombre de la tienda'


def test_cybershop_sigue_con_sus_datos(client, flask_app, tienda):
    tienda(True)
    with flask_app.test_request_context('/'):
        marca = pss.get_brand_config()
    assert all(marca[k] == DEF[k] for k in pss._DATOS_DE_CYBERSHOP)
    html = client.get('/').get_data(as_text=True)
    assert MAPA in html and LEMA in html and DEF['empresa_email'] in html


def test_los_datos_propios_se_respetan(flask_app, tienda, monkeypatch):
    tienda(False)
    original = pss._structured_settings_values
    monkeypatch.setattr(pss, '_structured_settings_values', lambda: {
        **original(), 'empresa_email': 'ventas@panaderiaqa.co', 'empresa_telefono': '(601) 234 5678',
        'empresa_tagline': 'Pan de la casa todos los días.'})
    with flask_app.test_request_context('/'):
        marca = pss.get_brand_config()
    assert marca['empresa_email'] == 'ventas@panaderiaqa.co' and marca['empresa_telefono'] == '(601) 234 5678'
    assert marca['empresa_tagline'] == 'Pan de la casa todos los días.'


def test_guardado_con_el_valor_de_cybershop_tampoco(flask_app, tienda, monkeypatch):
    """Quien grabó el formulario con el valor prellenado guardó el de CyberShop."""
    tienda(False)
    original = pss._structured_settings_values
    monkeypatch.setattr(pss, '_structured_settings_values', lambda: {
        **original(), 'empresa_email': DEF['empresa_email'].upper(), 'empresa_telefono': '301 596 3776'})
    with flask_app.test_request_context('/'):
        marca = pss.get_brand_config()
    assert marca['empresa_email'] == '' and marca['empresa_telefono'] == ''


def test_si_no_se_sabe_que_tienda_es_no_se_esconde_nada(flask_app, monkeypatch):
    def falla(*a, **k):
        raise RuntimeError('sin base')
    monkeypatch.setattr(pss, 'is_public_section_enabled', falla)
    with flask_app.test_request_context('/'):
        assert pss._es_operador() is None
        assert pss.es_dato_de_cybershop('empresa_email', DEF['empresa_email']) is False
        valores = pss._sin_datos_de_cybershop(dict(DEF))
    assert valores == DEF, 'los datos del operador nunca se pierden por un error'


def test_mensajes_del_formulario_van_a_la_tienda(flask_app, tienda, cursor):
    """Sin correo destino propio, los mensajes del formulario iban a CyberShop: ahora al
    dueño de la tienda (rol propietario)."""
    tienda(False)
    with cursor() as cur:
        cur.execute("""SELECT email FROM usuarios WHERE rol_id = 2 AND COALESCE(estado, 'habilitado') = 'habilitado'
                       AND COALESCE(email, '') <> '' ORDER BY id LIMIT 1""")
        fila = cur.fetchone()
    with flask_app.test_request_context('/'):
        destino = pss.get_public_contact_destination_email()
    assert destino != DEF['contacto_email_destino'] and destino == (fila['email'] if fila else '')
    tienda(True)
    with flask_app.test_request_context('/'):
        assert pss.get_public_contact_destination_email() == DEF['contacto_email_destino']


def test_el_mapa_de_contactenos_se_ve_como_mapa(client, tienda):
    """Guardado como dirección, el mapa salía como texto en Contáctanos."""
    tienda(True)
    html = client.get('/contactenos').get_data(as_text=True)
    caja = html.split('class="ct-mapa">', 1)[1].split('</div>', 1)[0]
    assert caja.strip().startswith('<iframe src="https://www.google.com/maps/embed') and 'title="Mapa de ubicación"' in caja
