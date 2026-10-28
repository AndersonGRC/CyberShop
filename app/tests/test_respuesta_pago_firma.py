# -*- coding: utf-8 -*-
"""Página de respuesta de PayU: el estado de la URL solo cuenta si PayU lo firmó.

Antes bastaba escribir «transactionState=4» en la URL para dejar un pedido
APROBADO (y activar tiendas, renovar planes o convertir pruebas gratis sin
pagar). Ahora sin firma válida se le pregunta a PayU y, si no responde, queda
«en proceso» hasta el webhook. Además, recargar la página no repite la
contabilidad ni la devolución de inventario. Contra la base de pruebas; todo lo
creado se borra al final."""
import hashlib
import uuid

import pytest

MARCA = uuid.uuid4().hex[:8].upper()
API_KEY = 'llave-de-prueba-pytest'


def _firma(ref, valor, estado, moneda='COP', merchant='508029'):
    from routes.payments import _valor_firma_respuesta
    crudo = f"{API_KEY}~{merchant}~{ref}~{_valor_firma_respuesta(valor)}~{moneda}~{estado}"
    return hashlib.md5(crudo.encode('utf-8')).hexdigest()


@pytest.fixture()
def payu(flask_app, monkeypatch):
    """Llave de prueba, sin esperas ni consultas reales a PayU; registra los
    efectos (contabilidad, venta de planes, devolución de stock)."""
    import routes.payments as pagos
    import routes.contabilidad as conta
    import services.venta_automatica_service as vas
    monkeypatch.setitem(flask_app.config, 'PAYU_API_KEY', API_KEY)
    monkeypatch.setattr(pagos.time, 'sleep', lambda s: None)
    efectos = {'contabilidad': 0, 'planes': 0, 'stock': 0, 'consultas': 0, 'payu': '7'}

    def consultar(ref):
        efectos['consultas'] += 1
        return efectos['payu']
    monkeypatch.setattr(pagos, 'consultar_estado_real_payu', consultar)
    monkeypatch.setattr(conta, 'registrar_movimiento', lambda **kw: efectos.__setitem__('contabilidad', efectos['contabilidad'] + 1))
    monkeypatch.setattr(vas, 'procesar_compra_plan', lambda ref, base_url=None: efectos.__setitem__('planes', efectos['planes'] + 1))
    original = pagos.liberar_stock
    monkeypatch.setattr(pagos, 'liberar_stock', lambda ref: (efectos.__setitem__('stock', efectos['stock'] + 1), original(ref)))
    return efectos


@pytest.fixture()
def pedido(cursor):
    refs = []

    def crear():
        ref = f'PYTEST-RESP-{MARCA}-{len(refs)}'
        with cursor() as cur:
            cur.execute("""INSERT INTO pedidos (referencia_pedido, cliente_nombre, cliente_email, monto_total,
                                                estado_pago, estado_envio)
                           VALUES (%s, 'Pytest', 'pytest@ejemplo.com', 1000, 'PENDIENTE', 'ESPERA_PAGO')""", (ref,))
        refs.append(ref)
        return ref
    yield crear
    with cursor() as cur:
        cur.execute('DELETE FROM pedidos WHERE referencia_pedido = ANY(%s)', (refs,))


def _estado(cursor, ref):
    with cursor() as cur:
        cur.execute('SELECT estado_pago FROM pedidos WHERE referencia_pedido = %s', (ref,))
        return cur.fetchone()['estado_pago']


def test_firma_de_la_respuesta(flask_app, monkeypatch):
    from routes.payments import firma_respuesta_valida, _valor_firma_respuesta
    monkeypatch.setitem(flask_app.config, 'PAYU_API_KEY', API_KEY)
    assert _valor_firma_respuesta('150.25') == '150.2' and _valor_firma_respuesta('150.35') == '150.4'
    assert _valor_firma_respuesta('1000') == '1000.0'
    args = {'merchantId': '508029', 'referenceCode': 'R1', 'TX_VALUE': '1000.00', 'currency': 'COP',
            'transactionState': '4', 'signature': _firma('R1', '1000.00', '4')}
    with flask_app.app_context():
        assert firma_respuesta_valida(args)
        assert not firma_respuesta_valida({**args, 'transactionState': '6'})       # estado cambiado
        assert not firma_respuesta_valida({**args, 'TX_VALUE': '1.00'})            # valor cambiado
        assert not firma_respuesta_valida({k: v for k, v in args.items() if k != 'signature'})
        monkeypatch.setitem(flask_app.config, 'PAYU_API_KEY', '')
        assert not firma_respuesta_valida(args)                                     # sin llave, nada vale


def test_url_falsificada_no_aprueba_nada(client, cursor, payu, pedido):
    ref = pedido()
    r = client.get(f'/respuesta-pago?transactionState=4&referenceCode={ref}&TX_VALUE=1000&currency=COP')
    assert r.status_code == 200 and 'Transacción Exitosa' not in r.get_data(as_text=True)
    assert _estado(cursor, ref) == 'PENDIENTE'
    assert payu['consultas'] >= 1                      # se le preguntó a PayU
    assert payu['contabilidad'] == 0 and payu['planes'] == 0
    # Un «rechazo» falsificado tampoco cancela el pedido ni devuelve stock.
    client.get(f'/respuesta-pago?transactionState=6&referenceCode={ref}&TX_VALUE=1000&currency=COP')
    assert _estado(cursor, ref) == 'PENDIENTE' and payu['stock'] == 0


def test_sin_firma_pero_payu_confirma(client, cursor, payu, pedido):
    """Si la firma no cuadra pero PayU confirma el pago al consultarle, se aprueba."""
    ref = pedido()
    payu['payu'] = '4'
    client.get(f'/respuesta-pago?transactionState=4&referenceCode={ref}&TX_VALUE=1000&currency=COP')
    assert _estado(cursor, ref) == 'APROBADO' and payu['contabilidad'] == 1


def test_contabilidad_usa_el_monto_del_pedido_no_el_de_la_url(client, cursor, payu, pedido, monkeypatch):
    """Sin firma, el estado se le confirma a PayU pero TX_VALUE lo escribe
    cualquiera: el ingreso y el comprobante usan el monto guardado del pedido."""
    import routes.contabilidad as conta
    ingresos = []
    monkeypatch.setattr(conta, 'registrar_movimiento', lambda **kw: ingresos.append(kw['monto']))
    ref = pedido()                                     # monto_total = 1000
    payu['payu'] = '4'
    html = client.get(f'/respuesta-pago?transactionState=4&referenceCode={ref}&TX_VALUE=99999999&currency=COP'
                      ).get_data(as_text=True)
    assert _estado(cursor, ref) == 'APROBADO' and ingresos == [1000.0]
    assert '1000.00 COP' in html and '99999999' not in html


def test_firma_valida_aprueba_una_sola_vez(client, cursor, payu, pedido):
    ref = pedido()
    url = (f'/respuesta-pago?merchantId=508029&transactionState=4&referenceCode={ref}&TX_VALUE=1000.00'
           f'&currency=COP&signature={_firma(ref, "1000.00", "4")}')
    html = client.get(url).get_data(as_text=True)
    assert 'Transacción Exitosa' in html and _estado(cursor, ref) == 'APROBADO'
    assert payu['contabilidad'] == 1 and payu['planes'] == 1 and payu['consultas'] == 0
    client.get(url)                                    # recargar la página
    assert payu['contabilidad'] == 1                   # no se repite el ingreso
    assert payu['planes'] == 2                         # la venta de planes es idempotente (respaldo del webhook)


def test_rechazo_firmado_devuelve_stock_una_vez(client, cursor, payu, pedido):
    ref = pedido()
    url = (f'/respuesta-pago?merchantId=508029&transactionState=6&referenceCode={ref}&TX_VALUE=1000.00'
           f'&currency=COP&signature={_firma(ref, "1000.00", "6")}')
    client.get(url)
    client.get(url)
    assert _estado(cursor, ref) == 'RECHAZADO' and payu['stock'] == 1


def test_liberar_stock_una_sola_vez_por_pedido(flask_app, cursor):
    """Un webhook repetido o una recarga no devuelven el inventario dos veces."""
    from routes.payments import liberar_stock
    with cursor() as cur:
        cur.execute('SELECT id, nombre, stock FROM productos ORDER BY id LIMIT 1')
        prod = cur.fetchone()
    if not prod:
        pytest.skip('La base de pruebas no tiene productos.')
    ref = f'PYTEST-STOCK-{MARCA}'
    try:
        with cursor() as cur:
            cur.execute("""INSERT INTO pedidos (referencia_pedido, estado_pago, estado_envio)
                           VALUES (%s, 'RECHAZADO', 'CANCELADO') RETURNING id""", (ref,))
            pedido_id = cur.fetchone()['id']
            cur.execute("""INSERT INTO detalle_pedidos (pedido_id, producto_nombre, cantidad, precio_unitario, subtotal)
                           VALUES (%s, %s, 2, 1000, 2000)""", (pedido_id, prod['nombre']))
        with flask_app.app_context():
            liberar_stock(ref)
            liberar_stock(ref)
        with cursor() as cur:
            cur.execute('SELECT stock FROM productos WHERE id = %s', (prod['id'],))
            assert cur.fetchone()['stock'] == (prod['stock'] or 0) + 2
    finally:
        with cursor() as cur:
            cur.execute('UPDATE productos SET stock = %s WHERE id = %s', (prod['stock'], prod['id']))
            cur.execute('DELETE FROM inventario_log WHERE motivo = %s', (f'Liberación pedido {ref}',))
            cur.execute('DELETE FROM detalle_pedidos WHERE pedido_id IN '
                        '(SELECT id FROM pedidos WHERE referencia_pedido = %s)', (ref,))
            cur.execute('DELETE FROM pedidos WHERE referencia_pedido = %s', (ref,))
