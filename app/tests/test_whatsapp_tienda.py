# -*- coding: utf-8 -*-
"""WhatsApp de cada tienda (1.9.9.2).

Los datos de contacto por defecto son los de CyberShop: una tienda que no ha puesto
su WhatsApp mandaba a sus compradores al de CyberShop (botón «Chatea con nosotros»,
página del pago, Contáctanos, chat…). Ahora cada tienda usa el suyo o su celular; si
no tiene ninguno, no hay botón. La página de CyberShop (el operador) sigue igual.
Contra la base de pruebas; lo que se cambia se restaura."""
import pytest

import routes.public as pub
from services import public_site_service as pss

WA_CYBERSHOP = pss.PUBLIC_FIELD_BY_KEY['empresa_whatsapp']['default']      # 573027974969
TEL_CYBERSHOP = pss.PUBLIC_FIELD_BY_KEY['empresa_telefono']['default']     # 3015963776


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
def contacto(monkeypatch):
    """Cambia en memoria el WhatsApp y el teléfono que ve la tienda."""
    original = pss.get_brand_config

    def poner(whatsapp, telefono):
        monkeypatch.setattr(pss, 'get_brand_config', lambda: {**original(), 'empresa_whatsapp': whatsapp,
                                                              'empresa_telefono': telefono})
    return poner


# ── La regla ────────────────────────────────────────────────────
def test_numero_para_wa_me():
    n = pss.numero_whatsapp
    assert n('300 123 4567') == n('+57 300-123-4567') == n('573001234567') == '573001234567'
    assert n('601 234 5678') == '576012345678', 'WhatsApp Business también en fijos'
    assert n('234 5678') == '' and n('') == '' and n(None) == ''
    assert n('+1 305 555 1234') == '13055551234'
    assert n('601 234 5678', solo_celular=True) == '', 'un fijo no sirve como WhatsApp de respaldo'
    assert n('310 444 5566', solo_celular=True) == '573104445566'


def test_cada_tienda_su_numero():
    wa = pss.whatsapp_de_la_tienda
    cliente = dict(operador=False)
    assert wa({'empresa_whatsapp': WA_CYBERSHOP, 'empresa_telefono': TEL_CYBERSHOP}, **cliente) == '', \
        'una tienda sin número propio no muestra el de CyberShop'
    assert wa({'empresa_whatsapp': '+57 300 123 4567', 'empresa_telefono': TEL_CYBERSHOP}, **cliente) == '573001234567'
    assert wa({'empresa_whatsapp': WA_CYBERSHOP, 'empresa_telefono': '310 444 5566'}, **cliente) == '573104445566', \
        'sin WhatsApp propio sirve su celular'
    assert wa({'empresa_whatsapp': '', 'empresa_telefono': '(601) 234 5678'}, **cliente) == '', 'un fijo no'
    assert wa({'empresa_whatsapp': WA_CYBERSHOP, 'empresa_telefono': TEL_CYBERSHOP}, operador=True) == WA_CYBERSHOP, \
        'la página de CyberShop sigue con su número'


# ── Las páginas ─────────────────────────────────────────────────
def test_boton_flotante(client, operador, contacto):
    operador(False)
    contacto(WA_CYBERSHOP, TEL_CYBERSHOP)
    html = client.get('/contactenos').get_data(as_text=True)
    assert 'class="chat-button"' not in html and f'wa.me/{WA_CYBERSHOP}' not in html

    contacto('3001234567', '')
    html = client.get('/contactenos').get_data(as_text=True)
    assert 'class="chat-button"' in html and html.count('wa.me/573001234567') >= 2, 'botón + dato de contacto'

    operador(True)
    contacto(WA_CYBERSHOP, TEL_CYBERSHOP)
    html = client.get('/contactenos').get_data(as_text=True)
    assert 'class="chat-button"' in html and f'wa.me/{WA_CYBERSHOP}' in html


def test_pagina_del_pago_sin_whatsapp_propio_va_a_contactenos(flask_app, operador, contacto):
    from flask import render_template
    operador(False)
    contacto(WA_CYBERSHOP, TEL_CYBERSHOP)
    with flask_app.test_request_context('/respuesta-pago'):
        html = render_template('respuesta_pago.html', datosApp=pub.get_common_data(),
                               datos={'estado': 'PENDIENTE', 'referencia': 'REF-QA-1'})
    assert 'wa.me/' not in html and 'href="/contactenos"' in html and 'Necesito ayuda' in html

    contacto('3001234567', '')
    with flask_app.test_request_context('/respuesta-pago'):
        html = render_template('respuesta_pago.html', datosApp=pub.get_common_data(),
                               datos={'estado': 'RECHAZADO', 'referencia': 'REF-QA-2'})
    assert 'wa.me/573001234567?text=Hola%2C%20mi%20pago%20fue%20rechazado%20ref%20REF-QA-2' in html


# ── Lo que lee la base directamente (chat, correos, IA) ─────────
@pytest.fixture()
def wa_guardado(flask_app):
    """Guarda en cliente_config el WhatsApp de CyberShop (lo que pasaba al grabar el
    formulario con el valor por defecto) y deja todo como estaba."""
    from database import get_db_cursor
    from services.config_tenant import set_cliente_config
    with flask_app.test_request_context('/'):
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'empresa_whatsapp' LIMIT 1")
            fila = cur.fetchone()
            set_cliente_config(cur, 'empresa_whatsapp', WA_CYBERSHOP, grupo='empresa', descripcion='WhatsApp')
    yield
    with flask_app.test_request_context('/'):
        with get_db_cursor() as cur:
            if fila:
                set_cliente_config(cur, 'empresa_whatsapp', fila['valor'], grupo='empresa', descripcion='WhatsApp')
            else:
                cur.execute("DELETE FROM cliente_config WHERE clave = 'empresa_whatsapp'")


def test_chat_correos_e_ia_no_dan_el_numero_de_cybershop(flask_app, operador, wa_guardado):
    from services.chat_publico.motor import config_publica
    from services.ia_datos.publico import datos_del_negocio
    from helpers_email_templates import _get_empresa_info
    operador(False)
    with flask_app.test_request_context('/'):
        assert config_publica()['whatsapp'] == ''
        assert datos_del_negocio().get('whatsapp') is None
        assert _get_empresa_info()['whatsapp'] == ''
    operador(True)
    with flask_app.test_request_context('/'):
        assert config_publica()['whatsapp'] == WA_CYBERSHOP, 'en la página de CyberShop sí'
        assert _get_empresa_info()['whatsapp'] == WA_CYBERSHOP


def test_mensajes_del_taller(flask_app, operador, contacto):
    from services.servicio_tecnico_mensajes import datos_negocio
    operador(False)
    contacto(WA_CYBERSHOP, TEL_CYBERSHOP)
    with flask_app.test_request_context('/'):
        assert datos_negocio()['telefono'] == ''
    contacto(WA_CYBERSHOP, '(601) 234 5678')
    with flask_app.test_request_context('/'):
        assert datos_negocio()['telefono'] == '(601) 234 5678', 'su fijo, tal como lo escribió'


# ── Toda tienda nueva sale con su WhatsApp ──────────────────────
@pytest.fixture()
def compra_pagada(cursor):
    """Un plan pagado listo para activar (se borra al final)."""
    import uuid
    from services import plan_compras_service as pcs
    pcs._ensure_table()
    marca = uuid.uuid4().hex[:8]
    with cursor() as cur:
        cur.execute("""INSERT INTO plan_compras (referencia_pedido, plan_key, periodo, buyer_email,
                                                 buyer_nombre, estado, token)
                       VALUES (%s, 'ultra', 'mes', %s, 'Ana Prueba', 'PAGADO', %s) RETURNING *""",
                    (f'PYTEST-WA-{marca}', f'pytest-wa-{marca}@ejemplo.com', f'pytest-wa-{marca}'))
        compra = dict(cur.fetchone())
    yield compra
    with cursor() as cur:
        cur.execute('DELETE FROM plan_compras WHERE id = %s', (compra['id'],))


def test_tienda_pagada_pide_su_whatsapp(client, compra_pagada, monkeypatch):
    import re
    from services import plan_compras_service as pcs
    import services.venta_automatica_service as vas
    creadas = []
    monkeypatch.setattr(vas, 'activar_tienda_async', lambda app, cid, slug, nombre: creadas.append(slug))
    url = f"/activar-tienda/{compra_pagada['token']}"
    html = client.get(url).get_data(as_text=True)
    assert re.search(r'id="buyer_telefono" name="buyer_telefono" required', html)

    datos = {'nombre_negocio': 'Panadería QA', 'subdominio': compra_pagada['token']}
    html = client.post(url, data=datos).get_data(as_text=True)
    assert 'Escribe el WhatsApp de tu negocio' in html and not creadas, 'sin WhatsApp no se crea'
    assert pcs.get_por_id(compra_pagada['id'])['estado'] == 'PAGADO'

    client.post(url, data={**datos, 'buyer_telefono': '+57 300 123 4567'})
    compra = pcs.get_por_id(compra_pagada['id'])
    assert creadas == [compra_pagada['token']] and compra['estado'] == 'ACTIVANDO'
    assert compra['buyer_telefono'] == '3001234567', 'de aquí sale el botón de su tienda'
