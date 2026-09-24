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
