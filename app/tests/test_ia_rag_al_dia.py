# -*- coding: utf-8 -*-
"""El índice de textos se arma y se refresca solo.

En producción el chat del sitio respondía «Esa no me la sé» a «¿Quiénes son
ustedes?»: nada construía el índice (solo guardar una FAQ indexaba su grupo).
Ahora la primera pregunta de prosa lo arma si está vacío, y lo rehace si tiene
más de un día — revisando como mucho cada 10 min por proceso y con un candado
para que dos procesos no lo reconstruyan a la vez.
"""
import pytest

from database import get_db_cursor, get_db_connection
from services.ia_rag import indexador

PALABRA = 'mapache5519'


@pytest.fixture()
def indice(flask_app, monkeypatch):
    """Índice de pruebas con la revisión por proceso en cero; al terminar queda
    reconstruido para las demás pruebas."""
    with flask_app.app_context():
        with get_db_cursor() as cur:
            if not indexador.indice_disponible(cur):
                pytest.skip('este cliente no tiene la migración 0012 aplicada')
        monkeypatch.setattr(indexador, '_REVISADO', {})
        yield
        indexador.reindexar()


def _filas():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT COUNT(*) AS n FROM ia_documentos')
        return cur.fetchone()['n']


def _vaciar():
    with get_db_cursor() as cur:
        cur.execute('DELETE FROM ia_documentos')


def test_arma_el_indice_si_esta_vacio(indice):
    _vaciar()
    resultado = indexador.mantener_al_dia()
    assert resultado and 'producto' in resultado
    assert _filas() > 0


def test_no_lo_rehace_si_esta_fresco(indice):
    indexador.reindexar()
    assert indexador.mantener_al_dia() is None


def test_lo_rehace_si_tiene_mas_de_un_dia(indice):
    indexador.reindexar()
    with get_db_cursor() as cur:
        cur.execute("UPDATE ia_documentos SET actualizado_en = NOW() - INTERVAL '2 days'")
    assert indexador.mantener_al_dia() is not None
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT MIN(actualizado_en) > NOW() - INTERVAL '1 hour' AS fresco FROM ia_documentos")
        assert cur.fetchone()['fresco']


def test_revisa_como_mucho_cada_diez_minutos(indice):
    indexador.reindexar()
    indexador.mantener_al_dia()          # primera revisión: fresco, no hace nada
    _vaciar()
    assert indexador.mantener_al_dia() is None, 'dentro de los 10 min no vuelve a mirar'
    assert _filas() == 0


def test_si_otro_proceso_lo_esta_armando_no_se_pisa(indice):
    _vaciar()
    otra = get_db_connection()
    try:
        with otra.cursor() as cur:
            cur.execute('SELECT pg_advisory_lock(%s)', (indexador._CANDADO_INDICE,))
        assert indexador.mantener_al_dia() is None
        assert _filas() == 0
    finally:
        with otra.cursor() as cur:
            cur.execute('SELECT pg_advisory_unlock(%s)', (indexador._CANDADO_INDICE,))
        otra.close()


def test_el_chat_del_sitio_encuentra_lo_publicado_sin_reindexar_a_mano(
        indice, chat_encendido, as_propietario, monkeypatch):
    """El caso de producción: una FAQ publicada, el índice vacío y un visitante
    que pregunta. Antes: «Esa no me la sé»."""
    from services.chat_publico import motor
    r = as_propietario.post('/admin/chat-publico/faq/crear', data={
        'title': 'TEST-ALDIA ¿Hacen envíos?',
        'description': f'Sí, enviamos a domicilio con {PALABRA}.', 'sort_order': '1',
        'is_active': 'on'})
    assert r.status_code in (200, 302)
    try:
        _vaciar()
        monkeypatch.setattr(motor, '_registrar', lambda *a, **k: None)
        plan = motor.preparar(f'¿Qué es {PALABRA}?')
        assert plan['via'] == motor.VIA_RAG
        assert PALABRA in plan['texto_base']
    finally:
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM public_site_items WHERE item_type='faq' AND title LIKE 'TEST-ALDIA%%'")


def test_la_tabla_del_codigo_es_la_de_la_migracion_0012():
    """El código crea el índice si la migración 0012 aún no llegó al cliente: la
    tabla y sus índices deben ser idénticos (la migración además intenta
    instalar las extensiones, que el código no toca)."""
    import os
    import re
    app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidatos = [os.path.normpath(os.path.join(app, *rel, 'CyberShopAdmin', 'migrations',
                                                'tenant', '0012_ia_documentos.sql'))
                  for rel in (('..', '..'), ('..',))]
    ruta = next((r for r in candidatos if os.path.exists(r)), None)
    if ruta is None:
        pytest.skip('el repo del maestro no está al lado')
    with open(ruta, encoding='utf-8') as f:
        sql = re.sub(r'--[^\n]*', '', f.read())
    sql = sql[sql.index('CREATE TABLE IF NOT EXISTS ia_documentos'):]

    def normal(texto):
        return re.sub(r'\s+', ' ', texto).strip()
    assert normal(indexador._DDL_INDICE) == normal(sql)
