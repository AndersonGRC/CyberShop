# -*- coding: utf-8 -*-
"""Base de conocimiento de la IA: bitácora, restaurar y preguntas pendientes.

Antes: borrar una pregunta frecuente la perdía para siempre, editar un
documento interno pisaba el texto anterior y nadie quedaba registrado. Ahora
cada cambio deja una foto de antes y después en ia_conocimiento_log y se puede
deshacer desde /admin/chat-publico/conocimiento.
"""
import pytest

from database import get_db_cursor

MARCA = 'TEST-KB'


def _faq(titulo):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM public_site_items WHERE item_type='faq' AND title=%s "
                    "ORDER BY id DESC LIMIT 1", (titulo,))
        return cur.fetchone()


def _log(tipo=None, titulo_like=f'{MARCA}%'):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT to_regclass('public.ia_conocimiento_log') AS t")
        if cur.fetchone()['t'] is None:
            return []
        cur.execute("""SELECT * FROM ia_conocimiento_log WHERE titulo LIKE %s
                       AND (%s IS NULL OR tipo = %s) ORDER BY id""",
                    (titulo_like, tipo, tipo))
        return cur.fetchall()


@pytest.fixture()
def limpiar(flask_app):
    yield
    with flask_app.app_context():
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM public_site_items WHERE item_type='faq' AND title LIKE %s",
                        (f'{MARCA}%',))
            cur.execute("SELECT to_regclass('public.ia_conocimiento_log') AS t")
            if cur.fetchone()[0] is not None:
                cur.execute('DELETE FROM ia_conocimiento_log WHERE titulo LIKE %s', (f'{MARCA}%',))
            cur.execute("SELECT to_regclass('public.ia_consultas') AS t")
            if cur.fetchone()[0] is not None:
                cur.execute('DELETE FROM ia_consultas WHERE pregunta_sin_herramienta LIKE %s',
                            (f'{MARCA}%',))
            cur.execute("SELECT to_regclass('public.ia_documentos_internos') AS t")
            if cur.fetchone()[0] is not None:
                cur.execute('DELETE FROM ia_documentos_internos WHERE titulo LIKE %s', (f'{MARCA}%',))
        from services.ia_rag.indexador import reindexar_uno
        reindexar_uno('faq', None)


def _crear(client, titulo, respuesta='Respuesta de prueba', **extra):
    datos = {'title': titulo, 'description': respuesta, 'sort_order': '5', 'is_active': 'on'}
    datos.update(extra)
    return client.post('/admin/chat-publico/faq/crear', data=datos)


# ── Bitácora de preguntas frecuentes ──────────────────────────

def test_cada_cambio_de_una_faq_queda_con_quien_y_el_antes(as_propietario, limpiar):
    _crear(as_propietario, f'{MARCA} horario', 'Abrimos de 8 a 6.')
    faq = _faq(f'{MARCA} horario')
    as_propietario.post(f"/admin/chat-publico/faq/editar/{faq['id']}",
                        data={'title': f'{MARCA} horario', 'description': 'Abrimos de 9 a 7.',
                              'sort_order': '5', 'is_active': 'on'})
    as_propietario.post(f"/admin/chat-publico/faq/toggle/{faq['id']}")
    as_propietario.post(f"/admin/chat-publico/faq/eliminar/{faq['id']}")
    assert _faq(f'{MARCA} horario') is None

    log = _log('faq')
    assert [r['accion'] for r in log] == ['crear', 'editar', 'despublicar', 'eliminar']
    assert all(r['usuario_nombre'] == 'PytestUser' and r['usuario_id'] == 1 for r in log)
    assert log[0]['antes'] is None and log[0]['despues']['description'] == 'Abrimos de 8 a 6.'
    assert log[1]['antes']['description'] == 'Abrimos de 8 a 6.'
    assert log[1]['despues']['description'] == 'Abrimos de 9 a 7.'
    assert log[3]['antes']['title'] == f'{MARCA} horario' and log[3]['despues'] is None


def test_una_faq_borrada_se_restaura_desde_el_historial(as_propietario, limpiar):
    _crear(as_propietario, f'{MARCA} envios', 'Enviamos a todo el país.')
    faq = _faq(f'{MARCA} envios')
    as_propietario.post(f"/admin/chat-publico/faq/eliminar/{faq['id']}")
    borrado = [r for r in _log('faq') if r['accion'] == 'eliminar'][-1]

    r = as_propietario.post(f"/admin/chat-publico/conocimiento/restaurar/{borrado['id']}")
    assert r.status_code == 302
    vuelta = _faq(f'{MARCA} envios')
    assert vuelta is not None
    assert vuelta['description'] == 'Enviamos a todo el país.' and vuelta['is_active'] is True
    assert _log('faq')[-1]['accion'] == 'restaurar'
    assert _log('faq')[-1]['origen'] == 'historial'
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT to_regclass('public.ia_documentos') AS t")
        if cur.fetchone()['t'] is not None:
            cur.execute("SELECT canal_publico FROM ia_documentos WHERE fuente='faq' AND fuente_id=%s",
                        (str(vuelta['id']),))
            fila = cur.fetchone()
            assert fila is not None and fila['canal_publico'] is True    # el chat ya la ve


def test_una_edicion_de_faq_se_deshace_en_la_misma_fila(as_propietario, limpiar):
    _crear(as_propietario, f'{MARCA} pagos', 'Efectivo y tarjeta.')
    faq = _faq(f'{MARCA} pagos')
    as_propietario.post(f"/admin/chat-publico/faq/editar/{faq['id']}",
                        data={'title': f'{MARCA} pagos', 'description': 'Solo efectivo.',
                              'sort_order': '5', 'is_active': 'on'})
    edicion = [r for r in _log('faq') if r['accion'] == 'editar'][-1]
    as_propietario.post(f"/admin/chat-publico/conocimiento/restaurar/{edicion['id']}")
    vuelta = _faq(f'{MARCA} pagos')
    assert vuelta['id'] == faq['id'] and vuelta['description'] == 'Efectivo y tarjeta.'


def test_crear_y_publicar_no_se_ofrecen_para_deshacer(as_propietario, limpiar):
    from services.ia_rag.conocimiento import puede_restaurar
    _crear(as_propietario, f'{MARCA} nada')
    creada = _log('faq')[-1]
    assert not puede_restaurar(creada)
    r = as_propietario.post(f"/admin/chat-publico/conocimiento/restaurar/{creada['id']}")
    assert r.status_code == 302 and len(_log('faq')) == 1


def test_sin_pregunta_o_respuesta_no_se_guarda(as_propietario, limpiar):
    _crear(as_propietario, f'{MARCA} vacia', '')
    assert _faq(f'{MARCA} vacia') is None and _log('faq') == []


def test_si_la_bitacora_falla_el_guardado_sigue(flask_app, monkeypatch, limpiar):
    from services.ia_rag import bitacora

    def falla(_cur):
        raise RuntimeError('sin tabla')
    monkeypatch.setattr(bitacora, 'asegurar_tabla', falla)
    with flask_app.test_request_context():
        assert bitacora.registrar('faq', 'crear', 1, f'{MARCA} x') is False


# ── Documentos internos: versiones ────────────────────────────

def test_editar_un_documento_guarda_la_version_anterior_y_se_restaura(flask_app, limpiar):
    from services.ia_rag import conocimiento, internos
    with flask_app.app_context():
        doc_id = internos.guardar(f'{MARCA} apertura', 'Abrir la reja a las 7.', 'equipo')
        internos.guardar(f'{MARCA} apertura', 'Abrir la reja a las 8.', 'equipo', doc_id=doc_id)
        internos.cambiar_estado(doc_id, False)
        log = _log('documento')
        assert [r['accion'] for r in log] == ['crear', 'editar', 'archivar']
        assert log[1]['antes']['texto'] == 'Abrir la reja a las 7.'

        ok, _msg, _tipo, _id = conocimiento.restaurar(log[1]['id'])
        assert ok and internos.obtener(doc_id)['texto'] == 'Abrir la reja a las 7.'
        ok, _msg, _tipo, _id = conocimiento.restaurar(log[2]['id'])
        assert ok and internos.obtener(doc_id)['activo'] is True


# ── Lo que el chat no supo responder ──────────────────────────

def _sin_respuesta(*preguntas):
    from services.ai_service import _DDL_IA_CONSULTAS
    with get_db_cursor() as cur:
        cur.execute(_DDL_IA_CONSULTAS)
        for p in preguntas:
            cur.execute("""INSERT INTO ia_consultas (canal, pregunta_sin_herramienta)
                           VALUES ('publico', %s)""", (p,))


def test_las_pendientes_se_agrupan_y_las_atendidas_desaparecen(as_propietario, flask_app, limpiar):
    from services.ia_rag.conocimiento import descartar_pregunta, preguntas_pendientes
    _sin_respuesta(f'{MARCA} ¿Hacen domicilios?', f'{MARCA} hacen domicilios',
                   f'{MARCA} ¿Tienen parqueadero?', f'{MARCA} ¿Venden al por mayor?')
    with flask_app.test_request_context():
        mias = [p for p in preguntas_pendientes(limite=100) if p['pregunta'].startswith(MARCA)]
    domicilios = [p for p in mias if 'domicilios' in p['pregunta'].lower()]
    assert len(domicilios) == 1 and domicilios[0]['veces'] == 2
    assert mias[0] is domicilios[0]                                # la más repetida primero

    with flask_app.test_request_context():
        descartar_pregunta(f'{MARCA} ¿Tienen parqueadero?')
    # Responder desde la pantalla: crea la FAQ y marca la pregunta atendida.
    _crear(as_propietario, f'{MARCA} ¿Venden al por mayor?', 'Sí, desde 12 unidades.',
           pregunta_origen=f'{MARCA} ¿Venden al por mayor?', volver='conocimiento')
    assert _faq(f'{MARCA} ¿Venden al por mayor?') is not None
    with flask_app.test_request_context():
        quedan = [p['pregunta'] for p in preguntas_pendientes(limite=100)
                  if p['pregunta'].startswith(MARCA)]
    assert quedan == [domicilios[0]['pregunta']]


def test_la_pantalla_reune_todo(as_propietario, limpiar):
    _sin_respuesta(f'{MARCA} ¿Abren los domingos?')
    _crear(as_propietario, f'{MARCA} garantia', 'Seis meses en todos los productos.')
    r = as_propietario.get('/admin/chat-publico/conocimiento')
    assert r.status_code == 200
    html = r.data.decode('utf-8')
    for texto in ('Base de conocimiento', 'Probar una pregunta', f'{MARCA} ¿Abren los domingos?',
                  f'{MARCA} garantia', 'Historial de cambios', 'PytestUser'):
        assert texto in html, texto
    r = as_propietario.get('/admin/chat-publico/conocimiento?probar=garantia de los productos')
    assert r.status_code == 200 and 'El chat del sitio encontraría' in r.data.decode('utf-8')


def test_un_empleado_no_ve_ni_restaura_documentos_internos(client, flask_app, limpiar):
    from services.ia_rag import internos
    with flask_app.app_context():
        doc_id = internos.guardar(f'{MARCA} secreto', 'Clave de la caja fuerte: no.', 'administracion')
        internos.guardar(f'{MARCA} secreto', 'Texto nuevo.', 'administracion', doc_id=doc_id)
    edicion = [r for r in _log('documento') if r['accion'] == 'editar'][-1]
    with client.session_transaction() as s:
        s['usuario_id'], s['rol_id'], s['username'] = 3, 4, 'Empleado'      # ROL_EMPLEADO
    html = client.get('/admin/chat-publico/conocimiento').data.decode('utf-8')
    assert f'{MARCA} secreto' not in html
    client.post(f"/admin/chat-publico/conocimiento/restaurar/{edicion['id']}")
    with flask_app.app_context():
        assert internos.obtener(doc_id)['texto'] == 'Texto nuevo.'


def test_la_tabla_del_codigo_es_la_de_la_migracion_del_maestro():
    import os
    import re
    from services.ia_rag import bitacora
    app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidatos = [os.path.join(app, *rel, 'CyberShopAdmin', 'migrations', 'tenant',
                               '0028_ia_conocimiento_log.sql') for rel in (('..', '..'), ('..',))]
    ruta = next((os.path.normpath(r) for r in candidatos if os.path.exists(os.path.normpath(r))), None)
    if ruta is None:
        pytest.skip('el repo del maestro no está al lado')
    with open(ruta, encoding='utf-8') as f:
        sql = re.sub(r'--[^\n]*', '', f.read())

    def normal(texto):
        return re.sub(r'\s+', ' ', texto).strip().rstrip(';').strip()
    assert normal(bitacora._DDL) == normal(sql)
