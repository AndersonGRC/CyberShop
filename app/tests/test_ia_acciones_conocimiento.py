# -*- coding: utf-8 -*-
"""Acciones del asistente sobre la base de conocimiento: preguntas frecuentes
por chat, con vista previa, confirmación y bitácora.

«Agrega a las preguntas frecuentes: ¿Abren los domingos? Sí, de 9 a 2» →
propuesta → confirmar → la FAQ queda publicada, en el índice del chat y en el
historial con origen «asistente». Nunca se llama a un modelo: el texto es
público y se toma literal de lo que escribió la persona.
"""
import inspect
import uuid

import pytest

from services import ia_acciones as acciones
from services import ia_acciones_conocimiento as kb

MARCA = 'Qkb' + uuid.uuid4().hex[:5]


@pytest.fixture()
def limpio(cursor, flask_app):
    yield
    with cursor() as cur:
        cur.execute("DELETE FROM public_site_items WHERE item_type = 'faq' AND title LIKE %s",
                    (f'%{MARCA}%',))
        cur.execute("SELECT to_regclass('public.ia_conocimiento_log') AS t")
        if cur.fetchone()['t'] is not None:
            cur.execute('DELETE FROM ia_conocimiento_log WHERE titulo LIKE %s', (f'%{MARCA}%',))
    with flask_app.app_context():
        from services.ia_rag.indexador import reindexar_uno
        reindexar_uno('faq', None)


def _ciclo(cursor, plan):
    with cursor() as cur:
        payload, resumen, detalles = acciones._preparar_datos(cur, plan)
    with cursor() as cur:
        resultado = acciones._ejecutar(cur, {'tipo': plan['tipo'], 'payload': payload}, 1)
    return resumen, detalles, resultado


def _faq(cursor, faq_id):
    with cursor() as cur:
        cur.execute("SELECT * FROM public_site_items WHERE id = %s", (faq_id,))
        return cur.fetchone()


def _bitacora(cursor, faq_id):
    with cursor() as cur:
        cur.execute("""SELECT accion, origen, antes, despues, usuario_id FROM ia_conocimiento_log
                       WHERE tipo = 'faq' AND objeto_id = %s ORDER BY id""", (str(faq_id),))
        return cur.fetchall()


# ── Qué orden es cada frase ──────────────────────────────────
@pytest.mark.parametrize('frase, tipo', [
    ('Agrega a las preguntas frecuentes: ¿Abren los domingos? Sí, de 9 a 2', 'crear_faq'),
    ('Por favor crea una pregunta frecuente «¿Hacen envíos?» «Sí, a todo el país»', 'crear_faq'),
    ('Cambia la pregunta frecuente de domicilios: Sí, a toda Bogotá', 'editar_faq'),
    ('Corrige la FAQ 12: Abrimos de 8 a 6', 'editar_faq'),
    ('Elimina la pregunta frecuente de parqueadero', 'archivar_faq'),
    ('Quita de las preguntas frecuentes la de horarios', 'archivar_faq'),
    ('Publica la pregunta frecuente de horarios', 'publicar_faq'),
    ('Crea una tarea para revisar las preguntas frecuentes', 'crear_tarea'),
    ('Aprueba la reseña de Ana sobre la torta', 'aprobar_resena'),
])
def test_cada_orden_va_a_su_proceso(frase, tipo):
    assert acciones.parece_operativa(frase)
    assert acciones._tipo_solicitado(frase) == tipo


@pytest.mark.parametrize('frase', ['¿Cómo agrego una pregunta frecuente?',
                                   '¿Cuántas preguntas frecuentes tengo?',
                                   'Muéstrame las preguntas frecuentes'])
def test_preguntas_no_son_ordenes(frase):
    assert not acciones.parece_operativa(frase)


# ── El texto sale literal de la orden ────────────────────────
@pytest.mark.parametrize('orden, pregunta, respuesta', [
    ('Agrega a las preguntas frecuentes: ¿Abren los domingos? Sí, de 9 a 2.',
     '¿Abren los domingos?', 'Sí, de 9 a 2.'),
    ('Agrega una pregunta frecuente «¿Hacen envíos?» «Sí, a todo el país»',
     '¿Hacen envíos?', 'Sí, a todo el país'),
    ('Crea una pregunta frecuente: pregunta: ¿Tienen parqueadero? respuesta: No, pero hay uno cerca',
     '¿Tienen parqueadero?', 'No, pero hay uno cerca'),
])
def test_crear_toma_pregunta_y_respuesta_literales(orden, pregunta, respuesta):
    assert kb.plan(orden, 'crear_faq') == {'tipo': 'crear_faq', 'pregunta': pregunta,
                                           'respuesta': respuesta}


def test_si_falta_la_respuesta_la_pide_y_la_completa():
    orden = 'Agrega a las preguntas frecuentes: ¿Abren los festivos?'
    with pytest.raises(acciones.AccionAclarar, match='Qué respuesta'):
        kb.plan(orden, 'crear_faq')
    completa = acciones.combinar(orden, 'Sí, de 10 a 4')
    assert kb.plan(completa, 'crear_faq')['respuesta'] == 'Sí, de 10 a 4'
    with pytest.raises(acciones.AccionAclarar, match='pregunta y su respuesta'):
        kb.plan('Agrega una pregunta frecuente', 'crear_faq')


def test_editar_lee_cual_y_el_texto_nuevo():
    assert kb.plan('Cambia la pregunta frecuente de domicilios: Sí, a toda Bogotá', 'editar_faq') == \
        {'tipo': 'editar_faq', 'faq': 'de domicilios', 'respuesta': 'Sí, a toda Bogotá'}
    assert kb.plan('Corrige la FAQ 12: Abrimos de 8 a 6', 'editar_faq') == \
        {'tipo': 'editar_faq', 'faq_id': 12, 'respuesta': 'Abrimos de 8 a 6'}
    assert kb.plan('Elimina la pregunta frecuente de parqueadero. Dato adicional: ID 7',
                   'archivar_faq') == {'tipo': 'archivar_faq', 'faq_id': 7}


def test_no_usa_el_modelo(monkeypatch):
    import services.ai_service as ai

    def prohibido(*a, **k):
        raise AssertionError('las preguntas frecuentes no pasan por el modelo')
    monkeypatch.setattr(ai, '_chat', prohibido)
    plan = acciones._interpretar('Agrega a las preguntas frecuentes: ¿Abren los domingos? Sí')
    assert plan['pregunta'] == '¿Abren los domingos?'


def test_un_texto_que_no_dijo_la_persona_se_rechaza():
    with pytest.raises(acciones.AccionAclarar):
        acciones._solo_datos_dichos({'tipo': 'crear_faq', 'pregunta': '¿Abren?',
                                     'respuesta': 'Sí, todos los días de 7 a 10'},
                                    'Agrega a las preguntas frecuentes: ¿Abren? Sí', None)


# ── Ciclo completo contra la base de pruebas ─────────────────
def test_crear_publica_indexa_y_deja_bitacora(cursor, limpio):
    pregunta = f'¿{MARCA} hacen domicilios?'
    resumen, detalles, resultado = _ciclo(cursor, {'tipo': 'crear_faq', 'pregunta': pregunta,
                                                   'respuesta': 'Sí, en toda la ciudad.'})
    assert 'Agregar a las preguntas frecuentes' in resumen
    assert any('deshacer' in d for d in detalles)
    fila = _faq(cursor, resultado['faq_id'])
    assert fila['title'] == pregunta and fila['description'] == 'Sí, en toda la ciudad.'
    assert fila['is_active'] is True
    log = _bitacora(cursor, fila['id'])
    assert [(r['accion'], r['origen'], r['usuario_id']) for r in log] == [('crear', 'asistente', 1)]
    with cursor() as cur:
        cur.execute("SELECT to_regclass('public.ia_documentos') AS t")
        if cur.fetchone()['t'] is not None:
            cur.execute("SELECT canal_publico FROM ia_documentos WHERE fuente='faq' AND fuente_id=%s",
                        (str(fila['id']),))
            assert cur.fetchone()['canal_publico'] is True       # el chat ya la encuentra


def test_una_pregunta_repetida_no_se_crea_dos_veces(cursor, limpio):
    pregunta = f'¿{MARCA} tienen garantía?'
    _ciclo(cursor, {'tipo': 'crear_faq', 'pregunta': pregunta, 'respuesta': 'Seis meses.'})
    with pytest.raises(acciones.AccionError, match='Ya existe'):
        with cursor() as cur:
            acciones._preparar_datos(cur, {'tipo': 'crear_faq', 'pregunta': pregunta.upper(),
                                           'respuesta': 'Un año.'})


def test_editar_despublicar_y_publicar_con_su_antes(cursor, limpio):
    _r, _d, creada = _ciclo(cursor, {'tipo': 'crear_faq', 'pregunta': f'¿{MARCA} horario?',
                                     'respuesta': 'De 8 a 6.'})
    fid = creada['faq_id']
    _ciclo(cursor, {'tipo': 'editar_faq', 'faq': f'{MARCA} horario', 'respuesta': 'De 9 a 7.'})
    assert _faq(cursor, fid)['description'] == 'De 9 a 7.'
    _ciclo(cursor, {'tipo': 'archivar_faq', 'faq_id': fid})
    assert _faq(cursor, fid)['is_active'] is False                # no se borra
    _ciclo(cursor, {'tipo': 'publicar_faq', 'faq_id': fid})
    assert _faq(cursor, fid)['is_active'] is True
    log = _bitacora(cursor, fid)
    assert [r['accion'] for r in log] == ['crear', 'editar', 'despublicar', 'publicar']
    assert log[1]['antes']['description'] == 'De 8 a 6.'
    assert log[1]['despues']['description'] == 'De 9 a 7.'


def test_si_cambio_desde_la_vista_previa_no_se_aplica(cursor, limpio):
    _r, _d, creada = _ciclo(cursor, {'tipo': 'crear_faq', 'pregunta': f'¿{MARCA} pagos?',
                                     'respuesta': 'Efectivo.'})
    with cursor() as cur:
        payload, _res, _det = acciones._preparar_datos(
            cur, {'tipo': 'editar_faq', 'faq_id': creada['faq_id'], 'respuesta': 'Tarjeta.'})
    with cursor() as cur:
        cur.execute("UPDATE public_site_items SET description = 'Nequi.' WHERE id = %s",
                    (creada['faq_id'],))
    with pytest.raises(acciones.AccionError, match='cambió'):
        with cursor() as cur:
            acciones._ejecutar(cur, {'tipo': 'editar_faq', 'payload': payload}, 1)
    assert _faq(cursor, creada['faq_id'])['description'] == 'Nequi.'


def test_lo_hecho_por_el_asistente_se_deshace_desde_el_historial(cursor, limpio, flask_app):
    from services.ia_rag import conocimiento
    _r, _d, creada = _ciclo(cursor, {'tipo': 'crear_faq', 'pregunta': f'¿{MARCA} envíos?',
                                     'respuesta': 'Gratis.'})
    _ciclo(cursor, {'tipo': 'editar_faq', 'faq_id': creada['faq_id'], 'respuesta': 'Cuestan $5.000.'})
    edicion = [r for r in _bitacora(cursor, creada['faq_id']) if r['accion'] == 'editar']
    with cursor() as cur:
        cur.execute("""SELECT id FROM ia_conocimiento_log WHERE tipo='faq' AND objeto_id=%s
                       AND accion='editar'""", (str(creada['faq_id']),))
        log_id = cur.fetchone()['id']
    assert edicion
    with flask_app.test_request_context():
        ok, _msg, _tipo, _id = conocimiento.restaurar(log_id)
    assert ok and _faq(cursor, creada['faq_id'])['description'] == 'Gratis.'


def test_nunca_borra_preguntas_frecuentes():
    fuente = inspect.getsource(kb).upper()
    assert 'DELETE FROM PUBLIC_SITE_ITEMS' not in fuente


def test_permisos():
    assert acciones.TIPOS['crear_faq'] == ('content', 'operar')
    assert acciones.TIPOS['archivar_faq'] == ('content', 'eliminar')
