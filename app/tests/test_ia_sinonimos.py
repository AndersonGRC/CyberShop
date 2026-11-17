# -*- coding: utf-8 -*-
"""Sinónimos propios de cada tienda (cliente_config `ia_sinonimos`).

«pola = cerveza»: una pregunta con «pola» encuentra la pregunta frecuente que
dice «cerveza». Cada tienda tiene los suyos, quedan en la bitácora y se pueden
deshacer.
"""
import pytest

from database import get_db_cursor
from services.ia_rag import sinonimos

MARCA = 'TEST-SIN'


@pytest.fixture()
def tienda(flask_app):
    """Guarda y repone los sinónimos y la bitácora de la tienda de pruebas."""
    with flask_app.app_context():
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = %s", (sinonimos.CLAVE,))
            fila = cur.fetchone()
            cur.execute("SELECT to_regclass('public.ia_conocimiento_log') AS t")
            tiene_log = cur.fetchone()['t'] is not None
            ultimo = 0
            if tiene_log:
                cur.execute('SELECT COALESCE(MAX(id), 0) AS m FROM ia_conocimiento_log')
                ultimo = cur.fetchone()['m']
    yield
    with flask_app.app_context():
        with get_db_cursor() as cur:
            if fila is None:
                cur.execute('DELETE FROM cliente_config WHERE clave = %s', (sinonimos.CLAVE,))
            else:
                cur.execute('UPDATE cliente_config SET valor = %s WHERE clave = %s',
                            (fila['valor'], sinonimos.CLAVE))
            cur.execute("SELECT to_regclass('public.ia_conocimiento_log')")
            if cur.fetchone()[0] is not None:
                cur.execute("DELETE FROM ia_conocimiento_log WHERE tipo = 'sinonimos' AND id > %s",
                            (ultimo,))
            cur.execute("DELETE FROM public_site_items WHERE item_type='faq' AND title LIKE %s",
                        (f'{MARCA}%',))
        sinonimos._CACHE.clear()
        from services.ia_rag.indexador import reindexar_uno
        reindexar_uno('faq', None)


# ── Leer lo que escribe el negocio ────────────────────────────
def test_parsear_acepta_igual_o_dos_puntos_y_quita_tildes():
    tabla, errores = sinonimos.parsear('Pola = Cerveza fría\n# comentario\n\nalmuerzo: menú corrientazo')
    assert errores == []
    assert tabla == {'pola': 'cerveza fria', 'almuerzo': 'menu corrientazo'}


def test_la_misma_palabra_dos_veces_se_junta():
    tabla, _ = sinonimos.parsear('domi = domicilio\ndomi = envio')
    assert tabla == {'domi': 'domicilio envio'}


@pytest.mark.parametrize('texto, error', [
    ('pola cerveza', 'escribe «palabra = equivalentes»'),
    ('cerveza fria = pola', 'una sola palabra'),
    ('pola = ', 'falta qué significa'),
])
def test_parsear_explica_cada_error(texto, error):
    _tabla, errores = sinonimos.parsear(texto)
    assert errores and error in errores[0]


def test_maximo_de_lineas():
    _tabla, errores = sinonimos.parsear('\n'.join(f'p{i} = x' for i in range(sinonimos.MAX_LINEAS + 5)))
    assert any('Máximo' in e for e in errores)


# ── Guardar, usar y deshacer ──────────────────────────────────
def test_guardar_los_usa_al_buscar_y_deja_bitacora(flask_app, tienda):
    from services.ia_rag.buscar import expandir
    with flask_app.test_request_context():
        assert 'cerveza' not in expandir('¿venden pola?')
        sinonimos.guardar('pola = cerveza')
        assert 'cerveza' in expandir('¿venden pola?')               # sin esperar la caché
        assert 'cerveza' in expandir('Pola, ¿tienen?')               # con signos pegados
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""SELECT accion, antes, despues FROM ia_conocimiento_log
                           WHERE tipo = 'sinonimos' ORDER BY id DESC LIMIT 1""")
            fila = cur.fetchone()
    assert fila['accion'] == 'editar' and fila['despues']['texto'] == 'pola = cerveza'


def test_un_error_no_guarda_nada(flask_app, tienda):
    with flask_app.test_request_context():
        antes = sinonimos.leer_texto()
        with pytest.raises(ValueError):
            sinonimos.guardar('pola cerveza')
        assert sinonimos.leer_texto() == antes


def test_se_deshace_desde_el_historial(flask_app, tienda):
    from services.ia_rag import conocimiento
    with flask_app.test_request_context():
        sinonimos.guardar('pola = cerveza')
        sinonimos.guardar('pola = cerveza\nguaro = aguardiente')
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""SELECT id FROM ia_conocimiento_log WHERE tipo = 'sinonimos'
                           ORDER BY id DESC LIMIT 1""")
            ultimo = cur.fetchone()['id']
        ok, _msg, _tipo, _id = conocimiento.restaurar(ultimo)
        assert ok and sinonimos.leer_texto() == 'pola = cerveza'


def test_el_chat_encuentra_la_faq_con_la_palabra_de_la_tienda(flask_app, tienda):
    from services.ia_rag.buscar import buscar
    from services.ia_rag.indexador import indice_disponible, reindexar_uno
    from services.public_site_service import save_public_site_item
    with flask_app.test_request_context():
        if not indice_disponible():
            pytest.skip('la base de pruebas no tiene el índice (migración 0012)')
        save_public_site_item({'item_type': 'faq', 'title': f'{MARCA} Cervezas frías',
                               'description': 'Sí, vendemos cerveza nacional e importada.',
                               'is_active': 'on'}, None, flask_app.root_path)
        reindexar_uno('faq', None)

        def titulos():
            return [d['titulo'] for d in buscar('¿venden pola bien helada?', solo_publico=True)]
        assert f'{MARCA} Cervezas frías' not in titulos()
        sinonimos.guardar('pola = cerveza')
        assert f'{MARCA} Cervezas frías' in titulos()


def test_la_pantalla_los_muestra_y_guarda(as_propietario, tienda):
    r = as_propietario.post('/admin/chat-publico/conocimiento/sinonimos',
                            data={'sinonimos': 'Pola = Cerveza'})
    assert r.status_code == 302
    html = as_propietario.get('/admin/chat-publico/conocimiento').data.decode('utf-8')
    assert 'Palabras que significan lo mismo' in html and 'pola = cerveza' in html
    assert 'abren = horario atencion abrimos' in html               # los comunes, a la vista
    as_propietario.post('/admin/chat-publico/conocimiento/sinonimos', data={'sinonimos': 'malo'})
    html = as_propietario.get('/admin/chat-publico/conocimiento').data.decode('utf-8')
    assert 'pola = cerveza' in html                                 # el error no la borró
