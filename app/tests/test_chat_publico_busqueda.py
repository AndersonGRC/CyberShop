# -*- coding: utf-8 -*-
"""Búsqueda de productos del chat del sitio: «¿tienen cargadores?» no encontraba
«CARGADOR PORTATIL ASUS» (plural, tildes, palabras de relleno), y el modelo
convertía ese «no encontré» en «Sí, tenemos cargadores»."""
import uuid

import pytest

from services.ia_datos import publico


@pytest.mark.parametrize('termino, esperado', [
    ('cargadores', ['cargador']),
    ('cargador para portátil asus', ['cargador', 'portatil', 'asus']),
    ('portátiles', ['portatil']),
    ('tarjeta de video RTX 4090', ['tarjeta', 'video', 'rtx', '4090']),
    ('impresoras', ['impresora']),
    ('mouse', []),          # una sola palabra que no cambia: la frase exacta ya la buscó
])
def test_palabras_clave(termino, esperado):
    assert publico._palabras_clave(termino) == esperado


@pytest.fixture()
def producto(cursor):
    nombre = f'CARGADOR PORTATIL ASUS PYT{uuid.uuid4().hex[:6].upper()}'
    genero_nuevo = None
    with cursor() as cur:
        cur.execute('SELECT id FROM generos ORDER BY id LIMIT 1')
        fila = cur.fetchone()
        if fila is None:
            cur.execute("INSERT INTO generos (nombre) VALUES ('PYTEST-BUSQUEDA') RETURNING id")
            fila = genero_nuevo = cur.fetchone()
        cur.execute("""INSERT INTO productos (imagen, nombre, precio, referencia, genero_id,
                                               descripcion, stock)
                       VALUES ('', %s, 117750, %s, %s, 'Original', 3) RETURNING id""",
                    (nombre, 'PYT-' + uuid.uuid4().hex[:8], fila['id']))
        pid = cur.fetchone()['id']
    yield nombre
    with cursor() as cur:
        cur.execute('DELETE FROM productos WHERE id = %s', (pid,))
        if genero_nuevo:
            cur.execute('DELETE FROM generos WHERE id = %s', (genero_nuevo['id'],))


def _nombres(datos):
    return [p['producto'] for p in datos.get('productos') or []]


@pytest.mark.parametrize('pregunta', [
    'cargadores', 'cargador para portátil asus', 'Cargadores Asus', 'portátil asus',
])
def test_encuentra_con_plural_tildes_y_relleno(flask_app, producto, pregunta):
    with flask_app.app_context():
        assert producto in _nombres(publico.buscar_productos(pregunta, limite=10))


def test_todas_las_palabras_deben_aparecer(flask_app, producto):
    """Mejor «no lo encontré» que ofrecer otro producto."""
    with flask_app.app_context():
        assert producto not in _nombres(publico.buscar_productos('cargador lenovo', limite=10))


def test_no_encontrado_no_pasa_por_el_modelo(flask_app, monkeypatch):
    from services.chat_publico import motor
    import services.ai_tools as tools
    from services.ia_datos.base import Herramienta
    monkeypatch.setattr(motor, 'config_publica', lambda: {
        'saludo': 'Hola', 'negocio': 'Tienda', 'tono': 'breve', 'whatsapp': '573001112233'})
    monkeypatch.setattr(motor, '_registrar', lambda *a, **k: None)
    herramienta = Herramienta('buscar_productos', lambda **_: {}, 'Catálogo.', ('texto',),
                              disparadores=('tienen',))
    monkeypatch.setattr(tools, 'permitidas', lambda _ctx: [herramienta])
    monkeypatch.setattr(tools, 'ejecutar', lambda code, params, ctx: {
        'buscado': 'impresoras', 'conclusion': 'No encontré «impresoras» en el catálogo.'})

    def _revienta(*a, **k):
        raise AssertionError('un «no encontré» no se le pasa al modelo')
    import services.ai_service as ai
    monkeypatch.setattr(ai, 'chat_con_motor', _revienta)
    motor._CACHE.clear()
    with flask_app.app_context():
        salida = motor.responder('¿Tienen impresoras?')
    assert 'No encontré «impresoras»' in salida['respuesta']
    assert salida['escalar'] is True


# ── Frases de compra que no nombran un producto ────────────────
@pytest.mark.parametrize('texto, esperado', [
    ('comprar unos productos', ''),
    ('algunas cosas', ''),
    ('saber cómo comprar', ''),
    ('comprar unos cables de red', 'cables de red'),
    ('un cargador para portátil asus', 'cargador para portátil asus'),
    ('gaseosa', 'gaseosa'),
])
def test_termino_de_producto(texto, esperado):
    from services.chat_publico.motor import _termino_de_producto
    assert _termino_de_producto(texto) == esperado


@pytest.fixture()
def chat(flask_app, monkeypatch):
    """Motor con las 3 capacidades públicas simuladas; guarda qué se buscó."""
    from services.chat_publico import motor
    import services.ai_tools as tools
    from services.ia.intenciones import INTENCIONES
    from services.ia_datos.base import Herramienta
    monkeypatch.setattr(motor, 'config_publica', lambda: {
        'saludo': 'Hola', 'negocio': 'Tienda', 'tono': 'breve', 'whatsapp': '573001112233'})
    monkeypatch.setattr(motor, '_registrar', lambda *a, **k: None)
    herramientas = [Herramienta(code, lambda **_: {}, code, params,
                                disparadores=INTENCIONES[code]['disparadores'])
                    for code, params in (('buscar_productos', ('texto',)),
                                         ('categorias_publicas', ()), ('como_comprar', ()))]
    monkeypatch.setattr(tools, 'permitidas', lambda _ctx: herramientas)
    buscados = []

    def _ejecutar(code, params, ctx):
        if code == 'buscar_productos':
            buscados.append(params['texto'])
            return {'buscado': params['texto'], 'conclusion': 'No encontré nada.'}
        if code == 'categorias_publicas':
            return {'categorias': [{'categoria': 'Repuestos', 'productos': 3}]}
        return {'como_comprar': 'Se puede comprar en línea.', 'enlace': '/productos'}
    monkeypatch.setattr(tools, 'ejecutar', _ejecutar)

    def _revienta(*a, **k):
        raise AssertionError('estas respuestas no pasan por el modelo')
    import services.ai_service as ai
    monkeypatch.setattr(ai, 'chat_con_motor', _revienta)
    motor._CACHE.clear()
    with flask_app.app_context():
        yield motor, buscados
    motor._CACHE.clear()


@pytest.mark.parametrize('pregunta', [
    'Necesito comprar unos productos', 'Quiero comprar algo', 'Me gustaría comprar unas cosas',
])
def test_frase_de_compra_dice_que_hay_y_como_comprar(chat, pregunta):
    motor, buscados = chat
    salida = motor.responder(pregunta, redactar=False)
    assert buscados == []
    assert 'Manejamos: Repuestos.' in salida['respuesta']
    assert 'Se puede comprar en línea.' in salida['respuesta']


def test_quiero_comprar_un_producto_lo_busca(chat):
    motor, buscados = chat
    motor.responder('Quiero comprar un cargador', redactar=False)
    assert buscados == ['cargador']


def test_no_encontrado_es_amable_y_ofrece_lo_que_hay(chat):
    motor, buscados = chat
    salida = motor.responder('¿Tienen impresoras?')
    assert buscados == ['impresoras']
    assert 'No encontré «impresoras»' in salida['respuesta']
    assert 'WhatsApp' in salida['respuesta'] and 'Manejamos: Repuestos.' in salida['respuesta']
    assert salida['escalar'] is True
