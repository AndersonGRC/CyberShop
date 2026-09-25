# -*- coding: utf-8 -*-
"""Respaldo de IA en la nube: que solo entre cuando toca y que no se desboque.

Sin red: la llamada HTTP se reemplaza por un doble. Lo que se cuida aquí es
dinero, así que las pruebas son sobre los frenos:

  - no entra antes de tiempo (el equipo puede estar reiniciándose),
  - no entra si se acabó el presupuesto del mes,
  - no atiende al sitio público salvo que se pida expresamente,
  - si la cuenta no tiene saldo, se apaga y deja de intentar.
"""

import time

import pytest
from flask import Flask

from services import ia_motores as mot
from services import ia_nube

_USO_DEL_MES_REAL = ia_nube.uso_del_mes


class RespuestaFalsa:
    def __init__(self, status, datos=None, texto=''):
        self.status_code = status
        self._datos = datos or {}
        self.text = texto

    def json(self):
        return self._datos


def _ok(texto='Listo.', entrada=100, salida=50):
    return RespuestaFalsa(200, {
        'content': [{'type': 'text', 'text': texto}],
        'usage': {'input_tokens': entrada, 'output_tokens': salida},
    })


SIN_SALDO = RespuestaFalsa(400, {'error': {
    'type': 'invalid_request_error',
    'message': 'Your credit balance is too low to access the Anthropic API.'}})


@pytest.fixture()
def app_nube(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        AI_BASE_URL='http://pc:11434', AI_MODEL='qwen2.5:14b', AI_TIMEOUT=120,
        AI_MOTOR_A_BASE_URL='', AI_MOTOR_A_MODEL='',
        AI_NUBE_API_KEY='sk-de-prueba', AI_NUBE_MODEL='claude-haiku-4-5-20251001',
        AI_NUBE_MAX_TOKENS=300, AI_NUBE_TIMEOUT=25, AI_NUBE_ESPERA_LOCAL_S=180,
        AI_NUBE_FALLOS_LOCAL_MIN=3,
        AI_NUBE_PRESUPUESTO_USD=5.0, AI_NUBE_PARA_PUBLICO=False,
        AI_NUBE_PRECIO_ENTRADA_USD_MTOK=1.0, AI_NUBE_PRECIO_SALIDA_USD_MTOK=5.0,
        AI_PUBLIC_MAX_CONCURRENCIA=1, AI_API_KEY='',
    )
    # El equipo del dueño, apagado; y sin tocar la BD para el contador.
    monkeypatch.setattr(mot, '_consultar_vivo', lambda motor: False)
    monkeypatch.setattr(mot, '_salud', {})
    monkeypatch.setattr(mot, '_sondeos_local_fallidos', {})
    monkeypatch.setattr(mot, '_local_caido_desde', {})
    monkeypatch.setattr(ia_nube, '_bloqueo', {})
    gastado = {'usd': 0.0}
    monkeypatch.setattr(ia_nube, '_sumar_uso',
                        lambda e, s: gastado.__setitem__('usd', gastado['usd'] + ia_nube._costo(e, s)))
    monkeypatch.setattr(ia_nube, 'uso_del_mes', lambda: {
        'periodo': '2026-09', 'llamadas': 1, 'tokens_entrada': 0, 'tokens_salida': 0,
        'costo_usd': gastado['usd'], 'tope_usd': 5.0,
        'restante_usd': 5.0 - gastado['usd'], 'aviso_enviado': True})
    with app.app_context():
        yield {'app': app, 'gastado': gastado}


# ── El freno de tiempo ─────────────────────────────────────────
def test_no_entra_apenas_se_cae_el_equipo(app_nube):
    """Un reinicio de Ollama no puede costar dinero."""
    motor, motivo = mot.motor_para()
    assert motor is None
    assert 'unos minutos' in motivo


def test_entra_despues_de_los_minutos_de_espera(app_nube):
    mot.motor_para()                                  # marca el inicio de la caída
    mot._local_caido_desde[mot._reloj_clave()] = time.time() - 200
    mot._salud.clear()
    motor, _ = mot.motor_para()                        # segundo sondeo real
    assert motor is None
    mot._salud.clear()
    motor, motivo = mot.motor_para()
    assert motor is not None and motor.es_nube
    assert motor.modelo == 'claude-haiku-4-5-20251001'
    assert 'se cobra' in motivo


def test_caida_de_un_cliente_no_adelanta_respaldo_de_otro(app_nube, monkeypatch):
    cliente = ['cyber_a']
    monkeypatch.setattr(mot, '_reloj_clave', lambda: cliente[0])
    mot.motor_para()
    mot._local_caido_desde['cyber_a'] = time.time() - 200
    cliente[0] = 'cyber_b'
    motor_b, motivo_b = mot.motor_para()
    assert motor_b is None and 'unos minutos' in motivo_b
    cliente[0] = 'cyber_a'
    mot._salud.clear()
    mot.motor_para()
    mot._salud.clear()
    motor_a, _ = mot.motor_para()
    assert motor_a is not None and motor_a.es_nube


def test_si_el_equipo_vuelve_se_reinicia_el_reloj(app_nube, monkeypatch):
    mot.motor_para()
    mot._local_caido_desde[mot._reloj_clave()] = time.time() - 200
    monkeypatch.setattr(mot, '_consultar_vivo', lambda motor: True)
    mot._salud.clear()
    motor, _ = mot.motor_para()
    assert motor.nivel == mot.NIVEL_B                 # volvió el equipo del dueño
    assert mot._reloj_clave() not in mot._local_caido_desde

    monkeypatch.setattr(mot, '_consultar_vivo', lambda motor: False)
    mot._salud.clear()
    motor, motivo = mot.motor_para()
    assert motor is None, 'tras volver y caerse otra vez, la espera empieza de cero'


def test_espera_en_cero_significa_inmediato(app_nube):
    """El cero es un valor válido, no «sin configurar»: `valor or defecto` lo
    convertía en los 180 s por defecto y el respaldo no entraba nunca."""
    app_nube['app'].config['AI_NUBE_ESPERA_LOCAL_S'] = 0
    app_nube['app'].config['AI_NUBE_FALLOS_LOCAL_MIN'] = 1
    mot.motor_para()
    motor, _ = mot.motor_para()
    assert motor is not None and motor.es_nube


# ── El freno del presupuesto ───────────────────────────────────
def test_sin_presupuesto_no_se_usa(app_nube, monkeypatch):
    app_nube['app'].config['AI_NUBE_PRESUPUESTO_USD'] = 0
    mot._local_caido_desde[mot._reloj_clave()] = time.time() - 300
    motor, _ = mot.motor_para()
    assert motor is None


def test_sin_contador_de_gasto_la_nube_falla_cerrada(app_nube, monkeypatch):
    def sin_db(**_kw):
        raise RuntimeError('BD no disponible')

    monkeypatch.setattr(ia_nube, 'uso_del_mes', _USO_DEL_MES_REAL)
    monkeypatch.setattr(ia_nube, 'get_db_cursor', sin_db)
    uso = ia_nube.uso_del_mes()
    assert uso['registro_disponible'] is False
    assert ia_nube.hay_presupuesto() is False


def test_modelo_con_precio_no_validado_no_usa_respaldo(app_nube):
    app_nube['app'].config['AI_NUBE_MODEL'] = 'claude-sonnet-5'
    assert ia_nube.configurada() is False
    texto, motivo = ia_nube.responder('sistema', 'usuario')
    assert texto is None and 'precio validado' in motivo


def test_al_pasar_el_tope_deja_de_responder(app_nube, monkeypatch):
    app_nube['gastado']['usd'] = 5.5        # por encima del tope de 5
    texto, motivo = ia_nube.responder('sistema', 'usuario')
    assert texto is None and 'tope de gasto' in motivo


# ── El freno del canal público ─────────────────────────────────
def test_el_sitio_publico_no_usa_la_nube_por_defecto(app_nube):
    mot._local_caido_desde[mot._reloj_clave()] = time.time() - 300
    motor, _ = mot.motor_para(canal=mot.CANAL_PUBLICO, tarea='chat_publico')
    assert motor is None, 'el chat del sitio responde con datos, no gastando tokens'


def test_el_sitio_publico_puede_habilitarse_a_proposito(app_nube):
    app_nube['app'].config['AI_NUBE_PARA_PUBLICO'] = True
    app_nube['app'].config['AI_NUBE_FALLOS_LOCAL_MIN'] = 1
    mot._local_caido_desde[mot._reloj_clave()] = time.time() - 300
    motor, _ = mot.motor_para(canal=mot.CANAL_PUBLICO, tarea='chat_publico')
    assert motor is not None and motor.es_nube


# ── La llamada ─────────────────────────────────────────────────
def test_una_respuesta_normal_cuenta_su_costo(app_nube, monkeypatch):
    monkeypatch.setattr(ia_nube.requests, 'post', lambda *a, **k: _ok('Sí, hacemos domicilios.'))
    texto, motivo = ia_nube.responder('sistema', 'usuario')
    assert texto == 'Sí, hacemos domicilios.' and motivo is None
    # 100 de entrada a US$1/M + 50 de salida a US$5/M
    assert abs(app_nube['gastado']['usd'] - 0.00035) < 1e-9


def test_el_llamador_no_puede_superar_tope_de_tokens(app_nube, monkeypatch):
    payloads = []

    def post(*_args, **kwargs):
        payloads.append(kwargs['json'])
        return _ok()

    monkeypatch.setattr(ia_nube.requests, 'post', post)
    app_nube['app'].config['AI_NUBE_MAX_TOKENS'] = 220
    ia_nube.responder('sistema', 'usuario', max_tokens=550)
    assert payloads[-1]['max_tokens'] == 220


def test_sin_saldo_se_apaga_y_deja_de_intentar(app_nube, monkeypatch):
    llamadas = {'n': 0}

    def post(*a, **k):
        llamadas['n'] += 1
        return SIN_SALDO

    monkeypatch.setattr(ia_nube.requests, 'post', post)
    texto, motivo = ia_nube.responder('sistema', 'usuario')
    assert texto is None and 'saldo' in motivo

    # La segunda vez ni siquiera sale a la red
    texto2, motivo2 = ia_nube.responder('sistema', 'usuario')
    assert texto2 is None and llamadas['n'] == 1, 'no debe reintentar en cada mensaje'
    assert ia_nube.motivo_bloqueo()


SIN_WORKSPACE = RespuestaFalsa(400, {'error': {
    'type': 'invalid_request_error',
    'message': ('This API key is not scoped to a workspace, so this request must include the '
                'anthropic-workspace-id header with the ID of the workspace to use. Add the '
                'header, or use an API key that is scoped to a workspace.')}})


def test_llave_sin_workspace_se_pausa_con_un_motivo_claro(app_nube, monkeypatch):
    """Caso real (sep-2026): una llave de organización sin workspace falla en
    TODAS las llamadas. Se pausa y el panel dice qué hacer, en vez de
    reintentar y fallar en cada pregunta."""
    llamadas = {'n': 0}

    def post(*a, **k):
        llamadas['n'] += 1
        return SIN_WORKSPACE

    monkeypatch.setattr(ia_nube.requests, 'post', post)
    texto, motivo = ia_nube.responder('sistema', 'usuario')
    assert texto is None and 'workspace' in motivo
    assert not ia_nube.disponible()
    ia_nube.responder('sistema', 'usuario')
    assert llamadas['n'] == 1, 'no debe reintentar en cada mensaje'
    assert 'workspace' in ia_nube.estado()['bloqueo']


def test_bloqueo_de_nube_no_afecta_otro_cliente(app_nube, monkeypatch):
    cliente = ['cyber_a']
    monkeypatch.setattr(ia_nube, '_clave_bloqueo', lambda: cliente[0])
    ia_nube._bloquear('sin saldo A')
    assert ia_nube.motivo_bloqueo() == 'sin saldo A'
    cliente[0] = 'cyber_b'
    assert ia_nube.motivo_bloqueo() is None
    assert ia_nube.disponible()


def test_un_fallo_de_red_no_rompe_nada(app_nube, monkeypatch):
    def post(*a, **k):
        raise ia_nube.requests.ConnectionError('sin internet')

    monkeypatch.setattr(ia_nube.requests, 'post', post)
    texto, motivo = ia_nube.responder('sistema', 'usuario')
    assert texto is None and 'no se pudo alcanzar' in motivo.lower()


def test_el_estado_sirve_para_el_panel(app_nube):
    est = ia_nube.estado()
    assert est['configurada'] is True
    assert est['para_publico'] is False
    assert est['espera_local_s'] == 180
    assert est['tope_usd'] == 5.0
