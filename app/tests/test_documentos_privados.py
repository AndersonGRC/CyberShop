# -*- coding: utf-8 -*-
"""Cotizaciones y cuentas de cobro en PDF: de cada tienda y nunca públicas (1.9.19.0).

- El PDF ya no queda en static/ (público y mezclado entre tiendas): se arma con lo
  guardado cada vez que se pide, desde el panel o con el enlace privado del cliente.
- /static deja de servir las dos carpetas viejas y lo que había se mueve (no se
  borra) a una carpeta cerrada.
- El enlace privado no se puede alterar, no sirve en otra tienda y vence a los 30 días.
- Eliminar una cotización o cuenta no borra archivos compartidos.
Contra la base de pruebas; lo que se crea se borra al final."""
import os
import uuid

import pytest

import routes.quotes as rq
from services import documentos_privados as docs

MARCA = uuid.uuid4().hex[:8]
CLIENTE = f'Cliente privado {MARCA}'


# ── Las carpetas públicas viejas ────────────────────────────────
@pytest.mark.parametrize('ruta, cerrada', [
    ('cotizaciones/pdf/Cotizacion_1.pdf', True),
    ('cuentas_cobro/pdf/CueCob_1.pdf', True),
    ('cotizaciones/pdf', True),
    ('img/../cotizaciones/pdf/Cotizacion_1.pdf', True),
    ('./cotizaciones//pdf/Cotizacion_1.pdf', True),
    ('Cotizaciones/PDF/Cotizacion_1.pdf', True),
    ('cotizaciones\\pdf\\Cotizacion_1.pdf', True),
    ('css/variables.css', False),
    ('cotizaciones/pdfs/x.pdf', False),
    ('img/cotizaciones/pdf/x.pdf', False),
    ('', False), (None, False),
])
def test_que_carpetas_de_static_estan_cerradas(ruta, cerrada):
    assert docs.es_carpeta_cerrada(ruta) is cerrada


def test_static_no_sirve_los_pdf_aunque_el_archivo_exista(flask_app, client):
    carpeta = os.path.join(flask_app.root_path, 'static', 'cotizaciones', 'pdf')
    os.makedirs(carpeta, exist_ok=True)
    nombre = f'prueba_{MARCA}.pdf'
    archivo = os.path.join(carpeta, nombre)
    with open(archivo, 'wb') as f:
        f.write(b'%PDF-1.4 prueba')
    try:
        for url in (f'/static/cotizaciones/pdf/{nombre}',
                    f'/static/img/../cotizaciones/pdf/{nombre}',
                    '/static/cuentas_cobro/pdf/CueCob_1.pdf'):
            assert client.get(url).status_code == 404, url
        assert client.get('/static/css/variables.css').status_code == 200, 'lo demás sigue igual'
    finally:
        os.remove(archivo)


def test_archivar_mueve_sin_borrar_ni_pisar(tmp_path):
    cot = tmp_path / 'static' / 'cotizaciones' / 'pdf'
    cue = tmp_path / 'static' / 'cuentas_cobro' / 'pdf'
    cot.mkdir(parents=True)
    cue.mkdir(parents=True)
    (cot / 'Cotizacion_1.pdf').write_bytes(b'uno')
    (cue / 'CueCob_7.pdf').write_bytes(b'siete')
    (cot / 'subcarpeta').mkdir()

    assert docs.archivar_pdf_publicos(str(tmp_path)) == 2
    archivo = tmp_path / 'uploads' / 'archivo_pdf_publicos'
    assert (archivo / 'cotizaciones' / 'Cotizacion_1.pdf').read_bytes() == b'uno'
    assert (archivo / 'cuentas_cobro' / 'CueCob_7.pdf').read_bytes() == b'siete'
    assert [p.name for p in cot.iterdir()] == ['subcarpeta'], 'solo se mueven archivos'
    assert not list(cue.iterdir())

    # Otra tienda sin actualizar vuelve a escribir el mismo nombre: se guardan los dos.
    (cot / 'Cotizacion_1.pdf').write_bytes(b'otro')
    assert docs.archivar_pdf_publicos(str(tmp_path)) == 1
    guardados = sorted(p.read_bytes() for p in (archivo / 'cotizaciones').iterdir())
    assert guardados == [b'otro', b'uno']
    assert docs.archivar_pdf_publicos(str(tmp_path)) == 0, 'sin nada que mover no falla'
    assert docs.archivar_pdf_publicos(str(tmp_path / 'no_existe')) == 0


# ── WhatsApp ────────────────────────────────────────────────────
@pytest.mark.parametrize('telefono, esperado', [
    ('3001234567', '573001234567'), ('300 123 45 67', '573001234567'),
    ('+57 300-123-4567', '573001234567'), ('573001234567', '573001234567'),
    ('6011234567', ''), ('1234', ''), ('', ''), (None, ''),
])
def test_celular_para_whatsapp(telefono, esperado):
    assert docs.celular_whatsapp(telefono) == esperado


def test_enlace_de_whatsapp_lleva_el_mensaje_codificado():
    url = docs.enlace_whatsapp('300 1234567', 'Hola Ana & Cía: https://x.co/doc/a?b=1')
    assert url.startswith('https://wa.me/573001234567?text=Hola%20Ana%20%26%20C%C3%ADa%3A%20https%3A%2F%2F')
    assert docs.enlace_whatsapp('', 'Hola').startswith('https://wa.me/?text='), 'sin celular: se escoge el contacto'


# ── Cotizaciones, de punta a punta ──────────────────────────────
@pytest.fixture()
def cotizacion(as_propietario, cursor, monkeypatch):
    """Una cotización creada por el formulario (sin CRM). Devuelve (id, contexto del PDF)."""
    import services.crm_service as crm
    monkeypatch.setattr(crm, 'upsert_contacto', lambda **kw: None)
    monkeypatch.setattr(crm, 'sync_oportunidad_cotizacion', lambda **kw: None)
    contexto = {}
    real = rq.render_template

    def capturar(plantilla, **kw):
        if plantilla == 'pdf_quote.html':
            contexto.clear()
            contexto.update(kw)
        return real(plantilla, **kw)
    monkeypatch.setattr(rq, 'render_template', capturar)
    datos = {'cliente_nombre': CLIENTE, 'cliente_documento': '900123456', 'cliente_telefono': '300 123 4567',
             'cliente_ciudad': 'Cali', 'notas_adicionales': 'GARANTÍA\n- 12 meses',
             'descripcion[]': ['Core i5', 'Instalación', 'Ryzen 5'], 'cantidad[]': ['2', '1', '1'],
             'precio[]': ['1000000', '50000', '800000'], 'descuento[]': ['10', '0', '0'],
             'iva[]': ['19', '0', '19'], 'opcion[]': ['Opción 1 — Intel', '', 'Opción 2 — AMD']}
    r = as_propietario.post('/admin/cotizar/generar', data=datos)
    assert r.status_code == 200 and r.mimetype == 'application/pdf', r.get_data(as_text=True)[:300]
    with cursor() as cur:
        cur.execute("SELECT id, pdf_path FROM cotizaciones WHERE cliente_nombre = %s ORDER BY id DESC LIMIT 1",
                    (CLIENTE,))
        fila = dict(cur.fetchone())
    yield fila, dict(contexto), contexto
    with cursor() as cur:
        cur.execute('DELETE FROM detalle_cotizacion WHERE cotizacion_id = %s', (fila['id'],))
        cur.execute('DELETE FROM cotizaciones WHERE id = %s', (fila['id'],))


def test_generar_ya_no_deja_el_pdf_en_static(cotizacion, flask_app):
    fila, _, _ = cotizacion
    assert fila['pdf_path'] is None
    publico = os.path.join(flask_app.root_path, 'static', 'cotizaciones', 'pdf', f"Cotizacion_{fila['id']}.pdf")
    assert not os.path.exists(publico)


def test_pdf_del_panel_es_el_mismo_documento(cotizacion, as_propietario):
    fila, al_generar, contexto = cotizacion
    r = as_propietario.get(f"/admin/cotizar/{fila['id']}/pdf")
    assert r.status_code == 200 and r.mimetype == 'application/pdf' and r.data.startswith(b'%PDF')
    assert 'no-store' in r.headers['Cache-Control'] and 'private' in r.headers['Cache-Control']
    assert 'noindex' in r.headers['X-Robots-Tag']
    assert 'attachment' not in r.headers.get('Content-Disposition', ''), 'se ve en el navegador'
    # Armado con lo guardado: las mismas cuentas, ítems, opciones, notas y cliente.
    for campo in ('id', 'fecha', 'cliente', 'items', 'opciones', 'base_subtotal', 'total', 'subtotal',
                  'descuento', 'mostrar_descuento', 'iva', 'notas', 'notas_bloques'):
        assert contexto[campo] == al_generar[campo], campo
    assert al_generar['cliente']['ciudad'] == 'Cali' and al_generar['mostrar_descuento'] is True
    assert [o['titulo'] for o in al_generar['opciones']] == ['Opción 1 — Intel', 'Opción 2 — AMD']


def test_pdf_del_panel_pide_sesion(cotizacion, flask_app):
    fila, _, _ = cotizacion
    r = flask_app.test_client().get(f"/admin/cotizar/{fila['id']}/pdf")
    assert r.status_code in (302, 401, 403) and r.mimetype != 'application/pdf'


def test_pdf_de_una_cotizacion_que_no_existe(as_propietario):
    r = as_propietario.get('/admin/cotizar/999999999/pdf')
    assert r.status_code == 302 and r.mimetype != 'application/pdf'


def _token(flask_app, tipo, doc_id):
    with flask_app.test_request_context('/'):
        return docs.firmar(tipo, doc_id)


def test_enlace_privado_abre_sin_sesion(cotizacion, flask_app):
    fila, _, _ = cotizacion
    r = flask_app.test_client().get(f"/doc/{_token(flask_app, 'cotizacion', fila['id'])}")
    assert r.status_code == 200 and r.mimetype == 'application/pdf' and r.data.startswith(b'%PDF')
    assert 'no-store' in r.headers['Cache-Control'] and 'noindex' in r.headers['X-Robots-Tag']


def test_enlace_alterado_o_de_otra_tienda_no_abre(cotizacion, flask_app, monkeypatch):
    fila, _, _ = cotizacion
    visitante = flask_app.test_client()
    bueno = _token(flask_app, 'cotizacion', fila['id'])
    assert visitante.get(f'/doc/{bueno[:-2]}xx').status_code == 404
    assert visitante.get('/doc/cualquier-cosa').status_code == 404
    # No se puede cambiar el número de la cotización conservando la firma.
    otro = _token(flask_app, 'cotizacion', fila['id'] + 1)
    mezcla = otro.split('.')[0] + '.' + '.'.join(bueno.split('.')[1:])
    assert visitante.get(f'/doc/{mezcla}').status_code == 404
    # Otra tienda con la MISMA llave (la heredan del archivo compartido): no abre aquí.
    import database
    with monkeypatch.context() as m:
        m.setattr(database, '_current_db_name', lambda: 'cyber_otra_tienda')
        de_otra = _token(flask_app, 'cotizacion', fila['id'])
    assert de_otra != bueno
    r = visitante.get(f'/doc/{de_otra}')
    assert r.status_code == 404 and r.mimetype == 'text/html' and 'no es válido' in r.get_data(as_text=True)


def test_enlace_vence(cotizacion, flask_app, monkeypatch):
    fila, _, _ = cotizacion
    token = _token(flask_app, 'cotizacion', fila['id'])
    monkeypatch.setattr(docs, 'ENLACE_DIAS', -1)   # como si ya hubieran pasado los 30 días
    r = flask_app.test_client().get(f'/doc/{token}')
    assert r.status_code == 410 and 'ya venció' in r.get_data(as_text=True)


def test_enlace_de_un_documento_eliminado(cotizacion, flask_app, as_propietario, cursor):
    fila, _, _ = cotizacion
    token = _token(flask_app, 'cotizacion', fila['id'])
    # Un PDF «compartido» con ese nombre (como los de antes): eliminar NO lo toca.
    carpeta = os.path.join(flask_app.root_path, 'static', 'cotizaciones', 'pdf')
    os.makedirs(carpeta, exist_ok=True)
    viejo = os.path.join(carpeta, f"Cotizacion_{fila['id']}.pdf")
    with open(viejo, 'wb') as f:
        f.write(b'%PDF de otra tienda')
    try:
        with cursor() as cur:
            cur.execute("UPDATE cotizaciones SET pdf_path = %s WHERE id = %s",
                        (f"cotizaciones/pdf/Cotizacion_{fila['id']}.pdf", fila['id']))
        r = as_propietario.post(f"/admin/cotizar/eliminar/{fila['id']}")
        assert r.status_code == 302
        with cursor() as cur:
            cur.execute("SELECT 1 FROM cotizaciones WHERE id = %s", (fila['id'],))
            assert cur.fetchone() is None
        assert os.path.isfile(viejo), 'eliminar la cotización no borra archivos compartidos'
    finally:
        os.remove(viejo)
    r = flask_app.test_client().get(f'/doc/{token}')
    assert r.status_code == 404 and 'ya no está disponible' in r.get_data(as_text=True)


def test_la_lista_trae_pdf_whatsapp_y_copiar_enlace(cotizacion, as_propietario):
    fila, _, _ = cotizacion
    html = as_propietario.get('/admin/mis_cotizaciones').get_data(as_text=True)
    assert f'href="/admin/cotizar/{fila["id"]}/pdf"' in html
    assert 'static/cotizaciones/pdf' not in html, 'ningún enlace al archivo público'
    assert 'https://wa.me/573001234567?text=' in html and 'js-copiar-enlace' in html
    assert '/doc/' in html and f'COT%20{fila["id"]:010d}' in html


# ── Cuentas de cobro ────────────────────────────────────────────
@pytest.fixture()
def cuenta(cursor):
    with cursor() as cur:
        cur.execute("""INSERT INTO cuentas_cobro (consecutivo, fecha, cliente_nombre, cliente_nit,
                           cliente_direccion, cliente_telefono, cliente_ciudad, contractor_nombre,
                           contractor_id, contractor_telefono, contractor_email, texto_pago, total)
                       VALUES (%s, '2026-03-05', %s, '900123456', 'Calle 1', '3109876543', 'Cali',
                               'Contratista QA', '1020304050', '3000000000', 'qa@example.com',
                               'Consignar a la cuenta de ahorros', 350000) RETURNING id""",
                    (f'CC-{MARCA}', CLIENTE))
        cid = cur.fetchone()['id']
        cur.execute("""INSERT INTO detalle_cuenta_cobro (cuenta_id, fecha_labor, descripcion, valor)
                       VALUES (%s, '2026-03-01', 'Soporte en sitio', 150000),
                              (%s, '2026-03-02', 'Mantenimiento', 200000)""", (cid, cid))
    yield cid
    with cursor() as cur:
        cur.execute('DELETE FROM detalle_cuenta_cobro WHERE cuenta_id = %s', (cid,))
        cur.execute('DELETE FROM cuentas_cobro WHERE id = %s', (cid,))


def test_pdf_de_la_cuenta_de_cobro_con_lo_guardado(cuenta, as_propietario, flask_app, monkeypatch):
    import routes.billing as rb
    contexto = {}
    real = rb.render_template

    def capturar(plantilla, **kw):
        if plantilla == 'pdf_cuenta_cobro.html':
            contexto.update(kw)
        return real(plantilla, **kw)
    monkeypatch.setattr(rb, 'render_template', capturar)

    r = as_propietario.get(f'/admin/cuenta_cobro/{cuenta}/pdf')
    assert r.status_code == 200 and r.mimetype == 'application/pdf' and r.data.startswith(b'%PDF')
    assert 'no-store' in r.headers['Cache-Control']
    assert contexto['consecutivo'] == f'05-03-2026-{cuenta}' and contexto['fecha'] == '5 de Marzo de 2026'
    assert contexto['cliente'] == {'nombre': CLIENTE, 'nit': '900123456', 'direccion': 'Calle 1', 'ciudad': 'Cali'}
    assert contexto['contractor']['nombre'] == 'Contratista QA'
    assert [(i['fecha'], i['descripcion'], i['valor']) for i in contexto['items']] == [
        ('2026-03-01', 'Soporte en sitio', 150000.0), ('2026-03-02', 'Mantenimiento', 200000.0)]
    assert contexto['total_texto'] == 'TRESCIENTOS CINCUENTA MIL PESOS M/CTE'

    # Sin sesión solo con el enlace privado; y un enlace de cotización no abre una cuenta.
    visitante = flask_app.test_client()
    assert visitante.get(f'/admin/cuenta_cobro/{cuenta}/pdf').mimetype != 'application/pdf'
    r = visitante.get(f"/doc/{_token(flask_app, 'cuenta_cobro', cuenta)}")
    assert r.status_code == 200 and r.mimetype == 'application/pdf'
    assert _token(flask_app, 'cuenta_cobro', cuenta) != _token(flask_app, 'cotizacion', cuenta)


def test_la_lista_de_cuentas_trae_pdf_whatsapp_y_enlace(cuenta, as_propietario):
    html = as_propietario.get('/admin/mis_cuentas_cobro').get_data(as_text=True)
    assert f'href="/admin/cuenta_cobro/{cuenta}/pdf"' in html
    assert 'static/cuentas_cobro/pdf' not in html
    assert 'https://wa.me/573109876543?text=' in html and 'js-copiar-enlace' in html


def test_eliminar_la_cuenta_no_borra_archivos_compartidos(cuenta, as_propietario, flask_app, cursor):
    carpeta = os.path.join(flask_app.root_path, 'static', 'cuentas_cobro', 'pdf')
    os.makedirs(carpeta, exist_ok=True)
    viejo = os.path.join(carpeta, f'CueCob_{cuenta}.pdf')
    with open(viejo, 'wb') as f:
        f.write(b'%PDF de otra tienda')
    try:
        with cursor() as cur:
            cur.execute("UPDATE cuentas_cobro SET pdf_path = %s WHERE id = %s",
                        (f'cuentas_cobro/pdf/CueCob_{cuenta}.pdf', cuenta))
        assert as_propietario.post(f'/admin/cuenta_cobro/eliminar/{cuenta}').status_code == 302
        with cursor() as cur:
            cur.execute("SELECT 1 FROM cuentas_cobro WHERE id = %s", (cuenta,))
            assert cur.fetchone() is None
        assert os.path.isfile(viejo)
    finally:
        os.remove(viejo)
