# -*- coding: utf-8 -*-
"""Nómina con base de datos: cálculo guardado, bloqueos de integridad,
novedades, liquidación con vista previa, PILA y páginas.

Los datos de prueba llevan el marcador TEST-NOM y se borran al terminar;
los registros que ya existían en la BD de pruebas no se tocan."""
from datetime import date

import pytest

SMMLV = 1750905.0


@pytest.fixture()
def nomina(flask_app, cursor):
    """Parámetros 2026, un empleado, un contratista y un periodo de julio 2026."""
    from services import nomina_service
    nomina_service.asegurar_esquema()
    creados = {'params': False}
    with cursor() as cur:
        cur.execute("SELECT 1 FROM nomina_parametros WHERE anio = 2026")
        if not cur.fetchone():
            cur.execute("""INSERT INTO nomina_parametros (anio, salario_minimo, auxilio_transporte, uvt, exonerado_114_1)
                           VALUES (2026, %s, 249095, 52374, TRUE)""", (SMMLV,))
            creados['params'] = True
        cur.execute("""INSERT INTO nomina_empleados (tipo_documento, numero_documento, nombres, apellidos, fecha_ingreso,
                           tipo_vinculacion, cargo, salario_base, nivel_arl, eps, fondo_pension, fondo_cesantias, activo)
                       VALUES ('CC', 'TEST-NOM-1', 'Ana', 'TEST-NOM', '2025-03-01', 'INDEFINIDO', 'Cajera', %s, 'I',
                               'Sura', 'Porvenir', 'Porvenir', TRUE) RETURNING id""", (SMMLV,))
        emp = cur.fetchone()['id']
        cur.execute("""INSERT INTO nomina_empleados (tipo_documento, numero_documento, nombres, apellidos, fecha_ingreso,
                           tipo_vinculacion, cargo, salario_base, nivel_arl, activo)
                       VALUES ('CC', 'TEST-NOM-2', 'Luis', 'TEST-NOM', '2026-01-01', 'CONTRATISTA', 'Diseño', 8000000, 'I', TRUE)
                       RETURNING id""")
        con = cur.fetchone()['id']
        cur.execute("""INSERT INTO nomina_periodos (anio, mes, numero_periodo, fecha_inicio, fecha_fin, estado, observaciones)
                       VALUES (2026, 7, 0, '2026-07-01', '2026-07-31', 'borrador', 'TEST-NOM') RETURNING id""")
        per = cur.fetchone()['id']
    yield {'empleado': emp, 'contratista': con, 'periodo': per}
    with cursor() as cur:
        cur.execute("SELECT id FROM nomina_empleados WHERE numero_documento LIKE 'TEST-NOM-%%'")
        ids = [r['id'] for r in cur.fetchall()]
        cur.execute("SELECT id FROM nomina_periodos WHERE observaciones = 'TEST-NOM'")
        periodos = [r['id'] for r in cur.fetchall()]
        if ids:
            cur.execute("DELETE FROM nomina_contratistas_pila WHERE empleado_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM nomina_liquidaciones WHERE empleado_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM nomina_novedades WHERE empleado_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM nomina_detalle WHERE empleado_id = ANY(%s)", (ids,))
        if periodos:
            cur.execute("DELETE FROM nomina_novedades WHERE periodo_id = ANY(%s)", (periodos,))
            cur.execute("DELETE FROM nomina_detalle WHERE periodo_id = ANY(%s)", (periodos,))
            cur.execute("DELETE FROM nomina_periodos WHERE id = ANY(%s)", (periodos,))
        if ids:
            cur.execute("DELETE FROM nomina_empleados WHERE id = ANY(%s)", (ids,))
        if creados['params']:
            cur.execute("DELETE FROM nomina_parametros WHERE anio = 2026")


def _detalle(cursor, periodo, empleado):
    with cursor() as cur:
        cur.execute("SELECT * FROM nomina_detalle WHERE periodo_id = %s AND empleado_id = %s", (periodo, empleado))
        return cur.fetchone()


def _estado(cursor, periodo):
    with cursor() as cur:
        cur.execute("SELECT * FROM nomina_periodos WHERE id = %s", (periodo,))
        return cur.fetchone()


def test_calcular_guarda_aportes_provisiones_y_explicacion(as_propietario, nomina, cursor):
    r = as_propietario.post(f"/admin/nomina/periodos/{nomina['periodo']}/calcular")
    assert r.status_code == 302
    d = _detalle(cursor, nomina['periodo'], nomina['empleado'])
    assert float(d['total_devengado']) == pytest.approx(2000000)
    assert float(d['pension_empleador']) == pytest.approx(210108.6)
    assert float(d['ccf']) == pytest.approx(70036.2)
    assert float(d['cesantias_provision']) == pytest.approx(166666.67)
    assert d['calculo']['tipo'] == 'EMPLEADO'
    c = _detalle(cursor, nomina['periodo'], nomina['contratista'])
    assert float(c['salud_empleado']) == 0
    assert float(c['neto_pagar']) == pytest.approx(8000000 - float(c['retencion_fuente']))
    assert float(c['ss_contratista']) == pytest.approx(400000 + 512000 + 3200000 * 0.00522, abs=0.02)
    p = _estado(cursor, nomina['periodo'])
    assert p['estado'] == 'calculada' and p['motor_version'] and p['parametros_usados']['horas_mes'] == 210


def test_periodo_aprobado_no_se_recalcula(as_propietario, nomina, cursor):
    from services import nomina_service
    as_propietario.post(f"/admin/nomina/periodos/{nomina['periodo']}/calcular")
    with cursor() as cur:
        cur.execute("UPDATE nomina_periodos SET estado = 'aprobada' WHERE id = %s", (nomina['periodo'],))
    antes = _detalle(cursor, nomina['periodo'], nomina['empleado'])
    with pytest.raises(nomina_service.PeriodoBloqueado):
        with cursor() as cur:
            nomina_service.calcular_y_guardar_periodo(cur, nomina['periodo'])
    as_propietario.post(f"/admin/nomina/periodos/{nomina['periodo']}/calcular")
    despues = _detalle(cursor, nomina['periodo'], nomina['empleado'])
    assert despues['id'] == antes['id'] and despues['neto_pagar'] == antes['neto_pagar']


def test_novedad_rechazada_en_periodo_aprobado(as_propietario, nomina, cursor):
    with cursor() as cur:
        cur.execute("UPDATE nomina_periodos SET estado = 'aprobada' WHERE id = %s", (nomina['periodo'],))
    as_propietario.post('/admin/nomina/novedades/crear', data={
        'periodo_id': nomina['periodo'], 'empleado_id': nomina['empleado'], 'tipo_novedad': 'HED',
        'cantidad': '2', 'fecha_novedad': '2026-07-20'})
    with cursor() as cur:
        cur.execute("SELECT count(*) n FROM nomina_novedades WHERE periodo_id = %s", (nomina['periodo'],))
        assert cur.fetchone()['n'] == 0


def test_novedad_automatica_y_manual(as_propietario, nomina, cursor):
    base = {'periodo_id': nomina['periodo'], 'empleado_id': nomina['empleado'], 'fecha_novedad': '2026-07-20'}
    as_propietario.post('/admin/nomina/novedades/crear', data={**base, 'tipo_novedad': 'HED', 'cantidad': '10'})
    as_propietario.post('/admin/nomina/novedades/crear', data={**base, 'tipo_novedad': 'HEN', 'cantidad': '1', 'valor_total': '12345'})
    as_propietario.post('/admin/nomina/novedades/crear', data={**base, 'tipo_novedad': 'PRESTAMO', 'valor_total': '50000'})
    with cursor() as cur:
        cur.execute("SELECT tipo_novedad, valor_total, valor_manual FROM nomina_novedades WHERE periodo_id = %s ORDER BY id", (nomina['periodo'],))
        filas = cur.fetchall()
    assert [f['tipo_novedad'] for f in filas] == ['HED', 'HEN', 'PRESTAMO']
    assert float(filas[0]['valor_total']) == pytest.approx(SMMLV / 210 * 1.25 * 10, abs=0.01)
    assert filas[0]['valor_manual'] is False
    assert float(filas[1]['valor_total']) == 12345 and filas[1]['valor_manual'] is True

    as_propietario.post(f"/admin/nomina/periodos/{nomina['periodo']}/calcular")
    d = _detalle(cursor, nomina['periodo'], nomina['empleado'])
    assert float(d['horas_extras']) == pytest.approx(SMMLV / 210 * 1.25 * 10 + 12345, abs=0.02)
    assert float(d['prestamos']) == 50000


def test_novedad_en_periodo_calculado_lo_devuelve_a_borrador(as_propietario, nomina, cursor):
    as_propietario.post(f"/admin/nomina/periodos/{nomina['periodo']}/calcular")
    assert _estado(cursor, nomina['periodo'])['estado'] == 'calculada'
    as_propietario.post('/admin/nomina/novedades/crear', data={
        'periodo_id': nomina['periodo'], 'empleado_id': nomina['empleado'], 'tipo_novedad': 'RN',
        'cantidad': '4', 'fecha_novedad': '2026-07-10'})
    assert _estado(cursor, nomina['periodo'])['estado'] == 'borrador'


def test_novedad_del_escritorio_se_recalcula_con_el_motor_vigente(as_propietario, nomina, cursor):
    # El escritorio viejo calculaba con 240 h; el servidor recalcula al liquidar.
    with cursor() as cur:
        cur.execute("""INSERT INTO nomina_novedades (periodo_id, empleado_id, tipo_novedad, cantidad, valor_total, fecha_novedad)
                       VALUES (%s, %s, 'HED', 10, %s, '2026-07-20')""", (nomina['periodo'], nomina['empleado'], SMMLV / 240 * 1.25 * 10))
    as_propietario.post(f"/admin/nomina/periodos/{nomina['periodo']}/calcular")
    with cursor() as cur:
        cur.execute("SELECT valor_total FROM nomina_novedades WHERE periodo_id = %s", (nomina['periodo'],))
        assert float(cur.fetchone()['valor_total']) == pytest.approx(SMMLV / 210 * 1.25 * 10, abs=0.01)


def test_sincronizacion_no_borra_novedades_de_periodo_aprobado(flask_app, nomina, cursor):
    from routes import api_sync
    with cursor() as cur:
        cur.execute("""INSERT INTO nomina_novedades (periodo_id, empleado_id, tipo_novedad, cantidad, valor_total)
                       VALUES (%s, %s, 'BONIF_S', 1, 1000) RETURNING id""", (nomina['periodo'], nomina['empleado']))
        nid = cur.fetchone()['id']
        cur.execute("UPDATE nomina_periodos SET estado = 'aprobada' WHERE id = %s", (nomina['periodo'],))
    with pytest.raises(api_sync._ForbiddenError):
        with cursor() as cur:
            api_sync._apply_nomina_op(cur, {'op': 'delete_novedad', 'novedad_id': nid})
    with cursor() as cur:
        cur.execute("SELECT count(*) n FROM nomina_novedades WHERE id = %s", (nid,))
        assert cur.fetchone()['n'] == 1


def test_sincronizacion_calcula_igual_que_la_web(flask_app, nomina, cursor):
    from routes import api_sync
    with cursor() as cur:
        assert api_sync._apply_nomina_op(cur, {'op': 'calcular_periodo', 'periodo_id': nomina['periodo']}) == nomina['periodo']
    d = _detalle(cursor, nomina['periodo'], nomina['empleado'])
    assert float(d['pension_empleador']) == pytest.approx(210108.6)


def test_liquidacion_previa_no_guarda_y_confirmar_guarda_una_vez(as_propietario, nomina, cursor):
    datos = {'empleado_id': nomina['empleado'], 'fecha_retiro': '2026-11-15', 'motivo_retiro': 'RENUNCIA'}
    r = as_propietario.post('/admin/nomina/liquidaciones/crear', data={**datos, 'accion': 'previsualizar'})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'Vista previa' in html and 'Confirmar y guardar' in html
    with cursor() as cur:
        cur.execute("SELECT count(*) n FROM nomina_liquidaciones WHERE empleado_id = %s", (nomina['empleado'],))
        assert cur.fetchone()['n'] == 0

    r = as_propietario.post('/admin/nomina/liquidaciones/crear', data={**datos, 'accion': 'confirmar'})
    assert r.status_code == 302
    as_propietario.post('/admin/nomina/liquidaciones/crear', data={**datos, 'accion': 'confirmar'})
    with cursor() as cur:
        cur.execute("SELECT * FROM nomina_liquidaciones WHERE empleado_id = %s", (nomina['empleado'],))
        filas = cur.fetchall()
        cur.execute("SELECT activo FROM nomina_empleados WHERE id = %s", (nomina['empleado'],))
        activo = cur.fetchone()['activo']
    assert len(filas) == 1 and not activo
    assert float(filas[0]['indemnizacion']) == 0  # renuncia: sin indemnización
    r = as_propietario.get(f"/admin/nomina/liquidaciones/ver/{filas[0]['id']}")
    assert r.status_code == 200 and 'Renuncia voluntaria' in r.get_data(as_text=True)


def test_pila_incompleta_queda_pendiente(as_propietario, nomina, cursor):
    as_propietario.post(f"/admin/nomina/contratistas/pila/{nomina['contratista']}", data={
        'numero_planilla': 'TEST-NOM-PILA', 'fecha_pago': date.today().isoformat(), 'valor_pagado': '100000',
        'periodo_id': nomina['periodo']})
    with cursor() as cur:
        cur.execute("SELECT verificado, periodo_id FROM nomina_contratistas_pila WHERE empleado_id = %s", (nomina['contratista'],))
        fila = cur.fetchone()
    assert fila['verificado'] is False and fila['periodo_id'] == nomina['periodo']


def test_paginas_del_modulo_cargan(as_propietario, nomina):
    as_propietario.post(f"/admin/nomina/periodos/{nomina['periodo']}/calcular")
    for url in ('/admin/nomina/', '/admin/nomina/empleados', '/admin/nomina/empleados/crear',
                f"/admin/nomina/empleados/editar/{nomina['empleado']}", '/admin/nomina/contratistas',
                '/admin/nomina/periodos', f"/admin/nomina/periodos/{nomina['periodo']}",
                f"/admin/nomina/periodos/{nomina['periodo']}/desprendible/{nomina['empleado']}",
                f"/admin/nomina/periodos/{nomina['periodo']}/desprendible/{nomina['contratista']}",
                '/admin/nomina/novedades', '/admin/nomina/novedades/crear', '/admin/nomina/liquidaciones',
                '/admin/nomina/liquidaciones/crear', '/admin/nomina/parametros'):
        r = as_propietario.get(url)
        assert r.status_code == 200, url


def test_vista_previa_de_novedad(as_propietario, nomina):
    r = as_propietario.get('/admin/nomina/novedades/valor', query_string={
        'empleado_id': nomina['empleado'], 'tipo': 'HEDF', 'cantidad': 2, 'fecha': '2026-07-19'})
    d = r.get_json()
    assert d['ok'] and d['factor'] == pytest.approx(2.15) and d['horas_mes'] == 210


def test_empleado_guarda_campos_nuevos(as_propietario, nomina, cursor):
    r = as_propietario.post(f"/admin/nomina/empleados/editar/{nomina['empleado']}", data={
        'tipo_documento': 'CC', 'numero_documento': 'TEST-NOM-1', 'nombres': 'Ana', 'apellidos': 'TEST-NOM',
        'fecha_ingreso': '2025-03-01', 'tipo_vinculacion': 'INDEFINIDO', 'cargo': 'Gerente',
        'salario_base': '25000000', 'nivel_arl': 'I', 'salario_integral': '1', 'ret_dependientes': '1',
        'ret_medicina_prepagada': '300000'})
    assert r.status_code == 302
    with cursor() as cur:
        cur.execute("SELECT salario_integral, ret_dependientes, ret_medicina_prepagada FROM nomina_empleados WHERE id = %s", (nomina['empleado'],))
        e = cur.fetchone()
    assert e['salario_integral'] is True and e['ret_dependientes'] is True and float(e['ret_medicina_prepagada']) == 300000
