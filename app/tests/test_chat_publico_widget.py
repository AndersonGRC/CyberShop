# -*- coding: utf-8 -*-
"""El widget del chat del sitio se sostiene solo, sin depender de variables.css.

En producción salió transparente: sus colores vivían en variables.css, que los
@import piden sin ?v= y Cloudflare guarda 7 días. Además, importarlo tarde
volvía a aplicar los colores de marca por defecto encima de los del cliente.
"""
import os
import re

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leer(ruta):
    with open(os.path.join(_APP, ruta), encoding='utf-8') as f:
        return f.read()


def _sin_comentarios(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def test_css_del_widget_no_importa_otras_hojas():
    assert '@import' not in _sin_comentarios(_leer('static/css/chat_publico.css'))


def test_toda_variable_del_widget_esta_definida_en_su_propio_css():
    css = _leer('static/css/chat_publico.css')
    usadas = set(re.findall(r'var\((--[\w-]+)', css))
    definidas = set(re.findall(r'(--[\w-]+)\s*:', css))
    assert usadas, 'el widget debería usar sus propios tokens'
    assert usadas <= definidas, f'sin definir: {sorted(usadas - definidas)}'
    assert all(v.startswith('--cbchat-') for v in usadas), 'nunca variables de marca'


def test_hidden_oculta_de_verdad_dentro_del_widget():
    """Sin esto, `display:flex` por id anulaba [hidden] (sugerencias visibles)."""
    css = _leer('static/css/chat_publico.css')
    assert re.search(r'#cbchat-root \[hidden\]\s*\{\s*display:\s*none\s*!important', css)


def test_layout_pide_el_widget_versionado():
    js = _leer('static/js/layout.js')
    assert "'/static/css/chat_publico.css' + version" in js
    assert "'/static/js/chat_publico.js' + version" in js


def test_la_conversacion_se_guarda_solo_en_la_pestana():
    """Al cambiar de página (Productos, Contáctenos, login…) la conversación
    sigue. Se guarda en sessionStorage: solo esa pestaña, se borra al cerrarla y
    nunca en localStorage, que la dejaría en el equipo para el siguiente que lo use."""
    js = _leer('static/js/chat_publico.js')
    assert 'sessionStorage' in js
    assert 'localStorage' not in js
