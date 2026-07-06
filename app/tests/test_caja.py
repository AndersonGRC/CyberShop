# -*- coding: utf-8 -*-
"""Tests del módulo Caja / Arqueo: apertura, movimientos, cuadre, hardening."""
import pytest


def _abrir(client, base='50000'):
    return client.post('/admin/pos/caja/abrir', json={'base': base})


def test_abrir_caja_ok(as_cajero, modulo_caja_on, limpiar_caja):
    r = _abrir(as_cajero, '50.000')
    d = r.get_json()
    assert r.status_code == 200 and d['success'] and d['base'] == 50000.0


def test_doble_apertura_rechazada(as_cajero, modulo_caja_on, limpiar_caja):
    _abrir(as_cajero, '50000')
    r = _abrir(as_cajero, '10000')
    assert r.status_code == 409


@pytest.mark.parametrize('malo', ['nan', 'inf', 'Infinity', '-inf', '1e20', 'abc', '-5'])
def test_abrir_rechaza_montos_invalidos(as_cajero, modulo_caja_on, limpiar_caja, malo):
    r = _abrir(as_cajero, malo)
    assert r.status_code == 400, f"base={malo!r} deberia ser 400, fue {r.status_code}"


def test_movimiento_salida_crea_egreso(as_cajero, modulo_caja_on, limpiar_caja, cursor):
    d = _abrir(as_cajero, '50000').get_json()
    r = as_cajero.post('/admin/pos/caja/movimiento',
                       data={'tipo': 'salida', 'categoria': 'gasto_caja',
                             'descripcion': 'pytest domicilio', 'monto': '10000'})
    assert r.status_code in (200, 302)
    with cursor() as cur:
        cur.execute("""SELECT monto, tipo, categoria FROM contabilidad_movimientos
                       WHERE referencia_tipo='caja_movimiento' ORDER BY id DESC LIMIT 1""")
        m = cur.fetchone()
    assert m and float(m['monto']) == 10000 and m['tipo'] == 'egreso' and m['categoria'] == 'gasto_caja'


def test_movimiento_monto_nan_rechazado(as_cajero, modulo_caja_on, limpiar_caja, cursor):
    d = _abrir(as_cajero, '50000').get_json()
    as_cajero.post('/admin/pos/caja/movimiento',
                   data={'tipo': 'salida', 'categoria': 'gasto_caja', 'monto': 'nan'})
    with cursor() as cur:
        cur.execute("SELECT count(*) n FROM caja_movimientos WHERE caja_sesion_id=%s", (d['sesion_id'],))
        assert cur.fetchone()['n'] == 0


def test_cuadre_calcula_diferencia_y_excluye_anuladas(as_cajero, modulo_caja_on, limpiar_caja, cursor):
    d = _abrir(as_cajero, '50000').get_json()
    sid = d['sesion_id']
    with cursor() as cur:
        for num, met, tot in [('TEST-C1', 'EFECTIVO', 20000), ('TEST-C2', 'EFECTIVO', 15000),
                              ('TEST-C3', 'NEQUI', 30000), ('TEST-C4', 'EFECTIVO', 8000)]:
            cur.execute("""INSERT INTO ventas_pos (numero_venta,metodo_pago,subtotal,total,usuario_id,caja_sesion_id)
                           VALUES (%s,%s,%s,%s,1,%s)""", (num, met, tot, tot, sid))
        cur.execute("""INSERT INTO ventas_pos (numero_venta,metodo_pago,subtotal,total,usuario_id,caja_sesion_id,estado)
                       VALUES ('TEST-C5','EFECTIVO',99999,99999,1,%s,'anulada')""", (sid,))
    as_cajero.post('/admin/pos/caja/movimiento', data={'tipo': 'salida', 'categoria': 'gasto_caja', 'monto': '10000'})
    # esperado = 50000 + (20000+15000+8000) + 0 - 10000 = 83000 ; contado 81000 -> faltante 2000
    as_cajero.post('/admin/pos/caja/cerrar', data={'efectivo_contado': '81000'})
    with cursor() as cur:
        cur.execute("SELECT estado,efectivo_esperado,diferencia,total_ventas FROM caja_sesiones WHERE id=%s", (sid,))
        s = dict(cur.fetchone())
    assert s['estado'] == 'cerrada'
    assert float(s['efectivo_esperado']) == 83000
    assert float(s['diferencia']) == -2000
    assert float(s['total_ventas']) == 73000  # excluye la anulada


def test_cerrar_contado_nan_rechazado(as_cajero, modulo_caja_on, limpiar_caja, cursor):
    d = _abrir(as_cajero, '50000').get_json()
    as_cajero.post('/admin/pos/caja/cerrar', data={'efectivo_contado': 'nan'})
    with cursor() as cur:
        cur.execute("SELECT estado FROM caja_sesiones WHERE id=%s", (d['sesion_id'],))
        assert cur.fetchone()['estado'] == 'abierta'  # no se cerró con basura
