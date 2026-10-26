# -*- coding: utf-8 -*-
"""Antes de crear un producto con la IA se revisan los parecidos del catálogo (1.9.15.0):
el mismo producto escrito de otra forma no se duplica; otra presentación o la misma
palabra de otra marca solo avisan. Casos tomados de un catálogo real de minimercado."""
import uuid

import pytest

from services import ia_acciones as acciones
from services import productos_parecidos as pp


@pytest.mark.parametrize('nuevo, existente, tipo', [
    ('aceite diana 1L', 'DIANA ACEITE 1000 ML', 'duplicado'),          # 1L = 1000 ML, otro orden
    ('arroz roa kilo', 'ROA ARROZ 1000 GR', 'duplicado'),               # kilo = 1000 GR
    ('traident x 5 yerbabuena', 'TRIDENT X 5 YERBABUENA', 'duplicado'), # error de tecleo
    ('Spaguetti Doria 500 gr', 'DORIA SPAGHETTI 500 GR', 'duplicado'),
    ('Diana aceite', 'DIANA ACEITE', 'duplicado'),
    ('aceite diana 3000 ml', 'DIANA ACEITE 1000 ML', 'variante'),       # otra presentación
    ('GASEOSA COCA COLA 2 LITROS', 'GASEOSA COCA COLA 3 LITROS', 'variante'),
    ('Gaseosa Quatro 1.5', 'QUATRO GASEOSA 2.5', 'variante'),
    ('WINNY ETAPA 3', 'WINNY ETAPA 4', 'variante'),
    ('AROMA CAFE', 'AROMA CAFE 40 GR', 'sin_tamano'),                    # el nuevo sin tamaño
    ('agua brisa 600 ml', 'BRISA AGUA SABORIZADA 1,5', 'parecido'),
    ('PANTENE PRO-V REPARACION', 'PANTENE PRO-V RESTAURACION', 'parecido'),   # no es error de tecleo
    ('CAREFREE CON PERFUME', 'CAREFREE SIN PERFUME', 'parecido'),
    ('agua cielo 600 ml', 'BRISA AGUA 600 ML', None),                   # otra marca: una sola palabra común
    ('Croissant', 'Torta de chocolate', None),
])
def test_clasificar(nuevo, existente, tipo):
    assert pp.clasificar(nuevo, existente) == tipo


def test_revisar_avisa_sin_bloquear_lo_distinto():
    catalogo = [{'id': 5, 'nombre': 'DIANA ACEITE 500 ML'}, {'id': 6, 'nombre': 'DIANA ACEITE 1000 ML'},
                {'id': 7, 'nombre': 'PREMIER ACEITE 1000 ML'}]
    r = pp.revisar('aceite diana 3000 ml', catalogo)
    assert r['duplicado'] is None
    assert r['avisos'] == ['ℹ Ya tienes «DIANA ACEITE 500 ML» (ID 5), «DIANA ACEITE 1000 ML» (ID 6) en otra '
                           'presentación: este queda como producto aparte.']
    assert pp.revisar('Diana aceite 1L', catalogo)['duplicado']['id'] == 6
    sin = pp.revisar('aceite diana', catalogo)
    assert sin['duplicado'] is None and sin['avisos'][0].startswith('⚠ Ya tienes «DIANA ACEITE 500 ML»')
    assert pp.revisar('Aceite Premier 3000 ml', catalogo)['avisos'][0].startswith('ℹ Ya tienes «PREMIER')


# ── En la vista previa de la acción de la IA ──
MARCA = uuid.uuid4().hex[:6].upper()


@pytest.fixture()
def catalogo_prueba(cursor):
    with cursor() as cur:
        cur.execute('INSERT INTO generos (nombre) VALUES (%s) RETURNING id', (f'Zyxaceites {MARCA}',))
        gid = cur.fetchone()['id']
        cur.execute("""INSERT INTO productos (imagen, nombre, precio, referencia, genero_id, descripcion, stock)
                       VALUES ('', %s, 6000, %s, %s, '', 3) RETURNING id""",
                    (f'ZYXDIANA{MARCA} ACEITE 1000 ML', f'PYT-{MARCA}', gid))
        pid = cur.fetchone()['id']
    yield pid
    with cursor() as cur:
        cur.execute('DELETE FROM productos WHERE nombre ILIKE %s', (f'%{MARCA}%',))
        cur.execute('DELETE FROM generos WHERE nombre LIKE %s', (f'%{MARCA}%',))


def _plan(nombre):
    return {'tipo': 'crear_producto', 'campos': {'nombre': nombre, 'precio': '6.500',
                                                 'categoria': f'zyxaceites {MARCA}'}}


def test_vista_previa_no_duplica_el_mismo_producto(cursor, catalogo_prueba):
    with cursor() as cur:
        with pytest.raises(acciones.AccionError, match=f'Ya existe «ZYXDIANA{MARCA} ACEITE 1000 ML» '
                                                       f'\\(ID {catalogo_prueba}\\)'):
            acciones._preparar_datos(cur, _plan(f'aceite zyxdiana{MARCA.lower()} 1L'))


def test_vista_previa_avisa_otra_presentacion(cursor, catalogo_prueba):
    with cursor() as cur:
        _, _, detalles = acciones._preparar_datos(cur, _plan(f'Aceite ZYXDIANA{MARCA} 3000 ML'))
    assert any(d.startswith('ℹ Ya tienes «ZYXDIANA') and 'otra presentación' in d for d in detalles)
