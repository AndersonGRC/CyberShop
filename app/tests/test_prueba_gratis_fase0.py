# -*- coding: utf-8 -*-
"""Prueba gratis — arreglos urgentes (1.9.7.0):

- al convertir la prueba, la tienda NO hereda las llaves de CyberShop y una
  renovación se acredita una sola vez aunque el webhook y la página lleguen juntos;
- «tu tienda está lista» solo cuando lo está (marca, instancia y correo) y, si la
  creación falla, el operador se entera y el cliente ve cómo reintentar;
- el día 16 la tienda queda en PAUSA (no apagada): los visitantes ven el aviso,
  el dueño puede entrar y ve cómo activar su plan, y el correo dice la verdad;
- la tienda refleja su estado real (sincronizar) solo si es autoservicio;
- el píxel sale de la configuración de cada tienda y nunca en páginas con token;
- los correos no dejan pasar HTML de lo que escribió el cliente.

Contra la base de pruebas; lo creado se borra y lo cambiado se restaura."""
import time
import uuid
from datetime import date, timedelta

import pytest

import app as app_mod
from services import plan_compras_service as pcs
from services import tienda_estado_sync as tes

MARCA = uuid.uuid4().hex[:8]
CLAVES = ('tienda_autoservicio', 'trial_hasta', 'trial_renovar_url', 'trial_pausada', 'trial_eliminar_desde',
          'plan_renovar_url', 'soporte_whatsapp', 'soporte_email')


# ── Utilidades ─────────────────────────────────────────────────
@pytest.fixture()
def compras(cursor):
    """Filas de plan_compras de prueba (se borran al final)."""
    pcs._ensure_table()
    creadas = []

    def crear(**campos):
        n = len(creadas)
        fila = {'referencia_pedido': f'PYTEST-F0-{MARCA}-{n}', 'plan_key': 'ultra', 'periodo': 'mes',
                'buyer_email': f'pytest-f0-{MARCA}@ejemplo.com', 'buyer_nombre': 'Ana <b>Prueba</b>',
                'estado': 'ACTIVADA', **campos}
        columnas = ', '.join(fila)
        with cursor() as cur:
            cur.execute(f"INSERT INTO plan_compras ({columnas}) VALUES ({', '.join(['%s'] * len(fila))}) RETURNING *",
                        list(fila.values()))
            creada = dict(cur.fetchone())
        creadas.append(creada['id'])
        return creada
    yield crear
    with cursor() as cur:
        cur.execute('UPDATE plan_compras SET renovacion_de = NULL WHERE id = ANY(%s)', (creadas,))
        cur.execute('DELETE FROM plan_compras WHERE id = ANY(%s)', (creadas,))


@pytest.fixture()
def config_tienda(cursor):
    """Escribe claves en el cliente_config de la base de pruebas y las deja como estaban."""
    with cursor() as cur:
        cur.execute('SELECT clave, valor FROM cliente_config WHERE clave = ANY(%s)', (list(CLAVES),))
        antes = {r['clave']: r['valor'] for r in cur.fetchall()}

    def poner(**valores):
        from services.config_tenant import set_cliente_config
        with cursor() as cur:
            for clave, valor in valores.items():
                set_cliente_config(cur, clave, valor)
        for cache in (app_mod._PAUSA_CACHE, app_mod._TRIAL_CACHE, app_mod._DEMO_CACHE):
            cache['ts'] = 0

    def leer():
        with cursor() as cur:
            cur.execute('SELECT clave, valor FROM cliente_config WHERE clave = ANY(%s)', (list(CLAVES),))
            return {r['clave']: r['valor'] for r in cur.fetchall()}
    poner.leer = leer
    yield poner
    with cursor() as cur:
        cur.execute('DELETE FROM cliente_config WHERE clave = ANY(%s)', (list(CLAVES),))
        for clave, valor in antes.items():
            cur.execute("INSERT INTO cliente_config (clave, valor, tipo, grupo) VALUES (%s, %s, 'texto', 'sistema')",
                        (clave, valor))
    for cache in (app_mod._PAUSA_CACHE, app_mod._TRIAL_CACHE, app_mod._DEMO_CACHE):
        cache['ts'] = 0


# ── Conversión y renovación ────────────────────────────────────
def test_conversion_no_hereda_llaves_y_se_acredita_una_vez(flask_app, compras, monkeypatch):
    import services.master_client as mc
    import services.venta_automatica_service as vas
    hoy = date.today()
    padre = compras(es_trial=True, proximo_pago=hoy + timedelta(days=3), token_renovacion=f'tok-{MARCA}',
                    dominio='pytest.cybershopcol.com')
    hijo = compras(estado='PENDIENTE_PAGO', renovacion_de=padre['id'])
    modo, correos, sincronizadas = [], [], []
    monkeypatch.setattr(mc, 'modo_prueba', lambda tid, activo=True: modo.append(activo))
    monkeypatch.setattr(vas, 'limpiar_datos_trial', lambda c: None)
    monkeypatch.setattr(tes, 'sincronizar', lambda c: sincronizadas.append(dict(c)) or True)
    monkeypatch.setattr(vas, '_enviar', lambda destino, correo: correos.append((destino, correo[0])) or True)
    viejo = pcs.get_por_referencia(hijo['referencia_pedido'])      # leído ANTES (como en la carrera)
    with flask_app.app_context():
        assert vas.procesar_compra_plan(hijo['referencia_pedido']) == 'renovacion'
        # El webhook y la página de respuesta llegan a la vez: el segundo trae la fila vieja.
        monkeypatch.setattr(pcs, 'get_por_referencia', lambda ref: viejo)
        assert vas.procesar_compra_plan(hijo['referencia_pedido']) == 'ya-procesada'
    actual = pcs.get_por_id(padre['id'])
    assert actual['proximo_pago'] == pcs.siguiente_vencimiento(padre['proximo_pago'], 'mes')   # una sola vez
    assert actual['es_trial'] is False
    assert False not in modo                       # nunca se quitó el modo prueba (no hereda llaves)
    assert sincronizadas and sincronizadas[-1]['es_trial'] is False
    asuntos = [a for d, a in correos if d == padre['buyer_email']]
    assert asuntos and 'quedó activo' in asuntos[0]


def test_el_cliente_recibe_su_comprobante_sin_panel_maestro(flask_app):
    from helpers_email_templates import generar_email_pago_plan_cliente
    compra = {'buyer_nombre': '<script>x</script>', 'dominio': 'mi.cybershopcol.com',
              'proximo_pago': date(2026, 11, 16)}
    with flask_app.app_context():
        asunto, texto, html = generar_email_pago_plan_cliente(compra, {'nombre': 'Ultra', 'precio': 200000},
                                                              'REF-1', convertida=True)
    assert 'Panel maestro' not in html and 'admin.cybershopcol.com' not in html
    assert '<script>' not in html and '16/11/2026' in html and 'no es una factura electrónica' in html


# ── Creación: «lista» solo al final ────────────────────────────
@pytest.fixture()
def creacion_simulada(monkeypatch):
    import services.crm_pruebas_service as crm
    import services.master_client as mc
    import services.venta_automatica_service as vas
    pasos = []
    monkeypatch.setattr(mc, 'modo_prueba', lambda tid, activo=True: pasos.append(('integraciones_apagadas', activo)))
    monkeypatch.setattr(vas, '_sembrar_tienda_nueva', lambda c, r=None: True)
    monkeypatch.setattr(vas, '_sembrar_datos_trial', lambda c, r=None: None)
    monkeypatch.setattr(crm, 'prueba_activada', lambda c: None)
    monkeypatch.setattr(tes, 'sincronizar', lambda c: True)
    monkeypatch.setattr(vas, '_enviar', lambda destino, correo: pasos.append(('correo', correo[0])) or True)
    return pasos


def test_creacion_dice_lista_solo_al_final(flask_app, compras, creacion_simulada, monkeypatch):
    import services.master_client as mc
    import services.venta_automatica_service as vas
    compra = compras(es_trial=True, estado='ACTIVANDO', slug=f'pytest-{MARCA}', token=f'act-{MARCA}')
    monkeypatch.setattr(mc, 'crear_tenant_en_maestro', lambda **kw: {
        'tenant_id': 990000, 'domain': f'pytest-{MARCA}.cybershopcol.com', 'port': 1,
        'admin_email': 'a@b.co', 'admin_password': 'x'})

    def esperar(port, limite=90):
        fila = pcs.get_por_id(compra['id'])
        creacion_simulada.append(('esperando', fila['etapa'], pcs.esta_lista(fila)))
        return True
    monkeypatch.setattr(vas, '_esperar_tienda', esperar)
    vas.activar_tienda_async(flask_app, compra['id'], compra['slug'], 'Tienda').join(30)
    fila = pcs.get_por_id(compra['id'])
    assert ('esperando', 'encendiendo', False) in creacion_simulada     # ACTIVADA pero aún no «lista»
    assert ('integraciones_apagadas', True) in creacion_simulada
    assert [p for p in creacion_simulada if p[0] == 'correo'][0][1].startswith('🚀 Tu tienda está lista')
    assert fila['estado'] == 'ACTIVADA' and fila['etapa'] == 'lista' and pcs.esta_lista(fila)


def test_las_compras_pagadas_tambien_nacen_sin_llaves_de_cybershop(flask_app, compras, creacion_simulada,
                                                                   monkeypatch):
    import services.master_client as mc
    import services.venta_automatica_service as vas
    compra = compras(es_trial=False, estado='ACTIVANDO', slug=f'pytest-p-{MARCA}', token=f'actp-{MARCA}',
                     plan_key='software-cybershop')
    monkeypatch.setattr(mc, 'crear_tenant_en_maestro', lambda **kw: {'tenant_id': 990001, 'domain': 'p.x', 'port': 1})
    monkeypatch.setattr(vas, '_esperar_tienda', lambda port, limite=90: True)
    vas.activar_tienda_async(flask_app, compra['id'], compra['slug'], 'Tienda').join(30)
    assert ('integraciones_apagadas', True) in creacion_simulada


def test_si_falla_la_creacion_el_operador_se_entera(flask_app, compras, creacion_simulada, monkeypatch):
    import services.master_client as mc
    import services.venta_automatica_service as vas

    def falla(**kw):
        raise mc.MasterError('el maestro no respondió')
    monkeypatch.setattr(mc, 'crear_tenant_en_maestro', falla)
    compra = compras(es_trial=True, estado='ACTIVANDO', slug=f'pytest-e-{MARCA}', token=f'acte-{MARCA}')
    vas.activar_tienda_async(flask_app, compra['id'], compra['slug'], 'Tienda').join(30)
    assert pcs.get_por_id(compra['id'])['estado'] == 'ERROR'
    assert any(p[0] == 'correo' and 'No se pudo crear la tienda' in p[1] for p in creacion_simulada)


def test_estado_de_la_activacion(client, compras, cursor, monkeypatch):
    import services.venta_automatica_service as vas
    avisos = []
    monkeypatch.setattr(vas, 'avisar_falla_creacion', lambda c, s, d: avisos.append(d))
    a_medias = compras(es_trial=True, token=f'e1-{MARCA}', dominio='d.co')
    lista = compras(es_trial=True, token=f'e2-{MARCA}', dominio='d.co')
    vieja = compras(es_trial=True, token=f'e3-{MARCA}', dominio='d.co')
    atascada = compras(es_trial=True, estado='ACTIVANDO', token=f'e4-{MARCA}')
    with cursor() as cur:            # con el reloj de la BD, como en producción
        cur.execute('UPDATE plan_compras SET activated_at = NOW() WHERE id = ANY(%s)', ([a_medias['id'], lista['id']],))
        cur.execute('UPDATE plan_compras SET listo_at = NOW() WHERE id = %s', (lista['id'],))
        cur.execute("UPDATE plan_compras SET activated_at = NOW() - INTERVAL '20 minutes' WHERE id = %s", (vieja['id'],))
        cur.execute("UPDATE plan_compras SET activando_at = NOW() - INTERVAL '20 minutes' WHERE id = %s",
                    (atascada['id'],))
    assert client.get(f"/activar-tienda/{a_medias['token']}/estado").get_json()['estado'] == 'ACTIVANDO'
    assert client.get(f"/activar-tienda/{lista['token']}/estado").get_json() == {
        'estado': 'ACTIVADA', 'etapa': None, 'dominio': 'd.co'}
    assert client.get(f"/activar-tienda/{vieja['token']}/estado").get_json()['estado'] == 'ACTIVADA'
    assert client.get(f"/activar-tienda/{atascada['token']}/estado").get_json()['estado'] == 'ERROR'
    assert len(avisos) == 1
    client.get(f"/activar-tienda/{atascada['token']}/estado")
    assert len(avisos) == 1                                  # el aviso sale una sola vez


def test_pantalla_de_error_de_una_prueba(client, compras):
    compra = compras(es_trial=True, estado='ERROR', token=f'err-{MARCA}', slug=f'pytest-x-{MARCA}',
                     error='psql: FATAL detalle técnico')
    html = client.get(f"/activar-tienda/{compra['token']}").get_data(as_text=True)
    assert 'No pudimos terminar de crear tu tienda' in html and 'Intentar de nuevo' in html
    assert 'Tu pago está confirmado' not in html and 'FATAL' not in html


# ── Sincronizar y pausa del día 16 ─────────────────────────────
def test_valores_que_se_escriben_en_la_tienda():
    hoy = date.today()
    base = {'token_renovacion': 'tok', 'proximo_pago': hoy}
    escribir, borrar = tes.valores_para({**base, 'es_trial': True, 'suspendida_por_pago': False})
    assert escribir == {'trial_hasta': str(hoy), 'trial_renovar_url': 'https://cybershopcol.com/renovar/tok'}
    assert set(borrar) == {'trial_pausada', 'trial_eliminar_desde'}
    escribir, _ = tes.valores_para({**base, 'es_trial': True, 'suspendida_por_pago': True})
    assert escribir['trial_pausada'] == 'true'
    assert escribir['trial_eliminar_desde'] == str(hoy + timedelta(days=1 + tes.RETENCION_PRUEBA_DIAS))
    escribir, borrar = tes.valores_para({**base, 'es_trial': False})
    assert escribir == {'plan_renovar_url': 'https://cybershopcol.com/renovar/tok'}
    assert set(borrar) == set(tes.CLAVES_PRUEBA)


def test_sincronizar_solo_toca_tiendas_autoservicio(flask_app, config_tienda, monkeypatch):
    import os
    import services.venta_automatica_service as vas
    monkeypatch.setattr(vas, '_db_del_tenant', lambda tid, r=None: os.environ['DB_NAME'])
    monkeypatch.setattr(tes, 'soporte_operador', lambda: {'soporte_whatsapp': '573001112233', 'soporte_email': ''})
    compra = {'tenant_id': 1, 'estado': 'ACTIVADA', 'es_trial': True, 'suspendida_por_pago': True,
              'proximo_pago': date.today() - timedelta(days=1), 'token_renovacion': 'tok'}
    config_tienda(tienda_autoservicio='false')
    with flask_app.app_context():
        assert tes.sincronizar(compra) is False
        assert 'trial_pausada' not in config_tienda.leer()            # una tienda normal no se toca
        config_tienda(tienda_autoservicio='true', plan_renovar_url='viejo')
        assert tes.sincronizar(compra) is True
    valores = config_tienda.leer()
    assert valores['trial_pausada'] == 'true' and valores['soporte_whatsapp'] == '573001112233'
    assert valores['trial_renovar_url'].endswith('/renovar/tok')


def test_tienda_en_pausa_visitante_y_dueno(client, config_tienda):
    from tests.conftest import _login
    config_tienda(tienda_autoservicio='true', trial_pausada='true', trial_hasta='2026-10-15',
                  trial_eliminar_desde='2026-11-15', trial_renovar_url='https://cybershopcol.com/renovar/tok',
                  soporte_whatsapp='573001112233')
    r = client.get('/')
    html = r.get_data(as_text=True)
    assert r.status_code == 503 and 'está en pausa' in html
    assert '/renovar/tok' not in html                         # el enlace de pago no es público
    assert client.get('/login').status_code == 200            # el dueño puede entrar
    assert 'tienda_en_pausa' not in client.get('/api/v1/health').get_data(as_text=True)   # la revisión de salud sigue
    assert client.get('/api/v1/cualquier-cosa').get_json() == {'error': 'tienda_en_pausa',
                                                                'mensaje': 'La tienda está en pausa.'}
    _login(client, 2)
    html = client.get('/admin').get_data(as_text=True)
    assert 'Tu prueba gratis terminó' in html and '15/11/2026' in html
    assert 'https://cybershopcol.com/renovar/tok' in html and 'wa.me/573001112233' in html


def test_sin_autoservicio_no_hay_pausa(client, config_tienda):
    config_tienda(tienda_autoservicio='false', trial_pausada='true', trial_hasta='2026-10-15')
    assert client.get('/').status_code != 503


def test_aviso_de_prueba_terminada_no_dice_vence_hoy(flask_app, config_tienda):
    config_tienda(trial_hasta=str(date.today() - timedelta(days=3)), trial_renovar_url='https://x/renovar/t')
    with flask_app.app_context():
        info = app_mod._trial_banner_info()
    assert info['terminada'] is True and info['dias'] == 0


@pytest.fixture()
def cron(monkeypatch):
    """El cron de cobros con una sola prueba simulada; registra lo que hace."""
    import services.master_client as mc
    import tools.notificar_renovaciones as cron_mod
    hechos = {'correos': [], 'pausada': [], 'reanudada': [], 'sync': []}
    monkeypatch.setattr(pcs, 'compras_atascadas', lambda: [])
    monkeypatch.setattr(pcs, 'marcar_suspendida_por_pago', lambda cid: hechos['pausada'].append(cid))
    monkeypatch.setattr(pcs, 'marcar_recordatorio', lambda cid, etapa: None)
    monkeypatch.setattr(pcs, 'quitar_pausa', lambda cid: hechos['reanudada'].append(cid) or True)
    monkeypatch.setattr(tes, 'sincronizar', lambda c: hechos['sync'].append(dict(c)) or True)
    monkeypatch.setattr(cron_mod, '_enviar', lambda destino, correo: hechos['correos'].append(correo[0]) or True)
    monkeypatch.setattr(cron_mod, '_sincronizar_desde_panel', lambda compras: 0)

    def no_apagar(tid):
        raise AssertionError('una prueba vencida ya no apaga la tienda')
    monkeypatch.setattr(mc, 'suspender_tenant', no_apagar)

    def correr(compra):
        monkeypatch.setattr(pcs, 'compras_para_recordatorio', lambda: [compra])
        cron_mod.main()
        return hechos
    return correr


def _prueba(**campos):
    return {'id': -7, 'es_trial': True, 'suspendida_por_pago': False, 'dominio': 'p.cybershopcol.com',
            'buyer_email': 'p@ejemplo.com', 'buyer_nombre': 'Ana', 'buyer_telefono': '', 'token_renovacion': 'tok',
            'plan_key': 'ultra', 'tenant_id': 5, 'ultimo_recordatorio': 'trial15', **campos}


def test_dia_16_pausa_con_el_correo_correcto(flask_app, cron):
    with flask_app.app_context():
        hechos = cron(_prueba(proximo_pago=date.today() - timedelta(days=1)))
    assert hechos['pausada'] == [-7]
    assert hechos['sync'][0]['suspendida_por_pago'] is True
    assert any(a.startswith('Tu prueba gratis terminó') for a in hechos['correos'])
    assert not any('vence hoy' in a for a in hechos['correos'])


def test_mas_plazo_quita_la_pausa(flask_app, cron):
    with flask_app.app_context():
        hechos = cron(_prueba(proximo_pago=date.today() + timedelta(days=4), suspendida_por_pago=True))
    assert hechos['reanudada'] == [-7] and hechos['pausada'] == []
    assert hechos['sync'][-1]['suspendida_por_pago'] is False


def test_quien_tiene_prueba_no_compra_una_segunda_tienda(client, monkeypatch):
    import routes.public as pub
    from services.public_site_service import is_public_section_enabled as _orig
    from tests.conftest import _login
    enviados = []
    monkeypatch.setattr('services.public_site_service.is_public_section_enabled',
                        lambda clave, default=False: True if clave == 'mostrar_modulo_software' else _orig(clave, default))
    monkeypatch.setattr(pcs, 'prueba_activa_de', lambda correo: {
        'id': -3, 'plan_key': 'ultra', 'dominio': 'p.cybershopcol.com', 'token_renovacion': 'secreto'})
    monkeypatch.setattr(pub, '_enviar_enlace_activar_prueba', lambda prueba: enviados.append(prueba['id']) or True)
    _login(client, 3)
    r = client.get('/comprar-plan/ultra')
    assert r.status_code == 302 and '/software' in r.headers['Location'] and 'secreto' not in r.headers['Location']
    assert enviados == [-3]                                  # el enlace va a SU correo, no a la pantalla
    html = client.get('/comprar-plan/software-cybershop').get_data(as_text=True)
    assert 'tienda NUEVA y vacía' in html


# ── Píxel y correos ────────────────────────────────────────────
def test_pixel_desde_la_configuracion(client, monkeypatch):
    import routes.factura_electronica as fe
    from config import Config
    from services.meta_capi import should_track_pageview
    monkeypatch.setattr(fe, '_es_tienda_operadora', lambda: True)
    monkeypatch.setattr(Config, 'META_PIXEL_ID', '')
    assert "fbq('init'" not in client.get('/').get_data(as_text=True)      # tienda de prueba: sin píxel
    monkeypatch.setattr(Config, 'META_PIXEL_ID', '123456')
    assert "fbq('init', \"123456\")" in client.get('/').get_data(as_text=True)

    class _Req:
        method, headers = 'GET', {}

        def __init__(self, path):
            self.path = path
    assert should_track_pageview(_Req('/activar-tienda/token-secreto')) is False
    assert should_track_pageview(_Req('/renovar/token-secreto')) is False
    assert should_track_pageview(_Req('/software')) is True


def test_los_clientes_no_llevan_el_pixel(client, flask_app, monkeypatch):
    """Solo la tienda de CyberShop usa el píxel: un cliente que hereda el ID y el
    token del .conf compartido no lo pinta ni le manda nada a Meta."""
    import routes.factura_electronica as fe
    from config import Config
    from services import meta_capi
    monkeypatch.setattr(Config, 'META_PIXEL_ID', '4412332785657284')
    monkeypatch.setattr(Config, 'META_CAPI_ACCESS_TOKEN', 'token-heredado')
    enviados = []
    monkeypatch.setattr(meta_capi, '_send_sync',
                        lambda payload, logger, pixel: enviados.append((payload['data'][0]['event_name'], pixel)))

    monkeypatch.setattr(fe, '_es_tienda_operadora', lambda: False)        # tienda de un cliente
    assert "fbq('init'" not in client.get('/').get_data(as_text=True)
    with flask_app.test_request_context('/respuesta-pago'):
        assert meta_capi.pixel_id() == '' and meta_capi.is_enabled() is False
        meta_capi.send_event_async('Purchase', 'purchase-REF', user_data={})
    assert enviados == []                                                  # ni PageView ni Purchase

    monkeypatch.setattr(fe, '_es_tienda_operadora', lambda: True)         # CyberShop
    assert "fbq('init', \"4412332785657284\")" in client.get('/').get_data(as_text=True)
    with flask_app.test_request_context('/respuesta-pago'):
        meta_capi.send_event_async('Purchase', 'purchase-REF', user_data={})
    for _ in range(50):                                                    # el envío va en un hilo
        if ('Purchase', '4412332785657284') in enviados:
            break
        time.sleep(0.02)
    assert ('Purchase', '4412332785657284') in enviados


def test_correos_escapan_lo_que_escribe_el_cliente(flask_app):
    from helpers_email_templates import (generar_email_bienvenida_tienda, generar_email_confirmacion_trial,
                                         generar_email_trial_pausada)
    malo = {'buyer_nombre': '<a href="http://x">Gana</a>', 'nombre_negocio': '<img src=x onerror=1>',
            'dominio': 'p.cybershopcol.com', 'proximo_pago': date(2026, 10, 16), 'es_trial': True}
    with flask_app.app_context():
        _, _, html = generar_email_confirmacion_trial(malo, 'https://cybershopcol.com/c/t', '048213')
        assert '<a href="http://x">' not in html and '<img src=x' not in html
        _, _, html = generar_email_bienvenida_tienda(malo, {'nombre': 'Ultra'}, {'domain': 'p.cybershopcol.com'})
        assert 'https://p.cybershopcol.com/login' in html and 'Tu prueba gratis va hasta el 16/10/2026' in html
        asunto, _, html = generar_email_trial_pausada(malo, {'nombre': 'Ultra', 'precio': 200000},
                                                      'https://cybershopcol.com/renovar/t', date(2026, 11, 16))
    assert asunto.startswith('Tu prueba gratis terminó') and '16/11/2026' in html and 'en pausa' in html
