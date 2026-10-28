# -*- coding: utf-8 -*-
"""Facturación electrónica en el panel de la tienda (1.9.16.0).

El portal tributario se simula: ninguna prueba sale a la red ni a la DIAN.

- La bandeja se ve (antes salía en blanco: usaba un bloque que la base no pinta).
- Cada tienda entra a SU portal con un enlace que da el portal, nunca con la
  llave maestra (que abría la vista de administrador de todos los clientes).
- Una tienda que hereda la llave de CyberShop no factura a nombre de otro.
- Los errores llegan en palabras simples; reversar libera la venta para volver
  a facturarla.
- Una tienda SIN el módulo no hace llamadas ni se rompe.
"""
import copy
import json
import uuid

import pytest
import requests

import routes.factura_electronica as fe

LLAVE_PROPIA = 'llave-propia-de-la-tienda'
LLAVE_COMPARTIDA = 'llave-del-conf-compartido'


class _Resp:
    def __init__(self, status=200, datos=None, contenido=None, headers=None):
        self.status_code = status
        if contenido is None:
            contenido = json.dumps(datos if datos is not None else {}).encode('utf-8')
        self.content = contenido
        self.headers = headers or {'Content-Type': 'application/json'}

    def json(self):
        return json.loads(self.content.decode('utf-8') or '{}')


class PortalFalso:
    """Respuestas programadas por (método, ruta); guarda cada llamada."""

    def __init__(self):
        self.llamadas = []
        self.rutas = {}

    def responder(self, metodo, ruta, *respuestas):
        self.rutas[(metodo, ruta)] = list(respuestas)

    def request(self, metodo, url, headers=None, json=None, params=None, timeout=None):
        ruta = url.split('/api/v1', 1)[-1]
        # Copia: como en HTTP real, lo enviado queda fijo aunque el dict cambie después.
        self.llamadas.append({'metodo': metodo, 'ruta': ruta, 'headers': dict(headers or {}),
                              'json': copy.deepcopy(json), 'params': params})
        cola = self.rutas.get((metodo, ruta))
        if not cola:
            return _Resp(404, {'error': 'no simulado'})
        respuesta = cola[0] if len(cola) == 1 else cola.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    def get(self, url, headers=None, timeout=None):
        return self.request('GET', url, headers=headers)


@pytest.fixture()
def portal(monkeypatch):
    falso = PortalFalso()
    monkeypatch.setattr(fe.requests, 'request', falso.request)
    monkeypatch.setattr(fe.requests, 'get', falso.get)
    monkeypatch.setattr(fe, 'DIAN_API_KEY', LLAVE_PROPIA)
    monkeypatch.setattr(fe, '_llave_compartida', lambda: LLAVE_COMPARTIDA)
    monkeypatch.setattr(fe, '_es_tienda_operadora', lambda: False)
    return falso


@pytest.fixture()
def modulo_on(monkeypatch):
    monkeypatch.setattr(fe, 'facturacion_habilitada', lambda: True)


@pytest.fixture()
def modulo_off(monkeypatch):
    monkeypatch.setattr(fe, 'facturacion_habilitada', lambda: False)


ME = {'nombre': 'Tienda QA', 'razon_social': 'TIENDA QA SAS', 'nit': '900123456', 'dv': 7,
      'ambiente': 'habilitacion', 'prefijo': 'QA', 'resolucion': '18760000001',
      'vigencia_hasta': '2028-10-26', 'modo_aprobacion': 'automatico', 'grace_minutos': 30,
      'grace_maximo': 21600, 'portal_activo': True, 'listo_para_emitir': True}


# ── Conexión: quién factura y con qué llave ─────────────────────────────────

def test_sin_llave_no_hay_conexion(monkeypatch):
    monkeypatch.setattr(fe, 'DIAN_API_KEY', '')
    ok, motivo = fe.estado_conexion_local()
    assert not ok and 'todavía no está conectada' in motivo


def test_llave_heredada_de_cyberShop_no_factura_a_nombre_de_otro(portal, monkeypatch):
    monkeypatch.setattr(fe, 'DIAN_API_KEY', LLAVE_COMPARTIDA)
    ok, motivo = fe.estado_conexion_local()
    assert not ok and 'a nombre de otro' in motivo
    res = fe._emitir_a_dian('cotizaciones', 1, {'referencia_pedido': 'COT-1'})
    assert res['error'] == motivo
    assert portal.llamadas == []          # no se habló con el portal


def test_la_tienda_operadora_si_usa_la_llave_compartida(portal, monkeypatch):
    monkeypatch.setattr(fe, 'DIAN_API_KEY', LLAVE_COMPARTIDA)
    monkeypatch.setattr(fe, '_es_tienda_operadora', lambda: True)
    assert fe.estado_conexion_local() == (True, None)


@pytest.mark.parametrize('respuesta, esperado', [
    (_Resp(403, {'error': 'API Key inválido o tenant inactivo'}), 'rechazó la conexión'),
    (_Resp(500, {'error': 'Traceback…'}), 'error interno'),
    (requests.exceptions.ConnectionError('caído'), 'No hay conexión'),
    (requests.exceptions.Timeout('lento'), 'tardó demasiado'),
    (_Resp(422, {'error': 'cliente.email debe tener formato válido'}), 'El correo del cliente debe tener formato válido'),
    (_Resp(422, {'error': 'items[1].precio_unitario no puede ser negativo'}), 'El producto 2 (precio) no puede ser negativo'),
])
def test_errores_en_palabras_simples(portal, respuesta, esperado):
    portal.responder('GET', '/config-envio', respuesta)
    res = fe.obtener_politica_envio()
    assert esperado in res['error']
    assert 'Traceback' not in res['error']


def test_informacion_de_conexion_con_portal_anterior(portal):
    """Un portal sin /me (aún no actualizado) igual confirma que la llave sirve."""
    portal.responder('GET', '/config-envio', _Resp(200, {'modo_aprobacion': 'manual', 'grace_minutos': 30}))
    assert fe.informacion_conexion() == {'ok': True, 'sin_detalle': True}


# ── Reemisión tras reversar o rechazo ───────────────────────────────────────

def test_reemite_con_referencia_nueva_si_la_anterior_fue_reversada(portal, monkeypatch):
    guardado = {}
    monkeypatch.setattr(fe, '_guardar_factura_id_tabla',
                        lambda tabla, rid, fid: guardado.update(tabla=tabla, id=rid, factura=fid))
    portal.responder('POST', '/facturas',
                     _Resp(200, {'id': 'vieja', 'estado': 'CANCELADA'}),
                     _Resp(202, {'id': 'nueva', 'estado': 'PENDIENTE'}))
    res = fe._emitir_a_dian('tabla_que_no_existe_pytest', 7, {'referencia_pedido': 'COT-7', 'items': []})
    assert res['id'] == 'nueva'
    refs = [ll['json']['referencia_pedido'] for ll in portal.llamadas]
    assert refs == ['COT-7', 'COT-7-R2']
    assert guardado == {'tabla': 'tabla_que_no_existe_pytest', 'id': 7, 'factura': 'nueva'}


def test_reversar_libera_la_venta(portal, monkeypatch):
    liberadas = []
    monkeypatch.setattr(fe, 'desvincular_factura', liberadas.append)
    portal.responder('POST', '/facturas/abc/cancelar', _Resp(200, {'estado': 'CANCELADA'}))
    assert not fe.cancelar_factura_dian('abc').get('error')
    assert liberadas == ['abc']


def test_reversar_fallido_no_libera(portal, monkeypatch):
    liberadas = []
    monkeypatch.setattr(fe, 'desvincular_factura', liberadas.append)
    portal.responder('POST', '/facturas/abc/cancelar', _Resp(409, {'error': 'ya fue procesada'}))
    assert fe.cancelar_factura_dian('abc')['error'] == 'Ya fue procesada'
    assert liberadas == []


def test_desvincular_quita_la_marca_de_facturada(cursor):
    col = fe.columna_fe('cuentas_cobro')
    assert col, 'falta la migración 0026 en la base de pruebas'
    marca = str(uuid.uuid4())
    with cursor() as cur:
        cur.execute(f"""INSERT INTO cuentas_cobro (consecutivo, fecha, cliente_nombre, cliente_nit,
                                                    contractor_nombre, contractor_id, total, {col})
                       VALUES (%s, CURRENT_DATE, 'PYTEST FE', '900123456', 'PYTEST', '1', 1000, %s)
                       RETURNING id""", (f'PYTEST-{marca[:8]}', marca))
        cid = cur.fetchone()['id']
    try:
        fe.desvincular_factura(marca)
        with cursor() as cur:
            cur.execute(f"SELECT {col} AS doc FROM cuentas_cobro WHERE id = %s", (cid,))
            assert cur.fetchone()['doc'] is None
    finally:
        with cursor() as cur:
            cur.execute("DELETE FROM cuentas_cobro WHERE id = %s", (cid,))


# ── Bandeja ─────────────────────────────────────────────────────────────────

DOCS = {'items': [
    {'id': 'd1', 'estado': 'PENDIENTE', 'numero_factura': None, 'referencia_pedido': 'POS-20261027-0001',
     'error_mensaje': None, 'requiere_aprobacion': True, 'procesar_en': '2026-10-27T10:00:00',
     'creado_en': '2026-10-27T09:00:00', 'cancelable': True},
    {'id': 'd2', 'estado': 'ACEPTADA', 'numero_factura': 'QA1', 'referencia_pedido': 'COT-15',
     'error_mensaje': None, 'requiere_aprobacion': False, 'procesar_en': None,
     'creado_en': '2026-10-26T09:00:00', 'cancelable': False},
    {'id': 'd3', 'estado': 'RECHAZADA', 'numero_factura': 'QA2', 'referencia_pedido': 'CC-0004',
     'error_mensaje': 'Regla FAU14: total no cuadra', 'requiere_aprobacion': False, 'procesar_en': None,
     'creado_en': '2026-10-25T09:00:00', 'cancelable': False},
]}


def _portal_bandeja(portal):
    portal.responder('GET', '/me', _Resp(200, ME))
    portal.responder('GET', '/facturas', _Resp(200, DOCS))
    portal.responder('GET', '/config-envio', _Resp(200, {'modo_aprobacion': 'automatico', 'grace_minutos': 30}))


def test_bandeja_se_ve_con_lo_que_entiende_el_dueno(as_propietario, portal, modulo_on):
    _portal_bandeja(portal)
    h = as_propietario.get('/admin/facturacion-dian/bandeja').get_data(as_text=True)
    assert 'Conexión con la DIAN' in h and 'TIENDA QA SAS' in h and 'NIT 900123456-7' in h
    assert 'Modo de pruebas' in h
    assert 'Venta en el POS' in h and 'Cotización' in h and 'Cuenta de cobro' in h
    assert 'Espera que la envíes' in h and 'Aceptada por la DIAN' in h and 'Rechazada por la DIAN' in h
    assert 'Regla FAU14' in h
    assert '/admin/facturacion-dian/bandeja/d1/enviar' in h
    assert '/admin/facturacion-dian/bandeja/d1/reversar' in h
    assert '/admin/facturacion-dian/bandeja/d2/pdf' in h
    assert 'A los 15 días' in h and 'la DIAN exige expedir la factura' in h


def test_bandeja_sin_conexion_explica_que_pasa(as_propietario, portal, modulo_on):
    portal.responder('GET', '/me', _Resp(403, {'error': 'API Key inválido o tenant inactivo'}))
    h = as_propietario.get('/admin/facturacion-dian/bandeja').get_data(as_text=True)
    assert 'No hay conexión con el portal tributario' in h and 'rechazó la conexión' in h
    assert 'Mis facturas electrónicas' not in h
    assert [ll['ruta'] for ll in portal.llamadas] == ['/me']


def test_portal_con_enlace_de_la_tienda_no_con_la_maestra(as_propietario, portal, modulo_on):
    portal.responder('GET', '/portal/token',
                     _Resp(200, {'url': 'https://portal.test/ui/tenant-auto-login?tenant=t1', 'expires_in': 30}))
    r = as_propietario.get('/admin/facturacion-dian')
    assert r.status_code == 302 and 'tenant-auto-login' in r.headers['Location']
    assert '/ui/auto-login' not in r.headers['Location']


def test_portal_no_habilitado_vuelve_a_la_bandeja(as_propietario, portal, modulo_on):
    portal.responder('GET', '/portal/token', _Resp(403, {'error': 'El portal no está habilitado'}))
    r = as_propietario.get('/admin/facturacion-dian')
    assert r.status_code == 302 and r.headers['Location'].endswith('/admin/facturacion-dian/bandeja')


NO_HABILITADO = {'error': 'El portal no está habilitado para este tenant. Contacta al administrador.'}


def test_enlace_portal_desactualizado(portal):
    """El portal viejo responde «no habilitado» SIEMPRE: hay que decir que falta actualizarlo."""
    portal.responder('GET', '/portal/token', _Resp(403, NO_HABILITADO))
    portal.responder('GET', '/me', _Resp(404, {'error': 'Endpoint no encontrado'}))
    assert 'desactualizado' in fe.enlace_portal()['error']


def test_enlace_portal_acceso_apagado(portal):
    portal.responder('GET', '/portal/token', _Resp(403, NO_HABILITADO))
    portal.responder('GET', '/me', _Resp(200, ME))
    assert 'Acceso al portal: Habilitado' in fe.enlace_portal()['error']


def test_enlace_portal_llave_rechazada(portal):
    portal.responder('GET', '/portal/token', _Resp(403, {'error': 'API Key inválido o tenant inactivo'}))
    assert 'rechazó la conexión' in fe.enlace_portal()['error']


def test_funcion_que_el_portal_viejo_no_tiene(portal):
    portal.responder('POST', '/facturas/d1/enviar', _Resp(404, {'error': 'Endpoint no encontrado'}))
    assert 'desactualizado' in fe.enviar_factura_ya('d1')['error']


def test_bandeja_avisa_portal_desactualizado(as_propietario, portal, modulo_on):
    portal.responder('GET', '/me', _Resp(404, {'error': 'Endpoint no encontrado'}))
    portal.responder('GET', '/config-envio', _Resp(200, {'modo_aprobacion': 'automatico', 'grace_minutos': 30}))
    portal.responder('GET', '/facturas', _Resp(200, {'items': []}))
    h = as_propietario.get('/admin/facturacion-dian/bandeja').get_data(as_text=True)
    assert 'Conectado con el portal tributario' in h and 'está desactualizado' in h


def test_enviar_ya(as_propietario, portal, modulo_on):
    portal.responder('POST', '/facturas/d1/enviar', _Resp(200, {'estado': 'PENDIENTE'}))
    r = as_propietario.post('/admin/facturacion-dian/bandeja/d1/enviar')
    assert r.status_code == 302
    assert portal.llamadas[-1]['ruta'] == '/facturas/d1/enviar'
    assert portal.llamadas[-1]['headers'].get('X-Usuario') == 'PytestUser'


def test_ver_pdf(as_propietario, portal, modulo_on):
    portal.responder('GET', '/facturas/d2/pdf', _Resp(200, contenido=b'%PDF-1.4 prueba', headers={
        'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename=QA1.pdf'}))
    r = as_propietario.get('/admin/facturacion-dian/bandeja/d2/pdf')
    assert r.status_code == 200 and r.mimetype == 'application/pdf'
    assert r.data.startswith(b'%PDF') and 'QA1.pdf' in r.headers['Content-Disposition']


@pytest.mark.parametrize('envio, modo, espera', [('21600', 'automatico', 21600), ('1', 'automatico', 1)])
def test_politica_con_opciones_hasta_15_dias(as_propietario, portal, modulo_on, envio, modo, espera):
    portal.responder('PUT', '/config-envio', _Resp(200, {}))
    as_propietario.post('/admin/facturacion-dian/politica', data={'envio': envio})
    assert portal.llamadas[-1]['json'] == {'modo_aprobacion': modo, 'grace_minutos': espera}


def test_politica_manual_conserva_la_espera(as_propietario, portal, modulo_on):
    portal.responder('GET', '/config-envio', _Resp(200, {'modo_aprobacion': 'automatico', 'grace_minutos': 120}))
    portal.responder('PUT', '/config-envio', _Resp(200, {}))
    as_propietario.post('/admin/facturacion-dian/politica', data={'envio': 'manual'})
    assert portal.llamadas[-1]['json'] == {'modo_aprobacion': 'manual', 'grace_minutos': 120}


def test_politica_rechaza_valores_fuera_de_la_lista(as_propietario, portal, modulo_on):
    as_propietario.post('/admin/facturacion-dian/politica', data={'envio': '99999'})
    assert not any(ll['metodo'] == 'PUT' for ll in portal.llamadas)


# ── Tiendas sin facturación electrónica ─────────────────────────────────────

def test_tienda_sin_modulo_no_llama_y_no_se_rompe(as_propietario, portal, modulo_off):
    assert 'Módulo no activado' in as_propietario.get('/admin/facturacion-dian/bandeja').get_data(as_text=True)
    assert 'Módulo no activado' in as_propietario.get('/admin/facturacion-dian').get_data(as_text=True)
    assert as_propietario.post('/admin/pos/1/facturar').status_code == 403
    assert as_propietario.post('/admin/cuenta_cobro/1/facturar').status_code == 403
    assert as_propietario.post('/admin/cotizar/1/facturar').status_code == 403
    cuentas = as_propietario.get('/admin/mis_cuentas_cobro')
    assert cuentas.status_code == 200 and 'class="cc-fe-btn"' not in cuentas.get_data(as_text=True)
    cotizaciones = as_propietario.get('/admin/mis_cotizaciones')
    assert cotizaciones.status_code == 200
    assert 'class="btn-act btn-facturar-fe"' not in cotizaciones.get_data(as_text=True)
    assert portal.llamadas == []


def test_pos_sin_modulo_vende_sin_factura(as_cajero, portal, modulo_off, flask_app):
    from database import get_db_cursor
    import tenant_features as tf
    with get_db_cursor() as cur:
        cur.execute("UPDATE cliente_config SET valor='false' WHERE clave='caja_habilitado'")
    tf._clear_cache()
    vid = None
    try:
        r = as_cajero.post('/admin/pos/procesar', json={
            'items': [{'producto_id': None, 'descripcion': 'Item FE pytest', 'cantidad': 1, 'precio_unitario': 1000}],
            'facturar_electronicamente': True, 'cliente_nombre': 'PYTEST'})
        d = r.get_json()
        vid = d.get('venta_id')
        assert d['success'] and d['factura_electronica'] is None
        assert portal.llamadas == []
    finally:
        with get_db_cursor() as cur:
            if vid:
                cur.execute("DELETE FROM contabilidad_movimientos WHERE referencia_tipo='venta_pos' AND referencia_id=%s", (vid,))
                cur.execute("DELETE FROM detalle_venta_pos WHERE venta_id=%s", (vid,))
                cur.execute("DELETE FROM ventas_pos WHERE id=%s", (vid,))
            cur.execute("UPDATE cliente_config SET valor='true' WHERE clave='caja_habilitado'")
        tf._clear_cache()


def test_pos_con_modulo_deja_la_factura_en_cola_al_cobrar(as_cajero, portal, modulo_on, flask_app):
    """El cajero marca «Facturar electrónicamente» y cobra: la factura queda en
    cola sin un segundo botón (que además el cajero no tenía permitido)."""
    from database import get_db_cursor
    import tenant_features as tf
    portal.responder('POST', '/facturas', _Resp(202, {'id': str(uuid.uuid4()), 'estado': 'PENDIENTE'}))
    with get_db_cursor() as cur:
        cur.execute("UPDATE cliente_config SET valor='false' WHERE clave='caja_habilitado'")
    tf._clear_cache()
    vid = None
    try:
        r = as_cajero.post('/admin/pos/procesar', json={
            'items': [{'producto_id': None, 'descripcion': 'Item FE pytest', 'cantidad': 2, 'precio_unitario': 1500}],
            'facturar_electronicamente': True, 'cliente_nombre': 'PYTEST',
            'cliente_documento': '1027150819', 'cliente_email': 'qa@example.com', 'cliente_tipo_doc': 'CC'})
        d = r.get_json()
        vid = d.get('venta_id')
        assert d['success'] and d['factura_electronica'] == {'ok': True, 'estado': 'PENDIENTE'}
        enviado = portal.llamadas[-1]['json']
        assert enviado['referencia_pedido'] == d['numero_venta']
        assert enviado['cliente']['email'] == 'qa@example.com'
        assert enviado['items'][0]['cantidad'] == 2
    finally:
        with get_db_cursor() as cur:
            if vid:
                cur.execute("DELETE FROM contabilidad_movimientos WHERE referencia_tipo='venta_pos' AND referencia_id=%s", (vid,))
                cur.execute("DELETE FROM detalle_venta_pos WHERE venta_id=%s", (vid,))
                cur.execute("DELETE FROM ventas_pos WHERE id=%s", (vid,))
            cur.execute("UPDATE cliente_config SET valor='true' WHERE clave='caja_habilitado'")
        tf._clear_cache()


def test_pos_si_el_portal_falla_la_venta_igual_se_guarda(as_cajero, portal, modulo_on, flask_app):
    from database import get_db_cursor
    import tenant_features as tf
    portal.responder('POST', '/facturas', requests.exceptions.ConnectionError('caído'))
    with get_db_cursor() as cur:
        cur.execute("UPDATE cliente_config SET valor='false' WHERE clave='caja_habilitado'")
    tf._clear_cache()
    vid = None
    try:
        d = as_cajero.post('/admin/pos/procesar', json={
            'items': [{'producto_id': None, 'descripcion': 'Item FE pytest', 'cantidad': 1, 'precio_unitario': 1000}],
            'facturar_electronicamente': True, 'cliente_nombre': 'PYTEST'}).get_json()
        vid = d.get('venta_id')
        assert d['success'] and vid
        assert d['factura_electronica']['ok'] is False
        assert 'No hay conexión' in d['factura_electronica']['mensaje']
    finally:
        with get_db_cursor() as cur:
            if vid:
                cur.execute("DELETE FROM contabilidad_movimientos WHERE referencia_tipo='venta_pos' AND referencia_id=%s", (vid,))
                cur.execute("DELETE FROM detalle_venta_pos WHERE venta_id=%s", (vid,))
                cur.execute("DELETE FROM ventas_pos WHERE id=%s", (vid,))
            cur.execute("UPDATE cliente_config SET valor='true' WHERE clave='caja_habilitado'")
        tf._clear_cache()


# ── Cotización aprobada sin factura ─────────────────────────────────────────

@pytest.fixture()
def cotizacion_aprobada(cursor):
    with cursor() as cur:
        cur.execute("""INSERT INTO cotizaciones (cliente_nombre, cliente_documento, total, estado)
                       VALUES ('PYTEST FE COT', '900123456', 119000, 'aprobada') RETURNING id""")
        cid = cur.fetchone()['id']
        cur.execute("""INSERT INTO detalle_cotizacion (cotizacion_id, descripcion, cantidad, precio_unitario,
                                                       subtotal, descuento_porc, iva_porc)
                       VALUES (%s, 'Servicio pytest', 1, 100000, 100000, 0, 19)""", (cid,))
    yield cid
    with cursor() as cur:
        cur.execute("DELETE FROM detalle_cotizacion WHERE cotizacion_id = %s", (cid,))
        cur.execute("DELETE FROM cotizaciones WHERE id = %s", (cid,))


def test_cotizacion_aprobada_se_puede_facturar_despues(as_propietario, portal, modulo_on,
                                                      cotizacion_aprobada, cursor):
    fid = str(uuid.uuid4())
    portal.responder('POST', '/facturas', _Resp(202, {'id': fid, 'estado': 'PENDIENTE'}))
    r = as_propietario.post(f'/admin/cotizar/{cotizacion_aprobada}/facturar')
    assert r.get_json() == {'success': True, 'factura_id': fid, 'estado': 'PENDIENTE'}
    assert portal.llamadas[-1]['json']['referencia_pedido'] == f'COT-{cotizacion_aprobada}'
    col = fe.columna_fe('cotizaciones')
    with cursor() as cur:
        cur.execute(f"SELECT {col} AS doc FROM cotizaciones WHERE id = %s", (cotizacion_aprobada,))
        assert str(cur.fetchone()['doc']) == fid
    # Y en la lista ya no ofrece facturarla otra vez
    h = as_propietario.get('/admin/mis_cotizaciones').get_data(as_text=True)
    assert f'data-id="{cotizacion_aprobada}"' not in h


def test_cotizacion_pendiente_no_se_factura(as_propietario, portal, modulo_on, cursor):
    with cursor() as cur:
        cur.execute("""INSERT INTO cotizaciones (cliente_nombre, total, estado)
                       VALUES ('PYTEST FE PEND', 1000, 'pendiente') RETURNING id""")
        cid = cur.fetchone()['id']
    try:
        r = as_propietario.post(f'/admin/cotizar/{cid}/facturar')
        assert r.status_code == 400 and portal.llamadas == []
    finally:
        with cursor() as cur:
            cur.execute("DELETE FROM cotizaciones WHERE id = %s", (cid,))


def test_listas_no_se_vacian_sin_las_columnas_de_factura(as_propietario, monkeypatch, modulo_off):
    """En bases sin las columnas de facturación electrónica (clientes nuevos sin
    la migración 0026), las listas de cotizaciones y cuentas igual se ven."""
    monkeypatch.setattr(fe, 'sql_columnas_fe',
                        lambda tabla: 'FALSE AS facturar_electronicamente, NULL AS factura_dian_id')
    import routes.quotes as rq
    llamadas = []
    real = rq.render_template

    def capturar(plantilla, **kw):
        if plantilla == 'mis_cotizaciones.html':
            llamadas.append(kw.get('cotizaciones'))
        return real(plantilla, **kw)
    monkeypatch.setattr(rq, 'render_template', capturar)
    assert as_propietario.get('/admin/mis_cotizaciones').status_code == 200
    assert as_propietario.get('/admin/mis_cuentas_cobro').status_code == 200
    assert llamadas and isinstance(llamadas[0], list)


def test_columnas_fe_sin_columnas_no_rompen(monkeypatch):
    monkeypatch.setattr(fe, '_table_has_column', lambda t, c: False)
    monkeypatch.setattr(fe, '_tipo_columna', lambda t, c: None)
    assert fe.columna_fe('cotizaciones') is None
    assert fe.sql_columnas_fe('cotizaciones') == 'FALSE AS facturar_electronicamente, NULL AS factura_dian_id'


# ── La tienda operadora (dueña del portal) entra como administrador ─────────

def test_operador_se_decide_por_su_base(monkeypatch):
    import database
    monkeypatch.setattr(fe, '_base_del_conf', lambda: 'cybershop')
    monkeypatch.setattr(database, '_current_db_name', lambda: 'cybershop')
    assert fe._es_tienda_operadora() is True
    monkeypatch.setattr(database, '_current_db_name', lambda: 'cyber_t014')
    assert fe._es_tienda_operadora() is False          # un cliente no puede hacerse pasar
    monkeypatch.setattr(fe, '_base_del_conf', lambda: '')
    monkeypatch.setattr(database, '_current_db_name', lambda: '')
    assert fe._es_tienda_operadora() is False


def test_operador_entra_al_portal_como_administrador(as_propietario, portal, modulo_on, monkeypatch):
    monkeypatch.setattr(fe, '_es_tienda_operadora', lambda: True)
    monkeypatch.setenv('DIAN_MASTER_KEY', 'maestra-pytest')
    monkeypatch.setenv('DIAN_UI_URL', 'https://portal.test/ui')
    r = as_propietario.get('/admin/facturacion-dian')
    assert r.status_code == 302
    assert r.headers['Location'].startswith('https://portal.test/ui/auto-login?token=')
    assert portal.llamadas == []


def test_cliente_nunca_entra_como_administrador(as_propietario, portal, modulo_on, monkeypatch):
    monkeypatch.setenv('DIAN_MASTER_KEY', 'maestra-heredada')   # aunque la herede del conf
    portal.responder('GET', '/portal/token',
                     _Resp(200, {'url': 'https://portal.test/ui/tenant-auto-login?tenant=t1', 'expires_in': 30}))
    r = as_propietario.get('/admin/facturacion-dian')
    assert 'tenant-auto-login' in r.headers['Location'] and 'auto-login?token' not in r.headers['Location'].replace('tenant-auto-login', '')
