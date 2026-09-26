# -*- coding: utf-8 -*-
"""Saludos del chat del sitio.

Pedido del dueño (sep-2026): «hola, hola, hola» siempre respondía lo mismo, que
además ya estaba escrito arriba (el widget muestra el saludo al abrirse). Ahora:

  - cada «hola» repetido responde distinto y al tercero se ofrece una persona;
  - «hola, ¿tienen portátiles?» es una pregunta, no un saludo (antes se perdía);
  - mientras el modelo del equipo no esté listo, Claude redacta el saludo (si
    está activo para el chat del sitio); la respuesta queda en caché.
"""
from contextlib import contextmanager

import pytest

import services.ai_service as ai
from services import ia_motores as mot
from services.ia_datos.base import Herramienta

CFG = {'saludo': '¡Hola! Soy el asistente de Tienda. ¿En qué te ayudo?', 'negocio': 'Tienda',
       'tono': 'cercano y breve', 'whatsapp': '573001112233',
       'sugerencias': ['¿Qué productos manejan?', '¿Dónde están ubicados?']}


@pytest.fixture()
def base(flask_app, monkeypatch):
    from services.chat_publico import motor
    monkeypatch.setattr(motor, 'config_publica', lambda: dict(CFG))
    monkeypatch.setattr(motor, '_registrar', lambda *a, **k: None)
    monkeypatch.setitem(flask_app.config, 'AI_BASE_URL', 'http://pc:11434')
    monkeypatch.setitem(flask_app.config, 'AI_MODEL', 'modelo-local')
    motor._CACHE.clear()
    with flask_app.app_context():
        yield motor
    motor._CACHE.clear()


@pytest.fixture()
def nube(monkeypatch):
    """Claude activo para el chat del sitio y el equipo del dueño sin cargar."""
    llamadas = []
    monkeypatch.setattr(ai, '_puente_disponible', lambda canal: canal == 'publico')
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ai, '_responder_nube',
                        lambda s, u, mt, t: llamadas.append(u) or ('¡Hola! Qué gusto saludarte.', None))
    return llamadas


def _hist(*mensajes):
    return [{'rol': 'usuario', 'texto': m} for m in mensajes]


# ── Cada «hola» responde distinto ──────────────────────────────
def test_el_primer_hola_no_repite_el_saludo_que_ya_se_ve(base):
    salida = base.responder('hola')
    assert salida['via'] == base.VIA_CORTESIA
    assert salida['respuesta'] != CFG['saludo']
    assert 'productos' in salida['respuesta']


def test_el_segundo_hola_propone_preguntas_concretas(base):
    salida = base.responder('hola', historial=_hist('hola'))
    assert salida['respuesta'].startswith('¡Hola de nuevo!')
    assert '«¿Qué productos manejan?»' in salida['respuesta']


def test_al_tercer_hola_ofrece_una_persona(base):
    salida = base.responder('hola', historial=_hist('hola', 'buenas'))
    assert salida['escalar'] is True
    assert salida['whatsapp'] == '573001112233'
    assert 'WhatsApp' in salida['respuesta']


@pytest.mark.parametrize('texto', ['hola', 'Hola!', 'Hola, buenas tardes', 'hola que tal',
                                   'buenos días', 'Buenas'])
def test_saludos_con_y_sin_relleno(base, texto):
    assert base._es_saludo(texto)


def test_hola_mas_una_pregunta_es_una_pregunta(base, monkeypatch):
    import services.ai_tools as tools
    herramienta = Herramienta('buscar_productos', lambda **_: {}, 'Catálogo.', ('texto',),
                              disparadores=('tienen', 'tienes'))
    monkeypatch.setattr(tools, 'permitidas', lambda _ctx: [herramienta])
    monkeypatch.setattr(tools, 'ejecutar', lambda code, params, ctx: {
        'buscado': 'portátiles', 'encontrados': 1,
        'productos': [{'producto': 'Portátil X', 'disponible': True}]})
    assert not base._es_saludo('Hola, ¿tienen portátiles?')
    plan = base.preparar('Hola, ¿tienen portátiles?')
    assert plan['via'] == base.VIA_KEYWORD
    assert 'Portátil X' in plan['texto_base']


# ── Claude redacta mientras el equipo no está listo ────────────
def test_en_frio_claude_redacta_el_saludo(base, nube):
    salida = base.responder('hola')
    assert salida['respuesta'] == '¡Hola! Qué gusto saludarte.'
    assert salida['via'] == 'cortesia+modelo'
    assert len(nube) == 1


def test_el_saludo_de_claude_queda_en_cache(base, nube):
    base.responder('hola')
    salida = base.responder('Hola!')
    assert salida['via'] == 'cortesia+cache'
    assert len(nube) == 1, 'el mismo saludo no se vuelve a pagar'


def test_con_el_equipo_listo_el_saludo_es_instantaneo(base, nube, monkeypatch):
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: True)
    salida = base.responder('hola')
    assert salida['via'] == base.VIA_CORTESIA
    assert nube == []


def test_sin_claude_ni_se_pregunta_por_el_equipo(base, monkeypatch):
    """Sin Claude para el chat del sitio (hoy en producción) el saludo sigue
    siendo instantáneo: ni siquiera se consulta /api/ps."""
    monkeypatch.setattr(ai, '_puente_disponible', lambda canal: False)

    def _no_consultar(modelo):
        raise AssertionError('no debía consultarse el estado del equipo')
    monkeypatch.setattr(ai, '_modelo_en_memoria', _no_consultar)
    salida = base.responder('hola')
    assert salida['via'] == base.VIA_CORTESIA


def test_el_saludo_con_claude_igual_calienta_el_equipo(base, nube, monkeypatch):
    pedidos = []
    monkeypatch.setattr(ai, '_pedir_carga', lambda modelo: pedidos.append(modelo))
    base.responder('hola')
    assert pedidos == ['modelo-local']


def test_pedir_una_persona_nunca_va_a_claude(base, nube):
    salida = base.responder('quiero hablar con una persona')
    assert salida['escalar'] is True
    assert nube == []


@contextmanager
def _sin_turno():
    yield False


def test_sin_turno_libre_el_saludo_sale_de_python(base, nube, monkeypatch):
    monkeypatch.setattr(mot, 'turno_publico', _sin_turno)
    salida = base.responder('hola')
    assert salida['via'] == base.VIA_CORTESIA
    assert nube == []
