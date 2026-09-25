# -*- coding: utf-8 -*-
"""Preguntas de compatibilidad del chat público (módulo ai_public_compat).

Solo cuando el catálogo ya encontró un producto real Y la pregunta es de
compatibilidad, el modelo puede usar conocimiento general — y únicamente el
modelo del equipo del dueño (NIVEL_B), ya cargado en memoria. Nunca la nube,
nunca el puente de arranque en frío. Si el modelo no está listo, se responde
con el catálogo y se ofrece WhatsApp.
"""
from contextlib import contextmanager

import pytest

from services import ia_motores as mot
from services.ia_datos.base import Herramienta


def _catalogo(monkeypatch, con_producto=True):
    import services.ai_tools as tools
    herramienta = Herramienta('buscar_productos', lambda **_: {}, 'Catálogo.', ('texto',),
                              disparadores=('tienen', 'tienes', 'busco'))
    monkeypatch.setattr(tools, 'permitidas', lambda _ctx: [herramienta])
    if con_producto:
        datos = {'buscado': 'rtx', 'encontrados': 1,
                 'productos': [{'producto': 'Tarjeta RTX 4060', 'categoria': 'Componentes',
                                'disponible': True}]}
    else:
        datos = {'buscado': 'algo', 'conclusion': 'No encontré «algo» en el catálogo.'}
    monkeypatch.setattr(tools, 'ejecutar', lambda code, params, ctx: datos)


@pytest.fixture()
def base(flask_app, monkeypatch):
    from services.chat_publico import motor
    monkeypatch.setattr(motor, 'config_publica', lambda: {
        'saludo': 'Hola', 'negocio': 'Tienda', 'tono': 'breve', 'whatsapp': '573001112233'})
    monkeypatch.setattr(motor, '_compat_activo', lambda: True)
    motor._CACHE.clear()
    with flask_app.app_context():
        yield motor
    motor._CACHE.clear()


PREGUNTA_COMPAT = 'es compatible con mi pc de 2018? tienen rtx'


# ── Cuándo se marca como compatibilidad ────────────────────────
def test_producto_y_frase_de_compatibilidad_marca_el_plan(base, monkeypatch):
    _catalogo(monkeypatch)
    plan = base.preparar(PREGUNTA_COMPAT)
    assert plan['via'] == base.VIA_COMPATIBILIDAD
    assert plan['escalar'] is True
    assert 'Tarjeta RTX 4060' in plan['texto_base']
    assert 'WhatsApp' in plan['texto_base']


def test_sin_frase_de_compatibilidad_es_una_consulta_normal(base, monkeypatch):
    _catalogo(monkeypatch)
    plan = base.preparar('tienen rtx')
    assert plan['via'] == base.VIA_KEYWORD


def test_sin_producto_encontrado_no_se_marca(base, monkeypatch):
    _catalogo(monkeypatch, con_producto=False)
    plan = base.preparar(PREGUNTA_COMPAT)
    assert plan['via'] != base.VIA_COMPATIBILIDAD


def test_modulo_apagado_es_una_consulta_normal(base, monkeypatch):
    _catalogo(monkeypatch)
    monkeypatch.setattr(base, '_compat_activo', lambda: False)
    plan = base.preparar(PREGUNTA_COMPAT)
    assert plan['via'] == base.VIA_KEYWORD


# ── Qué motor puede responder ──────────────────────────────────
@contextmanager
def _turno():
    yield True


def _preparar_motor(monkeypatch, motor_obj, cargado):
    import services.ai_service as ai
    monkeypatch.setattr(mot, 'turno_publico', _turno)
    monkeypatch.setattr(mot, 'motor_para', lambda *a, **k: (motor_obj, 'x'))
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: cargado)
    llamadas = []

    def _chat(motor, sistema, usuario, max_tokens, temperature, canal='panel', permitir_puente=True,
              esperar_carga=True):
        llamadas.append({'nivel': motor.nivel, 'permitir_puente': permitir_puente,
                         'esperar_carga': esperar_carga, 'sistema': sistema})
        return 'Normalmente sí es compatible, pero confírmalo por WhatsApp.', None

    monkeypatch.setattr(ai, 'chat_con_motor', _chat)
    return llamadas


def _motor_b():
    return mot.Motor(mot.NIVEL_B, 'http://pc:11434', 'qwen2.5:14b', 120, 'tu equipo de IA')


def test_modelo_local_cargado_responde_sin_puente(base, monkeypatch):
    _catalogo(monkeypatch)
    llamadas = _preparar_motor(monkeypatch, _motor_b(), cargado=True)
    salida = base.responder(PREGUNTA_COMPAT)
    assert len(llamadas) == 1
    assert llamadas[0]['permitir_puente'] is False
    assert 'conocimiento técnico general' in llamadas[0]['sistema']
    assert salida['respuesta'].startswith('Normalmente')
    assert salida['escalar'] is True


def test_modelo_local_frio_no_se_usa_y_responde_el_catalogo(base, monkeypatch):
    _catalogo(monkeypatch)
    llamadas = _preparar_motor(monkeypatch, _motor_b(), cargado=False)
    salida = base.responder(PREGUNTA_COMPAT)
    assert llamadas == [], 'con el modelo frío no se debe esperar ni desviar a la nube'
    assert 'Tarjeta RTX 4060' in salida['respuesta']
    assert 'WhatsApp' in salida['respuesta']


def test_estado_desconocido_del_modelo_cuenta_como_no_listo(base, monkeypatch):
    _catalogo(monkeypatch)
    llamadas = _preparar_motor(monkeypatch, _motor_b(), cargado=None)
    base.responder(PREGUNTA_COMPAT)
    assert llamadas == []


def test_nunca_usa_la_nube_para_compatibilidad(base, monkeypatch):
    _catalogo(monkeypatch)
    nube = mot.Motor('nube', '', 'claude-haiku-4-5-20251001', 25, 'respaldo', proveedor='nube')
    llamadas = _preparar_motor(monkeypatch, nube, cargado=True)
    base.responder(PREGUNTA_COMPAT)
    assert llamadas == []


def test_consulta_normal_sigue_permitiendo_el_puente(base, monkeypatch):
    """Lo de compatibilidad no cambia las respuestas normales."""
    _catalogo(monkeypatch)
    llamadas = _preparar_motor(monkeypatch, _motor_b(), cargado=False)
    base.responder('tienen rtx')
    assert len(llamadas) == 1
    assert llamadas[0]['permitir_puente'] is True
    assert llamadas[0]['esperar_carga'] is False, 'al visitante nunca se le espera la carga'
    assert 'conocimiento técnico general' not in llamadas[0]['sistema']
