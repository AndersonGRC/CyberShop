# -*- coding: utf-8 -*-
"""Prueba gratis: la tienda se crea SOLO cuando la persona escribe el código de 6
números que le llegó al correo (1.9.9.0).

Antes bastaba con abrir el enlace del correo y los filtros de seguridad de los
correos (y los robots) lo abren solos: se creaban tiendas que nadie confirmó.
Ahora el enlace solo lleva a escribir el código; el código vale 2 horas y 5
intentos; pedir otro invalida el anterior; un WhatsApp sirve para una sola
prueba; y hay un tope de pruebas nuevas por hora. Además, los acentos de la
tienda salen del color que se eligió (no el naranja de CyberShop).
Contra la base de pruebas; todo lo creado se borra."""
import re
import uuid

import pytest

from services import marca_service as marca
from services import plan_compras_service as pcs

MARCA = uuid.uuid4().hex[:6]


def _email(n=''):
    return f'pytest-codigo-{MARCA}{n}@ejemplo.com'


@pytest.fixture(autouse=True)
def _sin_dns(monkeypatch):
    import security
    from services import correo_service
    monkeypatch.setattr(correo_service, '_dominio_existe', lambda dominio, segundos=3.0: True)
    monkeypatch.setattr(security, 'request_log', {})        # los límites por IP empiezan en cero


@pytest.fixture()
def limpiar(cursor):
    yield
    with cursor() as cur:
        cur.execute("SELECT id FROM crm_contactos WHERE email LIKE %s", (f'pytest-codigo-{MARCA}%',))
        ids = [r['id'] for r in cur.fetchall()]
        if ids:
            cur.execute('DELETE FROM crm_tareas WHERE contacto_id = ANY(%s)', (ids,))
            cur.execute('DELETE FROM crm_actividades WHERE contacto_id = ANY(%s)', (ids,))
            cur.execute('DELETE FROM crm_contactos WHERE id = ANY(%s)', (ids,))
        cur.execute("DELETE FROM plan_compras WHERE buyer_email LIKE %s", (f'pytest-codigo-{MARCA}%',))


@pytest.fixture()
def software_visible(flask_app):
    from services.public_site_service import is_public_section_enabled, set_public_section
    with flask_app.test_request_context('/'):
        antes = is_public_section_enabled('mostrar_modulo_software', False)
        set_public_section('mostrar_modulo_software', True)
    yield
    with flask_app.test_request_context('/'):
        set_public_section('mostrar_modulo_software', antes)


@pytest.fixture()
def correo(monkeypatch):
    """Los correos que «salen» (sin enviar nada): [(correo, código)]."""
    import routes.public as pub
    enviados = []
    monkeypatch.setattr(pub, '_enviar_confirmacion_trial',
                        lambda compra, codigo: enviados.append((compra['buyer_email'], codigo)) or True)
    return enviados


@pytest.fixture()
def creacion(monkeypatch):
    """La creación de la tienda simulada: [compra_id] de las que se empezaron a crear."""
    import services.venta_automatica_service as vas
    creadas = []
    monkeypatch.setattr(vas, 'activar_tienda_async', lambda app, cid, slug, nombre: creadas.append(cid))
    return creadas


def _registrar(client, monkeypatch, n='', telefono='3001234567'):
    import routes.public as pub
    monkeypatch.setattr(pub, '_slug_ocupado', lambda slug: False)
    return client.post('/prueba-gratis', data={
        'nombre_negocio': 'Tienda Código', 'buyer_nombre': 'Ana Código', 'buyer_email': _email(n),
        'buyer_telefono': telefono, 'subdominio': f'codigo-{MARCA}{n}', 'color_marca': '#0f766e',
        'tipo_negocio': 'tienda'})


def test_el_enlace_del_correo_no_crea_nada(limpiar, client, software_visible, correo, creacion, monkeypatch):
    """Un robot que abre el enlace (o la página de activación) no crea la tienda."""
    r = _registrar(client, monkeypatch)
    assert r.status_code == 302 and r.headers['Location'].endswith('/prueba-gratis/codigo')
    (destino, codigo), = correo
    assert destino == _email() and re.fullmatch(r'\d{6}', codigo)
    from database import get_db_cursor
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM plan_compras WHERE buyer_email = %s", (_email(),))
        compra = dict(cur.fetchone())
    assert compra['estado'] == 'TRIAL_PENDIENTE' and compra['codigo_hash'] and compra['codigo_hash'] != codigo
    robot = client.application.test_client()                          # otro navegador, sin la sesión
    r = robot.get(f"/prueba-gratis/confirmar/{compra['token']}")
    assert r.status_code == 302 and '/prueba-gratis/codigo?t=' in r.headers['Location']
    r = robot.get(f"/activar-tienda/{compra['token']}")
    assert r.status_code == 302 and '/prueba-gratis/codigo?t=' in r.headers['Location']
    r = robot.post(f"/activar-tienda/{compra['token']}", data={})
    assert pcs.get_por_id(compra['id'])['estado'] == 'TRIAL_PENDIENTE' and creacion == []
    html = robot.get(f"/prueba-gratis/codigo?t={compra['token']}").get_data(as_text=True)
    assert 'Escribe el código que te enviamos' in html and _email() not in html and 'py***@ejemplo.com' in html
    assert 'name="t" value="' + compra['token'] in html                     # sigue con el enlace, sin sesión


def test_solo_el_codigo_correcto_crea_la_tienda(limpiar, client, software_visible, correo, creacion, monkeypatch):
    _registrar(client, monkeypatch, 'b')
    codigo = correo[-1][1]
    malo = f'{(int(codigo) + 1) % 1000000:06d}'
    html = client.post('/prueba-gratis/codigo', data={'codigo': malo}).get_data(as_text=True)
    assert 'Ese código no es' in html and 'te quedan 4 intentos' in html and creacion == []
    r = client.post('/prueba-gratis/codigo', data={'codigo': codigo})
    compra = pcs.get_por_token(re.search(r'/activar-tienda/([^/?]+)', r.headers['Location']).group(1))
    assert compra['estado'] == 'ACTIVANDO' and creacion == [compra['id']] and compra['codigo_hash'] is None
    r = client.post('/prueba-gratis/codigo', data={'codigo': codigo})       # otra vez: ya no hace nada nuevo
    assert creacion == [compra['id']]


def test_cinco_errores_piden_otro_codigo(limpiar, client, cursor, software_visible, correo, creacion, monkeypatch):
    _registrar(client, monkeypatch, 'c')
    codigo = correo[-1][1]
    malo = f'{(int(codigo) + 7) % 1000000:06d}'
    for _ in range(pcs.CODIGO_INTENTOS_MAX):
        html = client.post('/prueba-gratis/codigo', data={'codigo': malo}).get_data(as_text=True)
    assert 'Pide uno nuevo' in html
    html = client.post('/prueba-gratis/codigo', data={'codigo': codigo}).get_data(as_text=True)
    assert 'Pide uno nuevo' in html and creacion == [], 'agotado: ni el correcto sirve'
    with cursor() as cur:                                               # (pasó el minuto de espera)
        cur.execute("UPDATE plan_compras SET codigo_enviado_at = NOW() - INTERVAL '2 minutes' "
                    "WHERE buyer_email = %s", (_email('c'),))
    client.post('/prueba-gratis/correo', data={'accion': 'reenviar'})
    nuevo = correo[-1][1]
    assert len(correo) == 2
    r = client.post('/prueba-gratis/codigo', data={'codigo': nuevo})
    assert r.status_code == 302 and '/activar-tienda/' in r.headers['Location'] and len(creacion) == 1


def test_el_codigo_vence(limpiar, cursor):
    assert pcs.CODIGO_HORAS == 2, 'el código vale 2 horas (pedido del usuario: 1 a 2 horas)'
    cid, _token = pcs.crear_trial('Vence', 'Ana Vence', _email('d'), f'vence-{MARCA}', telefono='3001234560')
    _fila, codigo = pcs.nuevo_codigo(cid)
    with cursor() as cur:
        cur.execute("UPDATE plan_compras SET codigo_enviado_at = NOW() - INTERVAL '121 minutes' WHERE id = %s", (cid,))
    assert pcs.verificar_codigo(cid, codigo) == ('vencido', 0)
    assert pcs.get_por_id(cid)['estado'] == 'TRIAL_PENDIENTE', 'sin código vigente no se crea nada'


def test_el_codigo_sirve_dentro_de_las_dos_horas(limpiar, cursor):
    cid, _token = pcs.crear_trial('Vigente', 'Ana Vigente', _email('e'), f'vigente-{MARCA}', telefono='3001234561')
    _fila, codigo = pcs.nuevo_codigo(cid)
    with cursor() as cur:
        cur.execute("UPDATE plan_compras SET codigo_enviado_at = NOW() - INTERVAL '115 minutes' WHERE id = %s", (cid,))
    assert pcs.verificar_codigo(cid, codigo)[0] == 'ok'
    assert pcs.get_por_id(cid)['estado'] == 'PAGADO'


def test_tope_de_pruebas_por_hora_no_gasta_el_codigo(limpiar, client, software_visible, correo, creacion,
                                                      monkeypatch):
    _registrar(client, monkeypatch, 'e')
    monkeypatch.setattr(pcs, 'pruebas_creadas_ultima_hora', lambda: pcs.PRUEBAS_POR_HORA)
    html = client.post('/prueba-gratis/codigo', data={'codigo': correo[-1][1]}).get_data(as_text=True)
    assert 'muchas tiendas' in html and creacion == []
    monkeypatch.setattr(pcs, 'pruebas_creadas_ultima_hora', lambda: 0)
    r = client.post('/prueba-gratis/codigo', data={'codigo': correo[-1][1]})
    assert '/activar-tienda/' in r.headers['Location'] and len(creacion) == 1


def test_un_whatsapp_una_prueba(limpiar):
    cid, _ = pcs.crear_trial('Uno', 'Ana Uno', _email('f1'), f'wa1-{MARCA}', telefono='3009998877')
    assert pcs.crear_trial('Dos', 'Ana Dos', _email('f2'), f'wa2-{MARCA}', telefono='3009998877')[0], \
        'mientras la primera no se confirme, se puede corregir con otro correo'
    pcs.marcar_trial_verificado(cid)
    compra_id, error = pcs.crear_trial('Tres', 'Ana Tres', _email('f3'), f'wa3-{MARCA}', telefono='3009998877')
    assert compra_id is None and 'WhatsApp ya usó' in error


def test_el_correo_trae_el_codigo_y_el_enlace(flask_app):
    from helpers_email_templates import generar_email_confirmacion_trial
    with flask_app.app_context():
        asunto, texto, html = generar_email_confirmacion_trial(
            {'buyer_nombre': 'Ana', 'nombre_negocio': 'Panadería'}, 'https://cybershopcol.com/prueba-gratis/confirmar/t',
            '048213')
    assert asunto.startswith('048213') and '048213' in html and '048213' in texto
    assert 'https://cybershopcol.com/prueba-gratis/confirmar/t' in texto and 'sin el código no se crea nada' in texto


# ── Colores: los acentos salen del color elegido ───────────────
def test_la_paleta_no_deja_el_naranja_de_cybershop():
    p = marca.paleta_desde('#0f766e')
    assert p['color_acento_secundario'] == p['color_hover_menu'] == marca.mezclar('#0f766e', '#ffffff', 0.45)
    assert '#fb8500' not in p.values()


def test_acentos_de_tiendas_ya_creadas():
    actuales = {'color_primario': '#0F766E', 'color_acento_secundario': '#fb8500'}
    assert marca.acentos_por_corregir(actuales, '#0f766e') == {
        'color_acento_secundario': marca.paleta_desde('#0f766e')['color_acento_secundario'],
        'color_hover_menu': marca.paleta_desde('#0f766e')['color_hover_menu']}
    assert marca.acentos_por_corregir(actuales, '#1e40af') == {}, 'cambió su color: no se toca'
    assert marca.acentos_por_corregir({**actuales, 'color_acento_secundario': '#123456',
                                       'color_hover_menu': '#654321'}, '#0f766e') == {}, 'los eligió el dueño'
