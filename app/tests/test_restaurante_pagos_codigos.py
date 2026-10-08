# -*- coding: utf-8 -*-
"""Atender mesas: buscar productos por código (escrito o con el lector) y cobrar
con los mismos medios de pago del POS (Nequi, Daviplata…).

- El código se compara sin espacios, guiones ni ceros a la izquierda, contra la
  referencia y el código de barras.
- Lo que no está en la página se busca en el servidor: un producto registrado
  después de abrir «Atender» también se encuentra.
- El cobro usa la lista configurable del POS; los códigos de antes (Mixto…)
  se siguen aceptando.
Contra la base de pruebas; no crea ventas."""
import json
import re

import pytest

from services import restaurant_tables_service as rt
from tests.test_restaurante_mesas import modulo_mesas  # noqa: F401  (fixture)


# ── Códigos ─────────────────────────────────────────────────────
@pytest.mark.parametrize('escrito, guardado', [
    ('REF-004', 'REF-004'), ('ref 004', 'REF-004'), ('REF004', 'REF-004'),
    ('0012345', '12345'), ('77-01.23 ', '770123'), (' abc-9 ', 'ABC9'),
])
def test_codigos_comparables(escrito, guardado):
    assert rt.normalizar_codigo(escrito) == rt.normalizar_codigo(guardado)


def test_buscar_por_codigo_y_por_nombre():
    con_ref = next((p for p in rt.get_product_catalog() if p.get('referencia')), None)
    if not con_ref:
        pytest.skip('La base de pruebas no tiene productos con referencia.')
    ref = con_ref['referencia']
    r = rt.buscar_productos(ref.lower().replace('-', ' '))
    assert r['exacto'] and r['exacto']['id'] == con_ref['id']
    assert r['productos'][0]['id'] == con_ref['id']
    por_nombre = rt.buscar_productos(con_ref['nombre'][:4])
    assert por_nombre['exacto'] is None or por_nombre['exacto']['id'] == con_ref['id']
    assert any(p['id'] == con_ref['id'] for p in por_nombre['productos'])
    assert rt.buscar_productos('XQZ-NO-EXISTE-999') == {'exacto': None, 'productos': []}
    assert rt.buscar_productos('  ') == {'exacto': None, 'productos': []}


def test_buscar_por_codigo_de_barras(monkeypatch):
    """Productos del POS de escritorio: el código del lector va en `barcode`."""
    monkeypatch.setattr(rt, 'get_product_catalog', lambda: [
        {'id': 7, 'nombre': 'Gaseosa 400', 'precio': 3000, 'stock': 5, 'referencia': 'SKU-7',
         'barcode': '7702004003508', 'genero_nombre': 'Bebidas'},
        {'id': 8, 'nombre': 'Agua', 'precio': 2000, 'stock': 5, 'referencia': 'SKU-8',
         'barcode': None, 'genero_nombre': 'Bebidas'}])
    assert rt.buscar_productos('7702004003508')['exacto']['id'] == 7
    assert rt.buscar_productos('07702004003508')['exacto']['id'] == 7     # el lector agregó un cero
    assert [p['id'] for p in rt.buscar_productos('400350')['productos']] == [7]   # parte del código


def test_ruta_de_busqueda(as_propietario, modulo_mesas):
    con_ref = next((p for p in rt.get_product_catalog() if p.get('referencia')), None)
    if not con_ref:
        pytest.skip('La base de pruebas no tiene productos con referencia.')
    d = as_propietario.get('/admin/restaurante/productos/buscar?q=' + con_ref['referencia']).get_json()
    assert d['success'] and d['exacto']['id'] == con_ref['id']


def test_la_busqueda_pide_sesion_y_modulo(client, modulo_mesas):
    assert client.get('/admin/restaurante/productos/buscar?q=x').status_code in (302, 401, 403)


# ── Medios de pago: los del POS ─────────────────────────────────
def test_los_medios_de_la_mesa_son_los_del_pos():
    from services import metodos_pago_service as mps
    mesa = [m['codigo'] for m in rt.metodos_pago()]
    assert mesa == [m['codigo'] for m in mps.listar()]
    assert {'NEQUI', 'DAVIPLATA'} <= set(rt.etiquetas_pago()) and 'MIXTO' in rt.etiquetas_pago()


def test_cerrar_valida_el_medio_de_pago():
    with pytest.raises(ValueError, match='método de pago no es válido'):
        rt.close_table_order(1, 999999, {'payment_method': 'BITCOIN'})
    # Nequi pasa la validación (falla después, porque la mesa no tiene cuenta).
    with pytest.raises(ValueError, match='no tiene una cuenta abierta'):
        rt.close_table_order(1, 999999, {'payment_method': 'nequi'})
    with pytest.raises(ValueError, match='no tiene una cuenta abierta'):
        rt.close_table_order(1, 999999, {'payment_method': 'MIXTO'})   # código de antes


def test_atender_muestra_los_medios_del_pos(as_propietario, modulo_mesas):
    html = as_propietario.get('/admin/restaurante/mesas/atencion').get_data(as_text=True)
    datos = re.search(r'paymentMethods: (\[.*?\]),\n', html).group(1)
    nombres = [m['nombre'] for m in json.loads(datos)]
    assert 'Nequi' in nombres and 'Daviplata' in nombres
    assert all(m.get('color') and m.get('icono') for m in json.loads(datos))
    assert '/admin/restaurante/productos/buscar' in html


def test_factura_electronica_traduce_los_medios_del_pos():
    from routes.factura_electronica import METODO_PAGO_MAP
    assert METODO_PAGO_MAP['NEQUI'] == METODO_PAGO_MAP['DAVIPLATA'] == METODO_PAGO_MAP['TRANSFERENCIA']
    assert METODO_PAGO_MAP['TARJETA'] == METODO_PAGO_MAP['CARD']
