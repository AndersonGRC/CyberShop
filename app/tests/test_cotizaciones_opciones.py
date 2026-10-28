# -*- coding: utf-8 -*-
"""Cotizaciones con opciones (1.9.18.0): alternativas que el cliente compara y elige.

- Ej.: dos computadores armados. Cada opción sale en el PDF con su propio total
  (sus ítems + los comunes, como instalación o transporte) y NO se suman entre sí.
- El orden de los ítems es el del formulario: primero los comunes y luego cada
  opción con los suyos.
- Al aprobar hay que decir qué opción aceptó el cliente: a contabilidad va el total
  de esa opción y la factura electrónica lleva solo lo común y esa opción. En bloque
  no se sabe cuál, así que esas cotizaciones se omiten.
- Las cotizaciones sin opciones no cambian.
Contra la base de pruebas; lo que se crea se borra al final."""
import os
import uuid

import pytest
from flask import render_template

import routes.quotes as rq

MARCA = uuid.uuid4().hex[:8]
CLIENTE = f'Cliente opciones {MARCA}'


def _linea(total, opcion=None):
    return {'opcion': opcion, 'subtotal': total, 'descuento': 0.0, 'iva': 0.0, 'total': total}


def test_cada_opcion_suma_lo_comun_y_no_las_otras():
    lineas = [_linea(100, 'Intel'), _linea(50), _linea(300, 'AMD'), _linea(20, 'Intel')]
    comunes, opciones = rq._agrupar_por_opcion(lineas)
    assert [l['total'] for l in comunes] == [50]
    assert [(o['titulo'], o['total']) for o in opciones] == [('Intel', 170), ('AMD', 350)], \
        'en el orden en que aparecen, cada una con lo común'
    assert rq._agrupar_por_opcion([_linea(10), _linea(5)])[1] == [], 'sin opciones, como siempre'


def test_nombre_de_la_opcion():
    assert rq._titulo_opcion('  Opción 1 —   Equipo  gamer ') == 'Opción 1 — Equipo gamer'
    assert rq._titulo_opcion('') is None and rq._titulo_opcion(None) is None
    assert len(rq._titulo_opcion('x' * 200)) == rq.OPCION_MAX


def test_al_editar_sale_solo_el_nombre_que_escribio():
    """El número lo pone el formulario según el orden; el campo muestra solo el nombre."""
    assert rq._nombre_de_opcion('Opción 2 — Equipo gamer') == 'Equipo gamer'
    assert rq._nombre_de_opcion('Opción 1') == ''
    assert rq._nombre_de_opcion('Plan básico') == 'Plan básico', 'otro formato: tal cual'


# ── El PDF ──────────────────────────────────────────────────────
def _pdf(flask_app, **extra):
    datos = dict(id='COT 0000000001', fecha='1 de enero de 2026', cliente={'nombre': 'Cliente QA'},
                 items=[], total='$119.000', subtotal='$100.000', descuento='$0', iva='$19.000',
                 mostrar_descuento=False, logo='', colores=rq._get_brand_colors())
    datos.update(extra)
    with flask_app.test_request_context('/'):
        return render_template('pdf_quote.html', **datos)


def _opcion_pdf(titulo, descripcion, total):
    return {'titulo': titulo, 'items': [{'descripcion': descripcion, 'cantidad': 1, 'precio_unitario': total,
                                         'subtotal': total, 'imagen_local_path': None}],
            'subtotal': total, 'descuento': '$0', 'mostrar_descuento': False, 'iva': '$0', 'total': total}


def test_pdf_con_opciones_un_total_por_opcion_y_sin_gran_total(flask_app):
    html = _pdf(flask_app, items=[{'descripcion': 'Instalación de Windows', 'cantidad': 1,
                                   'precio_unitario': '$50.000', 'subtotal': '$50.000', 'imagen_local_path': None}],
                opciones=[_opcion_pdf('Opción 1 — Intel', 'Core i5 12400', '$2.050.000'),
                          _opcion_pdf('Opción 2 — AMD', 'Ryzen 5 5600', '$1.850.000')])
    assert '>Incluido en todas las opciones<' in html
    assert '>TOTAL OPCIÓN 1 — INTEL<' in html and '>TOTAL OPCIÓN 2 — AMD<' in html
    assert '>TOTAL<' not in html, 'no hay un total que sume las opciones'
    assert 'Sus valores no se suman entre sí' in html
    assert (html.index('Instalación de Windows') < html.index('Core i5 12400') < html.index('Ryzen 5 5600')), \
        'lo común arriba y las opciones en su orden'
    assert '(con lo incluido en todas las opciones)' in html


def test_pdf_sin_comunes_ni_opciones(flask_app):
    solo_opciones = _pdf(flask_app, opciones=[_opcion_pdf('Básico', 'Equipo A', '$1'),
                                              _opcion_pdf('Pro', 'Equipo B', '$2')])
    assert 'Incluido en todas' not in solo_opciones and '(con lo incluido' not in solo_opciones
    assert '>TOTAL BÁSICO<' in solo_opciones and '>TOTAL PRO<' in solo_opciones
    # Sin opciones (y la copia de la plantilla del escritorio, que no las manda): como antes.
    for html in (_pdf(flask_app, opciones=[]), _pdf(flask_app)):
        assert '>TOTAL<' in html and 'opcion-titulo">' not in html


# ── De punta a punta ────────────────────────────────────────────
@pytest.fixture()
def generar(as_propietario, cursor, monkeypatch, flask_app):
    """POST al generador como el dueño, sin CRM, guardando lo que recibe el PDF."""
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
    creadas = []

    def enviar(items, cotizacion_id=None):
        """items: [(descripcion, precio, opcion)] en el orden del formulario."""
        datos = {'cliente_nombre': CLIENTE,
                 'descripcion[]': [d for d, _, _ in items], 'cantidad[]': ['1'] * len(items),
                 'precio[]': [str(p) for _, p, _ in items], 'descuento[]': ['0'] * len(items),
                 'iva[]': ['0'] * len(items), 'opcion[]': [o for _, _, o in items]}
        if cotizacion_id:
            datos['cotizacion_id'] = str(cotizacion_id)
        r = as_propietario.post('/admin/cotizar/generar', data=datos)
        assert r.status_code == 200 and r.mimetype == 'application/pdf', r.get_data(as_text=True)[:300]
        with cursor() as cur:
            cur.execute("SELECT * FROM cotizaciones WHERE cliente_nombre = %s ORDER BY id DESC LIMIT 1", (CLIENTE,))
            fila = dict(cur.fetchone())
            cur.execute("SELECT descripcion, opcion, subtotal FROM detalle_cotizacion "
                        "WHERE cotizacion_id = %s ORDER BY id", (fila['id'],))
            lineas = [dict(l) for l in cur.fetchall()]
        if fila['id'] not in creadas:
            creadas.append(fila['id'])
        return fila, lineas, dict(contexto)
    yield enviar
    with cursor() as cur:
        cur.execute('DELETE FROM detalle_cotizacion WHERE cotizacion_id = ANY(%s)', (creadas,))
        cur.execute('DELETE FROM cotizaciones WHERE id = ANY(%s)', (creadas,))
    carpeta = os.path.join(flask_app.root_path, 'static', 'cotizaciones', 'pdf')
    for cid in creadas:
        archivo = os.path.join(carpeta, f'Cotizacion_{cid}.pdf')
        if os.path.isfile(archivo):
            os.remove(archivo)


COMPUTADOR = [('Core i5 12400', 1000000, 'Opción 1 — Intel'),
              ('Instalación de Windows', 50000, ''),
              ('Ryzen 5 5600', 800000, 'Opción 2 — AMD'),
              ('RAM 16 GB', 200000, 'Opción 1 — Intel')]


def test_guarda_cada_item_en_su_opcion_y_el_total_es_desde(generar):
    fila, lineas, pdf = generar(COMPUTADOR)
    assert [(l['descripcion'], l['opcion']) for l in lineas] == [
        ('Instalación de Windows', None),
        ('Core i5 12400', 'Opción 1 — Intel'), ('RAM 16 GB', 'Opción 1 — Intel'),
        ('Ryzen 5 5600', 'Opción 2 — AMD')], 'comunes primero y cada opción con los suyos'
    assert float(fila['total']) == 850000.0, 'sin aprobar, «desde» la más barata (AMD + instalación)'
    assert [i['descripcion'] for i in pdf['items']] == ['Instalación de Windows']
    assert [(o['titulo'], len(o['items'])) for o in pdf['opciones']] == [('Opción 1 — Intel', 2), ('Opción 2 — AMD', 1)]
    assert [o['total'] for o in pdf['opciones']] == [rq.formatear_moneda(1250000.0), rq.formatear_moneda(850000.0)]


def test_sin_opciones_todo_suma_como_siempre(generar):
    fila, lineas, pdf = generar([(d, p, '') for d, p, _ in COMPUTADOR])
    assert float(fila['total']) == 2050000.0 and pdf['opciones'] == []
    assert [l['descripcion'] for l in lineas] == [d for d, _, _ in COMPUTADOR], 'en el orden del formulario'
    assert all(l['opcion'] is None for l in lineas)


def test_formulario_viejo_sin_el_campo_opcion(as_propietario, generar, cursor):
    """Quien envía el formulario sin `opcion[]` (una pestaña abierta antes de actualizar)."""
    r = as_propietario.post('/admin/cotizar/generar', data={
        'cliente_nombre': CLIENTE, 'descripcion[]': ['A', 'B'], 'cantidad[]': ['1', '1'],
        'precio[]': ['10', '20'], 'descuento[]': ['0', '0'], 'iva[]': ['0', '0']})
    assert r.status_code == 200
    fila, _, _ = generar([('C', 5, '')])      # registra la limpieza; la anterior se borra a mano
    with cursor() as cur:
        cur.execute("SELECT id, total FROM cotizaciones WHERE cliente_nombre = %s AND id <> %s",
                    (CLIENTE, fila['id']))
        vieja = cur.fetchone()
        assert float(vieja['total']) == 30.0
        cur.execute('DELETE FROM detalle_cotizacion WHERE cotizacion_id = %s', (vieja['id'],))
        cur.execute('DELETE FROM cotizaciones WHERE id = %s', (vieja['id'],))


def test_editar_muestra_cada_opcion_en_su_bloque(generar, as_propietario):
    fila, _, _ = generar(COMPUTADOR)
    html = as_propietario.get(f"/admin/cotizar/editar/{fila['id']}").get_data(as_text=True)
    comunes = html.split('id="items-container"', 1)[1].split('id="opciones-container"', 1)[0]
    opciones = html.split('id="opciones-container"', 1)[1].split('id="items-total"', 1)[0]
    assert 'value="Instalación de Windows"' in comunes and 'Core i5' not in comunes
    assert opciones.count('class="cot-opcion"') == 2
    intel, amd = opciones.split('class="cot-opcion"')[1:]
    assert 'value="Intel"' in intel and 'value="Core i5 12400"' in intel and 'value="RAM 16 GB"' in intel
    assert 'value="AMD"' in amd and 'value="Ryzen 5 5600"' in amd
    # La plantilla de un ítem nuevo trae el inventario (la macro ve los productos).
    plantilla = html.split('id="item-template"', 1)[1].split('</template>', 1)[0]
    assert 'name="opcion[]"' in plantilla and 'Seleccionar de Inventario' in plantilla

    fila, lineas, _ = generar(COMPUTADOR[:2] + [('Ryzen 7 5700X', 1100000, 'Opción 2 — AMD')],
                              cotizacion_id=fila['id'])
    assert [l['descripcion'] for l in lineas] == ['Instalación de Windows', 'Core i5 12400', 'Ryzen 7 5700X']
    assert float(fila['total']) == 1050000.0


# ── Aprobar ─────────────────────────────────────────────────────
@pytest.fixture()
def contabilidad(monkeypatch):
    import routes.contabilidad as conta
    registros = []
    monkeypatch.setattr(conta, 'sincronizar_movimiento_referencia', lambda **kw: registros.append(kw))
    return registros


def test_aprobar_exige_la_opcion_y_registra_su_total(generar, as_propietario, cursor, contabilidad):
    fila, _, _ = generar(COMPUTADOR)
    r = as_propietario.post(f"/admin/cotizar/aprobar/{fila['id']}")
    assert r.status_code == 302 and not contabilidad
    with cursor() as cur:
        cur.execute("SELECT COALESCE(estado, 'pendiente') AS estado FROM cotizaciones WHERE id = %s", (fila['id'],))
        assert cur.fetchone()['estado'] == 'pendiente', 'sin decir la opción no se aprueba'
    with as_propietario.session_transaction() as s:
        assert 'elige la que aceptó el cliente' in str(s.get('_flashes'))

    lista = as_propietario.get('/admin/mis_cotizaciones').get_data(as_text=True)
    assert '<option value="Opción 1 — Intel">' in lista and '2 opciones (no se suman)' in lista

    as_propietario.post(f"/admin/cotizar/aprobar/{fila['id']}", data={'opcion': 'Opción 1 — Intel'})
    with cursor() as cur:
        cur.execute('SELECT estado, total, opcion_elegida FROM cotizaciones WHERE id = %s', (fila['id'],))
        cot = cur.fetchone()
    assert cot['estado'] == 'aprobada' and cot['opcion_elegida'] == 'Opción 1 — Intel'
    assert float(cot['total']) == 1250000.0
    assert [c['monto'] for c in contabilidad] == [1250000.0], 'a contabilidad va la opción elegida'
    assert 'Opción elegida: Opción 1 — Intel' in as_propietario.get('/admin/mis_cotizaciones').get_data(as_text=True)


def test_aprobar_en_bloque_omite_las_que_tienen_opciones(generar, as_propietario, cursor, contabilidad):
    con, _, _ = generar(COMPUTADOR)
    sin, _, _ = generar([('Mantenimiento', 90000, '')])
    as_propietario.post('/admin/cotizar/bulk_accion', data={'accion': 'aprobar', 'ids': [con['id'], sin['id']]})
    with cursor() as cur:
        cur.execute("SELECT id, COALESCE(estado, 'pendiente') AS estado FROM cotizaciones WHERE id = ANY(%s)", ([con['id'], sin['id']],))
        estados = {f['id']: f['estado'] for f in cur.fetchall()}
    assert estados == {con['id']: 'pendiente', sin['id']: 'aprobada'}
    assert [c['monto'] for c in contabilidad] == [90000.0]


def test_la_factura_lleva_lo_comun_y_la_opcion_elegida(generar, as_propietario, contabilidad):
    from routes.factura_electronica import construir_json_cotizacion
    fila, _, _ = generar(COMPUTADOR)
    as_propietario.post(f"/admin/cotizar/aprobar/{fila['id']}", data={'opcion': 'Opción 2 — AMD'})
    doc = construir_json_cotizacion(fila['id'])
    assert sorted(i['descripcion'] for i in doc['items']) == ['Instalación de Windows', 'Ryzen 5 5600']
