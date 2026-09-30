# -*- coding: utf-8 -*-
"""Fase 2 de las acciones del panel: productos, movimientos de inventario y
categorías. Contra la base de pruebas, con registros de nombre inventado que se
borran al final. Nunca se llama a un modelo."""
import inspect
import uuid

import pytest

from services import ia_acciones as acciones
from services import ia_acciones_catalogo as catalogo

MARCA = uuid.uuid4().hex[:6].upper()


@pytest.fixture()
def base(cursor):
    """Una categoría y un producto propios de la prueba."""
    creados = {'productos': [], 'generos': []}
    with cursor() as cur:
        cur.execute('INSERT INTO generos (nombre) VALUES (%s) RETURNING id', (f'Zyxbebidas {MARCA}',))
        gid = cur.fetchone()['id']
        creados['generos'].append(gid)
        cur.execute("""INSERT INTO productos (imagen, nombre, precio, referencia, genero_id, descripcion, stock)
                       VALUES ('', %s, 3000, %s, %s, 'Original', 10) RETURNING id""",
                    (f'Zyxgaseosa {MARCA}', f'PYT-{MARCA}', gid))
        creados['productos'].append(cur.fetchone()['id'])
    yield creados
    with cursor() as cur:
        cur.execute('SELECT id FROM productos WHERE nombre LIKE %s', (f'%{MARCA}%',))
        ids = [r['id'] for r in cur.fetchall()] + creados['productos']
        cur.execute('DELETE FROM inventario_log WHERE producto_id = ANY(%s)', (ids,))
        cur.execute('DELETE FROM productos WHERE id = ANY(%s)', (ids,))
        cur.execute('DELETE FROM generos WHERE nombre LIKE %s', (f'%{MARCA}%',))


def _preparar_y_ejecutar(cursor, plan):
    with cursor() as cur:
        payload, resumen, detalles = acciones._preparar_datos(cur, plan)
    with cursor() as cur:
        resultado = acciones._ejecutar(cur, {'tipo': plan['tipo'], 'payload': payload}, 1)
    return resumen, detalles, resultado


# ── Productos ──────────────────────────────────────────────────
def test_crear_producto_con_referencia_generada_y_stock_inicial(base, cursor):
    plan = {'tipo': 'crear_producto', 'campos': {
        'nombre': f'Zyxarepa {MARCA}', 'precio': '3.500', 'categoria': f'zyxbebidas {MARCA}',
        'stock': 7}}
    resumen, detalles, resultado = _preparar_y_ejecutar(cursor, plan)
    assert resumen == f'Crear producto Zyxarepa {MARCA} a $ 3.500,00.'
    assert 'Sin foto: la puedes subir después en el panel de productos.' in detalles
    with cursor() as cur:
        cur.execute('SELECT precio, referencia, stock, genero_id FROM productos WHERE id = %s',
                    (resultado['producto_id'],))
        fila = cur.fetchone()
        assert float(fila['precio']) == 3500 and fila['stock'] == 7
        assert fila['referencia'].startswith('IA-') and fila['genero_id'] == base['generos'][0]
        cur.execute('SELECT cantidad, stock_nuevo FROM inventario_log WHERE producto_id = %s',
                    (resultado['producto_id'],))
        assert [dict(r) for r in cur.fetchall()] == [{'cantidad': 7, 'stock_nuevo': 7}]


def test_no_crea_dos_productos_con_el_mismo_nombre(base, cursor):
    with cursor() as cur, pytest.raises(acciones.AccionError, match='Ya existe un producto'):
        acciones._preparar_datos(cur, {'tipo': 'crear_producto', 'campos': {
            'nombre': f'zyxgaseosa {MARCA}', 'precio': 100, 'categoria': f'Zyxbebidas {MARCA}'}})


def test_categoria_inexistente_lista_las_que_hay(base, cursor):
    with cursor() as cur, pytest.raises(acciones.AccionAclarar, match='Las que hay son'):
        acciones._preparar_datos(cur, {'tipo': 'crear_producto', 'campos': {
            'nombre': f'Zyxnuevo {MARCA}', 'precio': 100, 'categoria': 'Qqqinexistente'}})


def test_editar_precio_por_parecido_y_sin_cambios(base, cursor):
    plan = {'tipo': 'editar_producto', 'producto': f'gaseosa {MARCA}', 'cambios': {'precio': 3800}}
    resumen, detalles, _ = _preparar_y_ejecutar(cursor, plan)
    assert 'Precio: $ 3.000,00 → $ 3.800,00' in detalles
    with cursor() as cur:
        cur.execute('SELECT precio FROM productos WHERE id = %s', (base['productos'][0],))
        assert float(cur.fetchone()['precio']) == 3800
        with pytest.raises(acciones.AccionError, match='ya son los actuales'):
            acciones._preparar_datos(cur, {**plan, 'cambios': {'precio': '3.800'}})


def test_editar_rechaza_si_cambio_desde_la_vista_previa(base, cursor):
    plan = {'tipo': 'editar_producto', 'producto_id': base['productos'][0], 'cambios': {'precio': 4000}}
    with cursor() as cur:
        payload, _, _ = acciones._preparar_datos(cur, plan)
        cur.execute('UPDATE productos SET precio = 3100 WHERE id = %s', (base['productos'][0],))
    with cursor() as cur, pytest.raises(acciones.AccionError, match='cambió desde la vista previa'):
        acciones._ejecutar(cur, {'tipo': 'editar_producto', 'payload': payload}, 1)


def test_una_venta_no_invalida_un_cambio_de_precio(base, cursor):
    plan = {'tipo': 'editar_producto', 'producto_id': base['productos'][0], 'cambios': {'precio': 4200}}
    with cursor() as cur:
        payload, _, _ = acciones._preparar_datos(cur, plan)
        cur.execute('UPDATE productos SET stock = stock - 1 WHERE id = %s', (base['productos'][0],))
    with cursor() as cur:
        acciones._ejecutar(cur, {'tipo': 'editar_producto', 'payload': payload}, 1)


@pytest.mark.parametrize('cambios, error', [
    ({'referencia': 'X-1'}, 'La referencia no se cambia'),
    ({'stock': 3}, 'El stock se cambia con un movimiento'),
])
def test_referencia_y_stock_no_se_editan(base, cursor, cambios, error):
    with cursor() as cur, pytest.raises(acciones.AccionError, match=error):
        acciones._preparar_datos(cur, {'tipo': 'editar_producto',
                                       'producto_id': base['productos'][0], 'cambios': cambios})


def test_archivar_sin_columna_active_no_se_hace(base, cursor):
    with cursor() as cur:
        if 'active' in catalogo._columnas(cur):
            pytest.skip('esta base sí tiene productos.active')
        with pytest.raises(acciones.AccionError, match='no permite archivar'):
            acciones._preparar_datos(cur, {'tipo': 'archivar_producto',
                                           'producto_id': base['productos'][0]})


def test_archivar_y_reactivar_cambian_active_y_nunca_borran():
    fuente = inspect.getsource(catalogo)
    assert 'DELETE' not in fuente.upper().replace('# NUNCA SE BORRA', '')

    termo = {'id': 5, 'nombre': 'Termo', 'referencia': 'T-1', 'precio': 10, 'stock': 1,
             'genero_id': 1, 'descripcion': '', 'active': True}

    class Cursor:
        def __init__(self):
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append((sql, params))

        def fetchall(self):
            if 'information_schema' in self.sql[-1][0]:
                return [{'column_name': c} for c in ('active', 'visible_en_ecommerce')]
            return [termo]

    cur = Cursor()
    payload = {'tipo': 'archivar_producto', 'producto_id': 5, 'snapshot': catalogo._snapshot(termo)}
    catalogo.ejecutar(cur, {'tipo': 'archivar_producto', 'payload': payload}, 1)
    ultimo = cur.sql[-1]
    assert ultimo[0] == 'UPDATE productos SET active = %s, visible_en_ecommerce = %s WHERE id = %s'
    assert ultimo[1] == (False, False, 5)


# ── Movimientos de inventario ──────────────────────────────────
def test_entrada_y_salida_con_rastro(base, cursor):
    pid = base['productos'][0]
    _, detalles, _ = _preparar_y_ejecutar(cursor, {
        'tipo': 'movimiento_inventario', 'producto_id': pid, 'direccion': 'entrada', 'cantidad': 5})
    assert 'Stock: 10 → 15' in detalles
    _preparar_y_ejecutar(cursor, {'tipo': 'movimiento_inventario', 'producto_id': pid,
                                  'direccion': 'salida', 'cantidad': 2, 'motivo': 'se dañaron'})
    with cursor() as cur:
        cur.execute('SELECT stock FROM productos WHERE id = %s', (pid,))
        assert cur.fetchone()['stock'] == 13
        cur.execute('SELECT cantidad, motivo FROM inventario_log WHERE producto_id = %s ORDER BY id',
                    (pid,))
        assert [(r['cantidad'], r['motivo']) for r in cur.fetchall()] == [
            (5, 'IA confirmada: Entrada de mercancía'), (-2, 'IA confirmada: se dañaron')]


def test_salida_mayor_al_stock_no_se_propone(base, cursor):
    with cursor() as cur, pytest.raises(acciones.AccionError, match='no alcanzan'):
        acciones._preparar_datos(cur, {'tipo': 'movimiento_inventario',
                                       'producto_id': base['productos'][0],
                                       'direccion': 'salida', 'cantidad': 99})


def test_movimiento_rechaza_si_el_stock_cambio(base, cursor):
    plan = {'tipo': 'movimiento_inventario', 'producto_id': base['productos'][0],
            'direccion': 'entrada', 'cantidad': 1}
    with cursor() as cur:
        payload, _, _ = acciones._preparar_datos(cur, plan)
        cur.execute('UPDATE productos SET stock = 4 WHERE id = %s', (base['productos'][0],))
    with cursor() as cur, pytest.raises(acciones.AccionError, match='cambió'):
        acciones._ejecutar(cur, {'tipo': 'movimiento_inventario', 'payload': payload}, 1)


# ── Categorías ─────────────────────────────────────────────────
def test_crear_categoria_y_no_duplicar(base, cursor):
    _, _, resultado = _preparar_y_ejecutar(cursor, {'tipo': 'crear_categoria',
                                                    'nombre': f'Zyxpostres {MARCA}'})
    assert resultado['categoria_id']
    with cursor() as cur, pytest.raises(acciones.AccionError, match='Ya existe la categoría'):
        acciones._preparar_datos(cur, {'tipo': 'crear_categoria', 'nombre': f'ZYXPOSTRES {MARCA}'})


def test_renombrar_categoria_toca_sus_productos(base, cursor):
    with cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'productos' "
                    "AND column_name IN ('updated_at', 'fecha_actualizacion')")
        columna = next((r['column_name'] for r in cur.fetchall()), None)
        if columna:
            cur.execute(f"UPDATE productos SET {columna} = NOW() - INTERVAL '1 day' WHERE id = %s",
                        (base['productos'][0],))
    _, detalles, _ = _preparar_y_ejecutar(cursor, {
        'tipo': 'renombrar_categoria', 'categoria': f'zyxbebidas {MARCA}',
        'nombre_nuevo': f'Zyxbebidas frias {MARCA}'})
    assert 'Productos que la usan: 1 (se actualizan también en el escritorio).' in detalles
    with cursor() as cur:
        cur.execute('SELECT nombre FROM generos WHERE id = %s', (base['generos'][0],))
        assert cur.fetchone()['nombre'] == f'Zyxbebidas frias {MARCA}'
        if columna:
            cur.execute(f"SELECT {columna} > NOW() - INTERVAL '1 minute' AS tocado FROM productos "
                        'WHERE id = %s', (base['productos'][0],))
            assert cur.fetchone()['tocado'], 'el escritorio no se enteraría del cambio'


# ── Datos dichos por la persona ────────────────────────────────
def test_precio_dicho_en_palabras_y_datos_opcionales_inventados():
    plan = {'tipo': 'crear_producto', 'campos': {
        'nombre': 'Arepa', 'precio': 3000, 'categoria': 'Comidas',
        'descripcion': 'Deliciosa arepa artesanal', 'costo': 1200}}
    acciones._solo_datos_dichos(plan, 'Crea el producto Arepa a 3 mil en Comidas', None)
    assert plan['campos'] == {'nombre': 'Arepa', 'precio': 3000, 'categoria': 'Comidas'}


@pytest.mark.parametrize('plan, frase, pregunta', [
    ({'tipo': 'crear_producto', 'campos': {'nombre': 'Arepa', 'precio': 3500, 'categoria': 'Comidas'}},
     'Crea el producto Arepa en Comidas', 'precio de venta'),
    ({'tipo': 'crear_producto', 'campos': {'nombre': 'Arepa', 'precio': 3500, 'categoria': 'Comidas'}},
     'Crea el producto Arepa a 3500', 'categoría'),
    ({'tipo': 'movimiento_inventario', 'producto': 'gaseosa', 'direccion': 'entrada', 'cantidad': 12},
     'Entraron gaseosas', 'Cuántas unidades'),
    ({'tipo': 'editar_producto', 'producto': 'gaseosa', 'cambios': {'precio': 3900}},
     'Sube el precio de la gaseosa', 'nuevo precio'),
])
def test_lo_no_dicho_se_pregunta(plan, frase, pregunta):
    with pytest.raises(acciones.AccionAclarar, match=pregunta):
        acciones._solo_datos_dichos(plan, frase, None)


def test_la_direccion_sale_del_verbo():
    plan = acciones._completar_identidad(
        {'tipo': 'movimiento_inventario', 'producto': 'tortas', 'direccion': 'entrada', 'cantidad': 2},
        'movimiento_inventario', 'Se dañaron 2 tortas')
    assert plan['direccion'] == 'salida'


@pytest.mark.parametrize('frase, tipo', [
    ('Crea el producto Gaseosa 400ml a 3.500 en Bebidas', 'crear_producto'),
    ('Crea el producto Pan y ponle precio 2000 en Panadería', 'crear_producto'),
    ('Sube el precio de la gaseosa a 3800', 'editar_producto'),
    ('Archiva el producto Termo de acero', 'archivar_producto'),
    ('Reactiva el producto Termo', 'reactivar_producto'),
    ('Entraron 10 gaseosas', 'movimiento_inventario'),
    ('Se dañaron 2 tortas de chocolate', 'movimiento_inventario'),
    ('Agrega 5 unidades al stock de arepas', 'movimiento_inventario'),
    ('Fija el stock de la gaseosa en 20 por conteo físico', 'ajustar_inventario'),
    ('Crea la categoría Postres', 'crear_categoria'),
    ('Renombra la categoría Bebidas a Bebidas frías', 'renombrar_categoria'),
    ('Crea un proveedor', 'crear_contacto'),
])
def test_cada_orden_va_a_su_proceso(frase, tipo):
    assert acciones.parece_operativa(frase) and acciones._tipo_solicitado(frase) == tipo


@pytest.mark.parametrize('frase', ['¿Cuántas gaseosas entraron ayer?',
                                   'Crea un pedido para el cliente Juan',
                                   '¿Cuál es el precio de la gaseosa?'])
def test_las_preguntas_no_son_ordenes(frase):
    assert not acciones.parece_operativa(frase)
