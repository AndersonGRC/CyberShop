# -*- coding: utf-8 -*-
"""Selector de motor: a qué máquina va cada petición.

Sin red ni BD: el chequeo de salud se reemplaza por un doble, así se puede
probar «el PC está apagado» sin apagar nada.

Lo que se cuida:
  - que el análisis profundo NO degrade a un modelo chico,
  - que un visitante no pueda disparar el profundo ni monopolizar la GPU,
  - que quedarse sin motores no rompa nada (se responde con los datos).
"""

import pytest
from flask import Flask

from services import ia_motores as mot


@pytest.fixture()
def app_ia(monkeypatch):
    """App mínima con los dos motores configurados y la salud bajo control."""
    app = Flask(__name__)
    app.config.update(
        AI_BASE_URL='http://pc:11434', AI_MODEL='qwen2.5:14b', AI_TIMEOUT=120,
        AI_MOTOR_A_BASE_URL='http://servidor:11434', AI_MOTOR_A_MODEL='qwen2.5:1.5b',
        AI_MOTOR_A_TIMEOUT=30, AI_MOTOR_C_MODEL='', AI_MOTOR_C_NUM_CTX=32768,
        AI_MOTOR_C_TIMEOUT=600, AI_PUBLIC_MAX_CONCURRENCIA=1, AI_PUBLIC_TIMEOUT=12,
        AI_API_KEY='',
    )
    encendidos = {'http://pc:11434': True, 'http://servidor:11434': True}
    llamadas = []

    def falso_vivo(motor):
        llamadas.append(motor.base_url)
        return encendidos.get(motor.base_url, False)

    monkeypatch.setattr(mot, '_consultar_vivo', falso_vivo)
    monkeypatch.setattr(mot, '_salud', {})
    monkeypatch.setattr(mot, '_semaforo_publico', None)
    with app.app_context():
        yield {'app': app, 'encendidos': encendidos, 'llamadas': llamadas}


# ── Quién atiende ──────────────────────────────────────────────
def test_lo_normal_lo_atiende_tu_equipo(app_ia):
    motor, _ = mot.motor_para()
    assert motor.nivel == mot.NIVEL_B and motor.modelo == 'qwen2.5:14b'


def test_si_tu_equipo_esta_apagado_contesta_el_servidor(app_ia):
    app_ia['encendidos']['http://pc:11434'] = False
    motor, motivo = mot.motor_para()
    assert motor.nivel == mot.NIVEL_A and 'servidor' in motivo


def test_sin_ningun_motor_no_se_rompe_nada(app_ia):
    app_ia['encendidos'].update({'http://pc:11434': False, 'http://servidor:11434': False})
    motor, motivo = mot.motor_para()
    assert motor is None
    assert 'datos' in motivo        # se responde con lo que hay, sin redacción


def test_sin_motor_a_configurado_cae_a_nada_no_a_un_error(app_ia):
    """Es la situación real de hoy: la VPS no tiene modelo."""
    app_ia['app'].config['AI_MOTOR_A_BASE_URL'] = ''
    app_ia['app'].config['AI_MOTOR_A_MODEL'] = ''
    app_ia['encendidos']['http://pc:11434'] = False
    motor, motivo = mot.motor_para()
    assert motor is None and motivo == mot.MSG_SIN_MOTOR


# ── Análisis profundo ──────────────────────────────────────────
@pytest.mark.parametrize('texto,perfil,limpio', [
    ('/profundo por qué bajaron las ventas', mot.PERFIL_PROFUNDO, 'por qué bajaron las ventas'),
    ('Analiza a fondo mis márgenes', mot.PERFIL_PROFUNDO, 'mis márgenes'),
    ('informe detallado del trimestre', mot.PERFIL_PROFUNDO, 'del trimestre'),
    ('¿cuánto vendí hoy?', mot.PERFIL_NORMAL, '¿cuánto vendí hoy?'),
    ('analiza mis ventas', mot.PERFIL_NORMAL, 'analiza mis ventas'),
    ('', mot.PERFIL_NORMAL, ''),
])
def test_el_perfil_se_pide_con_palabras_exactas(texto, perfil, limpio):
    assert mot.perfil_desde_texto(texto) == (perfil, limpio)


def test_el_profundo_usa_su_propio_modelo_y_contexto(app_ia):
    app_ia['app'].config['AI_MOTOR_C_MODEL'] = 'qwen2.5:32b'
    motor, _ = mot.motor_para(mot.PERFIL_PROFUNDO)
    assert motor.nivel == mot.NIVEL_C
    assert motor.modelo == 'qwen2.5:32b' and motor.num_ctx == 32768


def test_el_profundo_no_degrada_a_un_modelo_chico(app_ia):
    """Prefiere avisar a contestar mal: es la regla que pidió el dueño."""
    app_ia['encendidos']['http://pc:11434'] = False      # el PC apagado
    motor, motivo = mot.motor_para(mot.PERFIL_PROFUNDO)
    assert motor is None
    assert 'apagado' in motivo
    assert 'http://servidor:11434' not in app_ia['llamadas'], \
        'el profundo no debe siquiera mirar el motor del servidor'


def test_un_visitante_no_puede_pedir_analisis_profundo(app_ia):
    motor, _ = mot.motor_para(mot.PERFIL_PROFUNDO, canal=mot.CANAL_PUBLICO)
    assert motor.nivel == mot.NIVEL_B      # se ignora el perfil, se atiende normal


# ── Salud y tope ───────────────────────────────────────────────
def test_la_salud_se_consulta_una_vez_por_rato(app_ia):
    for _ in range(5):
        mot.motor_para()
    assert app_ia['llamadas'].count('http://pc:11434') == 1


def test_refrescar_vuelve_a_preguntar(app_ia):
    b = mot.motor_configurado(mot.NIVEL_B)
    mot.vivo(b)
    mot.vivo(b, refrescar=True)
    assert app_ia['llamadas'].count('http://pc:11434') == 2


def test_el_canal_publico_tiene_un_turno_a_la_vez(app_ia):
    with mot.turno_publico() as primero:
        assert primero is True
        with mot.turno_publico() as segundo:
            assert segundo is False, 'dos visitantes no pueden generar a la vez'
    with mot.turno_publico() as despues:
        assert despues is True, 'el turno debe liberarse al salir'


def test_el_estado_sirve_para_el_semaforo_del_panel(app_ia):
    est = mot.estado_motores()
    assert est['B']['en_linea'] is True and est['B']['modelo'] == 'qwen2.5:14b'
    assert est['A']['configurado'] is True
    assert 'disponible' in est['resumen']

    app_ia['encendidos'].update({'http://pc:11434': False, 'http://servidor:11434': False})
    mot._salud.clear()
    est = mot.estado_motores()
    assert est['B']['en_linea'] is False
    assert 'Sin redactor' in est['resumen']
