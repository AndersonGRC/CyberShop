# -*- coding: utf-8 -*-
"""CRM 1.9.24.0: contactos y tareas con el diseño nuevo, y el embudo con la
columna «No compró» siempre visible, «Mover a» (para celular) y el motivo.

Nada de esto depende del arrastre: en un teléfono no existe.
"""
import pytest

from database import get_db_cursor

MARCA = 'TEST-CRMD'


@pytest.fixture()
def negocio(flask_app):
    """Un contacto y una oportunidad de prueba; se borran al terminar."""
    with flask_app.app_context():
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""INSERT INTO crm_contactos (tipo, nombre, telefono, activo, notas)
                           VALUES ('lead', %s, '300 555 0199', TRUE, %s) RETURNING id""",
                        (f'{MARCA} Contacto', MARCA))
            cid = cur.fetchone()['id']
            cur.execute("""INSERT INTO crm_oportunidades (contacto_id, titulo, monto_estimado, etapa)
                           VALUES (%s, %s, 1500000, 'propuesta') RETURNING id""",
                        (cid, f'{MARCA} Negocio'))
            oid = cur.fetchone()['id']
    yield {'contacto': cid, 'oportunidad': oid}
    with flask_app.app_context():
        with get_db_cursor() as cur:
            cur.execute('DELETE FROM crm_oportunidades WHERE titulo LIKE %s', (f'{MARCA}%',))
            cur.execute('DELETE FROM crm_contactos WHERE notas = %s', (MARCA,))


def test_contactos_filtro_activo_se_lee_y_busca(as_propietario, negocio):
    r = as_propietario.get('/admin/crm/contactos')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # El filtro elegido lleva su propia clase (antes quedaba azul sobre azul).
    assert 'class="crm-chip is-on"' in html and 'aria-current="page"' in html
    assert 'btn-filtro' not in html and 'btn-info' not in html and 'btn-warning' not in html
    # Los botones dicen lo que hacen.
    for texto in ('>Ver</a>', '>Editar</a>', '>Eliminar</button>', 'Nuevo contacto', 'Interesados'):
        assert texto in html
    r = as_propietario.get('/admin/crm/contactos?q=' + MARCA)
    html = r.get_data(as_text=True)
    assert html.count('<article class="crow') == 1 and f'{MARCA} Contacto' in html
    assert 'href="tel:3005550199"' in html
    r = as_propietario.get('/admin/crm/contactos?q=zzz-no-existe-zzz')
    assert 'No hay contactos con ese filtro' in r.get_data(as_text=True)


def test_tareas_con_el_diseno_nuevo(as_propietario):
    r = as_propietario.get('/admin/crm/tareas')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'class="crm-chip is-on"' in html and 'Pendientes' in html
    assert 'btn-info' not in html


def test_embudo_muestra_no_compro_sin_pedirlo(as_propietario, negocio):
    r = as_propietario.get('/admin/crm/pipeline')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="col-perdida"' in html and 'No compró' in html
    assert 'Mostrar perdidas' not in html
    assert 'class="js-mover"' in html and 'id="dlg-motivo"' in html
    assert '<option value="perdida"' in html


def test_marcar_no_compro_guarda_el_motivo(as_propietario, negocio, flask_app):
    oid = negocio['oportunidad']
    r = as_propietario.post(f'/admin/crm/oportunidades/{oid}/etapa',
                            data={'etapa': 'perdida', 'motivo': 'Precio: lo consiguió más barato'})
    assert r.status_code == 200 and r.get_json()['ok'] is True
    with flask_app.app_context():
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT etapa, motivo_perdida, probabilidad FROM crm_oportunidades WHERE id = %s', (oid,))
            fila = cur.fetchone()
    assert fila['etapa'] == 'perdida' and fila['motivo_perdida'] == 'Precio: lo consiguió más barato'
    assert int(fila['probabilidad']) == 0
    html = as_propietario.get('/admin/crm/pipeline').get_data(as_text=True)
    assert 'Motivo: Precio: lo consiguió más barato' in html


def test_mover_sin_motivo_no_borra_el_que_habia(as_propietario, negocio, flask_app):
    oid = negocio['oportunidad']
    as_propietario.post(f'/admin/crm/oportunidades/{oid}/etapa', data={'etapa': 'perdida', 'motivo': 'Precio'})
    r = as_propietario.post(f'/admin/crm/oportunidades/{oid}/etapa', data={'etapa': 'perdida'})
    assert r.status_code == 200
    with flask_app.app_context():
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT motivo_perdida FROM crm_oportunidades WHERE id = %s', (oid,))
            assert cur.fetchone()['motivo_perdida'] == 'Precio'
    assert as_propietario.post(f'/admin/crm/oportunidades/{oid}/etapa',
                               data={'etapa': 'inventada'}).status_code == 400
