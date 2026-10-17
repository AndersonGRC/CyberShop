# -*- coding: utf-8 -*-
"""Notas adicionales de la cotización sugeridas por la IA (1.9.13.0).

- El catálogo revisado (services/notas_cotizacion.py) reconoce lo que se cotiza y arma
  notas por sección, legales en Colombia y justas: nunca abusivas, solo normas permitidas.
- La IA (services/ia_notas_cotizacion.py) parte de ese catálogo; su respuesta se revisa
  y se descarta lo que cite normas inventadas, sea abusivo o ya esté escrito.
- Solo con el módulo Asistente IA activo; al modelo no le llegan nombre ni documento.
- En el PDF las notas salen organizadas (título de sección + viñetas).
- El banco de 100 ejemplos para afinar el modelo cumple las mismas reglas."""
import json

import pytest
from flask import render_template

import routes.quotes as rq
from services import ia_notas_cotizacion as inc
from services import notas_cotizacion as nc

REPARACION = [{'cantidad': 2, 'descripcion': 'Mantenimiento preventivo de portátil', 'iva': 19},
              {'cantidad': 1, 'descripcion': 'Cambio de pantalla de portátil 15.6"', 'iva': 19}]
EMPRESA = {'nombre': 'Comercializadora Delta S.A.S.', 'documento': '901.234.567-1', 'ciudad': 'Bogotá'}
PERSONA = {'nombre': 'Laura Gómez', 'documento': '1.032.456.789', 'ciudad': 'Medellín'}


def _todas(secciones):
    return [n for s in secciones for n in s['notas']]


def _respeta_topes(secciones):
    titulos = [s['titulo'] for s in secciones]
    assert len(secciones) <= nc.MAX_SECCIONES and len(_todas(secciones)) <= nc.MAX_NOTAS
    assert all(len(s['notas']) <= nc.MAX_NOTAS_SECCION for s in secciones)
    assert titulos == sorted(titulos, key=nc.SECCIONES.index), 'secciones en el orden del PDF'
    for n in _todas(secciones):
        assert len(n) <= nc.MAX_LARGO_NOTA
        assert not nc.es_abusiva(n), n
        assert not nc.cita_norma_no_permitida(n), n


# ── Qué se cotiza y a quién ─────────────────────────────────────
@pytest.mark.parametrize('descripcion, esperada', [
    ('Mantenimiento preventivo de portátil', ['reparacion']),
    ('Instalación de cableado estructurado categoría 6', ['red']),
    ('Torta personalizada de tres pisos para 60 personas', ['alimentos']),
    ('Licencia Microsoft 365 Empresa Estándar (1 año)', ['software']),
    ('Tarjeta de video RTX 4060 nueva', []),           # un producto, no un servicio de video
])
def test_reconoce_lo_que_se_cotiza(descripcion, esperada):
    assert nc.categorias_de([{'descripcion': descripcion}]) == esperada


def test_servicio_o_producto():
    assert nc.es_servicio('Cambio de batería de celular') and nc.es_servicio('Diagnóstico de celular')
    assert not nc.es_servicio('Portátil Lenovo IdeaPad nuevo') and not nc.es_servicio('Mouse inalámbrico')


def test_empresa_o_persona():
    assert nc.tipo_cliente(EMPRESA['nombre'], '') == 'empresa'
    assert nc.tipo_cliente('Juan', '900.123.456-7') == 'empresa', 'NIT con dígito de verificación'
    assert nc.tipo_cliente(PERSONA['nombre'], PERSONA['documento']) == 'persona natural'


# ── Lo legal y lo justo ─────────────────────────────────────────
def test_solo_normas_permitidas():
    assert not nc.cita_norma_no_permitida('Garantía legal (art. 7 de la Ley 1480 de 2011).')
    assert not nc.cita_norma_no_permitida('Precios con IVA (Estatuto Tributario).')
    assert nc.cita_norma_no_permitida('Según el Decreto 1074 de 2015, no hay garantía.')
    assert nc.cita_norma_no_permitida('Aplica la Ley 2300 de 2023.')


@pytest.mark.parametrize('texto', ['El anticipo no es reembolsable.', 'No se aceptan devoluciones.',
                                   'Este producto no tiene garantía.', 'No nos hacemos responsables por daños.'])
def test_detecta_clausulas_abusivas(texto):
    assert nc.es_abusiva(texto)


def test_sugerencias_base_con_las_indicaciones_del_negocio():
    r = nc.sugerencias_base(REPARACION, EMPRESA, 'anticipo del 60 %, entrega en 8 días')
    _respeta_topes(r['secciones'])
    texto = ' '.join(_todas(r['secciones']))
    assert '60 %' in texto and '8 días' in texto
    titulos = [s['titulo'] for s in r['secciones']]
    assert 'Garantía' in titulos and 'Forma de pago' in titulos and r['avisos'] == []


def test_pedido_abusivo_se_niega_con_la_alternativa_justa():
    r = nc.sugerencias_base(REPARACION, PERSONA, 'pon que no hay garantía y el anticipo no es reembolsable')
    _respeta_topes(r['secciones'])
    assert len(r['avisos']) == 2 and all('Ley 1480' in a or 'costos' in a or 'garant' in a for a in r['avisos'])
    assert 'Garantía' in [s['titulo'] for s in r['secciones']], 'la garantía legal se mantiene'


def test_no_repite_lo_que_ya_escribio_el_negocio():
    antes = nc.sugerencias_base(REPARACION, EMPRESA)
    vigencia = next(s for s in antes['secciones'] if s['titulo'] == 'Vigencia y precios')['notas'][0]
    despues = nc.sugerencias_base(REPARACION, EMPRESA, notas_actuales='VIGENCIA Y PRECIOS\n• ' + vigencia)
    assert vigencia not in _todas(despues['secciones'])


# ── La respuesta de la IA se revisa ─────────────────────────────
def test_extraer_json_entre_texto():
    texto = 'Claro, aquí van:\n{"secciones": [{"titulo": "Garantía", "notas": ["Dura {6} meses"]}]}\nListo.'
    assert inc.extraer_json(texto)['secciones'][0]['notas'] == ['Dura {6} meses']
    assert inc.extraer_json('sin json') is None


def test_validar_descarta_lo_inventado_lo_abusivo_y_lo_repetido():
    ya = 'Precios con IVA incluido en todos los productos.'
    respuesta = {'secciones': [
        {'titulo': 'Condiciones de pago', 'notas': ['- **50 % de anticipo** y el saldo contra entrega del equipo.']},
        {'titulo': 'Garantía', 'notas': ['Según el Decreto 1074 de 2015 la garantía es de un mes.',
                                         'El anticipo no es reembolsable en ningún caso.',
                                         'Garantía de 3 meses sobre la mano de obra y los repuestos.']},
        {'titulo': 'Impuestos', 'notas': [ya, 'ok']},
    ]}
    secciones, descartadas = inc.validar(respuesta, notas_actuales=ya)
    assert descartadas == 3
    assert secciones == [
        {'titulo': 'Forma de pago', 'notas': ['50 % de anticipo y el saldo contra entrega del equipo.']},
        {'titulo': 'Garantía', 'notas': ['Garantía de 3 meses sobre la mano de obra y los repuestos.']},
    ]


def _ia(monkeypatch, texto=None, err=None, disponible=True):
    from services import ai_service as ai
    pedidos = []
    monkeypatch.setattr(ai, 'estado_ia', lambda: (disponible, 'La IA no está configurada.'))

    def _chat(system, user, **kw):
        pedidos.append({'system': system, 'user': user, **kw})
        return texto, err
    monkeypatch.setattr(ai, '_chat', _chat)
    return pedidos


RESPUESTA_IA = json.dumps({'secciones': [
    {'titulo': 'Vigencia y precios', 'notas': ['Cotización válida por 15 días calendario (arts. 845 y 846 del Código de Comercio).']},
    {'titulo': 'Forma de pago', 'notas': ['Anticipo del 60 % y saldo contra entrega del equipo reparado.']},
    {'titulo': 'Garantía', 'notas': ['La reparación tiene garantía de 3 meses sobre el trabajo y los repuestos.',
                                     'No cubre golpes, humedad ni variaciones de voltaje (art. 16 de la Ley 1480 de 2011).']},
], 'avisos': []}, ensure_ascii=False)


def test_sugerir_con_la_ia_sin_datos_del_cliente(flask_app, monkeypatch):
    pedidos = _ia(monkeypatch, texto='Aquí está: ' + RESPUESTA_IA)
    with flask_app.test_request_context('/admin/cotizar'):
        r = inc.sugerir(REPARACION, EMPRESA, 'anticipo del 60 %')
    assert r['origen'] == 'ia' and len(_todas(r['secciones'])) == 4 and r['descartadas'] == 0
    pedido = pedidos[0]
    assert pedido['tarea'] == inc.TAREA == 'cotizacion_notas'
    assert 'Delta' not in pedido['user'] and '901.234.567' not in pedido['user'], 'sin nombre ni documento'
    assert 'CLIENTE: empresa, en Bogotá' in pedido['user'] and 'Mantenimiento preventivo' in pedido['user']


@pytest.mark.parametrize('texto, err, disponible', [
    (None, None, False),                        # IA apagada o sin servidor
    (None, 'El servidor de IA no responde.', True),
    ('No sé qué responder.', None, True),       # respuesta que no sirve
])
def test_sin_ia_util_salen_las_sugerencias_base(flask_app, monkeypatch, texto, err, disponible):
    _ia(monkeypatch, texto=texto, err=err, disponible=disponible)
    with flask_app.test_request_context('/admin/cotizar'):
        r = inc.sugerir(REPARACION, PERSONA)
    assert r['origen'] == 'base' and len(_todas(r['secciones'])) >= 5
    assert 'sugerencias base' in r['avisos'][0]


def test_sin_items_no_pide_nada(flask_app, monkeypatch):
    pedidos = _ia(monkeypatch, texto=RESPUESTA_IA)
    with flask_app.test_request_context('/admin/cotizar'):
        r = inc.sugerir([{'descripcion': '  '}], PERSONA)
    assert r['origen'] == 'vacio' and not pedidos


# ── La ruta: solo con el módulo Asistente IA ────────────────────
@pytest.fixture()
def modulo_ia(flask_app):
    from database import get_db_cursor
    from services.config_tenant import set_cliente_config
    import tenant_features as tf

    with get_db_cursor() as cur:
        cur.execute("SELECT valor FROM cliente_config WHERE clave='ia_habilitado' LIMIT 1")
        fila = cur.fetchone()
    antes = fila[0] if fila else 'false'

    def poner(valor):
        with flask_app.test_request_context('/'):
            with get_db_cursor() as cur:
                set_cliente_config(cur, 'ia_habilitado', valor, descripcion='Asistente IA')
        tf._clear_cache()
    yield poner
    poner(antes)


def _login(client, usuario_id):
    with client.session_transaction() as s:
        s['usuario_id'], s['rol_id'], s['username'] = usuario_id, 2, 'PytestNotas'


PEDIDO = {'items': REPARACION, 'cliente': EMPRESA, 'indicaciones': 'anticipo del 60 %', 'notas_actuales': ''}


def test_ruta_con_el_modulo_apagado(client, modulo_ia, monkeypatch):
    modulo_ia('false')
    pedidos = _ia(monkeypatch, texto=RESPUESTA_IA)
    _login(client, 1)
    r = client.post('/admin/cotizar/sugerir-notas', json=PEDIDO)
    assert r.status_code == 403 and r.get_json()['ok'] is False and not pedidos
    assert 'id="cotIa"' not in client.get('/admin/cotizar').get_data(as_text=True), 'sin el botón de IA'


def test_ruta_con_el_modulo_activo(client, modulo_ia, monkeypatch):
    import security
    security.request_log.pop('cot-notas:1', None)
    modulo_ia('true')
    _ia(monkeypatch, texto=RESPUESTA_IA)
    _login(client, 1)
    r = client.post('/admin/cotizar/sugerir-notas', json=PEDIDO)
    datos = r.get_json()
    assert r.status_code == 200 and datos['ok'] and datos['origen'] == 'ia'
    assert [s['titulo'] for s in datos['secciones']] == ['Vigencia y precios', 'Forma de pago', 'Garantía']
    html = client.get('/admin/cotizar').get_data(as_text=True)
    assert 'id="cotIa"' in html and 'cotizar_notas_ia.js' in html and 'Sugerir notas con IA' in html


def test_ruta_pide_sesion(client):
    r = client.post('/admin/cotizar/sugerir-notas', json=PEDIDO)
    assert r.status_code in (302, 401, 403)


# ── Organizadas en el texto y en el PDF ─────────────────────────
def test_texto_organizado_ida_y_vuelta():
    secciones = [{'titulo': 'Forma de pago', 'notas': ['Anticipo del 50 %.', 'Saldo contra entrega.']},
                 {'titulo': 'Garantía', 'notas': ['Tres meses.']}]
    texto = nc.a_texto(secciones)
    assert texto == 'FORMA DE PAGO\n• Anticipo del 50 %.\n• Saldo contra entrega.\n\nGARANTÍA\n• Tres meses.'
    b = nc.bloques(texto + '\nNota suelta sin viñeta.')
    assert [x['titulo'] for x in b] == ['FORMA DE PAGO', 'GARANTÍA']
    assert b[1]['lineas'] == [{'vineta': True, 'texto': 'Tres meses.'},
                              {'vineta': False, 'texto': 'Nota suelta sin viñeta.'}]
    assert nc.bloques('Entrega:\n- 5 días <hábiles>')[0] == {
        'titulo': 'Entrega', 'lineas': [{'vineta': True, 'texto': '5 días <hábiles>'}]}


def test_pdf_con_notas_organizadas(flask_app):
    notas = 'FORMA DE PAGO\n• Anticipo del 50 %.\n• Saldo <contra> entrega.\n\nGARANTÍA\n• Tres meses.'
    datos = dict(id='COT 0000000001', fecha='1 de enero de 2026', cliente={'nombre': 'Cliente QA'},
                 items=[], total='$119.000', subtotal='$100.000', descuento='$0', iva='$19.000', logo='',
                 colores=rq._get_brand_colors(), mostrar_descuento=False, firma_empresa='',
                 notas=notas, notas_bloques=rq._bloques_notas(notas))
    with flask_app.test_request_context('/'):
        html = render_template('pdf_quote.html', **datos)
    assert html.count('class="notas-seccion"') == 2 and html.count('class="notas-vineta"') == 3
    assert 'Saldo &lt;contra&gt; entrega.' in html, 'texto escapado'
    assert html.index('>TOTAL<') < html.index('FORMA DE PAGO') < html.index('>Firma autorizada<')


# ── El banco de 100 ejemplos para afinar el modelo ──────────────
def test_banco_de_entrenamiento():
    from tools import ia_notas_dataset as ds
    escenarios = ds.escenarios()
    assert len(escenarios) == 100
    abusivos = 0
    for e in escenarios:
        fila, ctx = ds.ejemplo(e)
        system, user, assistant = (m['content'] for m in fila['messages'])
        assert [m['role'] for m in fila['messages']] == ['system', 'user', 'assistant']
        assert e['negocio'] in system and e['cliente']['nombre'] not in user
        respuesta = json.loads(assistant)
        _respeta_topes(respuesta['secciones'])
        assert len(_todas(respuesta['secciones'])) >= 8
        assert bool(respuesta['avisos']) == bool(ctx['avisos'])
        abusivos += bool(ctx['avisos'])
    assert abusivos >= 20, 'casos donde el negocio pide algo abusivo y el modelo debe negarse'
