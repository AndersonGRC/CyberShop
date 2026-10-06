# -*- coding: utf-8 -*-
"""Entrenamiento del asistente del panel: el banco de preguntas reales
(tests/banco_preguntas_panel.py) debe llegar a su consulta SIN modelo, y lo que
mezcla temas debe seguir yendo al modelo. Más las piezas que lo hacen posible:
tolerancia a errores de escritura, abreviaturas, períodos como palabras
completas, canal del panel y ejemplos guía para el modelo.

Para medir a mano: python tools/ia_banco.py"""
import pytest

from tests.banco_preguntas_panel import AL_MODELO, BANCO


def _panel():
    import services.ia_datos as d
    return [h for h in d.REGISTRO.values() if 'panel' in h.canales]


@pytest.mark.parametrize('pregunta, esperada', BANCO)
def test_banco_llega_a_su_consulta_sin_modelo(pregunta, esperada):
    from services.ia.enrutador import enrutar_panel_seguro
    r = enrutar_panel_seguro(pregunta, _panel())
    assert r and r[0][0] == esperada, f'«{pregunta}» → {r}'


@pytest.mark.parametrize('pregunta', AL_MODELO)
def test_lo_ambiguo_va_al_modelo(pregunta):
    from services.ia.enrutador import enrutar_panel_seguro
    assert enrutar_panel_seguro(pregunta, _panel()) == []


def test_errores_de_escritura_y_abreviaturas():
    from services.ia.enrutador import expandir, fonetico, normalizar
    assert fonetico(normalizar('Cuanto bendi')) == fonetico(normalizar('cuánto vendí'))
    assert fonetico('cotisaciones') == fonetico('cotizaciones')
    assert len(fonetico('precio de cierre')) == len('precio de cierre')     # misma longitud
    assert expandir('q cotizaciones tengo x cobrar') == 'que cotizaciones tengo por cobrar'
    assert expandir('Taxi') == 'Taxi' and expandir('x64') == 'x64'           # solo palabras sueltas


def test_periodos_solo_como_palabra_completa():
    from services.ia.enrutador import periodo_de
    assert periodo_de('¿Qué dice el manual de garantías?') is None           # «anual» ≠ «manual»
    assert periodo_de('¿Qué día de la semana se vende más?') is None
    assert periodo_de('ventas de la semana') == 'semana'
    assert periodo_de('¿cuánto vendí hoy?') == 'hoy'


def test_patron_horario_no_toma_dia_de_la_semana_como_periodo():
    from services.ia.enrutador import enrutar_panel_seguro
    r = enrutar_panel_seguro('¿Qué día de la semana se vende más?', _panel())
    assert r == [('patron_horario', {'periodo': 'todo'})]


def test_en_efectivo_vale_para_medios_de_pago_pero_no_para_ventas():
    from services.ia.enrutador import enrutar_panel_seguro
    assert enrutar_panel_seguro('¿Cuánto entró en efectivo y cuánto por transferencia?', _panel())[0][0] == 'metodos_pago'
    assert enrutar_panel_seguro('¿Cuánto vendí en efectivo?', _panel()) == []


def test_el_panel_no_usa_lo_exclusivo_del_sitio_publico(flask_app, monkeypatch):
    import services.ia_datos as d
    from services.ia_datos.acceso import Contexto, puede_usar
    monkeypatch.setattr('services.ia_datos.acceso._modulo_activo', lambda code: True)
    with flask_app.test_request_context('/'):
        assert not puede_usar(d.REGISTRO['buscar_productos'], Contexto(rol_id=2))
        assert puede_usar(d.REGISTRO['ventas_periodo'], Contexto(rol_id=2))
        from services.ia_datos.acceso import CANAL_PUBLICO
        assert puede_usar(d.REGISTRO['buscar_productos'], Contexto(canal=CANAL_PUBLICO))


def test_el_modelo_recibe_glosario_y_ejemplos_solo_de_lo_permitido():
    import services.ia_datos as d
    from services.ia.clarificaciones import instrucciones_para_catalogo
    texto = instrucciones_para_catalogo([d.REGISTRO['ventas_periodo'], d.REGISTRO['cartera_pendiente']])
    assert '«plata»' in texto and '«me deben» = cartera' in texto
    assert '→ ventas_periodo' in texto and '→ cartera_pendiente' in texto
    assert 'nomina_empleado' not in texto and 'taller_casos' not in texto


# ── Chat del sitio público ──────────────────────────────────────
@pytest.mark.parametrize('pregunta, esperada', __import__('tests.banco_preguntas_panel', fromlist=['PUBLICO']).PUBLICO)
def test_chat_publico_llega_a_su_consulta(pregunta, esperada):
    import services.ia_datos as d
    from services.ia.enrutador import enrutar
    publicas = [h for h in d.REGISTRO.values() if 'publico' in h.canales]
    r = enrutar(pregunta, publicas)
    assert r and r[0][0] == esperada, f'«{pregunta}» → {r}'


# ── Seguimientos: «¿y el mes pasado?» ───────────────────────────
@pytest.mark.parametrize('anterior, pregunta, periodo',
                         __import__('tests.banco_preguntas_panel', fromlist=['SEGUIMIENTOS']).SEGUIMIENTOS)
def test_seguimiento_de_periodo(anterior, pregunta, periodo):
    from services.ia.enrutador import enrutar_panel_seguro
    historial = [{'pregunta': 'pregunta anterior', 'respuesta': '...', 'herramienta': anterior}]
    r = enrutar_panel_seguro(pregunta, _panel(), historial=historial)
    if periodo is None:
        assert r == [], f'«{pregunta}» tras {anterior} debía ir al modelo: {r}'
    else:
        assert r == [(anterior, {'periodo': periodo})], r


def test_seguimiento_sin_herramienta_previa_va_al_modelo():
    from services.ia.enrutador import enrutar_panel_seguro
    assert enrutar_panel_seguro('¿Y el mes pasado?', _panel(), historial=[{'pregunta': 'hola'}]) == []
    assert enrutar_panel_seguro('¿Y el mes pasado?', _panel(),
                                historial=[{'pregunta': 'x', 'herramienta': 'aclaracion:ventas'}]) == []
    # Una capacidad que el rol no tiene no se usa aunque el historial la nombre.
    sin_nomina = [h for h in _panel() if h.code != 'nomina_resumen']
    assert enrutar_panel_seguro('¿Y el mes pasado?', sin_nomina,
                                historial=[{'pregunta': 'x', 'herramienta': 'nomina_resumen'}]) == []


def test_chat_del_panel_resuelve_el_seguimiento_sin_modelo(flask_app, monkeypatch):
    import services.ai_service as ai
    import services.ai_tools as tools
    from services import ia_motores
    consultas = []
    monkeypatch.setattr(tools, 'ejecutar', lambda code, params, ctx: consultas.append((code, params)) or
                        {'periodo': 'el mes pasado', 'total': '$ 99'})
    monkeypatch.setattr(ai, '_contexto_tenant', lambda: 'Tienda')
    monkeypatch.setattr(ai, '_contexto_panel', lambda: 'Tienda')
    monkeypatch.setattr(ai, '_modelo_en_memoria',
                        lambda *_: (_ for _ in ()).throw(AssertionError('no debe esperar Ollama')))
    monkeypatch.setattr(ai, '_chat', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('no debe llamar modelo')))
    monkeypatch.setattr(ai, '_registrar_consulta', lambda *a: None)
    monkeypatch.setattr(ia_motores, 'motor_para', lambda *_a, **_k: (None, 'sin motor'))
    historial = [{'pregunta': '¿Cuánto vendí este mes?', 'respuesta': '$ 10', 'herramienta': 'ventas_periodo'}]
    with flask_app.test_request_context('/'):
        res, err = ai.responder_chat('¿Y el mes pasado?', historial=historial,
                                     contexto=tools.Contexto(rol_id=2, usuario_id=1))
    assert err is None and '$ 99' in res['respuesta']
    assert consultas == [('ventas_periodo', {'periodo': 'mes_anterior'})]


# ── Preguntas compuestas y seguimientos con nombre ──────────────
@pytest.mark.parametrize('pregunta, esperado',
                         __import__('tests.banco_preguntas_panel', fromlist=['COMPUESTAS']).COMPUESTAS)
def test_pregunta_compuesta(pregunta, esperado):
    from services.ia.enrutador import enrutar_panel_seguro
    assert enrutar_panel_seguro(pregunta, _panel()) == esperado


@pytest.mark.parametrize('anterior, pregunta, params',
                         __import__('tests.banco_preguntas_panel', fromlist=['SEGUIMIENTOS_NOMBRE']).SEGUIMIENTOS_NOMBRE)
def test_seguimiento_con_nombre(anterior, pregunta, params):
    from services.ia.enrutador import enrutar_panel_seguro
    r = enrutar_panel_seguro(pregunta, _panel(), historial=[{'pregunta': 'x', 'herramienta': anterior}])
    assert r == ([(anterior, params)] if params else []), r


def test_chat_ejecuta_las_dos_consultas_de_una_pregunta_compuesta(flask_app, monkeypatch):
    import services.ai_service as ai
    import services.ai_tools as tools
    from services import ia_motores
    consultas = []
    monkeypatch.setattr(tools, 'ejecutar', lambda code, params, ctx: consultas.append((code, params)) or
                        {'dato': code})
    monkeypatch.setattr(ai, '_contexto_tenant', lambda: 'Tienda')
    monkeypatch.setattr(ai, '_contexto_panel', lambda: 'Tienda')
    monkeypatch.setattr(ai, '_modelo_en_memoria',
                        lambda *_: (_ for _ in ()).throw(AssertionError('no debe esperar Ollama')))
    monkeypatch.setattr(ai, '_chat', lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('no debe llamar modelo')))
    monkeypatch.setattr(ai, '_registrar_consulta', lambda *a: None)
    monkeypatch.setattr(ia_motores, 'motor_para', lambda *_a, **_k: (None, 'sin motor'))
    with flask_app.test_request_context('/'):
        res, err = ai.responder_chat('¿Cuánto vendí hoy y qué está agotado?',
                                     contexto=tools.Contexto(rol_id=2, usuario_id=1))
    assert err is None
    assert consultas == [('ventas_periodo', {'periodo': 'hoy'}), ('productos_bajo_stock', {})]
    assert 'ventas_periodo' in res['respuesta'] and 'productos_bajo_stock' in res['respuesta']


def test_el_anio_pasado_es_un_rango_exacto_no_este_anio():
    from datetime import date
    from services.ia.enrutador import enrutar_panel_seguro
    a = date.today().year - 1
    rango = {'desde': f'{a}-01-01', 'hasta': f'{a}-12-31'}
    assert enrutar_panel_seguro('¿Cuánto vendí el año pasado?', _panel()) == [('ventas_periodo', rango)]
    assert enrutar_panel_seguro('¿Cuánto gané el año anterior?', _panel()) == [('finanzas_periodo', rango)]
    assert enrutar_panel_seguro('¿Cuánto vendí el año pasado y cuánto gasté?', _panel()) == [
        ('ventas_periodo', rango), ('finanzas_periodo', rango)]
    assert enrutar_panel_seguro('¿Cuánto vendí este año?', _panel()) == [('ventas_periodo', {'periodo': 'anio'})]
    # Otra fecha en la misma pregunta, o una consulta sin período: al modelo.
    assert enrutar_panel_seguro('¿Cuánto vendí el año pasado y este mes?', _panel()) == []
    assert enrutar_panel_seguro('¿Qué está agotado el año pasado?', _panel()) == []
