# -*- coding: utf-8 -*-
"""Servicio Técnico (F1): equipos, órdenes, estados, clave cifrada, enlace
público, cotización enlazada y permisos.

Contra la base de pruebas. Todo lo creado lleva la marca PYTEST-ST-<uuid> y se
borra al final; el interruptor del módulo vuelve a quedar como estaba."""
import os
import re
import uuid

import pytest

from tests.conftest import _login

MARCA = 'PYTEST-ST-' + uuid.uuid4().hex[:6]
IMEI_OK = '490154203237518'


# ── Fixtures ────────────────────────────────────────────────────
def _poner_flag(cur, valor):
    cur.execute("SELECT valor FROM cliente_config WHERE clave = 'servicio_tecnico_habilitado'")
    filas = cur.fetchall()
    previo = filas[0]['valor'] if filas else None
    if filas:
        cur.execute("UPDATE cliente_config SET valor = %s WHERE clave = 'servicio_tecnico_habilitado'", (valor,))
    else:
        cur.execute("""INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
                       VALUES ('servicio_tecnico_habilitado', %s, 'boolean', 'modulos', 'Servicio Tecnico', 0)""",
                    (valor,))
    return filas, previo


@pytest.fixture()
def modulo(flask_app, cursor):
    """Enciende o apaga el módulo y lo deja como estaba."""
    import tenant_features as tf
    estado = {}

    def poner(valor):
        with cursor() as cur:
            filas, previo = _poner_flag(cur, 'true' if valor else 'false')
            estado.setdefault('filas', filas)
            estado.setdefault('previo', previo)
        tf._clear_cache()
    poner(True)
    yield poner
    with cursor() as cur:
        if estado['filas']:
            cur.execute("UPDATE cliente_config SET valor = %s WHERE clave = 'servicio_tecnico_habilitado'",
                        (estado['previo'],))
        else:
            cur.execute("DELETE FROM cliente_config WHERE clave = 'servicio_tecnico_habilitado'")
    tf._clear_cache()


@pytest.fixture()
def limpiar(cursor):
    yield
    with cursor() as cur:
        cur.execute("SELECT id FROM crm_contactos WHERE nombre LIKE %s", (MARCA + '%',))
        ids = [r['id'] for r in cur.fetchall()]
        if ids:
            cur.execute("SELECT to_regclass('public.st_ordenes') AS t")
            if cur.fetchone()['t']:
                cur.execute("SELECT id FROM st_ordenes WHERE crm_contacto_id = ANY(%s)", (ids,))
                ords = [r['id'] for r in cur.fetchall()]
                cur.execute("SELECT id FROM st_equipos WHERE crm_contacto_id = ANY(%s)", (ids,))
                eqs = [r['id'] for r in cur.fetchall()]
                cur.execute("DELETE FROM st_seguimientos WHERE orden_id = ANY(%s) OR equipo_id = ANY(%s)", (ords, eqs))
                cur.execute("SELECT to_regclass('public.st_fotos') AS t")
                if cur.fetchone()['t']:
                    cur.execute("DELETE FROM st_fotos WHERE equipo_id = ANY(%s)", (eqs,))
                    cur.execute("DELETE FROM st_mantenimientos WHERE equipo_id = ANY(%s)", (eqs,))
                cur.execute("DELETE FROM st_eventos WHERE orden_id = ANY(%s) OR equipo_id = ANY(%s)", (ords, eqs))
                cur.execute("DELETE FROM st_cambios WHERE equipo_id = ANY(%s)", (eqs,))
                cur.execute("DELETE FROM st_ordenes WHERE id = ANY(%s)", (ords,))
                cur.execute("DELETE FROM st_equipos WHERE id = ANY(%s)", (eqs,))
            cur.execute("DELETE FROM cotizaciones WHERE crm_contacto_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM crm_contactos WHERE id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM cotizaciones WHERE cliente_nombre LIKE %s", (MARCA + '%',))


@pytest.fixture()
def dueno(client):
    _login(client, 2)
    return client


def _form_orden(nombre=None, **extra):
    datos = {
        'cliente_nombre': nombre or MARCA + ' Ana',
        'cliente_whatsapp': '300 123 4567',
        'cliente_email': 'pytest-st@ejemplo.com',
        'equipo_tipo': 'celular',
        'equipo_marca': 'Samsung',
        'equipo_modelo': 'Galaxy A54',
        'equipo_serial': 'SER-' + MARCA,
        'equipo_imei': IMEI_OK,
        'equipo_extra_bateria_salud': '81',
        'equipo_extra_inventado': 'no debe guardarse',
        'falla_reportada': 'No carga y se calienta',
        'estado_fisico': 'Pantalla rayada',
        'accesorios': ['Cargador', 'SIM'],
        'clave': 'patron-L-1234',
        'valor_estimado': '120.000',
        'garantia_dias': '30',
    }
    datos.update(extra)
    return datos


def _crear(dueno, **extra):
    r = dueno.post('/admin/servicio-tecnico/nueva', data=_form_orden(**extra))
    assert r.status_code == 302, r.get_data(as_text=True)[:400]
    return int(r.headers['Location'].rstrip('/').split('/')[-1])


# ── Reglas fijas ────────────────────────────────────────────────
def test_imei_valida_digito_de_control():
    from services import servicio_tecnico_service as st
    assert st.imei_valido(IMEI_OK)
    assert st.imei_valido('49015 4203237518')
    assert not st.imei_valido('490154203237519')
    assert not st.imei_valido('49015420323751')


def test_extras_solo_del_tipo():
    from services import servicio_tecnico_tipos as tipos
    ups = tipos.limpiar_extras('ups', {'capacidad_va': '1000', 'topologia': 'Inventada', 'pulgadas': '55',
                                        'baterias_ultimo_cambio': '2024-01-10'})
    assert ups == {'capacidad_va': '1000', 'baterias_ultimo_cambio': '2024-01-10'}
    assert tipos.limpiar_extras('televisor', {'smart': 'on'}) == {'smart': 'si'}


@pytest.mark.parametrize('archivo, atributo', [('0018_servicio_tecnico.sql', 'DDL_0018'),
                                               ('0019_servicio_tecnico_solucion.sql', 'DDL_0019'),
                                               ('0020_servicio_tecnico_fotos_mantenimiento.sql', 'DDL_0020'),
                                               ('0021_servicio_tecnico_documentos_importacion.sql', 'DDL_0021')])
def test_migracion_del_maestro_igual_al_codigo(archivo, atributo):
    from services import servicio_tecnico_service as st
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ruta = os.path.normpath(os.path.join(app_dir, '..', '..', 'CyberShopAdmin', 'migrations', 'tenant', archivo))
    if not os.path.exists(ruta):
        pytest.skip('El repo del maestro no está al lado (servidor).')
    sql = open(ruta, encoding='utf-8').read()
    sql = '\n'.join(l for l in sql.splitlines() if not l.strip().startswith('--'))
    norm = lambda s: re.sub(r'\s+', ' ', s).strip()
    assert norm(sql) == norm(getattr(st, atributo))


# ── Módulo apagado ──────────────────────────────────────────────
def test_modulo_apagado_redirige_y_publico_404(modulo, dueno):
    modulo(False)
    r = dueno.get('/admin/servicio-tecnico/')
    assert r.status_code == 302
    assert dueno.get('/servicio/token-inexistente').status_code == 404


# ── Flujo completo ──────────────────────────────────────────────
def test_flujo_orden_completo(modulo, dueno, cursor, limpiar):
    orden_id = _crear(dueno)
    from services import servicio_tecnico_service as st
    with cursor() as cur:
        cur.execute('SELECT * FROM st_ordenes WHERE id = %s', (orden_id,))
        o = cur.fetchone()
        cur.execute('SELECT * FROM st_equipos WHERE id = %s', (o['equipo_id'],))
        e = cur.fetchone()
    assert o['numero'] == f'OS-{orden_id:06d}' and o['estado'] == 'recibido'
    assert o['accesorios'] == 'Cargador, SIM'
    assert float(o['valor_estimado']) == 120000
    # Clave cifrada: nunca en claro en la BD ni en la página
    assert o['clave_cifrada'] and 'patron-L-1234' not in o['clave_cifrada']
    assert e['extras'] == {'bateria_salud': '81'} and e['imei'] == IMEI_OK

    html = dueno.get(f'/admin/servicio-tecnico/orden/{orden_id}').get_data(as_text=True)
    assert o['numero'] in html and 'patron-L-1234' not in html

    r = dueno.post(f'/admin/servicio-tecnico/orden/{orden_id}/clave')
    assert r.get_json() == {'ok': True, 'clave': 'patron-L-1234'}
    assert any(ev['tipo'] == 'clave' for ev in st.eventos(orden_id=orden_id))

    # Transición inválida: no cambia nada
    dueno.post(f'/admin/servicio-tecnico/orden/{orden_id}/estado', data={'estado': 'entregado'})
    assert st.obtener_orden(orden_id)['estado'] == 'recibido'

    for nuevo in ('diagnostico', 'reparacion', 'listo'):
        dueno.post(f'/admin/servicio-tecnico/orden/{orden_id}/estado', data={'estado': nuevo})
    dueno.post(f'/admin/servicio-tecnico/orden/{orden_id}/estado',
               data={'estado': 'entregado', 'valor_final': '150000'})
    fin = st.obtener_orden(orden_id)
    assert fin['estado'] == 'entregado' and float(fin['valor_final']) == 150000
    assert fin['fecha_listo'] and fin['fecha_entregado'] and fin['garantia_hasta']
    assert (fin['garantia_hasta'] - fin['fecha_entregado'].date()).days == 30

    # El CRM ve la historia del contacto
    with cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM crm_actividades WHERE contacto_id = %s', (o['crm_contacto_id'],))
        assert cur.fetchone()['n'] >= 5

    # Página pública: estado sí; datos sensibles no
    pub = dueno.get(f"/servicio/{o['token_publico']}").get_data(as_text=True)
    assert o['numero'] in pub and 'Entregado' in pub
    for secreto in ('patron-L-1234', 'pytest-st@ejemplo.com', '300 123 4567', 'No carga y se calienta', 'SER-'):
        assert secreto not in pub


def test_imei_invalido_no_crea_nada(modulo, dueno, cursor, limpiar):
    r = dueno.post('/admin/servicio-tecnico/nueva', data=_form_orden(equipo_imei='490154203237519'))
    assert r.status_code == 400 and 'IMEI' in r.get_data(as_text=True)
    with cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM crm_contactos WHERE nombre LIKE %s', (MARCA + '%',))
        assert cur.fetchone()['n'] == 0      # todo en una transacción


def test_equipo_existente_y_serial_repetido(modulo, dueno, cursor, limpiar):
    from services import servicio_tecnico_service as st
    primera = st.obtener_orden(_crear(dueno))
    # Segunda orden del mismo equipo
    segunda = _crear(dueno, crm_contacto_id=str(primera['crm_contacto_id']), equipo_id=str(primera['equipo_id']))
    assert st.obtener_orden(segunda)['equipo_id'] == primera['equipo_id']
    assert len(st.ordenes_de_equipo(primera['equipo_id'])) == 2
    # Otro equipo del mismo cliente con el mismo serial: no
    r = dueno.post('/admin/servicio-tecnico/nueva',
                   data=_form_orden(crm_contacto_id=str(primera['crm_contacto_id']), equipo_imei=''))
    assert r.status_code == 400 and 'serial' in r.get_data(as_text=True)
    # Equipo de otro cliente: no
    otro = st.obtener_orden(_crear(dueno, nombre=MARCA + ' Beto', equipo_serial='OTRO-' + MARCA))
    r = dueno.post('/admin/servicio-tecnico/nueva',
                   data=_form_orden(crm_contacto_id=str(primera['crm_contacto_id']), equipo_id=str(otro['equipo_id'])))
    assert r.status_code == 400


def test_ficha_y_piezas(modulo, dueno, limpiar):
    from services import servicio_tecnico_service as st
    o = st.obtener_orden(_crear(dueno))
    r = dueno.post(f"/admin/servicio-tecnico/equipo/{o['equipo_id']}/cambio",
                   data={'componente': 'Batería', 'fecha': '2026-10-02', 'proxima_revision': '2026-01-01'})
    assert st.cambios_de_equipo(o['equipo_id']) == []          # revisión anterior al cambio
    dueno.post(f"/admin/servicio-tecnico/equipo/{o['equipo_id']}/cambio",
               data={'componente': 'Batería', 'detalle': '5000 mAh', 'fecha': '2026-10-02',
                     'proxima_revision': '2028-10-02', 'orden_id': o['id']})
    assert st.cambios_de_equipo(o['equipo_id'])[0]['componente'] == 'Batería'
    html = dueno.get(f"/admin/servicio-tecnico/equipo/{o['equipo_id']}").get_data(as_text=True)
    assert 'Salud de batería' in html and '5000 mAh' in html and 'Galaxy A54' in html
    r = dueno.post(f"/admin/servicio-tecnico/equipo/{o['equipo_id']}/editar",
                   data={'equipo_tipo': 'celular', 'equipo_marca': 'Samsung', 'equipo_modelo': 'Galaxy A55',
                         'equipo_extra_version_sistema': 'Android 14'})
    assert r.status_code == 302
    eq = st.obtener_equipo(o['equipo_id'])
    assert eq['modelo'] == 'Galaxy A55' and eq['extras'] == {'version_sistema': 'Android 14'}


def test_cotizacion_enlazada(modulo, dueno, cursor, limpiar):
    from services import servicio_tecnico_service as st
    o = st.obtener_orden(_crear(dueno))
    r = dueno.get(f"/admin/servicio-tecnico/orden/{o['id']}/cotizar")
    assert r.status_code == 302 and 'st_orden=' in r.headers['Location']
    html = dueno.get(f"/admin/cotizar?st_orden={o['id']}").get_data(as_text=True)
    assert o['numero'] in html and 'name="st_orden_id"' in html and MARCA in html

    with cursor() as cur:
        cur.execute("""INSERT INTO cotizaciones (cliente_nombre, total, crm_contacto_id)
                       VALUES (%s, 0, %s) RETURNING id""", (MARCA + ' COT', o['crm_contacto_id']))
        cot = cur.fetchone()['id']
    st.vincular_cotizacion(o['id'], cot)
    assert st.obtener_orden(o['id'])['estado'] == 'cotizado'
    st.al_aprobar_cotizacion(cot)
    assert st.obtener_orden(o['id'])['estado'] == 'aprobado'
    st.al_aprobar_cotizacion(999999999)                       # sin orden: no falla


def test_cotizar_sin_orden_queda_igual(modulo, dueno):
    html = dueno.get('/admin/cotizar?st_orden=999999999').get_data(as_text=True)
    assert 'name="st_orden_id"' not in html


# ── Permisos ────────────────────────────────────────────────────
def test_roles(modulo, client):
    _login(client, 4)                      # empleado: sí
    assert client.get('/admin/servicio-tecnico/').status_code == 200
    _login(client, 5)                      # contador: no
    assert client.get('/admin/servicio-tecnico/').status_code in (302, 403)
    _login(client, 3)                      # cliente de la tienda: no
    assert client.get('/admin/servicio-tecnico/').status_code in (302, 403)


def test_publico_token_desconocido(modulo, client):
    assert client.get('/servicio/' + 'x' * 30).status_code == 404
    assert client.get('/servicio/' + 'x' * 80).status_code == 404
