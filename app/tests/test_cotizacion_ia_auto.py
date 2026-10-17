# -*- coding: utf-8 -*-
"""Cotización generada por la IA con lo que mandó el cliente (1.9.14.0).

- Lo que llega del navegador se valida y recorta (imágenes, textos, margen).
- Los precios los pone Python, nunca la IA, y cada uno dice de dónde sale: catálogo →
  documento o cotización anterior → historial → costo + margen → internet (nube) → vacío.
- La nube solo se consulta para lo que quedó sin precio, en una llamada corta, sin datos
  del cliente, y lo consultado se recuerda (no se paga dos veces).
- El recorrido muestra el plan y cada paso; sin el módulo Asistente IA no hay nada."""
import json
from datetime import datetime

import pytest

from services import ia_cotizacion_auto as auto

PRODUCTOS = [
    {'id': 1, 'nombre': 'Mouse inalámbrico Logitech M170', 'referencia': 'M170', 'precio': 45000.0, 'costo': 30000.0,
     'impuesto': 'IVA 19%', 'stock': 10},
    {'id': 2, 'nombre': 'Cable UTP categoría 6 (metro)', 'referencia': '', 'precio': None, 'costo': 2000.0,
     'impuesto': '', 'stock': 300},
    {'id': 3, 'nombre': 'Disco sólido SSD 480 GB', 'referencia': 'SSD480', 'precio': 150000.0, 'costo': 170000.0,
     'impuesto': '', 'stock': 2},
]
LINEAS = [{'descripcion': 'Mantenimiento preventivo de portátil', 'precio_unitario': 80000, 'cantidad': 1,
           'iva_porc': 19, 'cotizacion_id': 41, 'fecha': datetime(2026, 9, 3), 'cliente_nombre': 'Laura Gómez',
           'cliente_telefono': '3001234567'}]


def _item(descripcion, **extra):
    return {'descripcion': descripcion, 'cantidad': 2, 'tipo': 'producto', 'iva': None, 'precio_referencia': None,
            'fuente_precio': '', 'costo': None, 'por_que': '', 'sugerido': False, **extra}


# ── Lo que llega del navegador ──────────────────────────────────
def test_entrada_valida():
    e = auto.leer_entrada({'archivos': [{'nombre': 'chat.png', 'tipo': 'imagen', 'texto': 'Cliente: hola\n\n\n\nNegocio: ¿qué necesitas?',
                                         'imagen': 'data:image/jpeg;base64,' + 'A' * 400}],
                           'margen': '250', 'cliente': {'nombre': 'Laura', 'otro': 'x'}})
    assert e['margen'] == 200 and e['consultar_nube'] is True
    assert e['archivos'][0]['texto'] == 'Cliente: hola\n\nNegocio: ¿qué necesitas?', 'conserva los saltos de línea'
    assert e['archivos'][0]['imagen'] == 'A' * 400 and set(e['cliente']) == {'nombre', 'documento', 'ciudad', 'telefono'}
    assert auto.leer_entrada({'conversacion': 'necesito 3 cámaras', 'consultar_nube': False})['consultar_nube'] is False


@pytest.mark.parametrize('datos, mensaje', [
    ({}, 'Adjunta'),
    ({'conversacion': 'hola'}, 'Adjunta'),
    ({'archivos': [{'nombre': 'x.png', 'imagen': 'A' * (auto.MAX_IMAGEN_B64 + 10)}]}, 'muy pesada'),
    ({'archivos': [{'nombre': 'x.png', 'imagen': '%%%no-es-base64%%%' * 30}]}, 'no se pudo leer'),
    (['no', 'es', 'un', 'objeto'], 'inválida'),
])
def test_entrada_invalida(datos, mensaje):
    with pytest.raises(auto.EntradaInvalida, match=mensaje):
        auto.leer_entrada(datos)


# ── Catálogo e historial ────────────────────────────────────────
def test_busca_en_el_catalogo():
    assert auto.buscar_en_catalogo('Mouse inalámbrico', PRODUCTOS)[0]['id'] == 1
    assert auto.buscar_en_catalogo('Cambiar disco por SSD480 del cliente', PRODUCTOS)[0]['id'] == 3, 'por referencia'
    assert auto.buscar_en_catalogo('Instalación de cámaras de seguridad', PRODUCTOS)[0] is None
    assert auto.buscar_en_historial('mantenimiento preventivo portátil', LINEAS)['cotizacion_id'] == 41
    assert auto.iva_habitual(LINEAS) is True and auto.iva_habitual([]) is None


def test_cotizaciones_anteriores_del_cliente():
    assert [n for n, _ in auto.cotizaciones_del_cliente({'nombre': 'laura gomez'}, LINEAS)] == [41]
    assert [n for n, _ in auto.cotizaciones_del_cliente({'telefono': '+57 300 123 4567'}, LINEAS)] == [41]
    assert auto.cotizaciones_del_cliente({'nombre': 'Ana'}, LINEAS) == []


# ── Precios: los pone Python, con su fuente ─────────────────────
def test_cada_precio_dice_de_donde_sale():
    items = auto.poner_precios([
        _item('Mouse inalámbrico'),                                       # catálogo
        _item('Licencia antivirus', precio_referencia=95000, fuente_precio='Cotización del cliente (PDF)'),
        _item('Mantenimiento preventivo de portátil'),                     # historial
        _item('Cable UTP categoría 6 metro'),                              # costo + margen
        _item('Instalación de cámaras de seguridad'),                      # nada
    ], 30, PRODUCTOS, LINEAS, iva_defecto=False)
    fuentes = [i['fuente'] for i in items]
    assert fuentes[0] == 'Catálogo: Mouse inalámbrico Logitech M170' and items[0]['precio'] == 45000
    assert fuentes[1] == 'Cotización del cliente (PDF)' and items[1]['precio'] == 95000
    assert fuentes[2] == 'Tu cotización 41 del 03/09/2026' and items[2]['precio'] == 80000
    assert fuentes[3] == 'Costo $2.000 + 30 % de margen' and items[3]['precio'] == 2600
    assert items[4]['precio'] == 0 and items[4]['avisos'] == ['Falta el precio']
    assert items[0]['iva'] is True, 'el producto del catálogo tiene IVA 19 %'
    assert items[4]['iva'] is False, 'sin dato: lo que el negocio suele hacer'
    assert items[0]['descripcion'] == 'Mouse inalámbrico', 'se conserva lo que pidió el cliente'


def test_avisa_perdidas_y_margenes_altos():
    [ssd] = auto.poner_precios([_item('Disco sólido SSD 480 GB')], 30, PRODUCTOS, [])
    assert 'Por debajo del costo ($170.000)' in ssd['avisos']
    caro = auto.poner_precios([_item('Mouse inalámbrico')], 10,
                              [{**PRODUCTOS[0], 'precio': 90000.0}], [])[0]
    assert caro['margen_real'] == 200.0 and any('justo' in a for a in caro['avisos'])


def test_precio_de_internet_sin_margen_encima():
    [item] = auto.poner_precios([_item('Instalación de cámaras de seguridad')], 30, PRODUCTOS, [])
    auto.aplicar_precio_de_mercado(item, 349_950, 'tienda.com.co')
    assert item['precio'] == 350_000 and item['fuente'] == 'Precio de mercado en internet (tienda.com.co)'
    assert item['avisos'] == ['Referencia de internet: verifícala']


def test_totales_y_ganancia():
    items = auto.poner_precios([_item('Mouse inalámbrico'), _item('Instalación de cámaras')], 30, PRODUCTOS, [])
    assert auto.totales(items) == {'subtotal': 90000, 'iva': 17100, 'total': 107100, 'ganancia_estimada': 30000}


# ── El plan de la IA se revisa ──────────────────────────────────
def test_validar_plan():
    plan = auto.validar_plan({'cliente': {'nombre': 'Laura', 'telefono': 3001234567},
                              'items': [{'descripcion': 'Portátil', 'cantidad': '2.6', 'tipo': 'Servicio técnico',
                                         'precio_referencia': -5, 'iva': 'si'},
                                        {'descripcion': 'x'}, 'basura'],
                              'condiciones': ['anticipo 50 %', 7], 'dudas': ['¿Qué marca?']})
    assert plan['items'] == [{'descripcion': 'Portátil', 'cantidad': 3, 'tipo': 'servicio', 'iva': None,
                              'precio_referencia': None, 'fuente_precio': '', 'costo': None, 'por_que': '',
                              'sugerido': False}]
    assert plan['cliente']['telefono'] == '3001234567' and plan['condiciones'] == ['anticipo 50 %']
    assert auto.validar_plan({'items': []}) is None and auto.validar_plan('nada') is None
    # Medido con el modelo real: repetía la cantidad dentro de la descripción.
    otro = auto.validar_plan({'items': [{'descripcion': 'Punto de red RJ45 Cat6 (12 unidades)', 'cantidad': 12},
                                        {'descripcion': '3 x Switch 16 puertos', 'cantidad': 3}]})
    assert [i['descripcion'] for i in otro['items']] == ['Punto de red RJ45 Cat6', 'Switch 16 puertos']


def test_peticion_al_modelo():
    texto = auto.peticion_plan([{'nombre': 'chat.png', 'tipo': 'imagen', 'texto': 'Cliente: 2 mouse'}],
                               PRODUCTOS[:1], [(41, LINEAS)], {'nombre': 'Laura', 'ciudad': ''})
    assert 'Cliente: 2 mouse' in texto and 'Cotización 41 (03/09/2026)' in texto
    assert '- Mouse inalámbrico Logitech M170 | $45.000' in texto and '"ciudad"' not in texto


# ── El recorrido completo ────────────────────────────────────────
PLAN = {'cliente': {'nombre': 'Laura Gómez', 'telefono': '3001234567', 'ciudad': 'Medellín'},
        'resumen': 'Pide dos mouse y la instalación de 4 cámaras.',
        'items': [{'descripcion': 'Mouse inalámbrico', 'cantidad': 2, 'por_que': '«necesito 2 mouse»'},
                  {'descripcion': 'Instalación de cámaras de seguridad', 'cantidad': 4, 'tipo': 'servicio'}],
        'condiciones': ['El transporte fuera de Medellín se cobra aparte'], 'dudas': ['¿Las cámaras son para exterior?']}


@pytest.fixture()
def simulado(monkeypatch):
    llamadas = {'vision': 0, 'nube': [], 'razonar': []}

    def mirar(nombre, imagen, ocr):
        llamadas['vision'] += 1
        return 'Cliente: necesito 2 mouse y que me instalen 4 cámaras', None

    def razonar(sistema, peticion):
        llamadas['razonar'].append(peticion)
        return 'Listo: ' + json.dumps(PLAN, ensure_ascii=False), None

    def mercado(descripciones, ciudad):
        llamadas['nube'].append(descripciones)
        return {0: (349_950, 'tienda.com.co')}, None

    monkeypatch.setattr(auto, 'vision_disponible', lambda: (True, ''))
    monkeypatch.setattr(auto, 'liberar_vision', lambda: llamadas.__setitem__('liberada', True))
    monkeypatch.setattr(auto, 'mirar_imagen', mirar)
    monkeypatch.setattr(auto, '_razonar', razonar)
    monkeypatch.setattr(auto, 'consultar_mercado', mercado)
    monkeypatch.setattr(auto, 'catalogo', lambda: PRODUCTOS)
    monkeypatch.setattr(auto, 'historial', lambda limite=1500: LINEAS)
    return llamadas


def _correr(flask_app, entrada):
    with flask_app.test_request_context('/admin/cotizar/ia/generar'):
        return list(auto.generar(auto.leer_entrada(entrada)))


ENTRADA = {'archivos': [{'nombre': 'chat.png', 'tipo': 'imagen', 'texto': 'necesito 2 mouse', 'imagen': 'A' * 400}],
           'margen': 30}


def test_recorrido_completo(flask_app, simulado):
    eventos = _correr(flask_app, ENTRADA)
    assert eventos[0] == ('plan', [{'id': i, 'titulo': t} for i, t in auto.PASOS])
    finales = {d['id']: d['estado'] for t, d in eventos if t == 'paso'}
    assert finales == {'leer': 'listo', 'vision': 'listo', 'contexto': 'listo', 'razonar': 'listo',
                       'precios': 'listo', 'mercado': 'listo', 'notas': 'listo'}
    tipo, r = eventos[-1]
    assert tipo == 'resultado' and simulado['vision'] == 1
    assert simulado.get('liberada'), 'la visión sale de la tarjeta antes del análisis profundo'
    assert [(i['descripcion'], i['precio']) for i in r['items']] == [('Mouse inalámbrico', 45000),
                                                                    ('Instalación de cámaras de seguridad', 350000)]
    assert simulado['nube'] == [['Instalación de cámaras de seguridad']], 'a la nube solo lo que faltaba'
    assert 'Cliente: necesito 2 mouse' in simulado['razonar'][0], 'la transcripción de la visión llega al análisis'
    assert '•' in r['notas'] and 'El transporte fuera de Medellín se cobra aparte.' in r['notas']
    assert r['dudas'] == ['¿Las cámaras son para exterior?'] and r['cliente']['nombre'] == 'Laura Gómez'


def test_sin_faltantes_no_se_usa_la_nube(flask_app, simulado, monkeypatch):
    monkeypatch.setattr(auto, '_razonar', lambda s, p: (json.dumps({**PLAN, 'items': PLAN['items'][:1]}), None))
    eventos = _correr(flask_app, ENTRADA)
    mercado = [d for t, d in eventos if t == 'paso' and d['id'] == 'mercado'][-1]
    assert mercado['estado'] == 'omitido' and 'sin costo' in mercado['detalle'] and simulado['nube'] == []


def test_la_nube_se_puede_apagar(flask_app, simulado):
    eventos = _correr(flask_app, {**ENTRADA, 'consultar_nube': False})
    assert simulado['nube'] == [] and eventos[-1][1]['items'][1]['precio'] == 0


def test_sin_vision_sigue_con_el_ocr(flask_app, simulado, monkeypatch):
    monkeypatch.setattr(auto, 'vision_disponible', lambda: (False, 'el modelo de visión no está instalado'))
    eventos = _correr(flask_app, ENTRADA)
    vision = [d for t, d in eventos if t == 'paso' and d['id'] == 'vision'][-1]
    assert vision['estado'] == 'omitido' and 'no está instalado' in vision['detalle']
    assert simulado['vision'] == 0 and 'necesito 2 mouse' in simulado['razonar'][0]
    assert eventos[-1][0] == 'resultado'


def test_si_la_ia_no_sirve_lo_dice(flask_app, simulado, monkeypatch):
    monkeypatch.setattr(auto, '_razonar', lambda s, p: (None, 'El análisis profundo corre en el equipo de IA y está apagado.'))
    eventos = _correr(flask_app, ENTRADA)
    assert eventos[-1][0] == 'error' and 'apagado' in eventos[-1][1]
    assert [d for t, d in eventos if t == 'paso' and d['id'] == 'razonar'][-1]['estado'] == 'error'


def test_en_hilo_emite_latidos(flask_app, monkeypatch):
    import time as _time
    with flask_app.test_request_context('/'):
        gen = auto.en_hilo(lambda: (_time.sleep(0.25), 'hecho')[1], cada=0.05)
        latidos = 0
        try:
            while True:
                next(gen)
                latidos += 1
        except StopIteration as fin:
            assert fin.value == 'hecho' and latidos >= 2


# ── La consulta de precios a la nube ────────────────────────────
class _Respuesta:
    status_code = 200

    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    def json(self):
        return self._cuerpo


def test_buscar_precios_en_la_nube(flask_app, monkeypatch):
    from services import ia_nube
    enviados, contados = [], []
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': True)
    monkeypatch.setattr(ia_nube, '_sumar_uso', lambda e, s: contados.append((e, s)))
    monkeypatch.setattr(ia_nube, '_cfg', lambda clave, defecto=None: {'AI_NUBE_API_KEY': 'k'}.get(clave, defecto))

    def post(url, headers, json, timeout):
        enviados.append(json)
        return _Respuesta({'content': [{'type': 'server_tool_use'}, {'type': 'text', 'text': 'Aquí: [{"n":1,"precio":350000,'
                           '"fuente":"tienda.com.co"},{"n":2,"precio":null,"fuente":""}]'}],
                           'usage': {'input_tokens': 900, 'output_tokens': 60, 'server_tool_use': {'web_search_requests': 2}}})
    monkeypatch.setattr(ia_nube.requests, 'post', post)
    ia_nube._PRECIOS_RECORDADOS.clear()
    with flask_app.test_request_context('/'):
        hallados, motivo = ia_nube.buscar_precios(['Cámara IP exterior 4 MP', 'Instalación especial'], 'Medellín')
        assert motivo is None and hallados == {0: (350000.0, 'tienda.com.co')}
        cuerpo = enviados[0]
        assert cuerpo['messages'][0]['content'] == '1. Cámara IP exterior 4 MP\n2. Instalación especial'
        assert cuerpo['tools'][0]['max_uses'] == 2 and cuerpo['tools'][0]['user_location']['city'] == 'Medellín'
        assert cuerpo['max_tokens'] <= 800
        assert contados == [(900 + 2 * 10_000, 60)], 'cada búsqueda (US$0,01) también se cuenta'
        # Lo ya consultado hoy no se vuelve a pagar (ni lo encontrado ni lo no encontrado).
        otra, _ = ia_nube.buscar_precios(['Cámara IP exterior 4 MP', 'instalacion especial'], 'Medellín')
        assert otra == {0: (350000.0, 'tienda.com.co')} and len(enviados) == 1
    ia_nube._PRECIOS_RECORDADOS.clear()


def test_sin_presupuesto_no_llama(flask_app, monkeypatch):
    from services import ia_nube
    monkeypatch.setattr(ia_nube, 'disponible', lambda canal='panel': False)
    monkeypatch.setattr(ia_nube.requests, 'post', lambda *a, **k: pytest.fail('no debía llamar'))
    with flask_app.test_request_context('/'):
        hallados, motivo = ia_nube.buscar_precios(['Algo'])
    assert hallados == {} and 'tope de gasto' in motivo


def test_a_la_nube_no_van_datos_del_cliente(monkeypatch):
    from services import ia_nube
    vistos = []
    monkeypatch.setattr(ia_nube, 'buscar_precios', lambda d, c: (vistos.append(d), ({}, None))[1])
    auto.consultar_mercado(['Reparación del portátil de laura@correo.com, cel 3001234567'], 'Cali')
    assert '3001234567' not in vistos[0][0] and 'laura@correo.com' not in vistos[0][0]


# ── El banco de 100 ejemplos para afinar el análisis ────────────
def test_banco_de_entrenamiento():
    from tools import ia_cotizacion_dataset as ds
    escenarios = ds.escenarios()
    assert len(escenarios) == 100
    con_previa = con_catalogo = 0
    for e in escenarios:
        fila = ds.ejemplo(e)
        system, user, assistant = (m['content'] for m in fila['messages'])
        assert e['negocio'] in system and user.startswith('LO QUE MANDÓ EL CLIENTE:')
        plan = auto.validar_plan(json.loads(assistant))
        assert plan is not None and plan['dudas'], 'la respuesta ideal es un plan válido y deja dudas'
        assert json.loads(assistant)['items'] == plan['items'], 'nada que limpiar: ya viene en el formato exacto'
        for x in plan['items']:
            assert x['por_que'].startswith('«'), 'cada ítem dice por qué'
            assert x['precio_referencia'] is None or 'Cotización' in x['fuente_precio'], 'precios solo con fuente'
        con_previa += any(x['precio_referencia'] for x in plan['items'])
        con_catalogo += bool(e['relacionados'])
    assert con_previa >= 20 and con_catalogo >= 40


# ── La ruta y la pantalla ───────────────────────────────────────
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


def _login(client):
    with client.session_transaction() as s:
        s['usuario_id'], s['rol_id'], s['username'] = 1, 2, 'PytestCotIA'


def _hasta_el_fin(client, trabajo, segundos=20):
    import time as _time
    fin = _time.time() + segundos
    while _time.time() < fin:
        d = client.get(f'/admin/cotizar/ia/estado/{trabajo}').get_json()
        if d['fin']:
            return d['eventos']
        _time.sleep(0.1)
    pytest.fail('el análisis no terminó')


def test_cancelar_el_analisis(client, modulo_ia, simulado, monkeypatch):
    import security
    import time as _time
    security.request_log.pop('cot-ia:1', None)

    def lento(sistema, peticion):
        _time.sleep(1.5)
        return json.dumps(PLAN, ensure_ascii=False), None
    monkeypatch.setattr(auto, '_razonar', lento)
    modulo_ia('true')
    _login(client)
    trabajo = client.post('/admin/cotizar/ia/generar', json={'conversacion': 'Cliente: necesito 2 mouse'}).get_json()['trabajo']
    assert client.post(f'/admin/cotizar/ia/cancelar/{trabajo}').get_json()['ok']
    eventos = _hasta_el_fin(client, trabajo)
    assert eventos[-1] == {'e': 'error', 'd': 'Análisis detenido.'}
    assert not any(e['e'] == 'resultado' for e in eventos)
    assert client.post('/admin/cotizar/ia/cancelar/noexiste1234567890').status_code == 404


def test_ruta_sin_el_modulo(client, modulo_ia):
    modulo_ia('false')
    _login(client)
    r = client.post('/admin/cotizar/ia/generar', json={'conversacion': 'necesito 2 mouse inalámbricos'})
    assert r.status_code == 403
    html = client.get('/admin/cotizar').get_data(as_text=True)
    assert 'Generar cotización con IA' not in html and 'cotizar_ia_auto.js' not in html


def test_ruta_con_el_modulo(client, modulo_ia, simulado):
    import security
    security.request_log.pop('cot-ia:1', None)
    modulo_ia('true')
    _login(client)
    assert client.post('/admin/cotizar/ia/generar', json={}).status_code == 400
    r = client.post('/admin/cotizar/ia/generar', json={'conversacion': 'Cliente: necesito 2 mouse inalámbricos'})
    assert r.status_code == 202, 'arranca en segundo plano: gunicorn corta las peticiones de más de 120 s'
    trabajo = r.get_json()['trabajo']
    eventos = _hasta_el_fin(client, trabajo)
    assert eventos[0]['e'] == 'plan' and eventos[-1]['e'] == 'resultado'
    assert eventos[-1]['d']['items'][0]['fuente'].startswith('Catálogo')
    # Pedir desde un punto devuelve solo lo nuevo.
    parte = client.get(f'/admin/cotizar/ia/estado/{trabajo}?desde={len(eventos) - 1}').get_json()
    assert parte['fin'] and [e['e'] for e in parte['eventos']] == ['resultado']
    # Otro usuario de la misma tienda no ve el análisis ajeno.
    with client.session_transaction() as s:
        s['usuario_id'] = 2
    assert client.get(f'/admin/cotizar/ia/estado/{trabajo}').status_code == 404
    assert client.get('/admin/cotizar/ia/estado/..%2F..%2Fetc').status_code == 404
    html = client.get('/admin/cotizar').get_data(as_text=True)
    assert 'Generar cotización con IA' in html and 'cotizar_ia_auto.js' in html and 'id="ciaDialogo"' in html
