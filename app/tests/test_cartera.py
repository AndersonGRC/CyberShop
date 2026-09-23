# -*- coding: utf-8 -*-
"""Cartera: estado de cobro de cotizaciones y cuentas de cobro.

Sin BD: el cursor se reemplaza por un doble que responde lo que responden
PostgreSQL y `information_schema`. Así se puede probar lo importante —que un
cliente SIN la migración no se rompa— sin tener que borrarle la columna a una
base real.
"""

from contextlib import contextmanager
from datetime import date, datetime

import pytest
from flask import Flask

import services.cartera_service as cs


# ── Dobles ─────────────────────────────────────────────────────
class Fila(dict):
    """Fila que se deja leer por nombre y por posición, como DictCursor."""

    def __getitem__(self, clave):
        if isinstance(clave, int):
            return list(self.values())[clave]
        return dict.__getitem__(self, clave)


class CursorFalso:
    def __init__(self, columnas, respuestas=()):
        self.columnas = columnas            # {tabla: {col, ...}}
        self.respuestas = list(respuestas)  # [(trozo_de_sql, [filas])]
        self.sqls = []
        self._pendiente = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        limpio = ' '.join(sql.split())
        self.sqls.append((limpio, params))
        if 'to_regclass' in limpio:
            tabla = (params[0] or '').split('.')[-1]
            self._pendiente = [Fila(reg=tabla if tabla in self.columnas else None)]
            return
        if 'information_schema.columns' in limpio:
            self._pendiente = [Fila(column_name=c) for c in self.columnas.get(params[0], ())]
            return
        if limpio.upper().startswith('UPDATE'):
            self.rowcount = 1
            self._pendiente = [Fila(id=params[-1])] if 'RETURNING' in limpio else []
            return
        for trozo, filas in self.respuestas:
            if trozo in limpio:
                self._pendiente = list(filas)
                return
        self._pendiente = []

    def fetchone(self):
        return self._pendiente[0] if self._pendiente else None

    def fetchall(self):
        return list(self._pendiente)

    def sql_con(self, trozo):
        return [s for s, _ in self.sqls if trozo in s]


@pytest.fixture()
def app_ctx():
    """Contexto mínimo de Flask: el servicio escribe en current_app.logger."""
    app = Flask(__name__)
    with app.app_context():
        yield app


@pytest.fixture()
def db(monkeypatch):
    """Reemplaza get_db_cursor por el doble. Devuelve el cursor activo."""
    estado = {}

    def preparar(columnas, respuestas=()):
        cur = CursorFalso(columnas, respuestas)
        estado['cur'] = cur

        @contextmanager
        def falso(dict_cursor=False):
            yield cur

        monkeypatch.setattr(cs, 'get_db_cursor', falso)
        return cur
    return preparar


CON_COLUMNA = {'cotizaciones': {'id', 'fecha', 'total', 'estado', 'estado_pago', 'fecha_pago',
                                'fecha_vencimiento', 'nota_pago', 'cliente_nombre'},
               'cuentas_cobro': {'id', 'fecha', 'total', 'consecutivo', 'estado_pago', 'fecha_pago',
                                 'fecha_vencimiento', 'nota_pago', 'cliente_nombre'}}
SIN_COLUMNA = {'cotizaciones': {'id', 'fecha', 'total', 'estado', 'cliente_nombre'},
               'cuentas_cobro': {'id', 'fecha', 'total', 'consecutivo', 'cliente_nombre'}}


# ── Estados válidos ────────────────────────────────────────────
def test_marcar_pagada_guarda_la_fecha(app_ctx, db):
    cur = db(CON_COLUMNA)
    ok, msg = cs.marcar_pago('cuenta_cobro', 7, 'pagada')
    assert ok and 'PAGADA' in msg
    sql, params = [s for s in cur.sqls if s[0].startswith('UPDATE')][0]
    assert params[0] == 'pagada' and params[1] == date.today() and params[-1] == 7


def test_marcar_pendiente_no_inventa_fecha_de_pago(app_ctx, db):
    cur = db(CON_COLUMNA)
    ok, msg = cs.marcar_pago('cotizacion', 3, 'pendiente')
    assert ok and 'PENDIENTE' in msg
    params = [s for s in cur.sqls if s[0].startswith('UPDATE')][0][1]
    assert params[0] == 'pendiente' and params[1] is None


def test_deshacer_vuelve_a_sin_dato(app_ctx, db):
    cur = db(CON_COLUMNA)
    for entrada in ('', 'sin_dato', None):
        ok, _ = cs.marcar_pago('cuenta_cobro', 1, entrada)
        assert ok
        assert [s for s in cur.sqls if s[0].startswith('UPDATE')][-1][1][0] is None


def test_estado_inventado_se_rechaza_sin_tocar_la_base(app_ctx, db):
    cur = db(CON_COLUMNA)
    ok, msg = cs.marcar_pago('cuenta_cobro', 1, 'anulada')
    assert not ok and 'no válido' in msg
    assert not [s for s in cur.sqls if s[0].startswith('UPDATE')]


def test_documento_desconocido_se_rechaza(app_ctx, db):
    db(CON_COLUMNA)
    ok, msg = cs.marcar_pago('factura', 1, 'pagada')
    assert not ok and 'desconocido' in msg.lower()


def test_la_nota_se_recorta_y_vacia_queda_nula(app_ctx, db):
    cur = db(CON_COLUMNA)
    cs.marcar_pago('cuenta_cobro', 1, 'pagada', nota='x' * 500)
    assert len([s for s in cur.sqls if s[0].startswith('UPDATE')][0][1][2]) == 200
    cs.marcar_pago('cuenta_cobro', 1, 'pagada', nota='   ')
    assert [s for s in cur.sqls if s[0].startswith('UPDATE')][-1][1][2] is None


# ── Cliente que aún no ha actualizado ──────────────────────────
def test_sin_columna_avisa_en_vez_de_reventar(app_ctx, db):
    cur = db(SIN_COLUMNA)
    ok, msg = cs.marcar_pago('cuenta_cobro', 1, 'pagada')
    assert not ok
    assert 'Actualiza la app' in msg
    assert not [s for s in cur.sqls if s[0].startswith('UPDATE')]


def test_sin_columna_el_resumen_no_miente_con_ceros(app_ctx, db):
    db(SIN_COLUMNA)
    r = cs.resumen_cartera()
    assert r['disponible'] is False
    assert r['pendiente_n'] == 0


def test_sin_columna_la_lista_sale_vacia(app_ctx, db):
    db(SIN_COLUMNA)
    assert cs.documentos_cartera() == []


def test_sin_columna_el_marcado_inicial_no_hace_nada(app_ctx, db):
    cur = db(SIN_COLUMNA)
    assert cs.marcar_pendiente_si_falta('cotizacion', 5) is False
    assert not [s for s in cur.sqls if s[0].startswith('UPDATE')]


def test_sin_tabla_tampoco_falla(app_ctx, db):
    db({})           # cliente heredado: no tiene ni cotizaciones ni cuentas de cobro
    assert cs.cartera_disponible() is False
    assert cs.documentos_cartera() == []
    assert cs.resumen_cartera()['disponible'] is False


# ── Marcado automático al nacer ────────────────────────────────
def test_al_nacer_solo_marca_si_nadie_lo_ha_tocado(app_ctx, db):
    cur = db(CON_COLUMNA)
    assert cs.marcar_pendiente_si_falta('cotizacion', 9) is True
    sql = [s for s in cur.sqls if s[0].startswith('UPDATE')][0][0]
    assert "estado_pago = 'pendiente'" in sql
    assert 'estado_pago IS NULL' in sql   # no pisa una ya marcada como pagada


# ── Lectura ────────────────────────────────────────────────────
def test_filtros_de_estado():
    assert cs.sql_filtro('pendiente') == "estado_pago = 'pendiente'"
    assert cs.sql_filtro('pagada') == "estado_pago = 'pagada'"
    assert cs.sql_filtro('sin_dato') == 'estado_pago IS NULL'
    assert cs.sql_filtro(None) == 'TRUE'
    assert cs.sql_filtro('; DROP TABLE cotizaciones') == 'TRUE'


def test_mora_solo_cuenta_en_las_pendientes(app_ctx, db):
    hoy = date.today()
    filas = [Fila(id=1, numero='CC-0001', fecha=hoy, cliente='Ana', total=1000,
                  estado_pago='pendiente', fecha_pago=None, nota_pago=None,
                  vence=hoy.replace(year=hoy.year - 1), consecutivo='CC-0001'),
             Fila(id=2, numero='CC-0002', fecha=hoy, cliente='Luis', total=500,
                  estado_pago='pagada', fecha_pago=hoy, nota_pago=None,
                  vence=hoy.replace(year=hoy.year - 1), consecutivo='CC-0002')]
    db({'cuentas_cobro': CON_COLUMNA['cuentas_cobro']}, [('FROM cuentas_cobro', filas)])
    docs = cs.documentos_cartera()
    pendiente = [d for d in docs if d['id'] == 1][0]
    pagada = [d for d in docs if d['id'] == 2][0]
    assert pendiente['vencida'] and pendiente['dias_mora'] >= 365
    assert not pagada['vencida'] and pagada['dias_mora'] == 0   # ya se cobró: no hay mora


def test_ordena_aunque_una_tabla_use_fecha_y_la_otra_fecha_y_hora(app_ctx, db):
    """cotizaciones guarda TIMESTAMP y cuentas_cobro DATE: compararlos crudos
    en Python lanza TypeError y tumbaba la pantalla."""
    cot = [Fila(id=1, numero='COT 1', fecha=datetime(2026, 5, 2, 10, 30), cliente='Ana', total=10,
                estado_pago='pendiente', fecha_pago=None, nota_pago=None,
                vence=date(2026, 6, 1), consecutivo=None)]
    cc = [Fila(id=2, numero='CC-0002', fecha=date(2026, 7, 9), cliente='Luis', total=20,
               estado_pago='pendiente', fecha_pago=None, nota_pago=None,
               vence=date(2026, 8, 8), consecutivo='CC-0002')]
    db(CON_COLUMNA, [('FROM cotizaciones', cot), ('FROM cuentas_cobro', cc)])
    docs = cs.documentos_cartera()
    assert [d['id'] for d in docs] == [2, 1]          # la más reciente primero


def test_resumen_suma_los_dos_documentos_y_formatea(app_ctx, db):
    grupo = [Fila(est='pendiente', n=2, t=3000, n_venc=1, t_venc=1000),
             Fila(est='pagada', n=1, t=500, n_venc=0, t_venc=0),
             Fila(est='sin_dato', n=4, t=700, n_venc=0, t_venc=0)]
    db(CON_COLUMNA, [('FROM cotizaciones', grupo), ('FROM cuentas_cobro', grupo)])
    r = cs.resumen_cartera()
    assert r['disponible'] is True
    assert r['pendiente_n'] == 4 and r['pendiente_total'] == 6000     # las dos tablas
    assert r['vencido_n'] == 2 and r['vencido_total'] == 2000
    assert r['pagado_n'] == 2 and r['sin_dato_n'] == 8
    assert '6' in r['pendiente_fmt']                                  # ya viene formateado


def test_el_filtro_de_la_lista_llega_al_sql(app_ctx, db):
    cur = db(CON_COLUMNA)
    cs.documentos_cartera('pendiente')
    assert all("estado_pago = 'pendiente'" in s for s in cur.sql_con('FROM cuentas_cobro'))


def test_solo_las_cotizaciones_aprobadas_son_cartera(app_ctx, db):
    cur = db(CON_COLUMNA)
    cs.documentos_cartera()
    assert all("= 'aprobada'" in s for s in cur.sql_con('FROM cotizaciones'))
