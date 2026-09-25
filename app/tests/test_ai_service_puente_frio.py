# -*- coding: utf-8 -*-
"""Puente a la nube durante el arranque en frío del motor local (NIVEL_B).

vivo()/api/tags (ia_motores.py) no distingue "Ollama arriba pero el modelo sin
cargar en memoria" de "modelo caliente" — así que el respaldo lento ya existente
(ia_nube, 180s + 3 sondeos fallidos reales) nunca se activa para este caso. Este
puente es aparte y usa la señal correcta (_modelo_en_memoria, /api/ps): si el
modelo no está cargado, responde por la nube SOLO la primera y segunda vez de la
racha, después vuelve al camino local de siempre — para no dejar esperando al
usuario los 1-3 minutos que tarda la carga, sin gastar de más.
"""
import pytest
from flask import Flask

from services import ai_service as ai
from services import ia_motores as mot
from services import ia_nube


def _motor_b(timeout=120):
    return mot.Motor(mot.NIVEL_B, 'http://pc:11434', 'qwen2.5:14b', timeout, 'tu equipo de IA')


@pytest.fixture()
def app_puente(monkeypatch):
    app = Flask(__name__)
    app.config.update(AI_BASE_URL='http://pc:11434', AI_API_KEY='',
                      AI_NUBE_PARA_PUBLICO=False)
    # Cada prueba empieza con la racha en cero y sin pedidos de carga pendientes.
    monkeypatch.setattr(ai, '_puente_nube_usos', {})
    monkeypatch.setattr(ai, '_CALENTANDO', {})
    monkeypatch.setattr(ia_nube, '_bloqueo', {})
    with app.app_context():
        yield app


def _sin_llamadas_locales(monkeypatch):
    """Si _chat_una_vez se invoca cuando no debía, la prueba falla de inmediato
    en vez de intentar una conexión real."""
    def _revienta(*a, **k):
        raise AssertionError('_chat_una_vez no debía llamarse: el puente debía responder')
    monkeypatch.setattr(ai, '_chat_una_vez', _revienta)


def _pedir_carga_silenciosa(monkeypatch):
    """No lanzar un hilo real que golpee la red durante la prueba."""
    monkeypatch.setattr(ai, '_pedir_carga', lambda modelo: None)


# ── El puente entra cuando toca ─────────────────────────────────
def test_primera_respuesta_fria_usa_la_nube_y_no_toca_el_local(app_puente, monkeypatch):
    _sin_llamadas_locales(monkeypatch)
    _pedir_carga_silenciosa(monkeypatch)
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: ('Respuesta de la nube.', None))

    texto, err = ai.chat_con_motor(_motor_b(), 'sistema', 'usuario', canal='panel')
    assert texto == 'Respuesta de la nube.'
    assert err is None


def test_pide_la_carga_en_segundo_plano_al_usar_el_puente(app_puente, monkeypatch):
    _sin_llamadas_locales(monkeypatch)
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: ('ok', None))
    pedidos = []
    monkeypatch.setattr(ai, '_pedir_carga', lambda modelo: pedidos.append(modelo))

    ai.chat_con_motor(_motor_b(), 'sistema', 'usuario')
    assert pedidos == ['qwen2.5:14b']


def test_segunda_respuesta_fria_tambien_usa_la_nube(app_puente, monkeypatch):
    _sin_llamadas_locales(monkeypatch)
    _pedir_carga_silenciosa(monkeypatch)
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: ('ok', None))

    ai.chat_con_motor(_motor_b(), 'sistema', 'usuario1')  # 1a
    texto, _ = ai.chat_con_motor(_motor_b(), 'sistema', 'usuario2')  # 2a
    assert texto == 'ok'


# ── El freno de "hasta la segunda, no más" ──────────────────────
def test_tercera_respuesta_fria_ya_no_usa_el_puente(app_puente, monkeypatch):
    _pedir_carga_silenciosa(monkeypatch)
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: ('de la nube', None))
    llamadas_locales = []
    monkeypatch.setattr(ai, '_chat_una_vez',
                        lambda *a, **k: (llamadas_locales.append(1) or 'de lo local', None))

    ai.chat_con_motor(_motor_b(), 's', 'u1')  # 1a: nube
    ai.chat_con_motor(_motor_b(), 's', 'u2')  # 2a: nube
    texto, _ = ai.chat_con_motor(_motor_b(), 's', 'u3')  # 3a: local, aunque siga frio
    assert texto == 'de lo local'
    assert len(llamadas_locales) == 1


# ── Una respuesta local exitosa limpia la racha ─────────────────
def test_una_respuesta_local_exitosa_reinicia_la_racha(app_puente, monkeypatch):
    _pedir_carga_silenciosa(monkeypatch)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: ('de la nube', None))
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de lo local', None))

    estados_cargado = iter([False, False, True, False])
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: next(estados_cargado))

    ai.chat_con_motor(_motor_b(), 's', 'u1')          # frio -> nube (racha 1)
    ai.chat_con_motor(_motor_b(), 's', 'u2')          # frio -> nube (racha 2)
    texto3, _ = ai.chat_con_motor(_motor_b(), 's', 'u3')  # "cargado" -> local, limpia racha
    assert texto3 == 'de lo local'

    # Racha limpia: una CUARTA consulta fria vuelve a tener puente disponible
    # (si no se hubiera limpiado, esta ya estaria en su 3er uso y no lo tendria).
    llamadas_locales = []
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: (llamadas_locales.append(1) or 'x', None))
    texto4, _ = ai.chat_con_motor(_motor_b(), 's', 'u4')
    assert texto4 == 'de la nube'
    assert llamadas_locales == []


# ── Respeta las mismas compuertas que ya protegen a ia_nube ─────
def test_sin_ia_nube_disponible_cae_al_camino_normal(app_puente, monkeypatch):
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': False)  # presupuesto en 0, por ej.
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de lo local (esperando)', None))

    texto, _ = ai.chat_con_motor(_motor_b(), 's', 'u')
    assert texto == 'de lo local (esperando)'


def test_publico_sin_opt_in_no_usa_el_puente(app_puente, monkeypatch):
    """AI_NUBE_PARA_PUBLICO sigue en False por defecto: el chat público no debe
    ganar el puente solo por estar frio, hasta que el dueño lo active a proposito."""
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    # ia_nube.disponible real (no mockeada) SI lee AI_NUBE_PARA_PUBLICO del config.
    monkeypatch.setattr(ia_nube, 'configurada', lambda: True)
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de lo local', None))

    texto, _ = ai.chat_con_motor(_motor_b(), 's', 'u', canal='publico')
    assert texto == 'de lo local'


# ── No se aplica a motores que no son el equipo del dueño (NIVEL_B) ─────
def test_no_se_aplica_a_un_motor_que_no_es_nivel_b(app_puente, monkeypatch):
    llamado = []
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: llamado.append(1) or False)
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de A', None))
    motor_a = mot.Motor(mot.NIVEL_A, 'http://servidor:11434', 'modelo-chico', 30, 'servidor')

    texto, _ = ai.chat_con_motor(motor_a, 's', 'u')
    assert texto == 'de A'
    assert llamado == [], '_modelo_en_memoria no deberia consultarse para un motor que no es NIVEL_B'


def test_permitir_puente_false_nunca_desvia_a_la_nube(app_puente, monkeypatch):
    """Las respuestas de compatibilidad solo pueden salir del modelo local."""
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    nube = []
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: nube.append(1) or ('nube', None))
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de lo local', None))

    texto, _ = ai.chat_con_motor(_motor_b(), 's', 'u', permitir_puente=False)
    assert texto == 'de lo local'
    assert nube == []


# ── Nunca lanza, ni si la nube falla a mitad de camino ──────────
def test_si_la_nube_tambien_falla_cae_al_local_sin_reventar(app_puente, monkeypatch):
    _pedir_carga_silenciosa(monkeypatch)
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: (None, 'la nube tambien fallo'))
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de lo local', None))

    texto, err = ai.chat_con_motor(_motor_b(), 's', 'u')
    assert texto == 'de lo local' and err is None
