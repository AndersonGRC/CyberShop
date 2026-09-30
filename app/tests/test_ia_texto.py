# -*- coding: utf-8 -*-
"""Cifras por su valor para los validadores de redacción.

Medido con Qwen el 30-sep: comparar los dígitos pegados descartaba 10 de 10
respuestas correctas del panel («$ 905.500,00» → «90550000» ≠ «905500») y 4 de 10
del chat público. Estas pruebas fijan las dos mitades: lo correcto pasa, lo
inventado no."""
import pytest

from services.ia.texto import cifras_respaldadas, lecturas, palabras


@pytest.mark.parametrize('cifra, valor', [
    ('905.500,00', '905500'), ('905500.0', '905500'), ('$117.750', '117750'),
    ('0,00', '0'), ('23', '23'), ('1.500', '1500'), ('3015963776', '3015963776'),
])
def test_lecturas_por_valor(cifra, valor):
    assert valor in lecturas(cifra.lstrip('$'))


@pytest.mark.parametrize('texto, fuente', [
    ('Vale $905.500 en total.', '{"valor": "$ 905.500,00"}'),
    ('Este mes vendiste $0.', '{"total": "$ 0,00"}'),
    ('Tienes 155 unidades.', '{"unidades": 155.0}'),
    ('1. Gaseosa: 23 unidades\n2. Arepa: 32 unidades', '{"a": 23, "b": 32}'),
    ('Estamos en la carrera 151 #136A-20, teléfono 3015963776.',
     'carrera 151#136A-20. Teléfono: 3015963776.'),
])
def test_lo_correcto_pasa(texto, fuente):
    assert cifras_respaldadas(texto, fuente)


@pytest.mark.parametrize('texto, fuente', [
    ('Vale $950.000.', '{"valor": "$ 905.500,00"}'),
    ('Tienes 156 unidades.', '{"unidades": 155}'),
    ('Te llega en 3 días.', 'Envío a todo el país.'),
    ('Llama al 3015963777.', 'Teléfono: 3015963776.'),
])
def test_lo_inventado_no_pasa(texto, fuente):
    assert not cifras_respaldadas(texto, fuente)


def test_la_numeracion_de_una_lista_no_es_una_cifra_del_negocio():
    assert cifras_respaldadas('1. Gaseosa\n2. Arepa\n3. Jugo', '{"productos": ["Gaseosa"]}')
    assert not cifras_respaldadas('Gaseosa: 7 unidades', '{"productos": ["Gaseosa"]}')


def test_chat_publico_acepta_precio_y_direccion_pero_no_precios_intercambiados():
    from services.chat_publico import motor
    uno = {'via': 'keyword', 'texto_base': 'Sí, lo tenemos:\n- CARGADOR ASUS ($ 117.750,00) — disponible'}
    assert motor._conserva_cifras(uno, 'Tenemos el cargador Asus, disponible por $117.750.')
    direccion = {'via': 'keyword',
                 'texto_base': 'Estamos en carrera 151#136A-20. Teléfono: 3015963776.'}
    assert motor._conserva_cifras(direccion, 'Estamos en la carrera 151 #136A-20; llama al 3015963776.')
    dos = {'via': 'keyword', 'texto_base': ('Esto es lo que encontré:\n- Cargador A ($ 100.000,00)'
                                            '\n- Cargador B ($ 200.000,00)')}
    assert not motor._conserva_cifras(dos, 'El cargador A cuesta $200.000 y el B $100.000.')


def test_palabras_de_busqueda():
    assert palabras('el Contacto de Cybershop Proveedores Tecnológicos') == [
        'cybershop', 'proveedor', 'tecnologico']
    assert palabras('correo ana@correo.com tel 3001234567') == [
        'correo', 'ana@correo.com', 'tel', '3001234567']
