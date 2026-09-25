# -*- coding: utf-8 -*-
"""Chat del panel con el modelo del equipo del dueño sin cargar.

Regla del dueño: se calienta siempre el modelo local; la nube (Claude) responde
cada pregunta mientras el equipo no esté listo —cada pregunta vuelve a revisar—
y NUNCA con datos solo locales (nómina, documentos internos), ni siquiera los
que vienen en la conversación anterior. Lo mismo vale para el respaldo con el
equipo apagado. Todo sin red ni modelo real: la nube y el modelo están simulados.
"""
import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from flask import session

import services.ai_service as ai
import services.ai_tools as tools
from services import ia_motores as mot
from services import ia_nube

MODELO = 'modelo-local'
SECRETO = '12.345.678'            # lo que costó la nómina: nunca debe llegar a la nube

DATOS = {
    'ventas_periodo': {'periodo': 'hoy', 'total': 500000},
    'nomina_resumen': {'periodo': 'mes', 'neto_pagado': SECRETO},
    'documentos_internos': {'documentos': [{'titulo': 'Apertura', 'texto': 'Abrir la reja.'}]},
}
HISTORIAL_CON_NOMINA = [
    {'pregunta': '¿Cuánto pagué de nómina este mes?', 'herramienta': 'nomina_resumen',
     'respuesta': f'Pagaste {SECRETO} de nómina.'},
    {'pregunta': '¿Cuántos pedidos hay?', 'herramienta': 'ventas_periodo',
     'respuesta': 'Hay 7 pedidos.'},
]


@pytest.fixture()
def panel(flask_app, monkeypatch):
    motor_b = mot.Motor(mot.NIVEL_B, 'http://pc:11434', MODELO, 120, 'tu equipo de IA')
    ns = SimpleNamespace(nube=[], local=[], frio=True, motor=motor_b, espera_ok=True,
                         nube_disponible=True, eleccion=None)
    monkeypatch.setitem(flask_app.config, 'AI_MODEL', MODELO)
    monkeypatch.setattr(ai, '_fecha_hoy', lambda: (date(2026, 9, 25), datetime(2026, 9, 25, 10)))
    monkeypatch.setattr(ai, '_contexto_tenant', lambda: 'Negocio de prueba.')
    monkeypatch.setattr(ai, '_registrar_consulta', lambda *a, **k: None)
    monkeypatch.setattr(ai, 'estado_ia', lambda: (True, None))
    monkeypatch.setattr(mot, 'motor_para', lambda *a, **k: (ns.motor, 'x'))
    # False = frío (Ollama arriba, modelo sin cargar); None = equipo apagado.
    monkeypatch.setattr(ai, '_modelo_en_memoria',
                        lambda modelo: None if ns.motor.es_nube else not ns.frio)
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': ns.nube_disponible)

    def _nube(sistema, usuario, **_k):
        ns.nube.append(usuario)
        if 'Eres un enrutador' in sistema:
            return json.dumps({'tools': [{'tool': ns.eleccion, 'params': {}}]}), None
        return 'Respuesta de la nube.', None
    monkeypatch.setattr(ia_nube, 'responder', _nube)

    def _local_stream(modelo, system, user, *a, **k):
        ns.local.append(user)
        yield 'Respuesta local.'
    monkeypatch.setattr(ai, '_chat_stream_una_vez', _local_stream)

    def _local(modelo, system, user, *a, **k):
        ns.local.append(user)
        if 'Eres un enrutador' in system:
            return json.dumps({'tools': [{'tool': ns.eleccion, 'params': {}}]}), None
        return 'Respuesta local.', None
    monkeypatch.setattr(ai, '_chat_una_vez', _local)

    def _espera(modelo, espera_max, intervalo=5):
        yield None
        return ns.espera_ok
    monkeypatch.setattr(ai, '_esperar_motor', _espera)

    capacidades = [tools.REGISTRO[c] for c in DATOS]
    monkeypatch.setattr(tools, 'permitidas', lambda ctx=None: capacidades)
    monkeypatch.setattr(tools, 'ejecutar', lambda code, params, ctx=None: DATOS[code])
    with flask_app.test_request_context('/'):
        session['rol_id'], session['usuario_id'] = 2, 1
        yield ns


def _stream(pregunta, historial=None):
    eventos = list(ai.responder_chat_stream(pregunta, historial=historial))
    fin = [d for e, d in eventos if e == 'fin']
    texto = ''.join(d for e, d in eventos if e == 'delta')
    return SimpleNamespace(eventos=eventos, fin=fin[0] if fin else None, texto=texto)


# ── Lo que puede salir: la nube redacta mientras el equipo carga ─
def test_en_frio_la_nube_redacta_lo_no_sensible(panel):
    r = _stream('¿Cuánto vendí hoy?')
    assert r.texto == 'Respuesta de la nube.'
    assert r.fin == {'herramienta': 'ventas_periodo', 'motor': 'nube'}
    assert panel.local == [], 'no se esperó ni se usó el modelo local'


def test_con_el_modelo_caliente_no_se_toca_la_nube(panel):
    panel.frio = False
    r = _stream('¿Cuánto vendí hoy?')
    assert r.texto == 'Respuesta local.'
    assert panel.nube == []


# ── Lo que nunca sale ──────────────────────────────────────────
def test_la_nomina_nunca_va_a_la_nube_espera_al_equipo(panel):
    r = _stream('¿Cuánto pagué de nómina este mes?')
    assert panel.nube == []
    assert r.texto == 'Respuesta local.'
    assert ('latido', None) in r.eventos, 'la espera manda latidos para que nginx no corte'


def test_la_nomina_sin_equipo_listo_sale_tal_cual_sin_nube(panel):
    panel.espera_ok = False
    r = _stream('¿Cuánto pagué de nómina este mes?')
    assert panel.nube == []
    assert r.texto.startswith('Datos verificados de nomina resumen')


def test_los_documentos_internos_nunca_van_a_la_nube(panel):
    r = _stream('¿Cuál es el procedimiento para abrir el local?')
    assert panel.nube == []
    assert r.texto == 'Respuesta local.'


def test_la_nube_no_ve_la_conversacion_sensible(panel):
    _stream('¿Cuánto vendí hoy?', historial=HISTORIAL_CON_NOMINA)
    assert len(panel.nube) == 1
    assert SECRETO not in panel.nube[0]
    assert 'Hay 7 pedidos.' in panel.nube[0], 'lo no sensible sí sirve de contexto'


def test_el_modelo_local_si_ve_toda_la_conversacion(panel):
    panel.frio = False
    _stream('¿Cuánto vendí hoy?', historial=HISTORIAL_CON_NOMINA)
    assert SECRETO in panel.local[0]


# ── Elegir herramientas en frío ────────────────────────────────
def test_en_frio_elegir_y_redactar_van_por_la_nube_sin_lo_sensible(panel):
    panel.eleccion = 'ventas_periodo'
    r = _stream('Necesito un análisis del negocio para decidir compras',
                historial=HISTORIAL_CON_NOMINA)
    assert r.texto == 'Respuesta de la nube.'
    assert len(panel.nube) == 2               # elegir + redactar
    assert all(SECRETO not in u for u in panel.nube)
    assert panel.local == []


def test_si_eligio_nomina_la_redaccion_espera_al_equipo(panel):
    panel.eleccion = 'nomina_resumen'
    r = _stream('Necesito revisar los costos del personal')
    assert len(panel.nube) == 1, 'solo la elección (sin datos) pasó por la nube'
    assert r.texto == 'Respuesta local.'


# ── Hasta que el equipo esté listo; cada pregunta vuelve a mirar ─
def test_mientras_siga_frio_todas_las_preguntas_van_a_la_nube(panel):
    textos = [_stream('¿Cuánto vendí hoy?').texto for _ in range(4)]
    assert textos == ['Respuesta de la nube.'] * 4
    assert panel.local == []


def test_en_cuanto_el_equipo_esta_listo_responde_el_local(panel):
    assert _stream('¿Cuánto vendí hoy?').texto == 'Respuesta de la nube.'
    panel.frio = False
    assert _stream('¿Cuánto vendí hoy?').texto == 'Respuesta local.'
    assert _stream('¿Cuánto vendí hoy?').texto == 'Respuesta local.'
    assert len(panel.nube) == 1


def test_sin_nube_configurada_espera_al_equipo_como_siempre(panel):
    panel.nube_disponible = False
    r = _stream('¿Cuánto vendí hoy?')
    assert panel.nube == []
    assert r.texto == 'Respuesta local.'


# ── Respaldo con el equipo apagado: el mismo candado ───────────
@pytest.fixture()
def equipo_apagado(panel):
    panel.motor = mot.Motor(mot.NIVEL_A, '', 'claude-haiku-4-5-20251001', 25,
                            'respaldo en la nube', proveedor='nube')
    return panel


def test_apagado_lo_sensible_sale_tal_cual_sin_nube(equipo_apagado):
    equipo_apagado.eleccion = 'nomina_resumen'
    r = _stream('Necesito revisar los costos del personal')
    assert len(equipo_apagado.nube) == 1, 'solo la elección, sin datos'
    assert all(SECRETO not in u for u in equipo_apagado.nube)
    assert r.texto.startswith('Datos verificados de nomina resumen')


def test_apagado_lo_no_sensible_se_redacta_sin_la_conversacion_sensible(equipo_apagado):
    equipo_apagado.eleccion = 'ventas_periodo'
    r = _stream('Necesito un análisis del negocio para decidir compras',
                historial=HISTORIAL_CON_NOMINA)
    assert r.texto == 'Respuesta de la nube.'
    assert all(SECRETO not in u for u in equipo_apagado.nube)


# ── Respuesta completa (escritorio y respaldo del panel) ───────
def test_completa_en_frio_la_nube_redacta_lo_no_sensible(panel):
    salida, err = ai.responder_chat('¿Cuánto vendí hoy?')
    assert err is None
    assert salida['respuesta'] == 'Respuesta de la nube.'


def test_completa_la_nomina_nunca_va_a_la_nube(panel):
    salida, err = ai.responder_chat('¿Cuánto pagué de nómina este mes?',
                                    historial=HISTORIAL_CON_NOMINA)
    assert err is None
    assert panel.nube == []
    assert salida['respuesta'] == 'Respuesta local.'


def test_completa_apagado_lo_sensible_sale_tal_cual(equipo_apagado):
    equipo_apagado.eleccion = 'nomina_resumen'
    salida, err = ai.responder_chat('Necesito revisar los costos del personal')
    assert err is None
    assert salida['respuesta'].startswith('Datos verificados de nomina resumen')
    assert all(SECRETO not in u for u in equipo_apagado.nube)


# ── Sin modelo: los documentos se leen como texto, no como JSON ─
def test_sin_modelo_los_documentos_salen_como_texto_legible():
    plan = {'herramientas': ['documentos_internos'],
            'datos': {'buscado': 'apertura', 'encontrados': 1,
                      'documentos': [{'titulo': 'Apertura', 'texto': 'Abrir la reja.'}]}}
    texto = ai._respuesta_datos_sin_modelo(plan)
    assert '«Apertura»\nAbrir la reja.' in texto
    assert '{' not in texto


def test_sin_modelo_si_no_hay_documentos_sale_la_explicacion():
    plan = {'herramientas': ['documentos_internos'],
            'datos': {'buscado': 'apertura', 'encontrados': 0,
                      'conclusion': 'No encontré documentos internos sobre «apertura».'}}
    assert ai._respuesta_datos_sin_modelo(plan).startswith('No encontré documentos internos')


def test_los_demas_datos_siguen_saliendo_verificados():
    plan = {'herramientas': ['ventas_periodo'], 'datos': DATOS['ventas_periodo']}
    assert ai._respuesta_datos_sin_modelo(plan).startswith('Datos verificados de ventas periodo')


# ── El filtro de la conversación ───────────────────────────────
def test_historial_para_nube_quita_solo_los_turnos_solo_locales():
    historial = ai._sanear_historial(HISTORIAL_CON_NOMINA + [
        {'pregunta': '¿Procedimiento de apertura?', 'herramienta': 'documentos_internos',
         'respuesta': 'Abrir la reja.'},
        {'pregunta': 'hola', 'herramienta': '', 'respuesta': '¡Hola!'},
    ])
    limpio = ai._historial_para_nube(historial)
    assert [t['pregunta'] for t in limpio] == ['¿Cuántos pedidos hay?', 'hola']
