# -*- coding: utf-8 -*-
"""Motor del chat IA: períodos, permisos por rol y enrutador multi-herramienta.

Sin BD ni servidor de IA: lo externo se reemplaza con dobles, así que corre en
cualquier máquina (no escribe datos)."""

import json
from datetime import date, datetime

import pytest

import services.ai_service as ai
import services.ia_datos as ia_datos
from services.ia_datos import acceso, base
from services.ia_datos.base import Herramienta, Rango


# ── Períodos ───────────────────────────────────────────────────
def test_periodos_historicos_conservan_su_sql():
    assert base._sql_periodo('hoy', 'fecha') == "DATE(fecha) = CURRENT_DATE"
    assert base._sql_periodo('semana', 'f') == "f >= date_trunc('week', CURRENT_DATE)"
    assert base._sql_periodo('mes', 'f') == "f >= date_trunc('month', CURRENT_DATE)"
    assert base._sql_periodo('todo', 'f') == "TRUE"
    assert base._sql_periodo('inventado', 'f') == base._sql_periodo('mes', 'f')


def test_rango_de_fechas_validado_y_acotado():
    hoy = date(2026, 9, 15)
    assert base.rango_desde_params({'desde': '2026-08-01', 'hasta': '2026-08-31'}, hoy) == \
        Rango(date(2026, 8, 1), date(2026, 8, 31))
    # nunca pasa de hoy, invierte fechas al revés y acota a 3 años
    assert base.rango_desde_params({'desde': '2026-09-01', 'hasta': '2027-01-01'}, hoy).hasta == hoy
    assert base.rango_desde_params({'desde': '2026-08-31', 'hasta': '2026-08-01'}, hoy) == \
        Rango(date(2026, 8, 1), date(2026, 8, 31))
    largo = base.rango_desde_params({'desde': '2010-01-01', 'hasta': '2026-09-15'}, hoy)
    assert (largo.hasta - largo.desde).days == base._RANGO_MAX_DIAS
    assert base.rango_desde_params({'desde': "2026-08-01'; DROP TABLE x;--"}, hoy) is not None
    assert base.rango_desde_params({'desde': 'agosto'}, hoy) is None
    assert base.rango_desde_params({}, hoy) is None


def test_sql_de_rango_solo_lleva_fechas():
    r = base.rango_desde_params({'desde': "2026-08-01'; DROP TABLE x;--", 'hasta': '2026-08-31'},
                                date(2026, 9, 15))
    sql = base._sql_periodo(r, 'v.fecha')
    assert sql == "v.fecha >= DATE '2026-08-01' AND v.fecha < DATE '2026-08-31' + 1"
    assert base._label_periodo(r) == 'del 01/08/2026 al 31/08/2026'


def test_sanear_params_alias_rango_y_numeros():
    h = Herramienta('x', lambda **_: {}, 'd', ('periodo', 'limite', 'empleado'))
    assert ia_datos.sanear_params(h, {'periodo': 'mes pasado'}) == {'periodo': 'mes_anterior', 'limite': 5}
    assert ia_datos.sanear_params(h, {'periodo': 'año'})['periodo'] == 'anio'
    assert isinstance(ia_datos.sanear_params(h, {'desde': '2026-08-01', 'hasta': '2026-08-31'})['periodo'], Rango)
    assert ia_datos.sanear_params(h, {'limite': 'muchos'})['limite'] == 5
    seguro = ia_datos.sanear_params(h, {'empleado': 'x' * 500, 'umbral': 3, 'sql': 'DROP'})
    assert len(seguro['empleado']) == 80 and 'umbral' not in seguro and 'sql' not in seguro
    assert ia_datos.sanear_params(h, 'no es dict') == {'limite': 5}


@pytest.mark.parametrize('periodo,desde,hasta', [
    ('hoy', date(2026, 9, 15), date(2026, 9, 15)),
    ('ayer', date(2026, 9, 14), date(2026, 9, 14)),
    ('semana', date(2026, 9, 14), date(2026, 9, 15)),          # lunes a hoy
    ('semana_anterior', date(2026, 9, 7), date(2026, 9, 13)),
    ('mes', date(2026, 9, 1), date(2026, 9, 15)),
    ('mes_anterior', date(2026, 8, 1), date(2026, 8, 31)),
    ('anio', date(2026, 1, 1), date(2026, 9, 15)),
])
def test_fechas_reales_de_cada_periodo(periodo, desde, hasta):
    assert base.rango_efectivo(date(2026, 9, 15), periodo) == (desde, hasta)
    assert base.rango_efectivo(date(2026, 9, 15), 'todo') == (None, date(2026, 9, 15))


def test_periodo_anterior_comparable():
    hoy = date(2026, 9, 15)
    # "este mes" va del 1 a hoy: se compara con el MISMO tramo del mes pasado, no con 15 días sueltos
    assert base.rango_anterior(*base.rango_efectivo(hoy, 'mes'), 'mes') == (date(2026, 8, 1), date(2026, 8, 15))
    assert base.rango_anterior(*base.rango_efectivo(hoy, 'anio'), 'anio') == (date(2025, 1, 1), date(2025, 9, 15))
    assert base.rango_anterior(*base.rango_efectivo(hoy, 'semana'), 'semana') == (date(2026, 9, 12), date(2026, 9, 13))
    assert base.rango_anterior(date(2026, 8, 1), date(2026, 8, 31)) == (date(2026, 7, 1), date(2026, 7, 31))
    assert base.rango_anterior(None, hoy, 'todo') == (None, None)


def test_cambio_porcentual():
    assert base.cambio_pct(120, 100) == '+20%'
    assert base.cambio_pct(80, 100) == '-20%'
    assert base.cambio_pct(0, 0) is None
    assert base.cambio_pct(50, 0) == 'sin base de comparación (antes no hubo)'
    assert base.cambio_pct(-50, -100) == '+50%'      # menos pérdida es mejora
    assert base.cambio_pct('x', 1) is None


def test_valor_anormal_solo_con_datos_suficientes():
    from services import estadistica as est
    estables = [100, 102, 98, 101, 99, 100, 103]
    assert est.z_score(100, estables[:5]) is None                 # pocos días
    assert est.z_score(100, [100] * 8) is None                    # sin variación
    assert abs(est.z_score(101, estables)) < 2                    # día normal
    assert est.z_score(40, estables) < -2                         # caída anormal
    assert est.z_score(160, estables) > 2                         # pico anormal
    assert est.desviacion_estandar([5]) is None


# ── Permisos por rol y canal ───────────────────────────────────
@pytest.fixture
def matriz(monkeypatch):
    """Empleado(4) ve CRM; Contador(5) ve contabilidad y nómina; el rol 9 es
    personalizado sobre Empleado con nómina ampliada por el dueño; 'caja' está
    apagado en el plan."""
    import services.permisos_service as ps
    import tenant_features
    permisos = {(4, 'crm'), (5, 'accounting'), (5, 'payroll'), (9, 'payroll')}
    monkeypatch.setattr(ps, 'tiene_permiso',
                        lambda rol, mod, accion='ver', cur=None: rol in (1, 2) or (rol, mod) in permisos)
    monkeypatch.setattr(ps, 'rol_base_efectivo', lambda rol, roles=None: {9: 4}.get(rol, rol))
    monkeypatch.setattr(tenant_features, 'is_module_active', lambda m, tenant_id=None: m != 'caja')


def _h(**kw):
    return Herramienta('h', lambda **_: {}, 'd', **kw)


def _ctx(rol=None, canal='web'):
    return acceso.Contexto(rol_id=rol, canal=canal)


def test_escritorio_solo_recibe_herramientas_publicas(matriz):
    assert acceso.puede_usar(_h(), _ctx(canal='escritorio'))
    assert not acceso.puede_usar(_h(permiso='crm'), _ctx(canal='escritorio'))
    assert not acceso.puede_usar(_h(sensible='nomina'), _ctx(canal='escritorio'))


def test_sistema_recibe_todo_menos_lo_sensible(matriz):
    assert acceso.puede_usar(_h(permiso='accounting'), _ctx(canal='sistema'))
    assert not acceso.puede_usar(_h(permiso='payroll', sensible='nomina'), _ctx(canal='sistema'))


@pytest.mark.parametrize('rol,herramienta,esperado', [
    (4, dict(), True),
    (4, dict(permiso='crm'), True),
    (4, dict(permiso='accounting'), False),
    (4, dict(permiso='payroll', sensible='nomina'), False),
    (5, dict(permiso='accounting'), True),
    (5, dict(permiso='payroll', sensible='nomina'), True),
    (9, dict(permiso='payroll', sensible='nomina'), False),   # base Empleado: nunca nómina
    (2, dict(permiso='payroll', sensible='nomina'), True),
    (1, dict(modulos=('caja',)), False),                      # módulo apagado: nadie
    (None, dict(permiso='crm'), False),
    (5, dict(sensible='otra_cosa'), False),                   # sensibilidad desconocida: se niega
])
def test_matriz_de_acceso_web(matriz, rol, herramienta, esperado):
    assert acceso.puede_usar(_h(**herramienta), _ctx(rol)) is esperado


def test_ejecutar_niega_sin_llamar_a_la_consulta(matriz, monkeypatch):
    llamadas = []
    monkeypatch.setitem(base.REGISTRO, 'finanzas_prueba',
                        Herramienta('finanzas_prueba', lambda **kw: llamadas.append(kw) or {}, 'd',
                                    permiso='accounting', etiqueta='tus finanzas'))
    res = ia_datos.ejecutar('finanzas_prueba', {}, _ctx(4))
    assert res['denegado'] is True and 'tus finanzas' in res['motivo'] and llamadas == []
    assert ia_datos.ejecutar('no_existe', {}, _ctx(4)) is None


# ── Enrutador y memoria ────────────────────────────────────────
def test_parsear_herramientas_formatos():
    p = ai._parsear_herramientas
    assert p('{"tools":[{"tool":"a","params":{"periodo":"mes"}},{"tool":"b"}]}') == \
        [('a', {'periodo': 'mes'}), ('b', {})]
    assert p('Claro: {"tool":"a","params":{"limite":3}}') == [('a', {'limite': 3})]
    assert p('{"tool":"ninguna"}') == [] and p('{"tools":[]}') == [] and p('sin json') == []
    assert p('{"tools":["a","a",{"tool":"a","params":{"periodo":"mes_anterior"}}]}') == \
        [('a', {}), ('a', {'periodo': 'mes_anterior'})]
    assert len(p(json.dumps({'tools': [{'tool': f't{i}'} for i in range(6)]}))) == ai._MAX_HERRAMIENTAS


def test_nombre_casi_correcto_se_corrige_sin_saltarse_permisos():
    permitidos = ['restaurante_ahora', 'ventas_periodo', 'caja_estado']
    assert ai._resolver_codigo('restaurant_ahora', permitidos) == 'restaurante_ahora'
    assert ai._resolver_codigo('Ventas_Periodo', permitidos) == 'ventas_periodo'
    assert ai._resolver_codigo('ventasperiodo', permitidos) == 'ventas_periodo'
    # No se parece a nada permitido, o es de otra herramienta: no se inventa una
    assert ai._resolver_codigo('finanzas_periodo', permitidos) is None
    assert ai._resolver_codigo('el clima', permitidos) is None
    assert ai._resolver_codigo('', permitidos) is None


def test_catalogo_anuncia_los_parametros_con_nombre():
    """Sin esto el modelo elegía la herramienta pero la llamaba sin el nombre."""
    h = Herramienta('cliente_historial', lambda **_: {}, 'Historial de un cliente.', ('cliente',))
    texto = ia_datos.catalogo_para_prompt([h, Herramienta('ventas_periodo', lambda **_: {}, 'Ventas.', ('periodo',))])
    assert '- cliente_historial: Historial de un cliente. (requiere el parámetro «cliente» con el nombre)' in texto
    assert texto.rstrip().endswith('- ventas_periodo: Ventas.')      # periodo no se anuncia aparte


def test_json_roto_del_modelo_no_pierde_la_consulta():
    """El modelo a veces cierra mal el JSON; antes se perdían todas las
    herramientas y la pregunta quedaba sin datos."""
    roto = ('{"tools":[{"tool":"ventas_periodo","params":{"periodo":"mes"}},'
            '"finanzas_periodo":{"params":{"periodo":"mes"}}]}')
    assert ai._parsear_herramientas(roto) == [('ventas_periodo', {'periodo': 'mes'}),
                                              ('finanzas_periodo', {'periodo': 'mes'})]
    assert ai._parsear_herramientas('{"tools":[{"tool":"top_productos","params":{"limite":3}}') == \
        [('top_productos', {'limite': 3})]
    assert ai._parsear_herramientas('lo siento, no entiendo') == []


def test_historial_se_recorta_y_valida():
    largo = [{'pregunta': f'p{i}', 'respuesta': 'r' * 900} for i in range(9)] + ['basura', {'respuesta': 'x'}]
    limpio = ai._sanear_historial(largo)
    assert [t['pregunta'] for t in limpio] == ['p7', 'p8']
    assert all(len(t['respuesta']) == 300 for t in limpio)
    assert ai._sanear_historial('no es lista') == []


@pytest.fixture
def motor(flask_app, matriz, monkeypatch):
    """Chat con enrutador y redactor simulados y tres herramientas de prueba."""
    llamadas = {'chat': [], 'consultas': []}

    def ventas(periodo='todo', **_):
        llamadas['consultas'].append(periodo)
        return {'periodo': base._label_periodo(periodo), 'total': '$ 10'}

    def falla(**_):
        raise RuntimeError('BD caída')

    for h in (Herramienta('ventas_prueba', ventas, 'Ventas.', ('periodo',), etiqueta='tus ventas'),
              Herramienta('finanzas_prueba', lambda **_: {'utilidad': 1}, 'Finanzas.',
                          permiso='accounting', etiqueta='tus finanzas'),
              Herramienta('nomina_prueba', lambda **_: {'neto': 1}, 'Nómina.', ('empleado',),
                          permiso='payroll', sensible='nomina', etiqueta='la nómina'),
              Herramienta('falla_prueba', falla, 'Falla.', etiqueta='algo que falla')):
        monkeypatch.setitem(base.REGISTRO, h.code, h)
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda m: True)
    monkeypatch.setattr(ai, '_contexto_tenant', lambda: 'CTX')
    monkeypatch.setattr(ai, '_fecha_hoy', lambda: (date(2026, 9, 15), datetime(2026, 9, 15, 10, 30)))
    respuestas = []

    def chat(system, user, **kw):
        llamadas['chat'].append((system, user))
        return respuestas.pop(0), None
    monkeypatch.setattr(ai, '_chat', chat)
    with flask_app.app_context():
        yield llamadas, respuestas


def _plan(pregunta, **kw):
    eventos = list(ai._plan_chat_pasos(pregunta, **kw))
    return eventos, dict(eventos).get('plan')


def test_varias_herramientas_y_comparacion_de_periodos(motor):
    llamadas, respuestas = motor
    respuestas.append(json.dumps({'tools': [
        {'tool': 'ventas_prueba', 'params': {'periodo': 'mes'}},
        {'tool': 'ventas_prueba', 'params': {'periodo': 'mes_anterior'}},
        {'tool': 'finanzas_prueba'}]}))
    eventos, plan = _plan('¿vendí más que el mes pasado y cuánto gané?', contexto=_ctx(4))
    estados = [d for e, d in eventos if e == 'estado']
    assert estados.count('Consultando tus ventas…') == 2 and 'Consultando tus finanzas…' in estados
    assert llamadas['consultas'] == ['mes', 'mes_anterior']
    assert set(plan['datos']) == {'ventas_prueba', 'ventas_prueba_2', 'finanzas_prueba'}
    assert plan['datos']['finanzas_prueba']['denegado'] is True     # el Empleado no la ve
    assert plan['herramienta'] == 'ventas_prueba,finanzas_prueba' and plan['max_tokens'] == 550
    enrutador = llamadas['chat'][0][0]
    assert '- ventas_prueba:' in enrutador and 'finanzas_prueba' not in enrutador   # ni la ve en su lista
    assert 'Hoy es martes 2026-09-15' in enrutador
    assert 'consultados el 2026-09-15 10:30' in plan['user']


def test_una_herramienta_conserva_la_forma_de_siempre(motor):
    _, respuestas = motor
    respuestas.append('{"tool":"ventas_prueba","params":{"periodo":"hoy"}}')
    _, plan = _plan('¿cuánto vendí hoy?', contexto=_ctx(4))
    assert plan['datos'] == {'periodo': 'hoy', 'total': '$ 10'}
    assert plan['herramienta'] == 'ventas_prueba' and plan['max_tokens'] == 350


def test_si_todas_fallan_termina_en_error_y_si_una_falla_sigue(motor):
    _, respuestas = motor
    respuestas.append('{"tools":[{"tool":"falla_prueba"}]}')
    eventos, plan = _plan('x', contexto=_ctx(4))
    assert eventos[-1] == ('error', 'No pude consultar esos datos en este momento.') and plan is None
    respuestas.append('{"tools":[{"tool":"falla_prueba"},{"tool":"ventas_prueba"}]}')
    _, plan = _plan('x', contexto=_ctx(4))
    assert 'error' in plan['datos']['falla_prueba'] and plan['datos']['ventas_prueba']['total'] == '$ 10'


def test_sin_herramienta_ofrece_solo_lo_que_el_rol_puede(motor):
    _, respuestas = motor
    respuestas.append('{"tools":[]}')
    _, plan = _plan('¿cuál es la clave del admin?', contexto=_ctx(4))
    assert plan['herramientas'] == [] and plan['datos'] is None
    assert 'tus ventas' in plan['user'] and 'tus finanzas' not in plan['user'] and 'la nómina' not in plan['user']


def test_seguimiento_usa_la_conversacion(motor):
    llamadas, respuestas = motor
    respuestas.append('{"tools":[{"tool":"ventas_prueba","params":{"periodo":"mes_anterior"}}]}')
    historial = [{'pregunta': '¿cuánto vendí este mes?', 'respuesta': 'Vendiste $ 10.', 'herramienta': 'ventas_prueba'}]
    _, plan = _plan('¿y el mes pasado?', historial=historial, contexto=_ctx(4))
    user_enrutador = llamadas['chat'][0][1]
    assert 'CONVERSACIÓN RECIENTE' in user_enrutador and 'Pregunta actual: «¿y el mes pasado?»' in user_enrutador
    assert '¿cuánto vendí este mes?' in plan['user']


def test_consulta_sensible_marca_auditoria(motor):
    _, respuestas = motor
    respuestas.append('{"tools":[{"tool":"nomina_prueba","params":{"empleado":"Ana Pérez"}}]}')
    _, plan = _plan('¿cuánto se le pagó a Ana?', contexto=_ctx(5))
    assert plan['sensible'] == 'nomina' and plan['objetivo'] == 'Ana Pérez'
    respuestas.append('{"tools":[{"tool":"nomina_prueba","params":{"empleado":"Ana Pérez"}}]}')
    _, plan = _plan('¿cuánto se le pagó a Ana?', contexto=_ctx(4))      # negada: no se marca
    assert plan['datos']['denegado'] is True and plan['sensible'] is None


def test_responder_chat_registra_la_consulta(motor, monkeypatch):
    _, respuestas = motor
    registros = []
    monkeypatch.setattr(ai, '_registrar_consulta', lambda *a: registros.append(a))
    respuestas.extend(['{"tools":[{"tool":"ventas_prueba"}]}', 'Vendiste $ 10.'])
    res, err = ai.responder_chat('¿cuánto vendí?', contexto=_ctx(4))
    assert err is None and res['respuesta'] == 'Vendiste $ 10.' and res['herramientas'] == ['ventas_prueba']
    ctx, pregunta, plan, error, _inicio = registros[-1]
    assert ctx.rol_id == 4 and pregunta == '¿cuánto vendí?' and plan['herramientas'] == ['ventas_prueba'] and error is None


def test_stream_registra_aunque_el_navegador_corte(motor, monkeypatch):
    _, respuestas = motor
    registros = []
    monkeypatch.setattr(ai, '_registrar_consulta', lambda *a: registros.append(a))
    monkeypatch.setattr(ai, '_chat_stream_una_vez', lambda *a, **k: iter(['Vendiste ', '$ 10.']))
    respuestas.append('{"tools":[{"tool":"ventas_prueba"}]}')
    gen = ai.responder_chat_stream('¿cuánto vendí?', contexto=_ctx(4))
    assert next(gen)[0] == 'estado'
    gen.close()
    assert registros and 'interrumpió' in registros[-1][3]

    respuestas.append('{"tools":[{"tool":"ventas_prueba"}]}')
    eventos = list(ai.responder_chat_stream('¿cuánto vendí?', contexto=_ctx(4)))
    assert eventos[-1] == ('fin', 'Vendiste $ 10.') and registros[-1][3] is None
    meta = dict(eventos)['meta']
    assert meta['herramientas'] == ['ventas_prueba']
