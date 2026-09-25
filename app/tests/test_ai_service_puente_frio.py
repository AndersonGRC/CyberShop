# -*- coding: utf-8 -*-
"""Arranque en frío del motor local (NIVEL_B): carga pedida y puente a la nube.

vivo()/api/tags (ia_motores.py) no distingue "Ollama arriba pero el modelo sin
cargar en memoria" de "modelo caliente" — así que el respaldo lento ya existente
(ia_nube, 180s + 3 sondeos fallidos reales) nunca se activa para este caso. Este
camino usa la señal correcta (_modelo_en_memoria, /api/ps): mientras el modelo
no esté listo, pide la carga y cada pregunta la responde la nube; en cuanto está
listo, responde el local (regla del dueño, sep-2026: sin tope de preguntas, el
gasto lo frena el presupuesto mensual). Con esperar_carga=False (chat del sitio)
nunca se espera la carga.

El pedido real de carga lo neutraliza conftest (_sin_carga_real_del_modelo).
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
    monkeypatch.setattr(ia_nube, '_bloqueo', {})
    with app.app_context():
        yield app


def _sin_llamadas_locales(monkeypatch):
    """Si _chat_una_vez se invoca cuando no debía, la prueba falla de inmediato
    en vez de intentar una conexión real."""
    def _revienta(*a, **k):
        raise AssertionError('_chat_una_vez no debía llamarse')
    monkeypatch.setattr(ai, '_chat_una_vez', _revienta)


def _registrar_cargas(monkeypatch):
    pedidos = []
    monkeypatch.setattr(ai, '_pedir_carga', lambda modelo: pedidos.append(modelo))
    return pedidos


# ── El puente entra cuando toca ─────────────────────────────────
def test_primera_respuesta_fria_usa_la_nube_y_no_toca_el_local(app_puente, monkeypatch):
    _sin_llamadas_locales(monkeypatch)
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
    pedidos = _registrar_cargas(monkeypatch)

    ai.chat_con_motor(_motor_b(), 'sistema', 'usuario')
    assert pedidos == ['qwen2.5:14b']


def test_segunda_respuesta_fria_tambien_usa_la_nube(app_puente, monkeypatch):
    _sin_llamadas_locales(monkeypatch)
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: ('ok', None))

    ai.chat_con_motor(_motor_b(), 'sistema', 'usuario1')  # 1a
    texto, _ = ai.chat_con_motor(_motor_b(), 'sistema', 'usuario2')  # 2a
    assert texto == 'ok'


# ── Hasta que el equipo esté listo, sin tope de preguntas ───────
def test_mientras_siga_frio_todas_las_preguntas_van_a_la_nube(app_puente, monkeypatch):
    _sin_llamadas_locales(monkeypatch)
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: ('de la nube', None))

    textos = [ai.chat_con_motor(_motor_b(), 's', f'u{i}')[0] for i in range(5)]
    assert textos == ['de la nube'] * 5


def test_cada_pregunta_revisa_y_en_cuanto_esta_listo_responde_el_local(app_puente, monkeypatch):
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: ('de la nube', None))
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de lo local', None))
    revisiones = []

    def _en_memoria(modelo):
        revisiones.append(1)
        return len(revisiones) > 2                   # listo desde la tercera pregunta

    monkeypatch.setattr(ai, '_modelo_en_memoria', _en_memoria)
    textos = [ai.chat_con_motor(_motor_b(), 's', f'u{i}')[0] for i in range(4)]
    assert textos == ['de la nube', 'de la nube', 'de lo local', 'de lo local']
    assert len(revisiones) == 4, 'cada pregunta vuelve a mirar si el equipo está listo'


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
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: (None, 'la nube tambien fallo'))
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de lo local', None))

    texto, err = ai.chat_con_motor(_motor_b(), 's', 'u')
    assert texto == 'de lo local' and err is None


# ── La carga se pide siempre que está frío ──────────────────────
def test_frio_sin_nube_igual_pide_la_carga(app_puente, monkeypatch):
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': False)
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de lo local', None))
    pedidos = _registrar_cargas(monkeypatch)

    ai.chat_con_motor(_motor_b(), 's', 'u')
    assert pedidos == ['qwen2.5:14b']


def test_modelo_caliente_no_pide_carga(app_puente, monkeypatch):
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: True)
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de lo local', None))
    pedidos = _registrar_cargas(monkeypatch)

    ai.chat_con_motor(_motor_b(), 's', 'u')
    assert pedidos == []


# ── esperar_carga=False: nadie se queda esperando la carga ──────
def test_sin_esperar_carga_responde_sin_modelo_y_deja_la_carga_pedida(app_puente, monkeypatch):
    _sin_llamadas_locales(monkeypatch)
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': False)
    pedidos = _registrar_cargas(monkeypatch)

    texto, motivo = ai.chat_con_motor(_motor_b(), 's', 'u', canal='publico', esperar_carga=False)
    assert texto is None
    assert motivo == ai.MSG_MOTOR_PREPARANDO
    assert pedidos == ['qwen2.5:14b']


def test_sin_esperar_carga_igual_usa_el_puente_si_hay_nube(app_puente, monkeypatch):
    _sin_llamadas_locales(monkeypatch)
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: False)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, 'responder', lambda *a, **k: ('de la nube', None))

    texto, _ = ai.chat_con_motor(_motor_b(), 's', 'u', canal='publico', esperar_carga=False)
    assert texto == 'de la nube'


def test_sin_esperar_carga_con_estado_desconocido_sigue_como_siempre(app_puente, monkeypatch):
    """Si /api/ps no contesta no se sabe si está frío: se le habla al modelo."""
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda modelo: None)
    monkeypatch.setattr(ai, '_chat_una_vez', lambda *a, **k: ('de lo local', None))

    texto, _ = ai.chat_con_motor(_motor_b(), 's', 'u', esperar_carga=False)
    assert texto == 'de lo local'


# ── precalentar(): solo el equipo del dueño, nunca la nube ──────
def test_precalentar_pide_la_carga_del_motor_local(app_puente, monkeypatch):
    pedidos = _registrar_cargas(monkeypatch)
    ai.precalentar(_motor_b())
    assert pedidos == ['qwen2.5:14b']


@pytest.mark.parametrize('motor', [
    None,
    mot.Motor(mot.NIVEL_A, 'http://servidor:11434', 'modelo-chico', 30, 'servidor'),
    mot.Motor(mot.NIVEL_A, '', 'claude-haiku-4-5-20251001', 25, 'respaldo', proveedor='nube'),
    mot.Motor(mot.NIVEL_B, '', '', 120, 'tu equipo de IA'),  # IA sin configurar
])
def test_precalentar_ignora_lo_que_no_es_el_equipo_del_dueno(app_puente, monkeypatch, motor):
    pedidos = _registrar_cargas(monkeypatch)
    ai.precalentar(motor)
    assert pedidos == []
