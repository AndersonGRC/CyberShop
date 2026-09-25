# -*- coding: utf-8 -*-
"""El chat del sitio deja el modelo del equipo del dueño cargándose en cada
pregunta, aunque la respuesta la arme Python, y nunca hace esperar al visitante
la carga en frío (1-3 min): sale el texto de Python al instante."""
from contextlib import contextmanager

import pytest

from services import ia_motores as mot
from services import ia_nube
from services.ia_datos.base import Herramienta


@pytest.fixture()
def base(flask_app, monkeypatch):
    from services.chat_publico import motor
    monkeypatch.setattr(motor, 'config_publica', lambda: {
        'saludo': 'Hola', 'negocio': 'Tienda', 'tono': 'breve', 'whatsapp': '573001112233'})
    monkeypatch.setattr(motor, '_registrar', lambda *a, **k: None)
    monkeypatch.setitem(flask_app.config, 'AI_BASE_URL', 'http://pc:11434')
    monkeypatch.setitem(flask_app.config, 'AI_MODEL', 'modelo-local')
    motor._CACHE.clear()
    with flask_app.app_context():
        yield motor
    motor._CACHE.clear()


@pytest.fixture()
def cargas(monkeypatch):
    import services.ai_service as ai
    pedidos = []
    monkeypatch.setattr(ai, '_pedir_carga', lambda modelo: pedidos.append(modelo))
    return pedidos


def _catalogo(monkeypatch):
    import services.ai_tools as tools
    herramienta = Herramienta('buscar_productos', lambda **_: {}, 'Catálogo.', ('texto',),
                              disparadores=('tienen', 'tienes', 'busco'))
    monkeypatch.setattr(tools, 'permitidas', lambda _ctx: [herramienta])
    monkeypatch.setattr(tools, 'ejecutar', lambda code, params, ctx: {
        'buscado': 'rtx', 'encontrados': 1,
        'productos': [{'producto': 'Tarjeta RTX 4060', 'categoria': 'Componentes',
                       'disponible': True}]})


# ── Respuestas de Python: igual se calienta ────────────────────
def test_saludo_contestado_por_python_igual_pide_la_carga(base, cargas):
    salida = base.responder('hola')
    assert salida['via'] == base.VIA_CORTESIA
    assert cargas == ['modelo-local']


def test_pregunta_sin_respuesta_igual_pide_la_carga(base, cargas, monkeypatch):
    _catalogo(monkeypatch)
    import services.ia_rag as rag
    monkeypatch.setattr(rag, 'buscar', lambda *a, **k: [])
    salida = base.responder('¿Hacen domicilios?')
    assert salida['via'] == base.VIA_SIN_RESPUESTA
    assert cargas == ['modelo-local']


def test_sin_ia_configurada_no_pide_nada(base, cargas, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'AI_BASE_URL', '')
    base.responder('hola')
    assert cargas == []


def test_sin_redaccion_no_pide_carga(base, cargas):
    base.responder('hola', redactar=False)
    assert cargas == []


# ── Modelo frío: respuesta al instante, carga pedida ───────────
@contextmanager
def _turno():
    yield True


def test_modelo_frio_no_hace_esperar_al_visitante(base, cargas, monkeypatch):
    import services.ai_service as ai
    _catalogo(monkeypatch)
    motor_b = mot.Motor(mot.NIVEL_B, 'http://pc:11434', 'modelo-local', 120, 'tu equipo de IA')
    monkeypatch.setattr(mot, 'turno_publico', _turno)
    monkeypatch.setattr(mot, 'motor_para', lambda *a, **k: (motor_b, 'x'))
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': False)

    def _revienta(*a, **k):
        raise AssertionError('con el modelo frío no se debe esperar su carga')
    monkeypatch.setattr(ai, '_chat_una_vez', _revienta)

    salida = base.responder('tienen rtx')
    assert 'Tarjeta RTX 4060' in salida['respuesta']
    assert salida['via'] == base.VIA_KEYWORD
    assert cargas and set(cargas) == {'modelo-local'}
