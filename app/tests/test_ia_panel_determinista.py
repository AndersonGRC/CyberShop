# -*- coding: utf-8 -*-
"""La consulta inequívoca del panel funciona aun sin Ollama ni Anthropic."""

import pytest

from services.ia.enrutador import enrutar_panel_seguro
from services.ia_datos.base import Herramienta, _suma


VENTAS = Herramienta('ventas_periodo', lambda **_: {}, 'Ventas.', ('periodo',),
                     disparadores=('cuanto vendi',))
STOCK = Herramienta('productos_bajo_stock', lambda **_: {}, 'Stock.',
                    disparadores=('agotado',))


def test_error_sql_no_se_disfraza_de_ventas_cero():
    class CursorRoto:
        def execute(self, _sql):
            raise RuntimeError('falló SQL')

    with pytest.raises(RuntimeError, match='falló SQL'):
        _suma(CursorRoto(), 'SELECT 1')


def test_ruta_rapida_solo_acepta_preguntas_inequivocas():
    assert enrutar_panel_seguro('¿Cuánto vendí hoy?', [VENTAS]) == [
        ('ventas_periodo', {'periodo': 'hoy'})]
    assert enrutar_panel_seguro('¿Cuánto vendí?', [VENTAS]) == [
        ('ventas_periodo', {'periodo': 'todo'})]
    assert enrutar_panel_seguro('¿Cuánto vendí hoy?', [VENTAS], historial=[{'pregunta': 'x'}]) == [
        ('ventas_periodo', {'periodo': 'hoy'})]
    for pregunta in ('¿Cuánto vendí hoy y ayer?', '¿Cuánto vendí en agosto?',
                     '¿Cuánto vendí en 2025?', '¿Cuánto vendí en efectivo?',
                     '¿Cuánto vendí hoy y qué está agotado?'):
        assert enrutar_panel_seguro(pregunta, [VENTAS, STOCK]) == []
    assert enrutar_panel_seguro('¿Y el mes pasado?', [VENTAS],
                               historial=[{'pregunta': '¿Cuánto vendí este mes?'}]) == []


def test_panel_responde_con_datos_autorizados_sin_modelo(flask_app, monkeypatch):
    import services.ai_service as ai
    import services.ai_tools as tools
    from services import ia_motores

    consultas = []
    registros = []
    monkeypatch.setattr(tools, 'permitidas', lambda _ctx: [VENTAS])
    monkeypatch.setattr(tools, 'ejecutar',
                        lambda code, params, _ctx: consultas.append((code, params)) or
                        {'periodo': 'hoy', 'total': '$ 10', 'cantidad': 2})
    monkeypatch.setattr(ai, '_contexto_tenant', lambda: 'Tienda de prueba')
    monkeypatch.setattr(ai, '_contexto_panel', lambda: 'Tienda de prueba')
    monkeypatch.setattr(ai, '_modelo_en_memoria',
                        lambda *_: (_ for _ in ()).throw(AssertionError('no debe esperar Ollama')))
    monkeypatch.setattr(ai, '_chat',
                        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('no debe llamar modelo')))
    monkeypatch.setattr(ai, '_registrar_consulta', lambda *args: registros.append(args))
    monkeypatch.setattr(ia_motores, 'motor_para', lambda *_a, **_k: (None, 'sin motor'))

    with flask_app.app_context():
        res, err = ai.responder_chat('¿Cuánto vendí hoy?', contexto=tools.Contexto(rol_id=1))
        assert err is None
        assert '"total": "$ 10"' in res['respuesta']
        assert consultas == [('ventas_periodo', {'periodo': 'hoy'})]
        assert registros[-1][2]['via'] == 'keyword'
        assert registros[-1][2]['motor'] == 'SQL'

        eventos = list(ai.responder_chat_stream('¿Cuánto vendí hoy?',
                                                contexto=tools.Contexto(rol_id=1)))
        assert eventos[-1][0] == 'fin'
        assert '"total": "$ 10"' in eventos[-1][1]
        assert registros[-1][3] is None


def test_el_panel_es_asesor_de_gestion_no_vendedor(flask_app, monkeypatch):
    """El dueño ya conoce su negocio: el chat del panel no le vende ni le da los
    datos de contacto de su empresa; lo asesora en control administrativo. Los
    textos de venta (descripciones, SEO) siguen con el contexto comercial."""
    import services.ai_service as ai
    monkeypatch.setattr('services.public_site_service.get_brand_config',
                        lambda: {'empresa_nombre': 'Tienda X'})
    with flask_app.app_context():
        panel, comercial = ai._contexto_panel(), ai._contexto_tenant()
    assert 'asesor de gestión de «Tienda X»' in panel
    assert 'persuasivo' not in panel and 'no les vendas' in panel
    assert 'recomendaciones concretas de gestión' in panel
    assert 'persuasivo' in comercial


def test_el_chat_del_panel_redacta_con_el_asesor(flask_app, monkeypatch):
    import services.ai_service as ai
    import services.ai_tools as tools
    monkeypatch.setattr(ai, '_contexto_panel', lambda: 'ASESOR')
    monkeypatch.setattr(ai, '_contexto_tenant', lambda: 'VENDEDOR')
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda m: True)
    monkeypatch.setattr(ai, '_chat', lambda *a, **k: ('{"tools":[{"tool":"conteo_general","params":{}}]}', None))
    monkeypatch.setattr(tools, 'ejecutar', lambda code, params, ctx: {'productos': 9})
    from services.ia_datos.acceso import Contexto
    with flask_app.app_context():
        plan, err = ai._plan_chat('¿Cuántos productos tengo?', contexto=Contexto(rol_id=1, canal='web'))
    assert err is None
    assert plan['system'].startswith('ASESOR') and 'VENDEDOR' not in plan['system']
