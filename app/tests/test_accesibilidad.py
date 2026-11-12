"""Base común de accesibilidad (1.9.21.0).

Las dos plantillas base llevan «Saltar al contenido», una zona principal con
id="contenido", nombres en los íconos y la hoja accesibilidad.css. Con mouse
nada cambia de aspecto: la hoja solo actúa con teclado (:focus-visible), con
«reducir movimiento» o para el lector de pantalla.
"""
import re
from pathlib import Path

ESTATICOS = Path(__file__).resolve().parent.parent / 'static'


def _fuente(flask_app, nombre):
    return flask_app.jinja_env.loader.get_source(flask_app.jinja_env, nombre)[0]


# ── La tienda pública ───────────────────────────────────────────────────────

def test_la_tienda_se_recorre_con_teclado_y_lector(client, flask_app):
    html = client.get('/').data.decode('utf-8')
    version = flask_app.config.get('APP_VERSION') or ''
    assert f'/static/css/accesibilidad.css?v={version}' in html
    assert f'/static/js/accesibilidad.js?v={version}' in html
    assert '<a class="a11y-saltar" href="#contenido">Saltar al contenido</a>' in html
    assert html.count('id="contenido"') == 1
    assert '<main id="contenido" tabindex="-1">' in html
    assert '<nav id="menu-principal" aria-label="Menú principal">' in html


def test_el_logo_y_los_iconos_de_la_tienda_tienen_nombre(client, flask_app):
    html = client.get('/').data.decode('utf-8')
    logo = re.search(r'<img id="logo"[^>]*>', html).group(0)
    alt = re.search(r'alt="([^"]*)"', logo)
    assert alt and alt.group(1).strip(), 'el logo necesita texto alternativo'
    assert 'aria-label="Idioma de la página"' in html
    # El carrito solo sale en tiendas con ventas activas: se revisa en la plantilla.
    fuente = _fuente(flask_app, 'plantillaindex.html')
    assert fuente.count('aria-label="Carrito de compras"') == 2      # menú y botón flotante
    for red in ('Facebook', 'X (Twitter)', 'Escribir un correo', 'YouTube', 'LinkedIn', 'Instagram'):
        assert f'aria-label="{red}"' in fuente, red


def test_el_menu_del_celular_responde_al_teclado(client):
    html = client.get('/').data.decode('utf-8')
    boton = re.search(r'<i class="fas fa-ellipsis-v btn-menu"[^>]*>', html).group(0)
    # Sigue siendo <i> con la misma clase (layout.js y app.js lo buscan por .btn-menu).
    for atributo in ('role="button"', 'tabindex="0"', 'aria-label="Abrir menú"',
                     'aria-expanded="false"', 'aria-controls="menu-principal"',
                     'data-a11y-boton', 'data-a11y-menu-tienda'):
        assert atributo in boton, atributo


def test_un_aviso_con_comillas_no_rompe_la_pagina(client):
    """Antes el aviso iba como '{{ message }}' dentro del script: una comilla en el
    mensaje cortaba el JavaScript y el aviso no salía."""
    with client.session_transaction() as s:
        s['_flashes'] = [('error', "No se encontró el producto 'Coca-Cola' </script>")]
    html = client.get('/').data.decode('utf-8')
    assert ('text: "No se encontr\\u00f3 el producto \\u0027Coca-Cola\\u0027 \\u003c/script\\u003e"'
            in html)
    assert "text: 'No se" not in html


# ── El panel ────────────────────────────────────────────────────────────────

def test_el_panel_se_recorre_con_teclado_y_lector(as_propietario, flask_app):
    r = as_propietario.get('/admin')
    assert r.status_code == 200
    html = r.data.decode('utf-8')
    version = flask_app.config.get('APP_VERSION') or ''
    assert f'/static/css/accesibilidad.css?v={version}' in html
    assert f'/static/js/accesibilidad.js?v={version}' in html
    # El salto es lo primero que se alcanza con Tab dentro del <body>.
    cuerpo = html[html.index('<body'):]
    assert cuerpo.index('class="a11y-saltar"') < cuerpo.index('id="app-sidebar"')
    assert '<main id="contenido" tabindex="-1">' in html
    assert html.count('id="contenido"') == 1
    assert '<nav aria-label="Menú principal">' in html
    assert 'alt="Logo del header"' not in html and 'alt="Logo del menú"' not in html


# ── Seguridad de las plantillas compartidas ─────────────────────────────────

def test_las_plantillas_siguen_sirviendo_con_el_codigo_anterior(flask_app):
    """Las plantillas son compartidas: una tienda que aún no se reinicia las lee
    con el código viejo. Nada de rutas nuevas por url_for ni variables nuevas."""
    # La tienda pública recibe `app_version` (en ella `config` es otra variable); el
    # panel usa `config.APP_VERSION`, como ya hacía con Font Awesome.
    for nombre, version in (('plantillaindex.html', '{{ app_version }}'),
                            ('plantillaapp.html', '{{ config.APP_VERSION }}')):
        texto = _fuente(flask_app, nombre)
        assert "filename='css/accesibilidad" not in texto
        assert f'/static/css/accesibilidad.css?v={version}' in texto
        assert f'/static/js/accesibilidad.js?v={version}' in texto


# ── La hoja de estilos ──────────────────────────────────────────────────────

def test_la_hoja_solo_actua_con_teclado_y_no_toca_los_campos():
    css = (ESTATICOS / 'css' / 'accesibilidad.css').read_text(encoding='utf-8')
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    reglas_foco = re.findall(r'([^{}]+)\{[^{}]*outline[^{}]*\}', css)
    for selector in reglas_foco:
        selector = selector.strip()
        if selector.startswith('#contenido') or selector.startswith('.a11y-saltar'):
            continue
        assert ':focus-visible' in selector, selector
        # Los campos de texto y listas conservan su propio foco (con mouse también lo muestran).
        assert 'textarea' not in selector and 'select' not in selector
        assert 'input:' not in selector and 'input,' not in selector
        assert 'input[type="text"]' not in selector
    assert '@media (prefers-reduced-motion: reduce)' in css
    # El salto vive fuera de la vista hasta recibir el foco.
    assert re.search(r'\.a11y-saltar\s*\{[^}]*top:\s*-200px', css)
    assert re.search(r'\.a11y-saltar:focus\s*\{[^}]*top:\s*8px', css)


def test_el_script_no_cambia_el_aspecto_de_nada():
    js = (ESTATICOS / 'js' / 'accesibilidad.js').read_text(encoding='utf-8')
    assert '.style.' not in js and 'classList.add' not in js and 'classList.remove' not in js
    assert "'Enter'" in js and "' '" in js
