# -*- coding: utf-8 -*-
"""CRUD de preguntas frecuentes (F8) de punta a punta vía HTTP.

FAQ usa item_type='faq' de services/public_site_service.py (PUBLIC_ITEM_TYPES)
— sin tabla propia, mismas funciones genéricas que slides/publicaciones/
servicios. También cubre el gate de cada pantalla (config: ADMIN_FULL,
FAQ: ADMIN_STAFF) y que guardar una FAQ la deja buscable por ia_rag (aunque
hoy reindexar_uno() reindexe el grupo 'sitio' completo, no solo esa fila —
limitación conocida, no es lo que esta prueba evalúa).
"""
import pytest

from database import get_db_cursor


@pytest.fixture()
def limpiar_faq_test():
    yield
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM public_site_items WHERE item_type='faq' AND title LIKE 'TEST-%%'")


def _buscar(titulo):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM public_site_items WHERE item_type='faq' AND title=%s", (titulo,))
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
    """save_public_site_item() dispara reindexar_uno('faq', id) — esta prueba
    confirma que el efecto real (aparecer en ia_rag.buscar) ocurre, sin
    importar el detalle interno de a cuánto alcanza ese reindexado."""
    from services.ia_rag.buscar import buscar
    _crear(as_propietario, 'TEST-Zorroquimico99', 'Respuesta unica Zorroquimico99 para la prueba de RAG.')
    resultados = buscar('Zorroquimico99', solo_publico=True)
    textos = [f"{r.get('titulo', '')} {r.get('texto', '')}" for r in resultados]
    assert any('Zorroquimico99' in t for t in textos), \
        f'la FAQ nueva no aparecio en la busqueda RAG: {resultados}'


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
