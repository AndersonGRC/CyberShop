"""Indicadores nuevos: cálculos, fecha de anulaciones y permisos del catálogo.

Son pruebas sin base real para no consultar datos de otros clientes.
"""

from contextlib import contextmanager
from datetime import date

import services.ia_datos as ia_datos
from services.ia_datos import analitica
from services.ia_datos.base import Rango


class CursorFalso:
    def __init__(self, filas=(), hoy=None):
        self.filas = list(filas)
        self.hoy = hoy
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        if self.hoy:
            return {'hoy': self.hoy}
        return self.filas.pop(0)

    def fetchall(self):
        return self.filas


def usar_cursor(monkeypatch, cursor):
    @contextmanager
    def abrir(dict_cursor=False):
        assert dict_cursor is True
        yield cursor

    monkeypatch.setattr(analitica, 'get_db_cursor', abrir)


def test_comparativo_usa_tramos_iguales_y_tres_canales(monkeypatch):
    cur = CursorFalso(hoy=date(2026, 9, 15))
    usar_cursor(monkeypatch, cur)
    tramos = []

    def totales(_cur, periodo):
        tramos.append(periodo)
        return ((12, 600.0, {'web': {}, 'pos_mostrador': {}, 'pos_escritorio': {}})
                if len(tramos) == 1 else (10, 500.0, {}))

    monkeypatch.setattr(analitica, '_totales_ventas', totales)
    monkeypatch.setattr(analitica, '_escritorio_sincronizado_hasta', lambda _: None)
    monkeypatch.setattr(analitica, 'formatear_moneda', lambda n: f'{n:.2f}')

    respuesta = analitica.comparativo_ventas('mes')
    assert tramos == [Rango(date(2026, 9, 1), date(2026, 9, 15)),
                      Rango(date(2026, 8, 1), date(2026, 8, 15))]
    assert respuesta['monto'] == '600.00'
    assert respuesta['comparacion_anterior']['cambio_monto'] == '+20%'
    assert respuesta['comparacion_anterior']['cambio_ventas'] == '+20%'
    assert set(respuesta['por_canal']) == {'web', 'pos_mostrador', 'pos_escritorio'}


def test_ticket_promedio_no_inventa_valor_cuando_no_hay_ventas(monkeypatch):
    usar_cursor(monkeypatch, CursorFalso())
    monkeypatch.setattr(analitica, '_totales_ventas', lambda _cur, _p: (0, 0.0, {}))
    monkeypatch.setattr(analitica, '_escritorio_sincronizado_hasta', lambda _: None)
    respuesta = analitica.ticket_promedio('ayer')
    assert respuesta['ventas'] == 0
    assert respuesta['ticket_promedio'] is None
    assert respuesta['confiabilidad'] == 'insuficiente'


def test_anulaciones_usan_fecha_de_nota_y_no_de_venta(monkeypatch):
    cur = CursorFalso([{'n': 2, 'monto': 100.0}])
    usar_cursor(monkeypatch, cur)
    monkeypatch.setattr(analitica, '_existe', lambda _cur, _tabla: True)
    monkeypatch.setattr(analitica, '_columnas', lambda _cur, _tabla: {'fecha_creacion', 'total'})
    monkeypatch.setattr(analitica, 'formatear_moneda', lambda n: f'{n:.2f}')
    respuesta = analitica.anulaciones_pos('mes')
    assert respuesta['anulaciones_pos'] == 2
    assert respuesta['monto_de_notas_credito'] == '100.00'
    assert len(cur.sql) == 1
    assert 'notas_credito_pos' in cur.sql[0][0]
    assert 'fecha_creacion' in cur.sql[0][0]
    assert 'ventas_pos' not in cur.sql[0][0]


def test_anulaciones_sin_fecha_no_fingen_un_periodo(monkeypatch):
    cur = CursorFalso()
    usar_cursor(monkeypatch, cur)
    monkeypatch.setattr(analitica, '_existe', lambda _cur, _tabla: True)
    monkeypatch.setattr(analitica, '_columnas', lambda _cur, _tabla: {'total'})
    respuesta = analitica.anulaciones_pos('mes')
    assert respuesta['confiabilidad'] == 'insuficiente'
    assert cur.sql == []


def test_inventario_por_categoria_totaliza_todo_y_limita_detalle(monkeypatch):
    filas = [{'categoria': f'Categoría {i}', 'productos': 1, 'unidades': 2,
              'agotados': 0, 'valor': 20.0} for i in range(25)]
    cur = CursorFalso(filas)
    usar_cursor(monkeypatch, cur)
    monkeypatch.setattr(analitica, 'formatear_moneda', lambda n: f'{n:.2f}')
    respuesta = analitica.inventario_por_categoria()
    assert respuesta['categorias'] == 25
    assert respuesta['productos'] == 25
    assert respuesta['unidades_disponibles'] == 50
    assert respuesta['valor_a_precio_de_venta'] == '500.00'
    assert len(respuesta['detalle']) == 20
    assert all(sql.lstrip().upper().startswith('SELECT') for sql, _ in cur.sql)


def test_nuevas_capacidades_solo_panel_y_con_permisos_especificos():
    for codigo in ('comparativo_ventas', 'ticket_promedio',
                   'anulaciones_pos', 'inventario_por_categoria'):
        assert ia_datos.REGISTRO[codigo].canales == ('panel',)
    assert ia_datos.REGISTRO['anulaciones_pos'].permiso == 'pos'
    assert ia_datos.REGISTRO['inventario_por_categoria'].permiso == 'inventory'
