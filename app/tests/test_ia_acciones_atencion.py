# -*- coding: utf-8 -*-
"""Fase 4 de las acciones del panel: reseñas (aprobar, responder) y tickets de
soporte (cerrar, reabrir). Contra la base de pruebas con registros de nombre
inventado que se borran al final. Nunca se llama a un modelo."""
import inspect
import uuid

import pytest

from services import ia_acciones as acciones
from services import ia_acciones_atencion as atencion

MARCA = 'Zyx' + uuid.uuid4().hex[:5]


@pytest.fixture()
def resenas(cursor):
    with cursor() as cur:
        cur.execute('SELECT id FROM productos ORDER BY id LIMIT 1')
        producto = cur.fetchone()
        if not producto:
            pytest.skip('La base de pruebas no tiene productos')
        ids = {}
        for autor, aprobado in ((f'{MARCA} Ana', False), (f'{MARCA} Beto', True)):
            cur.execute("""INSERT INTO producto_comentarios
                               (producto_id, autor_nombre, calificacion, comentario, aprobado)
                           VALUES (%s, %s, 4, 'Muy rica la torta', %s) RETURNING id""",
                        (producto['id'], autor, aprobado))
            ids[autor.split()[-1]] = cur.fetchone()['id']
    yield ids
    with cursor() as cur:
        cur.execute('DELETE FROM producto_comentarios WHERE autor_nombre LIKE %s', (f'{MARCA}%',))


@pytest.fixture()
def tickets(cursor):
    with cursor() as cur:
        cur.execute('SELECT id FROM usuarios ORDER BY id LIMIT 1')
        usuario = cur.fetchone()
        if not usuario:
            pytest.skip('La base de pruebas no tiene usuarios')
        ids = {}
        for asunto, estado in ((f'{MARCA} garantia cargador', 'abierto'),
                               (f'{MARCA} factura duplicada', 'cerrado')):
            cur.execute("""INSERT INTO tickets_soporte (usuario_id, asunto, mensaje, estado)
                           VALUES (%s, %s, 'Detalle', %s) RETURNING id""",
                        (usuario['id'], asunto, estado))
            ids[estado] = cur.fetchone()['id']
    yield ids
    with cursor() as cur:
        cur.execute('DELETE FROM tickets_soporte WHERE asunto LIKE %s', (f'{MARCA}%',))


def _ciclo(cursor, plan):
    with cursor() as cur:
        payload, resumen, detalles = acciones._preparar_datos(cur, plan)
    with cursor() as cur:
        resultado = acciones._ejecutar(cur, {'tipo': plan['tipo'], 'payload': payload}, 1)
    return resumen, detalles, resultado


# ── Reseñas ────────────────────────────────────────────────────
def test_aprobar_resena_por_autor(resenas, cursor):
    resumen, detalles, r = _ciclo(cursor, {'tipo': 'aprobar_resena', 'resena': f'{MARCA} Ana'})
    assert r['resena_id'] == resenas['Ana'] and 'Aprobar la reseña' in resumen
    assert 'Comentario: «Muy rica la torta»' in detalles
    with cursor() as cur:
        cur.execute('SELECT aprobado FROM producto_comentarios WHERE id = %s', (resenas['Ana'],))
        assert cur.fetchone()['aprobado'] is True


def test_aprobar_una_ya_aprobada_se_rechaza(resenas, cursor):
    with cursor() as cur, pytest.raises(acciones.AccionError, match='ya está aprobada'):
        acciones._preparar_datos(cur, {'tipo': 'aprobar_resena', 'resena_id': resenas['Beto']})


def test_responder_resena_publica_el_texto_literal(resenas, cursor):
    _, detalles, _ = _ciclo(cursor, {'tipo': 'responder_resena', 'resena_id': resenas['Beto'],
                                     'respuesta': '¡Gracias por tu compra!'})
    assert 'Respuesta que se publicará: «¡Gracias por tu compra!»' in detalles
    with cursor() as cur:
        cur.execute('SELECT respuesta, respuesta_fecha FROM producto_comentarios WHERE id = %s',
                    (resenas['Beto'],))
        fila = cur.fetchone()
        assert fila['respuesta'] == '¡Gracias por tu compra!' and fila['respuesta_fecha']
    with cursor() as cur:
        _, _, detalles = acciones._preparar_datos(cur, {'tipo': 'responder_resena',
                                                        'resena_id': resenas['Beto'],
                                                        'respuesta': 'Te esperamos'})
        assert any(d.startswith('Reemplaza la respuesta actual') for d in detalles)


def test_responder_rechaza_si_cambio_desde_la_vista_previa(resenas, cursor):
    with cursor() as cur:
        payload, _, _ = acciones._preparar_datos(cur, {'tipo': 'responder_resena',
                                                       'resena_id': resenas['Ana'],
                                                       'respuesta': 'Gracias'})
        cur.execute("UPDATE producto_comentarios SET respuesta = 'Otra' WHERE id = %s",
                    (resenas['Ana'],))
    with cursor() as cur, pytest.raises(acciones.AccionError, match='cambió'):
        acciones._ejecutar(cur, {'tipo': 'responder_resena', 'payload': payload}, 1)


def test_sin_decir_cual_muestra_las_pendientes(resenas, cursor):
    with cursor() as cur:
        cur.execute("""INSERT INTO producto_comentarios
                           (producto_id, autor_nombre, calificacion, comentario, aprobado)
                       SELECT producto_id, %s, 2, 'Llegó fría', FALSE
                       FROM producto_comentarios WHERE id = %s""", (f'{MARCA} Caro', resenas['Ana']))
    with cursor() as cur, pytest.raises(acciones.AccionAclarar, match=f'ID {resenas["Ana"]} · {MARCA} Ana'):
        acciones._preparar_datos(cur, {'tipo': 'aprobar_resena', 'resena': MARCA})


# ── Tickets ────────────────────────────────────────────────────
def test_cerrar_y_reabrir_ticket(tickets, cursor):
    resumen, detalles, r = _ciclo(cursor, {'tipo': 'cerrar_ticket', 'ticket': f'{MARCA} garantia'})
    assert r['ticket_id'] == tickets['abierto'] and atencion.SIN_CORREO in detalles
    assert 'Estado: abierto → cerrado' in detalles
    _ciclo(cursor, {'tipo': 'reabrir_ticket', 'ticket_id': tickets['abierto']})
    with cursor() as cur:
        cur.execute('SELECT estado FROM tickets_soporte WHERE id = %s', (tickets['abierto'],))
        assert cur.fetchone()['estado'] == 'abierto'


def test_cerrar_uno_cerrado_se_rechaza(tickets, cursor):
    with cursor() as cur, pytest.raises(acciones.AccionError, match='ya está cerrado'):
        acciones._preparar_datos(cur, {'tipo': 'cerrar_ticket', 'ticket_id': tickets['cerrado']})


def test_atencion_nunca_borra_ni_envia_correos():
    fuente = inspect.getsource(atencion).upper()
    assert 'DELETE' not in fuente
    assert 'ENVIAR_EMAIL' not in fuente and 'GMAIL' not in fuente


# ── Detección, texto literal y datos dichos ────────────────────
@pytest.mark.parametrize('frase, tipo', [
    ('Aprueba la reseña de Ana sobre la torta', 'aprobar_resena'),
    ('Publica la reseña 4', 'aprobar_resena'),
    ('Responde la reseña de Ana: ¡Gracias, ya llegaron 10 unidades!', 'responder_resena'),
    ('Cierra el ticket 12', 'cerrar_ticket'),
    ('Por favor cierra el ticket de garantía', 'cerrar_ticket'),
    ('Reabre el ticket de Juan', 'reabrir_ticket'),
    ('Crea una tarea para responder la reseña de Ana', 'crear_tarea'),
])
def test_cada_orden_va_a_su_proceso(frase, tipo):
    assert acciones.parece_operativa(frase) and acciones._tipo_solicitado(frase) == tipo


@pytest.mark.parametrize('frase', ['¿Cómo respondo una reseña?', 'Responde a mi pregunta sobre productos',
                                   '¿Cuántos tickets abiertos tengo?'])
def test_preguntas_no_son_ordenes(frase):
    assert not acciones.parece_operativa(frase)


def test_la_respuesta_sale_literal_de_lo_escrito():
    assert acciones.respuesta_dicha('Responde la reseña de Ana: ¡Gracias!') == '¡Gracias!'
    assert acciones.respuesta_dicha('Responde la reseña de Ana diciendo «Mil gracias»') == 'Mil gracias'
    assert acciones.respuesta_dicha('Responde la reseña de Ana. Dato adicional: ID 3. '
                                    'Dato adicional: Gracias por venir') == 'Gracias por venir'
    assert acciones.respuesta_dicha('Responde la reseña de Ana') is None
    with pytest.raises(acciones.AccionError, match='muy larga'):
        acciones.respuesta_dicha('Responde la reseña de Ana. Dato adicional: ' + 'x' * 280)


def test_el_modelo_no_redacta_la_respuesta():
    plan = acciones._completar_identidad(
        {'tipo': 'responder_resena', 'resena': 'Ana', 'respuesta': 'Gracias por tu opinión, Ana'},
        'responder_resena', 'Responde la reseña de Ana')
    with pytest.raises(acciones.AccionAclarar, match='Qué respuesta publico'):
        acciones._solo_datos_dichos(plan, 'Responde la reseña de Ana', None)


def test_identidad_desde_la_frase_si_el_modelo_pregunta():
    assert acciones._completar_identidad({'tipo': 'aclarar', 'campo': 'ticket'}, 'cerrar_ticket',
                                         'Cierra el ticket 12') == {'tipo': 'cerrar_ticket', 'ticket_id': 12}
    plan = acciones._completar_identidad({'tipo': 'aclarar', 'campo': 'resena'}, 'aprobar_resena',
                                         'Aprueba la reseña')
    assert plan == {'tipo': 'aprobar_resena', 'resena': ''}
    elegido = acciones._completar_identidad({'tipo': 'aprobar_resena', 'resena': 'Ana'}, 'aprobar_resena',
                                            'Aprueba la reseña de Ana. Dato adicional: ID 7')
    assert elegido == {'tipo': 'aprobar_resena', 'resena_id': 7}


def test_referencia_inventada_se_pregunta():
    with pytest.raises(acciones.AccionAclarar, match='Qué ticket cierro'):
        acciones._solo_datos_dichos({'tipo': 'cerrar_ticket', 'ticket': 'Pedro reembolso'},
                                    'Cierra el ticket de garantía', None)
    with pytest.raises(acciones.AccionAclarar, match='Qué reseña apruebo'):
        acciones._solo_datos_dichos({'tipo': 'aprobar_resena', 'resena_id': 9},
                                    'Aprueba la reseña de Ana', None)


def test_permisos_y_modulos():
    assert acciones.TIPOS['aprobar_resena'] == ('content', 'operar')
    assert acciones.TIPOS['cerrar_ticket'] == ('support', 'operar')
