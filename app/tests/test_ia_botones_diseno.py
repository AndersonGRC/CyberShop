# -*- coding: utf-8 -*-
"""Botones de la base de conocimiento según el CYBERSHOP Design System.

Lienzo de Claude Design «Botones de la base de conocimiento»: sin emojis, un
solo color fuerte por vista (nada de un botón rojo por fila: «Eliminar» vive
dentro de «Editar», con confirmación) y cada botón dice con palabras qué hace.
"""
import os
import re

import pytest

from database import get_db_cursor

MARCA = 'TEST-BTN'
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿]')


@pytest.fixture()
def faq(flask_app):
    with flask_app.app_context():
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""INSERT INTO public_site_items (item_type, title, description, sort_order,
                                                          is_active, created_at, updated_at)
                           VALUES ('faq', %s, 'Sí.', 10, TRUE, NOW(), NOW()) RETURNING id""",
                        (f'{MARCA} ¿Abren los domingos?',))
            fid = cur.fetchone()['id']
    yield fid
    with flask_app.app_context():
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM public_site_items WHERE item_type='faq' AND title LIKE %s",
                        (f'{MARCA}%',))


def _leer(*partes):
    with open(os.path.join(APP, *partes), encoding='utf-8') as f:
        return f.read()


def test_sin_emojis_en_la_pantalla_ni_en_el_chat():
    for partes in (('templates', 'admin', 'ia_conocimiento.html'),
                   ('templates', 'admin', 'chat_publico_faq.html'),
                   ('static', 'js', 'chat_publico.js')):
        assert not _EMOJI.search(_leer(*partes)), '/'.join(partes)


def test_en_las_filas_no_hay_boton_de_eliminar(as_propietario, faq):
    for ruta in ('/admin/chat-publico/conocimiento', '/admin/chat-publico/faq'):
        html = as_propietario.get(ruta).data.decode('utf-8')
        assert f'{MARCA} ¿Abren los domingos?' in html
        assert f'/faq/eliminar/{faq}' not in html, ruta
        assert 'Editar<span class="a11y-oculto">' in html and 'Ocultar<span class="a11y-oculto">' in html


def test_eliminar_vive_dentro_de_editar_con_confirmacion(as_propietario, faq):
    html = as_propietario.get(f'/admin/chat-publico/faq/editar/{faq}').data.decode('utf-8')
    formulario = html.split(f'/faq/eliminar/{faq}')[1][:600]
    assert 'Eliminar esta pregunta' in formulario
    assert "confirm(" in html.split(f'/faq/eliminar/{faq}')[1][:300]


def test_un_solo_boton_principal_visible_en_la_base_de_conocimiento(as_propietario, faq):
    html = as_propietario.get('/admin/chat-publico/conocimiento').data.decode('utf-8')
    # Principal = .kbx-btn sin variante. Los de los formularios de «Responder»
    # están ocultos hasta abrirlos; visible queda solo «Guardar sinónimos».
    visibles = re.findall(r'class="kbx-btn kbx-btn-md"', html.split('class="kbx-faq-form')[0])
    sinonimos = html.split('id="kbx-sinonimos"')[1]
    assert len(visibles) == 0 and 'class="kbx-btn kbx-btn-md"' in sinonimos


def test_el_chat_usa_iconos_con_palabras():
    js = _leer('static', 'js', 'chat_publico.js')
    bloque = js.split('function agregarCalificar')[1].split('function votar')[0]
    assert "'Sí'" in bloque and "'No'" in bloque and 'ICONO_SI' in bloque
    assert 'min-height: 40px' in _leer('static', 'css', 'chat_publico.css')
