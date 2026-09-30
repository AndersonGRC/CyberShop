# -*- coding: utf-8 -*-
"""CRUD de preguntas frecuentes (F8) de punta a punta vía HTTP.

FAQ usa item_type='faq' de services/public_site_service.py (PUBLIC_ITEM_TYPES)
— sin tabla propia, mismas funciones genéricas que slides/publicaciones/
servicios. También cubre el gate de cada pantalla (config: ADMIN_FULL,
FAQ: ADMIN_STAFF) y que guardar, despublicar o eliminar una FAQ actualiza
inmediatamente el índice público sin tocar los documentos de otras fuentes.
"""
from contextlib import contextmanager

import pytest

from database import get_db_cursor


@pytest.fixture()
def limpiar_faq_test():
    yield
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM public_site_items WHERE item_type='faq' AND title LIKE 'TEST-%%'")
    from services.ia_rag.indexador import reindexar_uno
    reindexar_uno('faq', None)


def _buscar(titulo):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM public_site_items WHERE item_type='faq' AND title=%s", (titulo,))
        return cur.fetchone()


def _indexada(item_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT canal_publico FROM ia_documentos "
                    "WHERE fuente = 'faq' AND fuente_id = %s", (str(item_id),))
        return cur.fetchone()


def _crear(client, title, description, sort_order=1, activa=True):
    datos = {'title': title, 'description': description, 'sort_order': str(sort_order)}
    if activa:
        datos['is_active'] = 'on'
    return client.post('/admin/chat-publico/faq/crear', data=datos)


def test_crear_faq(as_propietario, limpiar_faq_test):
    r = _crear(as_propietario, 'TEST-pregunta', 'TEST-respuesta', sort_order=7)
    assert r.status_code in (200, 302)
    fila = _buscar('TEST-pregunta')
    assert fila is not None
    assert fila['description'] == 'TEST-respuesta'
    assert fila['sort_order'] == 7
    assert fila['is_active'] is True


def test_faq_inactiva_al_crear_sin_checkbox(as_propietario, limpiar_faq_test):
    _crear(as_propietario, 'TEST-inactiva', 'TEST-desc', activa=False)
    fila = _buscar('TEST-inactiva')
    assert fila is not None
    assert fila['is_active'] is False


def test_faq_aparece_en_la_lista(as_propietario, limpiar_faq_test):
    _crear(as_propietario, 'TEST-lista', 'TEST-resp')
    r = as_propietario.get('/admin/chat-publico/faq')
    assert r.status_code == 200
    assert b'TEST-lista' in r.data


def test_editar_faq(as_propietario, limpiar_faq_test):
    _crear(as_propietario, 'TEST-original', 'TEST-desc')
    fila = _buscar('TEST-original')
    r = as_propietario.post(f'/admin/chat-publico/faq/editar/{fila["id"]}', data={
        'title': 'TEST-editado', 'description': 'TEST-desc2', 'sort_order': '2', 'is_active': 'on'})
    assert r.status_code in (200, 302)
    assert _buscar('TEST-original') is None
    editada = _buscar('TEST-editado')
    assert editada is not None and editada['description'] == 'TEST-desc2'


def test_editar_faq_precarga_el_formulario(as_propietario, limpiar_faq_test):
    _crear(as_propietario, 'TEST-precarga', 'TEST-desc-precarga')
    fila = _buscar('TEST-precarga')
    r = as_propietario.get(f'/admin/chat-publico/faq/editar/{fila["id"]}')
    assert r.status_code == 200
    assert b'TEST-precarga' in r.data
    assert b'TEST-desc-precarga' in r.data


def test_toggle_faq(as_propietario, limpiar_faq_test):
    _crear(as_propietario, 'TEST-toggle', 'TEST-desc')
    fila = _buscar('TEST-toggle')
    assert fila['is_active'] is True
    as_propietario.post(f'/admin/chat-publico/faq/toggle/{fila["id"]}')
    assert _buscar('TEST-toggle')['is_active'] is False
    as_propietario.post(f'/admin/chat-publico/faq/toggle/{fila["id"]}')
    assert _buscar('TEST-toggle')['is_active'] is True


def test_eliminar_faq(as_propietario, limpiar_faq_test):
    _crear(as_propietario, 'TEST-eliminar', 'TEST-desc')
    fila = _buscar('TEST-eliminar')
    as_propietario.post(f'/admin/chat-publico/faq/eliminar/{fila["id"]}')
    assert _buscar('TEST-eliminar') is None


def test_faq_guardada_queda_buscable_por_rag(as_propietario, limpiar_faq_test):
    """Crear una FAQ sin ID conocido reindexa solo el grupo de FAQ."""
    from services.ia_rag.buscar import buscar
    _crear(as_propietario, 'TEST-Zorroquimico99', 'Respuesta unica Zorroquimico99 para la prueba de RAG.')
    resultados = buscar('Zorroquimico99', solo_publico=True)
    textos = [f"{r.get('titulo', '')} {r.get('texto', '')}" for r in resultados]
    assert any('Zorroquimico99' in t for t in textos), \
        f'la FAQ nueva no aparecio en la busqueda RAG: {resultados}'


def test_despublicar_y_eliminar_faq_no_dejan_documento_publico(as_propietario,
                                                                 limpiar_faq_test):
    from services.ia_rag.buscar import buscar

    _crear(as_propietario, 'TEST-FaqUnicaZorro97', 'Respuesta TEST-FaqUnicaZorro97.')
    _crear(as_propietario, 'TEST-FaqVecinaZorro98', 'Respuesta TEST-FaqVecinaZorro98.')
    primera = _buscar('TEST-FaqUnicaZorro97')['id']
    vecina = _buscar('TEST-FaqVecinaZorro98')['id']
    assert _indexada(primera)['canal_publico'] is True
    assert _indexada(vecina)['canal_publico'] is True

    as_propietario.post(f'/admin/chat-publico/faq/toggle/{primera}')
    assert _indexada(primera)['canal_publico'] is False
    assert _indexada(vecina)['canal_publico'] is True
    assert all(d['fuente_id'] != str(primera)
               for d in buscar('FaqUnicaZorro97', solo_publico=True))

    as_propietario.post(f'/admin/chat-publico/faq/toggle/{primera}')
    assert _indexada(primera)['canal_publico'] is True
    as_propietario.post(f'/admin/chat-publico/faq/eliminar/{primera}')
    assert _indexada(primera) is None
    assert _indexada(vecina)['canal_publico'] is True
    assert all(d['fuente_id'] != str(primera)
               for d in buscar('FaqUnicaZorro97', solo_publico=True))


def test_reindexar_faq_borrada_solo_elimina_su_fila(monkeypatch, flask_app):
    from services.ia_rag import indexador

    class Cursor:
        def __init__(self):
            self.consultas = []

        def execute(self, sql, params=None):
            self.consultas.append((sql, params))

        def fetchall(self):
            return []  # la FAQ ya no existe en public_site_items

    cur = Cursor()

    @contextmanager
    def cursor(**_kwargs):
        yield cur

    monkeypatch.setattr(indexador, 'get_db_cursor', cursor)
    monkeypatch.setattr(indexador, 'indice_disponible', lambda _cur: True)
    monkeypatch.setattr(indexador, '_existe', lambda _cur, _tabla: True)
    monkeypatch.setattr(indexador, '_sql_tsv', lambda _cur: "to_tsvector('spanish', %s)")
    with flask_app.app_context():
        assert indexador.reindexar_uno('faq', 42) is True
    borrados = [(sql, params) for sql, params in cur.consultas if 'DELETE FROM ia_documentos' in sql]
    assert borrados == [('DELETE FROM ia_documentos WHERE fuente = %s AND fuente_id = %s',
                         ('faq', '42'))]
    assert any('WHERE item_type = %s AND id = %s' in sql and params == ('faq', 42)
               for sql, params in cur.consultas)


def test_reindexar_faq_inactiva_la_marca_no_publica(monkeypatch, flask_app):
    from services.ia_rag import indexador

    class Cursor:
        def execute(self, _sql, _params=None):
            pass

        def fetchall(self):
            return [{'id': 42, 'title': 'FAQ inactiva', 'subtitle': '',
                     'description': 'Respuesta anterior', 'extra_text': '',
                     'cta_url': '', 'is_active': False}]

    @contextmanager
    def cursor(**_kwargs):
        yield Cursor()

    guardadas = []
    monkeypatch.setattr(indexador, 'get_db_cursor', cursor)
    monkeypatch.setattr(indexador, 'indice_disponible', lambda _cur: True)
    monkeypatch.setattr(indexador, '_existe', lambda _cur, _tabla: True)
    monkeypatch.setattr(indexador, '_sql_tsv', lambda _cur: "to_tsvector('spanish', %s)")
    monkeypatch.setattr(indexador, '_upsert', lambda *args: guardadas.append(args) or True)
    with flask_app.app_context():
        assert indexador.reindexar_uno('faq', 42) is True
    assert len(guardadas) == 1
    assert guardadas[0][2:4] == ('faq', 42)
    assert guardadas[0][-1] is False


# ── Gates: cada pantalla exige el rol correcto ──
def test_faq_lista_exige_sesion(client):
    r = client.get('/admin/chat-publico/faq')
    assert r.status_code in (302, 401, 403)


def test_config_exige_sesion(client):
    r = client.get('/admin/chat-publico/')
    assert r.status_code in (302, 401, 403)


def test_config_exige_admin_full_no_solo_staff(as_cajero):
    """Cajero es rol operativo de restaurante (POS_OPERATIONAL), no ADMIN_FULL:
    no debe poder entrar a la configuracion del chat."""
    r = as_cajero.get('/admin/chat-publico/')
    assert r.status_code in (302, 401, 403)
