# -*- coding: utf-8 -*-
"""Fase 3 de las acciones del panel: tareas, actividades y oportunidades del CRM.
Contra la base de pruebas con un contacto de nombre inventado que se borra al
final (con sus tareas, actividades y oportunidades). Nunca se llama a un modelo."""
import inspect
import uuid
from datetime import date, timedelta

import pytest

from services import ia_acciones as acciones
from services import ia_acciones_crm as crm

MARCA = uuid.uuid4().hex[:6]


@pytest.fixture()
def contacto(cursor):
    with cursor() as cur:
        cur.execute("""INSERT INTO crm_contactos (tipo, nombre, activo, notas)
                       VALUES ('cliente', 'Zyxcomercial Andes', TRUE, %s) RETURNING id""",
                    (f'pytest {MARCA}',))
        cid = cur.fetchone()['id']
    yield cid
    with cursor() as cur:
        for tabla in ('crm_tareas', 'crm_actividades', 'crm_oportunidades'):
            cur.execute(f'DELETE FROM {tabla} WHERE contacto_id = %s', (cid,))
        cur.execute('DELETE FROM crm_contactos WHERE id = %s', (cid,))


def _ciclo(cursor, plan):
    with cursor() as cur:
        payload, resumen, detalles = acciones._preparar_datos(cur, plan)
    with cursor() as cur:
        resultado = acciones._ejecutar(cur, {'tipo': plan['tipo'], 'payload': payload}, 1)
    return resumen, detalles, resultado


# ── Fechas y listas cerradas desde las palabras ────────────────
@pytest.mark.parametrize('expresion, esperado', [
    ('mañana', date(2026, 9, 30) + timedelta(days=1)),
    ('pasado mañana', date(2026, 10, 2)),
    ('el viernes', date(2026, 10, 2)),       # 30-sep-2026 es miércoles
    ('en 5 días', date(2026, 10, 5)),
    ('15 de octubre', date(2026, 10, 15)),
    ('2026-11-03', date(2026, 11, 3)),
    ('5 de enero', date(2027, 1, 5)),         # ya pasó este año: el siguiente
    ('algún día', None),
])
def test_fechas_dichas(expresion, esperado):
    assert crm.fecha_de(expresion, hoy=date(2026, 9, 30)) == esperado


def test_listas_cerradas_salen_de_las_palabras():
    assert crm.prioridad_de('Llama a Juan, es urgente') == 'alta'
    assert crm.prioridad_de('Llama a Juan') is None
    assert crm.tipo_actividad_de('Registra que llamé a Ana') == 'llamada'
    assert crm.tipo_actividad_de('Anota que visité a Andes') == 'visita'
    assert crm.etapa_de('Ganamos el negocio con Andes') == 'ganada'
    assert crm.etapa_de('Pasa la oportunidad a negociación') == 'negociacion'
    plan = acciones._completar_identidad(
        {'tipo': 'registrar_actividad', 'contacto': 'Andes', 'tipo_actividad': 'reunion',
         'asunto': 'precios'}, 'registrar_actividad', 'Registra con Andes: acordamos precios')
    assert plan['tipo_actividad'] == 'otro', 'sin palabra clave no se inventa el tipo'


# ── Tareas ─────────────────────────────────────────────────────
def test_crear_completar_y_reabrir_tarea(contacto, cursor):
    resumen, detalles, r = _ciclo(cursor, {
        'tipo': 'crear_tarea', 'contacto': 'Zyxcomercial Andes', 'titulo': 'Enviar pedido',
        'prioridad': 'alta', 'fecha': '15 de octubre'})
    assert 'Prioridad: alta' in detalles and crm.SIN_AVISOS in detalles
    _ciclo(cursor, {'tipo': 'completar_tarea', 'tarea': 'enviar pedido Zyxcomercial'})
    with cursor() as cur:
        cur.execute('SELECT estado, completada_en FROM crm_tareas WHERE id = %s', (r['tarea_id'],))
        fila = cur.fetchone()
        assert fila['estado'] == 'completada' and fila['completada_en'] is not None
    _ciclo(cursor, {'tipo': 'reabrir_tarea', 'tarea_id': r['tarea_id']})
    with cursor() as cur:
        cur.execute('SELECT estado, completada_en FROM crm_tareas WHERE id = %s', (r['tarea_id'],))
        assert dict(cur.fetchone()) == {'estado': 'pendiente', 'completada_en': None}


def test_aplazar_tarea(contacto, cursor):
    _, _, r = _ciclo(cursor, {'tipo': 'crear_tarea', 'contacto_id': contacto,
                              'titulo': 'Cobrar factura Zyx'})
    _, detalles, _ = _ciclo(cursor, {'tipo': 'editar_tarea', 'tarea_id': r['tarea_id'],
                                     'cambios': {'fecha': '2026-12-01'}})
    assert 'Vence: (sin fecha) → 2026-12-01' in detalles


def test_fecha_que_no_se_entiende_se_pregunta(contacto, cursor):
    with cursor() as cur, pytest.raises(acciones.AccionAclarar, match='No entendí la fecha'):
        acciones._preparar_datos(cur, {'tipo': 'crear_tarea', 'contacto_id': contacto,
                                       'titulo': 'Llamar', 'fecha': 'algún día'})


# ── Actividades y oportunidades ────────────────────────────────
def test_registrar_actividad(contacto, cursor):
    _, _, r = _ciclo(cursor, {'tipo': 'registrar_actividad', 'contacto_id': contacto,
                              'tipo_actividad': 'llamada', 'asunto': 'Pidió cotización'})
    with cursor() as cur:
        cur.execute('SELECT tipo, asunto FROM crm_actividades WHERE id = %s', (r['actividad_id'],))
        assert dict(cur.fetchone()) == {'tipo': 'llamada', 'asunto': 'Pidió cotización'}


def test_oportunidad_crear_mover_y_ganar(contacto, cursor):
    _, detalles, r = _ciclo(cursor, {'tipo': 'crear_oportunidad', 'contacto_id': contacto,
                                     'titulo': 'Dotar oficina', 'monto': 5000000})
    assert 'Etapa: Prospecto (probabilidad 50 %)' in detalles
    _ciclo(cursor, {'tipo': 'mover_oportunidad', 'oportunidad': 'dotar oficina zyxcomercial',
                    'etapa': 'negociacion'})
    _, detalles, _ = _ciclo(cursor, {'tipo': 'mover_oportunidad', 'oportunidad_id': r['oportunidad_id'],
                                     'etapa': 'ganada'})
    assert 'Etapa: Negociación → Ganada' in detalles
    with cursor() as cur:
        cur.execute('SELECT etapa, probabilidad, fecha_cierre_real FROM crm_oportunidades '
                    'WHERE id = %s', (r['oportunidad_id'],))
        fila = cur.fetchone()
        assert fila['etapa'] == 'ganada' and fila['probabilidad'] == 100
        assert fila['fecha_cierre_real'] is not None
        with pytest.raises(acciones.AccionError, match='ya está en Ganada'):
            acciones._preparar_datos(cur, {'tipo': 'mover_oportunidad',
                                           'oportunidad_id': r['oportunidad_id'], 'etapa': 'ganada'})


def test_mover_rechaza_si_cambio_desde_la_vista_previa(contacto, cursor):
    _, _, r = _ciclo(cursor, {'tipo': 'crear_oportunidad', 'contacto_id': contacto,
                              'titulo': 'Mantenimiento'})
    with cursor() as cur:
        payload, _, _ = acciones._preparar_datos(cur, {'tipo': 'mover_oportunidad',
                                                       'oportunidad_id': r['oportunidad_id'],
                                                       'etapa': 'perdida'})
        cur.execute("UPDATE crm_oportunidades SET etapa = 'propuesta' WHERE id = %s",
                    (r['oportunidad_id'],))
    with cursor() as cur, pytest.raises(acciones.AccionError, match='cambió'):
        acciones._ejecutar(cur, {'tipo': 'mover_oportunidad', 'payload': payload}, 1)


def test_contacto_mencionado_en_la_frase(contacto, cursor):
    from services.ia.buscador import contacto_mencionado
    with cursor() as cur:
        assert contacto_mencionado(cur, 'Anota que visité a Zyxcomercial Andes ayer')['id'] == contacto
        assert contacto_mencionado(cur, 'anota que visite a zyxcomercial andes') is not None
        assert contacto_mencionado(cur, 'Anota que visité a Zyxcomercial') is None


def test_actividad_se_arma_desde_la_frase_si_el_modelo_pregunta_el_contacto(contacto):
    frase = 'Anota que visité a Zyxcomercial Andes y quedaron de pagar el viernes'
    plan = acciones._completar_crm({'tipo': 'aclarar', 'campo': 'contacto'},
                                   'registrar_actividad', frase)
    assert plan == {'tipo': 'registrar_actividad', 'contacto': 'Zyxcomercial Andes',
                    'asunto': 'Quedaron de pagar el viernes', 'tipo_actividad': 'visita'}


def test_sin_asunto_se_reinterpreta_con_el_id(contacto):
    plan = acciones._completar_crm({'tipo': 'aclarar', 'campo': 'contacto'},
                                   'registrar_actividad', 'Anota que visité a Zyxcomercial Andes')
    assert plan['tipo'] == 'reinterpretar' and f'ID {contacto}' in plan['orden']
    # Ya con el ID elegido, si el modelo vuelve a preguntar, se pregunta (no hay bucle).
    otra = acciones._completar_crm({'tipo': 'aclarar', 'campo': 'contacto'},
                                   'registrar_actividad', plan['orden'])
    assert otra['tipo'] == 'aclarar'


def test_el_crm_nunca_borra():
    assert 'DELETE' not in inspect.getsource(crm).upper()


# ── Datos dichos y detección ───────────────────────────────────
@pytest.mark.parametrize('plan, frase, pregunta', [
    ({'tipo': 'crear_tarea', 'contacto': 'Juan', 'titulo': 'Enviar la factura electrónica'},
     'Recuérdame llamar a Juan', 'Qué hay que hacer'),
    ({'tipo': 'crear_tarea', 'contacto': 'Juan', 'titulo': 'Llamar a Juan', 'fecha': 'el lunes'},
     'Recuérdame llamar a Juan mañana', 'Para qué fecha'),
    ({'tipo': 'crear_oportunidad', 'contacto': 'Andes', 'titulo': 'Dotar oficina', 'monto': 9000000},
     'Crea una oportunidad con Andes por 5 millones para dotar su oficina', 'Por cuánto'),
    ({'tipo': 'mover_oportunidad', 'oportunidad': 'Andes', 'etapa': 'ganada'},
     'Mueve la oportunidad de Andes', 'A qué etapa'),
    ({'tipo': 'crear_tarea', 'contacto': 'Beatriz', 'titulo': 'Llamar'},
     'Recuérdame llamar a Juan', 'Con qué contacto'),
])
def test_lo_no_dicho_se_pregunta(plan, frase, pregunta):
    with pytest.raises(acciones.AccionAclarar, match=pregunta):
        acciones._solo_datos_dichos(plan, frase, None)


def test_titulo_redactado_con_palabras_dichas_pasa():
    acciones._solo_datos_dichos({'tipo': 'crear_tarea', 'contacto': 'Juan Pérez',
                                 'titulo': 'Llamar a Juan Pérez para cobrar', 'fecha': 'mañana'},
                                'Recuérdame llamar a Juan Pérez mañana para cobrar', None)


@pytest.mark.parametrize('frase, tipo', [
    ('Recuérdame llamar a Juan Pérez mañana', 'crear_tarea'),
    ('Crea una tarea para revisar el stock', 'crear_tarea'),
    ('Marca como hecha la tarea de llamar a Juan', 'completar_tarea'),
    ('Reabre la tarea enviar pedido', 'reabrir_tarea'),
    ('Aplaza la tarea enviar pedido al lunes', 'editar_tarea'),
    ('Registra una llamada con Juan Pérez: pidió cotización', 'registrar_actividad'),
    ('Anota que visité a la Distribuidora Andes', 'registrar_actividad'),
    ('Crea una oportunidad con Andes por 5 millones', 'crear_oportunidad'),
    ('Ganamos el negocio con Andes', 'mover_oportunidad'),
    ('Pasa la oportunidad de Andes a negociación', 'mover_oportunidad'),
    ('Cambia el monto de la oportunidad de Andes a 6 millones', 'editar_oportunidad'),
])
def test_cada_orden_del_crm_va_a_su_proceso(frase, tipo):
    assert acciones.parece_operativa(frase) and acciones._tipo_solicitado(frase) == tipo


def test_preguntar_por_las_tareas_no_es_una_orden():
    assert not acciones.parece_operativa('¿Qué tareas tengo hoy?')
