# -*- coding: utf-8 -*-
"""El panel de IA le muestra al dueño el estado del respaldo Anthropic.

Sin esto no había cómo saber por qué Claude no respondía (llave sin
workspace, presupuesto en 0, pausa por saldo…). El gasto del mes es del
dueño: el resto del equipo no lo ve.
"""
import pytest

import services.ai_service as ai

_CLAVES = {'configurada', 'disponible', 'bloqueo', 'para_publico', 'modelo',
           'llamadas', 'costo_usd', 'tope_usd'}


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    """El estado del equipo local no se consulta de verdad en estas pruebas."""
    monkeypatch.setattr(ai, 'ping', lambda: {'online': False, 'modelo': None, 'motivo': 'apagado'})


def _como(client, rol):
    with client.session_transaction() as s:
        s['usuario_id'], s['rol_id'], s['username'] = 1, rol, 'PytestUser'
    return client


def test_el_dueno_ve_el_estado_de_claude(client):
    d = _como(client, 2).get('/admin/ia/estado').get_json()
    assert set(d['nube']) == _CLAVES
    assert d['online'] is False, 'sigue trayendo el estado del equipo local'


def test_el_empleado_no_ve_el_gasto(client):
    d = _como(client, 4).get('/admin/ia/estado').get_json()
    assert d['nube'] is None


def test_sin_llave_dice_no_configurado(client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.config, 'AI_NUBE_API_KEY', '')
    d = _como(client, 2).get('/admin/ia/estado').get_json()
    assert d['nube']['configurada'] is False
    assert d['nube']['disponible'] is False


def test_la_pagina_le_pinta_el_estado_solo_al_dueno(client):
    html = _como(client, 2).get('/admin/ia/').get_data(as_text=True)
    assert 'id="ia-nube-estado"' in html
    assert 'pintarNube({' in html
    html = _como(client, 4).get('/admin/ia/').get_data(as_text=True)
    assert 'pintarNube(null)' in html
