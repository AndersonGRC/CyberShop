# -*- coding: utf-8 -*-
"""Módulo Restaurante, diseño 1.5: autoguardado del plano sin pisar el estado,
salones (crear, renombrar, eliminar vacío), tamaños del lienzo 1436×640 dentro de
los rangos de la BD, menú lateral («Restaurante» abre Atender) y las pantallas.
Contra la base de pruebas; todo lo creado se borra al final."""
import json
import uuid

import pytest

from services import restaurant_tables_service as rt

MARCA = 'ZYX' + uuid.uuid4().hex[:5].upper()
CW, CH = 1436, 640
# Tamaños del diseño (px) → % que guarda el plano (mismo cálculo que restaurant_mesas.js).
TAMANOS = {'round': (120, 120), 'square': (144, 144), 'rectangle': (264, 132)}


def _pct(px, total):
    return round(px / total * 100, 2)


@pytest.fixture()
def salones_limpios(cursor):
    """Guarda y restaura la lista de salones; borra las mesas de la prueba."""
    with cursor() as cur:
        cur.execute("SELECT valor FROM cliente_config WHERE clave = %s", (rt.SALONES_CLAVE,))
        fila = cur.fetchone()
    previo = fila['valor'] if fila else None
    yield
    with cursor() as cur:
        cur.execute("""DELETE FROM restaurant_tables
                       WHERE codigo LIKE %s AND NOT EXISTS (
                           SELECT 1 FROM restaurant_table_orders o WHERE o.table_id = restaurant_tables.id)""",
                    (f'{MARCA}%',))
        if previo is None:
            cur.execute("DELETE FROM cliente_config WHERE clave = %s", (rt.SALONES_CLAVE,))
        else:
            cur.execute("UPDATE cliente_config SET valor = %s WHERE clave = %s", (previo, rt.SALONES_CLAVE))


def _mesa(codigo, area, forma='square', **extra):
    w, h = TAMANOS[forma]
    payload = {'codigo': codigo, 'area': area, 'capacidad': 4, 'forma': forma,
               'pos_x': 5, 'pos_y': 10, 'ancho': _pct(w, CW), 'alto': _pct(h, CH), 'rotacion': 0}
    payload.update(extra)
    return rt.upsert_table_layout(1, payload)


# ── Autoguardado: nunca pisa el estado ─────────────────────────
def test_autoguardado_sin_estado_conserva_cuenta_solicitada(salones_limpios, cursor):
    tid = _mesa(f'{MARCA}-1', f'{MARCA} salón')
    with cursor() as cur:
        cur.execute("UPDATE restaurant_tables SET estado = 'cuenta_solicitada' WHERE id = %s", (tid,))
    rt.upsert_table_layout(1, {'table_id': tid, 'codigo': f'{MARCA}-1', 'area': f'{MARCA} salón',
                               'forma': 'square', 'pos_x': 20, 'pos_y': 30, 'ancho': 10.03, 'alto': 22.5})
    with cursor() as cur:
        cur.execute('SELECT estado, pos_x FROM restaurant_tables WHERE id = %s', (tid,))
        fila = cur.fetchone()
    assert fila['estado'] == 'cuenta_solicitada' and float(fila['pos_x']) == 20.0


def test_mesa_nueva_sin_estado_arranca_disponible(salones_limpios, cursor):
    tid = _mesa(f'{MARCA}-2', f'{MARCA} salón')
    with cursor() as cur:
        cur.execute('SELECT estado FROM restaurant_tables WHERE id = %s', (tid,))
        assert cur.fetchone()['estado'] == 'disponible'
    assert rt.get_table_brief(tid)['codigo'] == f'{MARCA}-2'


@pytest.mark.parametrize('forma', ['round', 'square', 'rectangle'])
def test_tamanos_del_lienzo_caben_en_los_rangos_de_la_bd(forma, salones_limpios):
    w, h = TAMANOS[forma]
    assert 8 <= _pct(w, CW) <= 30 and 8 <= _pct(h, CH) <= 30
    # Esquina inferior derecha del lienzo (lo más lejos que puede quedar una mesa).
    _mesa(f'{MARCA}-{forma[:3]}', f'{MARCA} salón', forma,
          pos_x=_pct(CW - w, CW), pos_y=_pct(CH - h, CH), rotacion=90 if forma == 'rectangle' else 0)


# ── Salones ────────────────────────────────────────────────────
def test_salones_crear_renombrar_y_eliminar(salones_limpios, cursor):
    salon, nuevo = f'{MARCA} Terraza', f'{MARCA} Terraza norte'
    nombres = [s['nombre'] for s in rt.create_salon(salon)]
    assert salon in nombres
    with pytest.raises(ValueError, match='Ya existe'):
        rt.create_salon(salon.upper())

    tid = _mesa(f'{MARCA}-3', salon)
    with cursor() as cur:
        cur.execute("UPDATE restaurant_tables SET updated_at = NOW() - INTERVAL '1 day' WHERE id = %s", (tid,))
    with pytest.raises(ValueError, match='vacío'):
        rt.delete_salon(salon)

    salones = rt.rename_salon(salon, nuevo)
    assert nuevo in [s['nombre'] for s in salones] and salon not in [s['nombre'] for s in salones]
    with cursor() as cur:
        cur.execute("SELECT area, updated_at > NOW() - INTERVAL '1 minute' AS tocada "
                    "FROM restaurant_tables WHERE id = %s", (tid,))
        fila = cur.fetchone()
    assert fila['area'] == nuevo and fila['tocada'], 'el escritorio debe recibir el cambio'

    vacio = f'{MARCA} Patio'
    rt.create_salon(vacio)
    assert vacio not in [s['nombre'] for s in rt.delete_salon(vacio)]
    with cursor() as cur:
        cur.execute("SELECT valor FROM cliente_config WHERE clave = %s", (rt.SALONES_CLAVE,))
        guardados = json.loads(cur.fetchone()['valor'])
    assert nuevo in guardados and vacio not in guardados


def test_renombrar_a_un_salon_que_ya_existe_se_rechaza(salones_limpios):
    a, b = f'{MARCA} A', f'{MARCA} B'
    rt.create_salon(a)
    rt.create_salon(b)
    with pytest.raises(ValueError, match='Ya existe'):
        rt.rename_salon(a, b.lower())


def test_nombre_de_salon_vacio_o_largo(salones_limpios):
    with pytest.raises(ValueError, match='Escribe'):
        rt.create_salon('   ')
    with pytest.raises(ValueError, match='100'):
        rt.create_salon('x' * 101)


# ── Pantallas y menú ───────────────────────────────────────────
@pytest.fixture()
def modulo_mesas(flask_app):
    from database import get_db_cursor
    from services.config_tenant import set_cliente_config
    import tenant_features as tf
    with get_db_cursor() as cur:
        cur.execute("SELECT valor FROM cliente_config WHERE clave = 'restaurant_tables_habilitado'")
        fila = cur.fetchone()
        previo = fila[0] if fila else None
        set_cliente_config(cur, 'restaurant_tables_habilitado', 'true', descripcion='Mesas')
    tf._clear_cache()
    yield
    with get_db_cursor() as cur:
        if previo is None:
            cur.execute("DELETE FROM cliente_config WHERE clave = 'restaurant_tables_habilitado'")
        else:
            cur.execute("UPDATE cliente_config SET valor = %s WHERE clave = 'restaurant_tables_habilitado'",
                        (previo,))
    tf._clear_cache()


@pytest.mark.parametrize('ruta, pestana', [
    ('/admin/restaurante/mesas/atencion', 'Atender'),
    ('/admin/restaurante/mesas/construccion', 'Crear mesas'),
])
def test_pantallas_nuevas_con_menu_desplegado(as_propietario, modulo_mesas, ruta, pestana):
    r = as_propietario.get(ruta)
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'restaurant_mesas.js' in html and 'restaurant_mesas.css' in html
    assert f'</i>{pestana}' in html
    # Header y menú de la plantilla siguen ahí; «Restaurante» entra a Atender y queda abierto.
    assert 'id="app-sidebar"' in html and 'class="footer"' in html
    assert 'data-entrada="/admin/restaurante/mesas"' in html
    assert 'has-submenu active has-active-child' in html


def test_reportes_siguen_con_su_plantilla(as_propietario, modulo_mesas):
    html = as_propietario.get('/admin/restaurante/mesas/reportes').get_data(as_text=True)
    assert 'restaurant_tables.js' in html and 'restaurant_mesas.js' not in html


def test_mesero_no_ve_crear_mesas(client, modulo_mesas):
    from tests.conftest import _login
    _login(client, 6)  # ROL_MESERO
    html = client.get('/admin/restaurante/mesas/atencion').get_data(as_text=True)
    assert 'restaurant_mesas.js' in html and '</i>Crear mesas' not in html


def test_salones_por_la_ruta(as_propietario, modulo_mesas, salones_limpios):
    r = as_propietario.post('/admin/restaurante/salones', json={'accion': 'crear', 'nombre': f'{MARCA} Bar'})
    assert r.status_code == 200 and f'{MARCA} Bar' in [s['nombre'] for s in r.get_json()['salones']]
    r = as_propietario.post('/admin/restaurante/salones', json={'accion': 'borrar-todo'})
    assert r.status_code == 400
    r = as_propietario.post('/admin/restaurante/salones', json={'accion': 'eliminar', 'nombre': f'{MARCA} Bar'})
    assert r.status_code == 200


def test_el_plano_no_borra_nada_salvo_la_mesa_sin_historial():
    import inspect
    fuente = inspect.getsource(rt.create_salon) + inspect.getsource(rt.rename_salon) + \
        inspect.getsource(rt.delete_salon)
    assert 'DELETE FROM' not in fuente.upper()
