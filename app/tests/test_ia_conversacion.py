# -*- coding: utf-8 -*-
"""Conversación guardada del chat del panel: por usuario, en la BD del cliente,
retomable desde cualquier navegador, archivable y con borrado a los 30 días."""
import os
import re

import pytest
from flask import session

from services import ia_conversacion as conv

USUARIO, OTRO = 990001, 990002          # ids de prueba que no chocan con usuarios reales


@pytest.fixture()
def limpia(flask_app, cursor):
    def _borrar():
        with cursor() as cur:
            cur.execute(conv._DDL)
            cur.execute('DELETE FROM ia_conversacion WHERE usuario_id IN (%s, %s)', (USUARIO, OTRO))
    _borrar()
    yield
    _borrar()


def _como(flask_app, usuario):
    ctx = flask_app.test_request_context('/admin/ia/')
    ctx.push()
    session['usuario_id'] = usuario
    return ctx


def test_guarda_y_devuelve_en_orden(flask_app, limpia):
    ctx = _como(flask_app, USUARIO)
    try:
        for i in range(8):
            conv.guardar(f'pregunta {i}', f'respuesta {i}', 'ventas_periodo')
        turnos = conv.recientes()
    finally:
        ctx.pop()
    assert [t['pregunta'] for t in turnos] == [f'pregunta {i}' for i in range(2, 8)]
    assert turnos[-1]['herramienta'] == 'ventas_periodo'


def test_cada_usuario_ve_solo_la_suya(flask_app, limpia):
    ctx = _como(flask_app, USUARIO)
    conv.guardar('¿Cuánto pagué de nómina?', 'Pagaste 12.345.678.', 'nomina_resumen')
    ctx.pop()
    ctx = _como(flask_app, OTRO)
    try:
        assert conv.recientes() == []
    finally:
        ctx.pop()


def test_nueva_conversacion_deja_lo_anterior_fuera_del_contexto(flask_app, limpia):
    ctx = _como(flask_app, USUARIO)
    try:
        conv.guardar('vieja', 'r')
        assert conv.nueva() is True
        conv.guardar('nueva', 'r')
        assert [t['pregunta'] for t in conv.recientes()] == ['nueva']
    finally:
        ctx.pop()


def test_lo_de_mas_de_30_dias_se_borra(flask_app, limpia, cursor):
    with cursor() as cur:
        cur.execute("""INSERT INTO ia_conversacion (usuario_id, pregunta, respuesta, creado_en)
                       VALUES (%s, 'muy vieja', 'r', NOW() - INTERVAL '31 days')""", (USUARIO,))
    ctx = _como(flask_app, USUARIO)
    try:
        conv.guardar('hoy', 'r')
    finally:
        ctx.pop()
    with cursor() as cur:
        cur.execute("SELECT pregunta FROM ia_conversacion WHERE usuario_id = %s", (USUARIO,))
        assert [r['pregunta'] for r in cur.fetchall()] == ['hoy']


def test_sin_usuario_no_guarda_ni_lee(flask_app, limpia):
    with flask_app.test_request_context('/'):
        conv.guardar('x', 'y')
        assert conv.recientes() is None


def test_el_chat_usa_la_conversacion_guardada_y_la_amplia(flask_app, limpia, monkeypatch):
    from routes import ia as rutas
    monkeypatch.setattr(rutas, '_guard', lambda: None)
    vistos = []
    monkeypatch.setattr(rutas.ai, 'responder_chat', lambda p, historial=None, **k: (
        vistos.append(historial) or ({'respuesta': 'Hoy vendiste $ 100.', 'herramienta': 'ventas_periodo'}, None)))
    ctx = _como(flask_app, USUARIO)
    try:
        conv.guardar('¿Quién me vende gaseosas?', 'Distribuidora Andes.', 'proveedores')
    finally:
        ctx.pop()
    with flask_app.test_request_context('/admin/ia/chat', method='POST', json={
            'pregunta': '¿Cuánto vendí hoy?', 'historial': [{'pregunta': 'del navegador', 'respuesta': 'x'}]}):
        session['usuario_id'] = USUARIO
        r = rutas.chat.__wrapped__()
        assert r.json['respuesta'] == 'Hoy vendiste $ 100.'
        assert [t['pregunta'] for t in vistos[0]] == ['¿Quién me vende gaseosas?'], 'manda lo guardado'
        assert [t['pregunta'] for t in conv.recientes()][-1] == '¿Cuánto vendí hoy?', 'y guarda lo nuevo'


def test_la_tabla_del_codigo_es_la_de_la_migracion_del_maestro():
    app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidatos = [os.path.join(app, *rel, 'CyberShopAdmin', 'migrations', 'tenant',
                               '0017_ia_conversacion.sql') for rel in (('..', '..'), ('..',))]
    ruta = next((os.path.normpath(r) for r in candidatos if os.path.exists(os.path.normpath(r))), None)
    if ruta is None:
        pytest.skip('el repo del maestro no está al lado')
    with open(ruta, encoding='utf-8') as f:
        sql = re.sub(r'--[^\n]*', '', f.read())

    def normal(texto):
        return re.sub(r'\s+', ' ', texto).strip().rstrip(';').strip()
    assert normal(conv._DDL) == normal(sql)
