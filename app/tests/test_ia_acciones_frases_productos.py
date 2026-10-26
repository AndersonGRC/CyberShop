# -*- coding: utf-8 -*-
"""El filtro que decide qué acción pidió la persona (antes de llamar a la IA) entiende
las formas normales de pedir cosas sobre productos (1.9.15.0). Antes, estas frases las
rechazaba o las mandaba a otra acción, y el asistente respondía con incoherencias."""
import pytest

from services import ia_acciones as acciones


@pytest.mark.parametrize('frase, tipo', [
    ('Agrega Cable HDMI 2 metros a 18.900 en Cables', 'crear_producto'),
    ('Agrega Bolsa de hielo 2kg a 3.000 en la categoría Hielo', 'crear_producto'),
    ('agregame el producto Galletas de avena a 1.800 en la categoria Galletas', 'crear_producto'),
    ('Necesito que registres el producto Funda para celular Samsung A54 a 25.000 en Fundas', 'crear_producto'),
    ('Agrega el producto Disco SSD 480GB a 150.000 en Almacenamiento con referencia SSD480 y 5 unidades',
     'crear_producto'),
    ('Créalo a 3.500 en Bebidas', 'crear_producto'),
    ('Pasa el producto Brownie a la categoría Postres', 'editar_producto'),
    ('Pon el stock mínimo de la Leche entera 1 litro en 10', 'editar_producto'),
    ('Cambia la descripción del Brownie: con helado de vainilla', 'editar_producto'),
    ('Se perdieron 3 memorias USB 64GB', 'movimiento_inventario'),
    ('Se rompieron 2 vasos de vidrio', 'movimiento_inventario'),
    ('Ya no vendo el Cuaderno argollado 100 hojas, archívalo', 'archivar_producto'),
    ('Ya no manejamos la gaseosa de uva', 'archivar_producto'),
])
def test_frases_de_productos(frase, tipo):
    assert acciones.parece_operativa(frase), 'debe ir a las acciones, no al chat de consultas'
    assert acciones._tipo_solicitado(frase) == tipo


@pytest.mark.parametrize('frase, tipo', [
    ('Crea una tarea para cobrarle a Juan Pérez 3 mil mañana', 'crear_tarea'),
    ('Agrega el contacto Juan Pérez como proveedor', 'crear_contacto'),
    ('Llegaron 24 gaseosas 400ml', 'movimiento_inventario'),
    ('Agrega 10 unidades al inventario de la gaseosa', 'movimiento_inventario'),
    ('Pon el stock de la gaseosa en 20 por conteo', 'ajustar_inventario'),
    ('Crea la categoría Postres', 'crear_categoria'),
    ('Sube el precio de la gaseosa a 3.800', 'editar_producto'),
])
def test_lo_que_ya_funcionaba_no_cambia(frase, tipo):
    assert acciones._tipo_solicitado(frase) == tipo


@pytest.mark.parametrize('frase', ['¿Cuánto vale la gaseosa a 3.500?', 'hola', '¿Qué productos tengo?'])
def test_preguntas_siguen_en_el_chat(frase):
    assert not acciones.parece_operativa(frase)
