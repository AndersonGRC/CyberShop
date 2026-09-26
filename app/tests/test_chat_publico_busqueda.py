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
    assert salida['respuesta'] == 'No encontré «impresoras» en el catálogo.'
    assert salida['escalar'] is True
