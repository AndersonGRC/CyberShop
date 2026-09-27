# -*- coding: utf-8 -*-
"""Proveedores en la IA del panel y la respuesta cuando falta una herramienta.

Caso real: el dueño preguntó por sus proveedores y el chat le contestó que era
«un dato sensible y privado para tu negocio». No había herramienta de
proveedores y la instrucción de respaldo le pedía al modelo negarse «si es un
dato sensible»: el modelo decidió que lo era. Al dueño todo le pertenece.
"""
import uuid

import pytest

import services.ai_service as ai
import services.ai_tools as tools
from services.ia_datos.acceso import Contexto


@pytest.fixture()
def proveedor(cursor):
    nombre = f'PYT Distribuidora {uuid.uuid4().hex[:6]}'
    concepto = f'PYT compra de insumos {uuid.uuid4().hex[:6]}'
    with cursor() as cur:
        cur.execute("""INSERT INTO crm_contactos (tipo, nombre, empresa, telefono, activo)
                       VALUES ('proveedor', %s, 'Insumos SAS', '3000000000', TRUE) RETURNING id""",
                    (nombre,))
        cid = cur.fetchone()['id']
        cur.execute("""INSERT INTO contabilidad_movimientos (tipo, categoria, descripcion, monto, fecha)
                       VALUES ('egreso', 'proveedor', %s, 123456, CURRENT_DATE) RETURNING id""",
                    (concepto,))
        mid = cur.fetchone()['id']
    yield nombre, concepto
    with cursor() as cur:
        cur.execute('DELETE FROM contabilidad_movimientos WHERE id = %s', (mid,))
        cur.execute('DELETE FROM crm_contactos WHERE id = %s', (cid,))


def test_proveedores_trae_contactos_y_pagos(flask_app, proveedor):
    nombre, concepto = proveedor
    with flask_app.app_context():
        datos = tools.ejecutar('proveedores', {'periodo': 'mes', 'limite': 30},
                               Contexto(rol_id=2, canal='web'))
    assert nombre in [p['nombre'] for p in datos['proveedores']]
    assert concepto in [p['concepto'] for p in datos['ultimos_pagos']]
    assert datos['pagos'] >= 1


def test_la_pregunta_va_directo_a_la_herramienta(flask_app):
    from services.ia.enrutador import enrutar_panel_seguro
    with flask_app.app_context():
        disponibles = tools.permitidas(Contexto(rol_id=2, canal='web'))
    assert enrutar_panel_seguro('¿Quiénes son mis proveedores?', disponibles) == [
        ('proveedores', {'periodo': 'todo'})]


@pytest.mark.parametrize('rol, la_ve', [(1, True), (2, True), (5, True), (4, False)])
def test_quien_ve_los_proveedores(flask_app, rol, la_ve):
    """Dueño, administrador y contador sí; el empleado no (son pagos del negocio)."""
    with flask_app.app_context():
        codes = [h.code for h in tools.permitidas(Contexto(rol_id=rol, canal='web'))]
    assert ('proveedores' in codes) is la_ve


# ── Sin herramienta: al dueño nunca «es un dato sensible» ──────
def _plan_sin_herramienta(flask_app, monkeypatch, rol):
    monkeypatch.setattr(ai, '_contexto_panel', lambda: 'ASESOR')
    monkeypatch.setattr(ai, '_modelo_en_memoria', lambda m: True)
    monkeypatch.setattr(ai, '_chat', lambda *a, **k: ('{"tools":[]}', None))
    with flask_app.app_context():
        plan, err = ai._plan_chat('¿Cuál es el clima en Bogotá?', contexto=Contexto(rol_id=rol, canal='web'))
    assert err is None and plan['herramientas'] == []
    return plan['user']


def test_al_dueno_se_le_dice_que_no_esta_conectado(flask_app, monkeypatch):
    user = _plan_sin_herramienta(flask_app, monkeypatch, 2)
    assert 'todavía no está conectado' in user
    assert 'sin llamarlo sensible ni privado' in user
    assert 'si es un dato sensible niégate' not in user
    assert 'amable dueño' in user                     # como fórmula prohibida, no como saludo


def test_a_otro_cargo_se_le_menciona_el_permiso(flask_app, monkeypatch):
    user = _plan_sin_herramienta(flask_app, monkeypatch, 4)
    assert 'no tenga permiso' in user and 'administrador' in user
