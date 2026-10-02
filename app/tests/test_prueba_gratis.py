# -*- coding: utf-8 -*-
"""Prueba gratis 15 días: asistente, datos que pide, tienda neutra con la marca
del cliente, CRM del operador y pagos apagados sin llaves. Contra la base de
pruebas; todo lo creado se borra y la marca se restaura al final."""
import uuid
from datetime import date, timedelta

import pytest

from services import crm_pruebas_service as crmp
from services import marca_service as marca
from services import plan_compras_service as pcs

MARCA = uuid.uuid4().hex[:6]


def _email(n=''):
    return f'pytest-trial-{MARCA}{n}@ejemplo.com'


@pytest.fixture(autouse=True)
def _sin_dns(monkeypatch):
    """Ninguna prueba consulta el DNS real; el dominio «noexiste» se simula."""
    from services import correo_service
    monkeypatch.setattr(correo_service, '_dominio_existe',
                        lambda dominio, segundos=3.0: not dominio.startswith('noexiste'))


@pytest.fixture()
def limpiar(cursor):
    yield
    with cursor() as cur:
        cur.execute("SELECT id FROM crm_contactos WHERE email LIKE %s", (f'pytest-trial-{MARCA}%',))
        ids = [r['id'] for r in cur.fetchall()]
        if ids:
            cur.execute('DELETE FROM crm_tareas WHERE contacto_id = ANY(%s)', (ids,))
            cur.execute('DELETE FROM crm_actividades WHERE contacto_id = ANY(%s)', (ids,))
            cur.execute('DELETE FROM crm_contactos WHERE id = ANY(%s)', (ids,))
        cur.execute("DELETE FROM plan_compras WHERE buyer_email LIKE %s", (f'pytest-trial-{MARCA}%',))


# ── Marca ──────────────────────────────────────────────────────
def test_muestras_tienen_contraste_y_la_paleta_es_estable():
    for hexa, _nombre in marca.MUESTRAS:
        assert marca.contraste_con_blanco(hexa) >= marca.CONTRASTE_MINIMO
    p = marca.paleta_desde('#1E40AF')
    assert p == marca.paleta_desde('#1e40af')
    assert p['color_primario'] == '#1e40af' and p['color_botones'] == '#1e40af'
    assert marca.paleta_desde(None)['color_primario'] == marca.NEUTRO     # nunca el azul de CyberShop
    assert set(p) <= {f['key'] for f in __import__('services.public_site_service', fromlist=['x']).PUBLIC_COLOR_FIELDS}


@pytest.mark.parametrize('color, ok', [('#ffffff', False), ('#ffee00', False), ('azul', False),
                                       ('#0f4c81', True), ('334155', True)])
def test_validar_color(color, ok):
    c, err = marca.validar(color)
    assert bool(c) is ok and (err is None) is ok


def test_tienda_nueva_usa_sus_datos_no_los_de_cybershop():
    v = marca.valores_tienda_nueva(negocio='Panadería Roma', email='roma@x.com', whatsapp='3001234567',
                                   color='#b91c1c', tipo='restaurante', lema='Pan recién horneado')
    assert v['empresa_logo_url'] == marca.LOGO_PROVISIONAL
    assert v['contacto_email_destino'] == 'roma@x.com' and v['empresa_email'] == 'roma@x.com'
    assert v['empresa_whatsapp'] == '573001234567' and v['empresa_telefono'] == '3001234567'
    assert v['empresa_tagline'] == 'Pan recién horneado' and v['empresa_copyright'] == 'Panadería Roma'
    assert v['empresa_maps_embed'] == '' and v['color_primario'] == '#b91c1c'
    assert 'cybershop' not in ' '.join(str(x).lower() for x in v.values())


# ── WhatsApp ───────────────────────────────────────────────────
@pytest.mark.parametrize('entrada, salida', [
    ('300 123 4567', '3001234567'), ('+57 300-123-4567', '3001234567'), ('573001234567', '3001234567'),
    ('6015551234', '6015551234'), ('', None), ('12345', None), ('1234567890', None),
])
def test_whatsapp(entrada, salida):
    assert pcs.normalizar_whatsapp(entrada)[0] == salida


# ── Registro, reenvío y CRM ────────────────────────────────────
def test_registro_crea_lead_con_whatsapp_y_permite_reenviar(limpiar, cursor):
    cid, token = pcs.crear_trial('Panadería Zyx', 'Ana Zyx', _email(), f'zyx-{MARCA}',
                                 telefono='3001234567', color_marca='#b91c1c', tipo_negocio='restaurante',
                                 lema='Pan del día')
    with cursor() as cur:
        cur.execute('SELECT tipo, origen, telefono, whatsapp, empresa, tags FROM crm_contactos WHERE email = %s',
                    (_email(),))
        c = cur.fetchone()
    assert c['tipo'] == 'lead' and c['origen'] == 'prueba_gratis'
    assert c['telefono'] == '3001234567' and c['whatsapp'] == '3001234567'
    assert c['empresa'] == 'Panadería Zyx' and 'prueba-gratis' in c['tags']
    fila = pcs.get_por_id(cid)
    assert (fila['color_marca'], fila['tipo_negocio'], fila['lema']) == ('#b91c1c', 'restaurante', 'Pan del día')

    # No confirmó el correo y vuelve a intentar: misma prueba, datos actualizados, sin duplicar.
    cid2, token2 = pcs.crear_trial('Panadería Zyx Centro', 'Ana Zyx', _email(), f'zyx2-{MARCA}',
                                   telefono='3009876543')
    assert (cid2, token2) == (cid, token)
    assert pcs.get_por_id(cid)['slug'] == f'zyx2-{MARCA}'
    with cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM crm_contactos WHERE email = %s', (_email(),))
        assert cur.fetchone()['n'] == 1

    # Ya confirmada: no puede pedir otra.
    pcs.marcar_trial_verificado(cid)
    assert pcs.crear_trial('Otra', 'Ana', _email(), f'zyx3-{MARCA}', telefono='3001112233')[0] is None


def test_contacto_existente_se_completa_sin_duplicar(limpiar, cursor):
    with cursor() as cur:
        cur.execute("""INSERT INTO crm_contactos (tipo, nombre, email, activo) VALUES ('cliente', 'Bea', %s, TRUE)""",
                    (_email('b'),))
    pcs.crear_trial('Tienda Bea', 'Bea', _email('b'), f'bea-{MARCA}', telefono='3115550000')
    with cursor() as cur:
        cur.execute('SELECT tipo, telefono, tags FROM crm_contactos WHERE email = %s', (_email('b'),))
        filas = cur.fetchall()
    assert len(filas) == 1 and filas[0]['tipo'] == 'cliente'     # no le cambia el tipo
    assert filas[0]['telefono'] == '3115550000' and 'prueba-gratis' in filas[0]['tags']


def test_activacion_crea_actividad_y_una_sola_tarea(limpiar, cursor):
    cid, _ = pcs.crear_trial('Café Zyx', 'Leo Zyx', _email('c'), f'cafe-{MARCA}', telefono='3201234567')
    compra = dict(pcs.get_por_id(cid), dominio=f'cafe-{MARCA}.cybershopcol.com',
                  proximo_pago=date.today() + timedelta(days=15), token_renovacion='tok')
    contacto = crmp.prueba_activada(compra)
    crmp.prueba_activada(compra)
    with cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM crm_tareas WHERE contacto_id = %s', (contacto,))
        assert cur.fetchone()['n'] == 1
        cur.execute('SELECT prioridad, fecha_limite, descripcion FROM crm_tareas WHERE contacto_id = %s', (contacto,))
        t = cur.fetchone()
        assert t['prioridad'] == 'alta' and t['fecha_limite'] == date.today() + timedelta(days=11)
        assert '3201234567' in t['descripcion'] and '/renovar/tok' in t['descripcion']
        cur.execute('SELECT COUNT(*) AS n FROM crm_actividades WHERE contacto_id = %s', (contacto,))
        assert cur.fetchone()['n'] >= 1


def test_panel_calcula_estado_y_dias(limpiar, cursor):
    hoy = date(2026, 10, 1)
    filas = [('ACTIVADA', True, hoy + timedelta(days=10), 'a'), ('ACTIVADA', True, hoy + timedelta(days=2), 'b'),
             ('ACTIVADA', True, hoy - timedelta(days=3), 'c'), ('ACTIVADA', False, hoy + timedelta(days=20), 'd'),
             ('TRIAL_PENDIENTE', True, None, 'e')]
    with cursor() as cur:
        for estado, es_trial, vence, n in filas:
            cur.execute("""INSERT INTO plan_compras (referencia_pedido, plan_key, buyer_email, buyer_telefono,
                                                     estado, es_trial, proximo_pago, nombre_negocio)
                           VALUES (%s, 'ultra', %s, '3001234567', %s, %s, %s, 'N')""",
                        (f'TRIAL-PY{MARCA}{n}', _email(n), estado, es_trial, vence))
    pruebas, conteo = crmp.listar('todas', hoy=hoy)
    mias = {p['buyer_email'][-13:-12]: p for p in pruebas if MARCA in p['buyer_email']}
    assert mias['a']['estado_clave'] == 'activa' and mias['a']['dias_restantes'] == 10
    assert mias['b']['estado_clave'] == 'por_vencer'
    assert mias['c']['estado_clave'] == 'vencida' and mias['c']['estado_texto'].startswith('Vencida hace 3')
    assert mias['d']['estado_clave'] == 'convertida'
    assert mias['e']['estado_clave'] == 'pendiente'
    assert mias['a']['whatsapp_url'] == 'https://wa.me/573001234567'


# ── Rutas ──────────────────────────────────────────────────────
@pytest.fixture()
def software_visible(flask_app):
    from services.public_site_service import is_public_section_enabled, set_public_section
    with flask_app.test_request_context('/'):
        antes = is_public_section_enabled('mostrar_modulo_software', False)
        set_public_section('mostrar_modulo_software', True)
    yield
    with flask_app.test_request_context('/'):
        set_public_section('mostrar_modulo_software', antes)


def test_asistente_muestra_los_4_pasos(client, software_visible):
    html = client.get('/prueba-gratis').get_data(as_text=True)
    for texto in ('Tu negocio', 'Tu dirección web', 'Diseña tu página', 'Tus datos', 'Tu logo aquí',
                  'name="buyer_telefono"', 'prueba_gratis.js', 'no se conectan servicios externos'):
        assert texto in html


def test_whatsapp_obligatorio_vuelve_al_paso_4(client, software_visible, monkeypatch):
    import routes.public as pub
    monkeypatch.setattr(pub, '_slug_ocupado', lambda slug: False)
    r = client.post('/prueba-gratis', data={'nombre_negocio': 'Tienda Zyx', 'buyer_nombre': 'Ana Zyx',
                                            'buyer_email': _email('w'), 'buyer_telefono': '123',
                                            'subdominio': f'tienda-{MARCA}', 'color_marca': '#1e40af'})
    html = r.get_data(as_text=True)
    assert 'WhatsApp de 10 dígitos' in html and 'data-error-paso="4"' in html


def test_color_sin_contraste_vuelve_al_paso_3(client, software_visible, monkeypatch):
    import routes.public as pub
    monkeypatch.setattr(pub, '_slug_ocupado', lambda slug: False)
    r = client.post('/prueba-gratis', data={'nombre_negocio': 'Tienda Zyx', 'buyer_nombre': 'Ana Zyx',
                                            'buyer_email': _email('x'), 'buyer_telefono': '3001234567',
                                            'subdominio': f'tienda-{MARCA}', 'color_marca': '#fefefe'})
    assert 'data-error-paso="3"' in r.get_data(as_text=True)


def test_verificar_direccion(client, software_visible, monkeypatch):
    import services.master_client as mc
    monkeypatch.setattr(mc, 'slug_disponible', lambda slug: (slug != 'ocupada', ''))
    assert client.get('/prueba-gratis/slug?s=Mal_Nombre').get_json()['disponible'] is False
    assert client.get('/prueba-gratis/slug?s=ocupada').get_json()['disponible'] is False
    assert client.get(f'/prueba-gratis/slug?s=libre-{MARCA}').get_json()['disponible'] is True


def test_estado_de_activacion_solo_con_token(client):
    assert client.get('/activar-tienda/no-existe/estado').status_code == 404


def test_db_del_tenant_usa_el_mismo_nombre_que_el_maestro():
    from services.venta_automatica_service import _db_del_tenant
    assert _db_del_tenant(15) == 'cyber_t015'
    assert _db_del_tenant(150) == 'cyber_t150'
    assert _db_del_tenant(15, {'db_name': 'otra_bd'}) == 'otra_bd'


def test_crear_orden_sin_payu_no_va_a_la_pasarela(client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'PAYU_MERCHANT_ID', '')
    monkeypatch.setitem(flask_app.config, 'PAYU_API_KEY', '')
    with client.session_transaction() as s:
        s['carritoPendiente'] = {'items': [{'id': 1, 'cantidad': 1}], 'total': 1000}
    r = client.post('/crear-orden', data={'buyerFullName': 'X', 'buyerEmail': 'x@x.com'})
    assert r.status_code == 302 and '/metodos-pago' in r.headers['Location']


# ── Mi Negocio: color guiado ───────────────────────────────────
@pytest.fixture()
def colores_restaurables(flask_app):
    from services.public_site_service import get_brand_config, save_public_site_settings
    with flask_app.test_request_context('/'):
        antes = {k: get_brand_config().get(k) for k in marca.paleta_desde('#000000')}
    yield
    with flask_app.test_request_context('/'):
        save_public_site_settings(antes, list(antes))


@pytest.fixture()
def autoservicio(cursor):
    from services.config_tenant import set_cliente_config
    with cursor() as cur:
        cur.execute("SELECT valor FROM cliente_config WHERE clave = %s", (marca.CLAVE_AUTOSERVICIO,))
        fila = cur.fetchone()
        previo = fila['valor'] if fila else None
        set_cliente_config(cur, marca.CLAVE_AUTOSERVICIO, 'true')
    yield
    with cursor() as cur:
        if previo is None:
            cur.execute("DELETE FROM cliente_config WHERE clave = %s", (marca.CLAVE_AUTOSERVICIO,))
        else:
            cur.execute("UPDATE cliente_config SET valor = %s WHERE clave = %s", (previo, marca.CLAVE_AUTOSERVICIO))


def test_clientes_existentes_no_ven_ni_aplican_el_color(as_propietario, flask_app, colores_restaurables, cursor):
    with cursor() as cur:
        cur.execute("SELECT 1 FROM cliente_config WHERE clave = %s AND valor = 'true'", (marca.CLAVE_AUTOSERVICIO,))
        if cur.fetchone():
            pytest.skip('la base de pruebas está marcada como autoservicio')
    from services.public_site_service import get_brand_config, clear_public_site_cache
    html = as_propietario.get('/admin/mi-negocio').get_data(as_text=True)
    assert 'Colores de tu marca' not in html and 'Personaliza tu tienda' not in html
    with flask_app.test_request_context('/'):
        antes = get_brand_config().get('color_primario')
    as_propietario.post('/admin/mi-negocio', data={'color_marca': '#0f766e'})
    with flask_app.test_request_context('/'):
        clear_public_site_cache()
        assert get_brand_config().get('color_primario') == antes


def test_tienda_nueva_queda_marcada_como_autoservicio():
    v = marca.valores_tienda_nueva(negocio='X', email='x@x.com', whatsapp=None)
    assert v[marca.CLAVE_AUTOSERVICIO] == 'true'


def test_mi_negocio_cambia_la_paleta_solo_si_cambia_el_color(as_propietario, flask_app, colores_restaurables,
                                                            autoservicio):
    from services.public_site_service import get_brand_config, clear_public_site_cache
    with flask_app.test_request_context('/'):
        actual = marca.normalizar(get_brand_config().get('color_primario')) or marca.NEUTRO
        secundario = get_brand_config().get('color_secundario')
    assert 'Colores de tu marca' in as_propietario.get('/admin/mi-negocio').get_data(as_text=True)
    as_propietario.post('/admin/mi-negocio', data={'color_marca': actual})
    with flask_app.test_request_context('/'):
        clear_public_site_cache()
        assert get_brand_config().get('color_secundario') == secundario, 'sin cambio de color no toca la paleta'
    as_propietario.post('/admin/mi-negocio', data={'color_marca': '#0f766e'})
    with flask_app.test_request_context('/'):
        clear_public_site_cache()
        b = get_brand_config()
        assert b['color_primario'] == '#0f766e' and b['color_secundario'] == marca.paleta_desde('#0f766e')['color_secundario']
    r = as_propietario.post('/admin/mi-negocio', data={'color_marca': '#fafafa'}, follow_redirects=True)
    assert 'muy claro' in r.get_data(as_text=True)


# ── Correo: validación, corregir, reenviar y vencimiento ───────
@pytest.mark.parametrize('correo, fragmento', [
    ('ana@gmial.com', 'ana@gmail.com'), ('ana@hotmial.com', 'ana@hotmail.com'),
    ('ana@yopmail.com', 'temporal'), ('ana@noexiste-zyx.com', 'no existe'),
    ('ana@', 'correo válido'), ('ana..b@gmail.com', 'correo válido'),
])
def test_correo_invalido_o_mal_escrito(correo, fragmento):
    from services import correo_service
    ok, err = correo_service.validar(correo)
    assert ok is None and fragmento in err


def test_correo_valido_se_normaliza():
    from services import correo_service
    assert correo_service.validar('  Ana.Perez@Gmail.com ') == ('ana.perez@gmail.com', None)


def test_corregir_correo_invalida_el_enlace_anterior(limpiar, cursor):
    cid, token = pcs.crear_trial('Tienda Zyx', 'Ana Zyx', _email('v'), f'corr-{MARCA}', telefono='3001234567')
    fila, err = pcs.cambiar_correo_trial(cid, _email('n'))
    assert err is None and fila['buyer_email'] == _email('n') and fila['token'] != token
    assert pcs.get_por_token(token) is None, 'el enlace enviado al correo equivocado ya no sirve'
    with cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM crm_contactos WHERE email = %s', (_email('n'),))
        assert cur.fetchone()['n'] == 1, 'el contacto del CRM queda con el correo corregido'
    assert pcs.cambiar_correo_trial(cid, _email('n'))[1].startswith('Ese es el mismo correo')
    pcs.marcar_trial_verificado(cid)
    assert pcs.cambiar_correo_trial(cid, _email('m'))[0] is None, 'confirmada: ya no se cambia'


def test_no_corrige_a_un_correo_que_ya_uso_prueba(limpiar):
    pcs.crear_trial('A', 'Ana Zyx', _email('p1'), f'p1-{MARCA}', telefono='3001234567')
    cid, _ = pcs.crear_trial('B', 'Bea Zyx', _email('p2'), f'p2-{MARCA}', telefono='3001234568')
    assert 'ya usó' in pcs.cambiar_correo_trial(cid, _email('p1'))[1]


def test_enlace_vence_y_libera_la_direccion(limpiar, cursor, client):
    cid, token = pcs.crear_trial('Vieja Zyx', 'Ana Zyx', _email('x1'), f'vieja-{MARCA}', telefono='3001234567')
    assert pcs.slug_reservado(f'vieja-{MARCA}')
    with cursor() as cur:
        cur.execute("UPDATE plan_compras SET verificacion_enviada_at = NOW() - INTERVAL '73 hours' WHERE id = %s", (cid,))
    assert not pcs.confirmacion_vigente(pcs.get_por_id(cid))
    assert not pcs.slug_reservado(f'vieja-{MARCA}'), 'un correo falso no aparta la dirección para siempre'
    r = client.get(f'/prueba-gratis/confirmar/{token}')
    assert r.status_code == 302 and '/prueba-gratis' in r.headers['Location']
    assert pcs.get_por_id(cid)['estado'] == 'TRIAL_PENDIENTE', 'un enlace vencido no crea nada'
    assert pcs.reenviar_trial(cid) and pcs.confirmacion_vigente(pcs.get_por_id(cid))


def test_pantalla_corregir_correo_por_sesion(limpiar, client, software_visible, monkeypatch):
    import routes.public as pub
    enviados = []
    monkeypatch.setattr(pub, '_enviar_confirmacion_trial', lambda compra: enviados.append(compra['buyer_email']) or True)
    r = client.post('/prueba-gratis/correo', data={'accion': 'reenviar'})
    assert r.status_code == 302, 'sin prueba en la sesión no se puede tocar ningún registro'
    cid, _ = pcs.crear_trial('Ses Zyx', 'Ana Zyx', _email('s1'), f'ses-{MARCA}', telefono='3001234567')
    with client.session_transaction() as sess:
        sess['trial_pendiente'] = cid
    html = client.post('/prueba-gratis/correo', data={'accion': 'corregir', 'email': 'ana@gmial.com'}).get_data(as_text=True)
    assert 'ana@gmail.com' in html and enviados == []
    html = client.post('/prueba-gratis/correo', data={'accion': 'corregir', 'email': _email('s2')}).get_data(as_text=True)
    assert 'corregimos tu correo' in html and _email('s2') in html and enviados == [_email('s2')]
    html = client.post('/prueba-gratis/correo', data={'accion': 'reenviar'}).get_data(as_text=True)
    assert 'otra vez' in html and enviados[-1] == _email('s2')
    assert 'Me equivoqué de correo' in html and 'Tu tienda se crea solo cuando confirmes tu correo' in html


def test_registro_con_correo_mal_escrito_vuelve_al_paso_4(client, software_visible, monkeypatch):
    import routes.public as pub
    monkeypatch.setattr(pub, '_slug_ocupado', lambda slug: False)
    html = client.post('/prueba-gratis', data={'nombre_negocio': 'Tienda Zyx', 'buyer_nombre': 'Ana Zyx',
                                               'buyer_email': 'ana@gmial.com', 'buyer_telefono': '3001234567',
                                               'subdominio': f'tienda-{MARCA}', 'color_marca': '#1e40af'}).get_data(as_text=True)
    assert 'ana@gmail.com' in html and 'data-error-paso="4"' in html
