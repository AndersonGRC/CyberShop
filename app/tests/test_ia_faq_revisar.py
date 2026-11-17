# -*- coding: utf-8 -*-
"""Aviso de preguntas frecuentes viejas, con fechas o precios, o casi repetidas.

Una FAQ que dice «abrimos hasta el 31 de diciembre de 2025» o «envío a $5.000»
puede llevar meses diciendo algo falso en el chat. Se avisan para revisar, con
«Corregir» o «Sigue vigente» (queda en el historial).
"""
from datetime import date

import pytest

from database import get_db_cursor

MARCA = 'TEST-REV'


@pytest.fixture()
def faqs(flask_app):
    creadas = []

    def _crear(titulo, respuesta, dias=0, activa=True):
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""INSERT INTO public_site_items
                               (item_type, title, description, sort_order, is_active, created_at, updated_at)
                           VALUES ('faq', %s, %s, 10, %s, NOW() - make_interval(days => %s),
                                   NOW() - make_interval(days => %s)) RETURNING id""",
                        (f'{MARCA} {titulo}', respuesta, activa, dias, dias))
            creadas.append(cur.fetchone()['id'])
            return creadas[-1]
    with flask_app.test_request_context():
        yield _crear
    with flask_app.app_context():
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM public_site_items WHERE item_type='faq' AND title LIKE %s",
                        (f'{MARCA}%',))
            cur.execute("SELECT to_regclass('public.ia_conocimiento_log')")
            if cur.fetchone()[0] is not None:
                cur.execute('DELETE FROM ia_conocimiento_log WHERE titulo LIKE %s', (f'{MARCA}%',))


def _mias(lista):
    return {f['title'].replace(f'{MARCA} ', ''): f for f in lista if f['title'].startswith(MARCA)}


def test_avisa_viejas_fechas_pasadas_y_precios(faqs):
    from services.ia_rag.conocimiento import faqs_para_revisar
    faqs('horario', 'De 8 a 6.', dias=200)
    faqs('navidad', 'Abrimos hasta el 24 de diciembre de 2025.', dias=10)
    faqs('envios', 'El envío cuesta $5.000.', dias=120)
    faqs('envios nuevo', 'El envío cuesta $5.000.', dias=5)          # precio reciente: no
    faqs('pagos', 'Efectivo y tarjeta.', dias=5)                     # al día: no
    faqs('vieja oculta', 'x', dias=400, activa=False)                # no publicada: no
    revisar = _mias(faqs_para_revisar(hoy=date(2026, 11, 15)))
    assert set(revisar) == {'horario', 'navidad', 'envios'}
    assert 'meses sin revisarse' in revisar['horario']['motivos'][0]
    assert '2025' in revisar['navidad']['motivos'][0]
    assert 'precios' in revisar['envios']['motivos'][0]


def test_avisa_las_casi_repetidas(faqs):
    from services.ia_rag.conocimiento import faqs_parecidas
    faqs('¿Hacen domicilios?', 'Sí.')
    faqs('¿Hacen domicilios a la casa?', 'No.')
    faqs('¿Tienen parqueadero?', 'Sí.')
    pares = [(a['title'], b['title']) for a, b in faqs_parecidas()
             if a['title'].startswith(MARCA) and b['title'].startswith(MARCA)]
    assert pares == [(f'{MARCA} ¿Hacen domicilios?', f'{MARCA} ¿Hacen domicilios a la casa?')]


def test_sigue_vigente_la_saca_de_la_lista_y_queda_en_el_historial(faqs, as_propietario, flask_app):
    from services.ia_rag.conocimiento import faqs_para_revisar
    fid = faqs('horario viejo', 'De 8 a 6.', dias=300)
    html = as_propietario.get('/admin/chat-publico/conocimiento').data.decode('utf-8')
    assert 'Para revisar' in html and f'{MARCA} horario viejo' in html
    r = as_propietario.post(f'/admin/chat-publico/conocimiento/faq/{fid}/vigente')
    assert r.status_code == 302
    with flask_app.test_request_context():
        assert 'horario viejo' not in _mias(faqs_para_revisar())
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""SELECT accion FROM ia_conocimiento_log WHERE tipo='faq' AND objeto_id=%s""",
                        (str(fid),))
            assert [r['accion'] for r in cur.fetchall()] == ['revisar']
