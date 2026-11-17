# -*- coding: utf-8 -*-
"""Anular una venta POS y su factura electrónica (decisión del dueño, 15-nov-2026):
nota crédito SOLO si la venta ya estaba facturada; en cola se cancela; sin
factura, nada. Nunca se llama al portal real."""
import pytest

import routes.factura_electronica as fe


@pytest.fixture()
def portal(monkeypatch):
    llamadas = {'cancelar': [], 'emitir': []}
    estado = {'valor': {'estado': 'ACEPTADA', 'numero_factura': 'CYBR12', 'cufe': 'abc123',
                        'creado_en': '2026-11-10T09:00:00'}}
    monkeypatch.setattr(fe, 'consultar_estado_factura', lambda fid: dict(estado['valor']))
    monkeypatch.setattr(fe, 'cancelar_factura_dian',
                        lambda fid: llamadas['cancelar'].append(fid) or {'ok': True})
    monkeypatch.setattr(fe, 'construir_json_pos', lambda vid: {
        'referencia_pedido': f'POS-{vid}', 'cliente': {'nombre': 'Ana'}, 'metodo_pago': '10',
        'items': [{'descripcion': 'Pan', 'cantidad': 2, 'precio_unitario': 3000}]})
    monkeypatch.setattr(fe, '_dian_call', lambda metodo, ruta, **k:
                        llamadas['emitir'].append(k.get('payload')) or {'id': 'nc-1', 'estado': 'PENDIENTE'})
    llamadas['estado'] = estado
    return llamadas


def test_sin_factura_no_hace_nada(portal):
    assert fe.reversar_fe_por_anulacion_pos(7, None, 'error')['accion'] == 'ninguna'
    assert portal['emitir'] == [] and portal['cancelar'] == []


def test_facturada_y_aceptada_crea_la_nota_credito(portal):
    r = fe.reversar_fe_por_anulacion_pos(7, 'f-1', 'Cliente devolvió')
    assert r['accion'] == 'nota_credito' and 'CYBR12' in r['mensaje']
    nota = portal['emitir'][0]
    assert nota['tipo_documento'] == 'nota_credito' and nota['referencia_pedido'] == 'NC-POS-7'
    assert nota['documento_referencia']['numero'] == 'CYBR12'
    assert nota['documento_referencia']['cufe'] == 'abc123'
    assert nota['concepto_nota']['codigo'] == '2'
    assert nota['items'][0]['cantidad'] == 2                       # la misma venta, completa


def test_en_cola_se_cancela_sin_nota(portal):
    portal['estado']['valor'] = {'estado': 'PENDIENTE'}
    r = fe.reversar_fe_por_anulacion_pos(7, 'f-1')
    assert r['accion'] == 'cancelada' and portal['cancelar'] == ['f-1'] and portal['emitir'] == []


@pytest.mark.parametrize('estado', ['RECHAZADA', 'CANCELADA'])
def test_rechazada_o_cancelada_no_necesita_nota(portal, estado):
    portal['estado']['valor'] = {'estado': estado}
    assert fe.reversar_fe_por_anulacion_pos(7, 'f-1')['accion'] == 'ninguna'
    assert portal['emitir'] == []


@pytest.mark.parametrize('respuesta', [{'estado': 'PROCESANDO'}, {'estado': 'ERROR'},
                                       {'error': 'sin conexión'}])
def test_si_no_se_sabe_avisa_y_no_adivina(portal, respuesta):
    portal['estado']['valor'] = respuesta
    r = fe.reversar_fe_por_anulacion_pos(7, 'f-1')
    assert r['accion'] == 'revisar' and 'Bandeja' in r['mensaje'] and portal['emitir'] == []


def test_nunca_lanza(portal, monkeypatch):
    def falla(_fid):
        raise RuntimeError('caído')
    monkeypatch.setattr(fe, 'consultar_estado_factura', falla)
    assert fe.reversar_fe_por_anulacion_pos(7, 'f-1')['accion'] == 'revisar'
