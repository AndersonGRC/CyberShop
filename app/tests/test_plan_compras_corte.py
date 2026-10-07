# -*- coding: utf-8 -*-
"""Motor de cobro: renovar en línea no corre el día de pago (fecha de corte).

Antes, un pago tarde contaba 30 días desde HOY y, a tiempo, 30 días desde el
vencimiento: el día de cobro se corría cada mes. Ahora va por meses de
calendario sobre el día de corte."""
from datetime import date as D

import pytest

from services import plan_compras_service as pcs


@pytest.mark.parametrize('proximo, periodo, hoy, esperado', [
    (D(2026, 9, 18), 'mes', D(2026, 10, 7), D(2026, 10, 18)),    # 19 días tarde: sigue el 18
    (D(2026, 10, 18), 'mes', D(2026, 10, 10), D(2026, 11, 18)),   # por adelantado
    (D(2026, 10, 18), 'mes', D(2026, 10, 18), D(2026, 11, 18)),   # el mismo día
    (D(2026, 11, 18), 'mes', D(2026, 11, 1), D(2026, 12, 18)),    # sin correrse con meses de 30/31 días
    (D(2026, 8, 18), 'mes', D(2026, 10, 7), D(2026, 10, 18)),     # dos meses tarde: queda al día, mismo día
    (D(2027, 1, 31), 'mes', D(2027, 1, 20), D(2027, 2, 28)),      # fin de mes
    (D(2026, 10, 18), 'año', D(2026, 10, 1), D(2027, 10, 18)),    # plan anual
    (D(2026, 12, 20), 'mes', D(2027, 1, 3), D(2027, 1, 20)),      # cambio de año
])
def test_renovar_no_corre_el_dia_de_pago(proximo, periodo, hoy, esperado):
    assert pcs.siguiente_vencimiento(proximo, periodo, hoy) == esperado


def test_sin_fecha_arranca_hoy():
    assert pcs.siguiente_vencimiento(None, 'mes', D(2026, 10, 7)) == D(2026, 11, 7)


def test_doce_renovaciones_seguidas_no_mueven_el_dia():
    fecha = D(2026, 1, 18)
    for _ in range(12):
        fecha = pcs.siguiente_vencimiento(fecha, 'mes', fecha)
        assert fecha.day == 18
    assert fecha == D(2027, 1, 18)
