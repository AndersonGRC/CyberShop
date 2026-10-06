# -*- coding: utf-8 -*-
"""El asistente entiende las preguntas de cotizaciones, cuentas de cobro,
cartera y cobros: a qué consulta va cada forma de preguntar, qué devuelve cada
consulta y quién puede verla.

Contra la base de pruebas: los documentos creados llevan la marca y se borran."""
import uuid

import pytest

from services.ia_datos.acceso import Contexto

MARCA = 'PYTEST-COB-' + uuid.uuid4().hex[:6]

# (pregunta, consulta esperada, parámetros esperados o None si no importan)
BANCO = [
    ('¿Cuántas cotizaciones hice este mes?', 'cotizaciones_estado', {'periodo': 'mes'}),
    ('¿Cuánto he cotizado este año?', 'cotizaciones_estado', {'periodo': 'anio'}),
    ('¿Qué cotizaciones están pendientes?', 'cotizaciones_estado', None),
    ('¿Qué cotizaciones me rechazaron?', 'cotizaciones_estado', None),
    ('¿Cuál es mi tasa de aprobación de cotizaciones?', 'cotizaciones_estado', None),
    ('¿Cuántos presupuestos envié este mes?', 'cotizaciones_estado', {'periodo': 'mes'}),
    ('¿Cuál fue la cotización más grande del mes?', 'cotizaciones_estado', {'periodo': 'mes'}),
    ('¿A quién le he cotizado más?', 'cotizaciones_estado', None),
    ('¿Qué le cotizamos a Juan Pérez?', 'cotizacion_detalle', {'texto': 'Juan Pérez'}),
    ('Muéstrame la cotización COT 0000000012', 'cotizacion_detalle', {'texto': 'COT 0000000012'}),
    ('¿Ya me aprobaron la cotización de Juan Pérez?', 'cotizacion_detalle', {'texto': 'Juan Pérez'}),
    ('¿Cuánto fue la cotización 15?', 'cotizacion_detalle', {'texto': '15'}),
    ('¿Cuántas cuentas de cobro hice este mes?', 'cuentas_cobro_periodo', {'periodo': 'mes'}),
    ('¿Cuánto facturé en cuentas de cobro este año?', 'cuentas_cobro_periodo', {'periodo': 'anio'}),
    ('¿Cuánto he facturado en honorarios este año?', 'cuentas_cobro_periodo', {'periodo': 'anio'}),
    ('Muéstrame la cuenta de cobro de María López', 'cuenta_cobro_detalle', {'texto': 'María López'}),
    ('¿Ya pagaron la cuenta de cobro CC-0007?', 'cuenta_cobro_detalle', {'texto': 'CC-0007'}),
    ('¿Cuánto me deben?', 'cartera_pendiente', None),
    ('¿Quiénes no me han pagado?', 'cartera_pendiente', None),
    ('¿Qué clientes están morosos?', 'cartera_pendiente', None),
    ('¿Qué facturas están vencidas?', 'cartera_pendiente', None),
    ('¿Cuánto tengo en cuentas por cobrar?', 'cartera_pendiente', None),
    ('¿Cuánto cobré este mes?', 'cobros_recibidos', {'periodo': 'mes'}),
    ('¿Cuánto me pagaron esta semana?', 'cobros_recibidos', {'periodo': 'semana'}),
    ('¿Qué pagos recibí este mes?', 'cobros_recibidos', {'periodo': 'mes'}),
]


@pytest.mark.parametrize('pregunta, esperada, params', BANCO)
def test_cada_forma_de_preguntar_va_a_su_consulta(pregunta, esperada, params):
    """La ruta rápida del panel (sin modelo) entiende la pregunta."""
    import services.ia_datos as d
    from services.ia.enrutador import enrutar_panel_seguro
    elegidas = enrutar_panel_seguro(pregunta, list(d.REGISTRO.values()))
    assert elegidas and elegidas[0][0] == esperada, f'«{pregunta}» → {elegidas}'
    if params:
        for k, v in params.items():
            assert elegidas[0][1].get(k) == v


def test_dos_intenciones_distintas_son_dos_consultas():
    """Cada parte se entiende sola → una consulta por parte (nunca una sola)."""
    import services.ia_datos as d
    from services.ia.enrutador import enrutar_panel_seguro
    caps = [h for h in d.REGISTRO.values() if 'panel' in h.canales]
    assert enrutar_panel_seguro('¿Cuánto me deben y cuánto cobré este mes?', caps) == [
        ('cartera_pendiente', {}), ('cobros_recibidos', {'periodo': 'mes'})]
    assert enrutar_panel_seguro('¿Cuántas cotizaciones hice y cuánto vendí hoy?', caps) == [
        ('cotizaciones_estado', {'periodo': 'hoy'}), ('ventas_periodo', {'periodo': 'hoy'})]


# ── Datos ───────────────────────────────────────────────────────
@pytest.fixture()
def documentos(cursor):
    ids = {}
    with cursor() as cur:
        cur.execute("""INSERT INTO cotizaciones (cliente_nombre, total, fecha, estado, estado_pago, fecha_pago)
                       VALUES (%s, 9100000, NOW() - INTERVAL '3 days', 'aprobada', 'pagada', CURRENT_DATE)
                       RETURNING id""", (MARCA + ' Juan',))
        ids['cot_pagada'] = cur.fetchone()['id']
        cur.execute("""INSERT INTO cotizaciones (cliente_nombre, total, fecha, estado)
                       VALUES (%s, 450000, NOW() - INTERVAL '20 days', 'pendiente') RETURNING id""",
                    (MARCA + ' Juan',))
        ids['cot_pend'] = cur.fetchone()['id']
        cur.execute("""INSERT INTO detalle_cotizacion (cotizacion_id, descripcion, cantidad, precio_unitario, subtotal)
                       VALUES (%s, 'Mantenimiento de portátil', 2, 225000, 450000)""", (ids['cot_pend'],))
        cur.execute("""INSERT INTO cuentas_cobro (consecutivo, fecha, cliente_nombre, cliente_nit, contractor_nombre,
                                                   contractor_id, total, estado_pago, fecha_vencimiento)
                       VALUES (%s, NOW() - INTERVAL '40 days', %s, '900123', 'Técnico', '1001', 800000,
                               'pendiente', CURRENT_DATE - 10) RETURNING id""",
                    ('CC-9' + uuid.uuid4().hex[:3].translate(str.maketrans('abcdef', '123456')), MARCA + ' María'))
        ids['cc'] = cur.fetchone()['id']
        cur.execute("""INSERT INTO detalle_cuenta_cobro (cuenta_id, fecha_labor, descripcion, valor)
                       VALUES (%s, CURRENT_DATE - 41, 'Soporte técnico en sitio', 800000)""", (ids['cc'],))
        cur.execute('SELECT consecutivo FROM cuentas_cobro WHERE id = %s', (ids['cc'],))
        ids['cc_num'] = cur.fetchone()['consecutivo']
    yield ids
    with cursor() as cur:
        cur.execute('DELETE FROM detalle_cotizacion WHERE cotizacion_id = ANY(%s)', ([ids['cot_pagada'], ids['cot_pend']],))
        cur.execute('DELETE FROM cotizaciones WHERE cliente_nombre LIKE %s', (MARCA + '%',))
        cur.execute('DELETE FROM detalle_cuenta_cobro WHERE cuenta_id = %s', (ids['cc'],))
        cur.execute('DELETE FROM cuentas_cobro WHERE cliente_nombre LIKE %s', (MARCA + '%',))


def _ej(code, params=None, rol=2):
    import services.ia_datos as d
    return d.ejecutar(code, params or {}, Contexto(rol_id=rol, usuario_id=1))


def test_una_cotizacion_por_numero_y_por_cliente(flask_app, documentos):
    with flask_app.test_request_context('/'):
        r = _ej('cotizacion_detalle', {'texto': f"COT {documentos['cot_pend']:010d}"})
        c = r['cotizaciones'][0]
        assert c['estado'].startswith('Pendiente') and c['dias_sin_respuesta'] >= 19
        assert c['items'][0]['que'] == 'Mantenimiento de portátil'
        assert _ej('cotizacion_detalle', {'texto': str(documentos['cot_pend'])})['cotizaciones'][0]['numero'] == c['numero']
        por_cliente = _ej('cotizacion_detalle', {'texto': MARCA})
        assert por_cliente['cotizaciones_encontradas'] == 2
        pagada = next(x for x in por_cliente['cotizaciones'] if x['estado'] == 'Aprobada')
        assert pagada['cobro'] == 'Pagada' and '9.100.000' in pagada['total']
        assert 'No encontré' in _ej('cotizacion_detalle', {'texto': 'nadie-' + MARCA})['conclusion']


def test_una_cuenta_de_cobro(flask_app, documentos):
    with flask_app.test_request_context('/'):
        r = _ej('cuenta_cobro_detalle', {'texto': documentos['cc_num']})
        cc = r['cuentas_de_cobro'][0]
        assert cc['numero'] == documentos['cc_num'] and cc['cobro'] == 'Pendiente de pago'
        assert cc['dias_de_mora'] == 10 and cc['labores'][0]['que'] == 'Soporte técnico en sitio'
        assert _ej('cuenta_cobro_detalle', {'texto': MARCA})['cuentas_encontradas'] == 1


def test_cobros_recibidos_y_resumen_de_cotizaciones(flask_app, documentos):
    with flask_app.test_request_context('/'):
        r = _ej('cobros_recibidos', {'periodo': 'mes'})
        assert r['pagos_recibidos'] >= 1
        assert any(p['cliente'] == MARCA + ' Juan' for p in r['ultimos_pagos'])
        res = _ej('cotizaciones_estado', {'periodo': 'todo'})
        assert '9.100.000' in res['las_mas_grandes'][0]['monto']
        assert any(c['cliente'] == MARCA + ' Juan' for c in res['a_quien_se_cotiza_mas'])
        cartera = _ej('cartera_pendiente')
        assert any(v['cliente'] == MARCA + ' María' for v in cartera['lo_mas_vencido'])


def test_permisos_por_rol(flask_app, documentos):
    with flask_app.test_request_context('/'):
        # Empleado: cotizaciones sí, cuentas de cobro no (públicos distintos)
        assert 'cotizaciones' in _ej('cotizacion_detalle', {'texto': MARCA}, rol=4)
        assert _ej('cuenta_cobro_detalle', {'texto': MARCA}, rol=4).get('denegado')
        assert _ej('cobros_recibidos', rol=4).get('denegado')
        # Contador: cuentas de cobro y cobros sí, cotizaciones no
        assert _ej('cotizacion_detalle', {'texto': MARCA}, rol=5).get('denegado')
        assert 'cuentas_de_cobro' in _ej('cuenta_cobro_detalle', {'texto': MARCA}, rol=5)
