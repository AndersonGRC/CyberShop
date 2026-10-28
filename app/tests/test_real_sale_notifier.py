# -*- coding: utf-8 -*-
"""RealSaleNotifier: a Meta solo le llega la primera compra de un plan del
software por un cliente nuevo (no renovaciones, reactivaciones ni pedidos de
productos), una sola vez, cuando PayU la confirma en su webhook firmado, con el
valor y los productos del pedido guardado (no los de la URL), aunque el
cliente cierre el navegador. Contra la base de pruebas; todo lo creado se
borra al final."""
import hashlib
import uuid

import pytest

MARCA = uuid.uuid4().hex[:8].upper()
API_KEY = 'llave-de-prueba-pytest'
PIXEL = '4412332785657284'


def _firma_webhook(ref, valor, estado, merchant='508029', moneda='COP'):
    crudo = f"{API_KEY}~{merchant}~{ref}~{valor}~{moneda}~{estado}"
    return hashlib.md5(crudo.encode('utf-8')).hexdigest()


def _webhook(client, ref, estado='4', valor='1000.00'):
    """POST de PayU a /confirmacion-pago (la firma usa el valor con un decimal)."""
    return client.post('/confirmacion-pago', data={
        'merchant_id': '508029', 'reference_sale': ref, 'value': valor, 'currency': 'COP',
        'state_pol': estado, 'sign': _firma_webhook(ref, '1000.0', estado),
        'transaction_id': f'tx-{ref}', 'payment_method_name': 'PSE'})


@pytest.fixture()
def meta(flask_app, monkeypatch):
    """Tienda de CyberShop con píxel y token; registra cada envío a Meta y
    apaga los demás efectos del webhook (correo, CRM, planes, contabilidad)."""
    import helpers_gmail
    import routes.contabilidad as conta
    import routes.factura_electronica as fe
    import routes.payments as pagos
    import services.crm_service as crm
    import services.venta_automatica_service as vas
    from config import Config
    from services import meta_capi
    monkeypatch.setitem(flask_app.config, 'PAYU_API_KEY', API_KEY)
    monkeypatch.setattr(pagos.time, 'sleep', lambda s: None)
    monkeypatch.setattr(pagos, 'consultar_estado_real_payu', lambda ref: '7')
    monkeypatch.setattr(fe, '_es_tienda_operadora', lambda: True)
    monkeypatch.setattr(fe, 'facturacion_habilitada', lambda: False)
    monkeypatch.setattr(Config, 'META_PIXEL_ID', PIXEL)
    monkeypatch.setattr(Config, 'META_CAPI_ACCESS_TOKEN', 'token-prueba')
    monkeypatch.setattr(conta, 'registrar_movimiento', lambda **kw: None)
    monkeypatch.setattr(vas, 'procesar_compra_plan', lambda ref, base_url=None: None)
    monkeypatch.setattr(helpers_gmail, 'enviar_email_gmail', lambda *a, **k: True)
    monkeypatch.setattr(crm, 'upsert_contacto', lambda **kw: None)
    enviados = []
    monkeypatch.setattr(meta_capi, 'send_event_async', lambda event_name, **kw: enviados.append({'evento': event_name, **kw}))
    return enviados


def _compras(enviados):
    return [e for e in enviados if e['evento'] == 'Purchase']


@pytest.fixture()
def pedido(cursor):
    refs = []

    def crear(dias=0, email='ana@ejemplo.com'):
        ref = f'PYTEST-RSN-{MARCA}-{len(refs)}'
        with cursor() as cur:
            cur.execute("""INSERT INTO pedidos (referencia_pedido, cliente_nombre, cliente_email, cliente_telefono,
                                                monto_total, estado_pago, estado_envio, fecha_creacion)
                           VALUES (%s, 'Ana María Pytest', %s, '300 123 4567', 1000,
                                   'PENDIENTE', 'ESPERA_PAGO', CURRENT_TIMESTAMP - make_interval(days => %s))
                           RETURNING id""", (ref, email, dias))
            cur.execute("""INSERT INTO detalle_pedidos (pedido_id, producto_nombre, cantidad, precio_unitario, subtotal)
                           VALUES (%s, 'Plan: Básico', 1, 1000, 1000)""", (cur.fetchone()['id'],))
        refs.append(ref)
        return ref
    yield crear
    with cursor() as cur:
        cur.execute("SELECT to_regclass('ventas_reales_meta') IS NOT NULL AS hay")
        if cur.fetchone()['hay']:
            cur.execute('DELETE FROM ventas_reales_meta WHERE referencia_pedido = ANY(%s)', (refs,))
        cur.execute('DELETE FROM detalle_pedidos WHERE pedido_id IN '
                    '(SELECT id FROM pedidos WHERE referencia_pedido = ANY(%s))', (refs,))
        cur.execute('DELETE FROM pedidos WHERE referencia_pedido = ANY(%s)', (refs,))


@pytest.fixture()
def plan(cursor, pedido):
    """Compras de planes (plan_compras). Con pagar=True llevan su pedido
    pendiente (el webhook lo aprueba); sin él, solo la fila (prueba gratis o
    cliente cargado a mano al cobro automático)."""
    from services import plan_compras_service as pcs
    pcs._ensure_table()
    creadas = []

    def crear(email, renovacion_de=None, referencia=None, pagar=True, dias=0, **campos):
        fila = {'referencia_pedido': pedido(dias=dias, email=email) if pagar else referencia, 'plan_key': 'ultra',
                'buyer_email': email, 'renovacion_de': renovacion_de, 'estado': 'PENDIENTE_PAGO', **campos}
        with cursor() as cur:
            cur.execute(f"INSERT INTO plan_compras ({', '.join(fila)}) "
                        f"VALUES ({', '.join(['%s'] * len(fila))}) RETURNING id", list(fila.values()))
            creadas.append(cur.fetchone()['id'])
        return fila['referencia_pedido'], creadas[-1]
    yield crear
    with cursor() as cur:
        cur.execute('UPDATE plan_compras SET renovacion_de = NULL WHERE id = ANY(%s)', (creadas,))
        cur.execute('DELETE FROM plan_compras WHERE id = ANY(%s)', (creadas,))


def _avisados(enviados):
    return [c['custom_data']['order_id'] for c in _compras(enviados)]


def _correo(quien):
    """Un correo por prueba: el de otra prueba haría parecer «ya era cliente»."""
    return f'rsn-{quien}-{MARCA}@ejemplo.com'.lower()


def test_webhook_avisa_una_sola_vez_con_los_datos_del_pedido(client, flask_app, meta, plan):
    from services.real_sale_notifier import registrar_salida_a_payu
    correo = _correo('datos')
    ref, _ = plan(correo)
    # Al salir hacia PayU se guarda el navegador (el webhook llega sin él).
    with flask_app.test_request_context('/crear-orden', method='POST',
                                        headers={'User-Agent': 'Navegador/1.0', 'Cookie': '_fbp=fb.1.123.456',
                                                 'Referer': 'https://cybershopcol.com/comprar-plan/basico'}):
        registrar_salida_a_payu(ref)

    assert _webhook(client, ref).status_code == 200
    _webhook(client, ref)                                  # PayU reintenta el webhook
    compras = _compras(meta)
    assert len(compras) == 1
    compra = compras[0]
    assert compra['event_id'] == f'purchase-{ref}' and compra['action_source'] == 'website'
    assert compra['custom_data']['value'] == 1000.0 and compra['custom_data']['order_id'] == ref
    assert compra['custom_data']['contents'] == [{'id': 'Plan: Básico', 'quantity': 1, 'item_price': 1000.0}]
    datos = compra['user_data']
    assert datos['em'] == correo and datos['ph'] == '573001234567'
    assert datos['fn'] == 'Ana' and datos['ln'] == 'Pytest'
    assert datos['client_user_agent'] == 'Navegador/1.0' and datos['fbp'] == 'fb.1.123.456'
    assert compra['event_source_url'] == 'https://cybershopcol.com/comprar-plan/basico'


def test_la_pagina_de_respuesta_no_avisa_y_el_webhook_si(client, meta, plan):
    """El cliente vuelve primero a la página (aprueba el pedido) y la recarga:
    nada sale a Meta. Cuando llega el webhook firmado, sale la venta una vez."""
    from tests.test_respuesta_pago_firma import _firma
    ref, _ = plan(_correo('pagina'))
    url = (f'/respuesta-pago?merchantId=508029&transactionState=4&referenceCode={ref}&TX_VALUE=1000.00'
           f'&currency=COP&signature={_firma(ref, "1000.00", "4")}')
    assert 'Transacción Exitosa' in client.get(url).get_data(as_text=True)
    client.get(url)
    assert _compras(meta) == []
    _webhook(client, ref)                                  # ya estaba APROBADO
    _webhook(client, ref)
    assert len(_compras(meta)) == 1
    assert _compras(meta)[0]['action_source'] == 'system_generated'   # sin navegador guardado


def test_cerrar_el_navegador_no_pierde_la_venta(client, meta, plan):
    """Nadie vuelve a la página de respuesta: el webhook basta."""
    ref, _ = plan(_correo('cierra'))
    _webhook(client, ref)
    assert len(_compras(meta)) == 1


def test_un_pedido_de_productos_aprobado_no_envia_purchase(client, meta, pedido, cursor):
    """E-commerce: el pedido se aprueba (por la página y el webhook, o solo
    por el webhook) pero a Meta no le llega nada: no es una venta del software."""
    from tests.test_respuesta_pago_firma import _firma
    ref, otro = pedido(email=_correo('productos')), pedido(email=_correo('productos'))
    client.get(f'/respuesta-pago?merchantId=508029&transactionState=4&referenceCode={ref}&TX_VALUE=1000.00'
               f'&currency=COP&signature={_firma(ref, "1000.00", "4")}')
    for referencia in (ref, otro):
        assert _webhook(client, referencia).status_code == 200
    assert _compras(meta) == []
    with cursor() as cur:
        cur.execute('SELECT estado_pago FROM pedidos WHERE referencia_pedido = ANY(%s)', ([ref, otro],))
        assert [f['estado_pago'] for f in cur.fetchall()] == ['APROBADO', 'APROBADO']


def test_sin_aprobacion_o_pedido_viejo_no_hay_venta(client, meta, plan, cursor):
    (rechazado, _), (viejo, _) = plan(_correo('rechazado')), plan(_correo('viejo'), dias=30)
    _webhook(client, rechazado, estado='6')
    _webhook(client, viejo)                                # webhook repetido de hace un mes
    assert _compras(meta) == []
    with cursor() as cur:
        cur.execute('SELECT estado_pago FROM pedidos WHERE referencia_pedido = %s', (viejo,))
        assert cur.fetchone()['estado_pago'] == 'APROBADO'   # el pago se registra; solo no se avisa


def test_solo_la_primera_compra_de_un_cliente_nuevo(client, meta, plan):
    """La compra del plan sí; su renovación y otra tienda del mismo correo no."""
    correo = _correo('nuevo')
    primera, compra = plan(correo)
    _webhook(client, primera)
    renovacion, _ = plan(correo, renovacion_de=compra)
    _webhook(client, renovacion)
    otra_tienda, _ = plan(correo.upper())                  # el mismo cliente, escrito distinto
    _webhook(client, otra_tienda)
    assert _avisados(meta) == [primera]


def test_la_prueba_gratis_que_paga_es_cliente_nuevo(client, meta, plan):
    """Su primer pago sí (la prueba no se pagó); la renovación siguiente no.
    El padre ya viene sin es_trial: procesar_compra_plan corre antes del aviso."""
    correo = _correo('prueba')
    _, prueba = plan(correo, referencia=f'TRIAL-PYTEST{MARCA}', pagar=False, estado='ACTIVADA')
    conversion, _ = plan(correo, renovacion_de=prueba)
    _webhook(client, conversion)
    siguiente, _ = plan(correo, renovacion_de=prueba)
    _webhook(client, siguiente)
    assert _avisados(meta) == [conversion]


def test_renovar_o_reactivar_a_un_cliente_antiguo_no_es_venta_nueva(client, meta, plan):
    """Cliente cargado a mano al cobro automático (sin pedido pagado) que paga
    para reactivar su tienda suspendida: no sale."""
    correo = _correo('antiguo')
    _, antiguo = plan(correo, referencia=f'BACKFILL-PYTEST{MARCA}', pagar=False, estado='ACTIVADA',
                      suspendida_por_pago=True)
    reactivacion, _ = plan(correo, renovacion_de=antiguo)
    _webhook(client, reactivacion)
    assert _avisados(meta) == []


def test_los_clientes_no_avisan_ventas(client, meta, plan, monkeypatch):
    import routes.factura_electronica as fe
    monkeypatch.setattr(fe, '_es_tienda_operadora', lambda: False)
    _webhook(client, plan(_correo('cliente'))[0])
    assert _compras(meta) == []
