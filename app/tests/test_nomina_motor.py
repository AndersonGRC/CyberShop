# -*- coding: utf-8 -*-
"""Motor de nómina 2026: casos calculados a mano con la norma vigente.

SMMLV 2026 $1.750.905 · auxilio $249.095 · UVT $52.374 (Decreto 159/2026,
Decreto 1470/2025, Resolución DIAN 000238/2025)."""
from datetime import date

import pytest

import nomina_engine as m

SMMLV, AUX, UVT = 1750905.0, 249095.0, 52374.0
PARAMS = {'salario_minimo': SMMLV, 'auxilio_transporte': AUX, 'uvt': UVT, 'anio': 2026}
JULIO = {'anio': 2026, 'mes': 7, 'numero_periodo': 0, 'fecha_inicio': date(2026, 7, 1), 'fecha_fin': date(2026, 7, 31)}


def emp(id_=1, salario=SMMLV, **kw):
    base = {'id': id_, 'nombres': 'Ana', 'apellidos': 'Prueba', 'tipo_vinculacion': 'INDEFINIDO',
            'salario_base': salario, 'fecha_ingreso': date(2024, 1, 1), 'nivel_arl': 'I',
            'eps': 'Sura', 'fondo_pension': 'Porvenir', 'fondo_cesantias': 'Porvenir'}
    base.update(kw)
    return base


def uno(empleado, novedades=(), periodo=JULIO, params=PARAMS):
    r = m.liquidar_periodo(periodo, params, [empleado], list(novedades))
    return r['detalles'][0], r


# ---------------------------------------------------------------- jornada y recargos
@pytest.mark.parametrize('fecha, horas', [
    (date(2023, 7, 14), 240), (date(2023, 7, 15), 235), (date(2024, 7, 15), 230),
    (date(2025, 7, 14), 230), (date(2025, 7, 15), 220), (date(2026, 7, 14), 220), (date(2026, 7, 15), 210),
])
def test_divisor_mensual_ley_2101(fecha, horas):
    assert m.horas_mes(fecha) == horas


def test_valor_hora_cambia_el_15_de_julio_de_2026():
    assert m.calcular_valor_hora(SMMLV, date(2026, 7, 14)) == pytest.approx(SMMLV / 220)
    assert m.calcular_valor_hora(SMMLV, date(2026, 7, 15)) == pytest.approx(SMMLV / 210)


@pytest.mark.parametrize('tipo, fecha, factor', [
    ('HED', date(2026, 8, 1), 1.25), ('HEN', date(2026, 8, 1), 1.75), ('RN', date(2026, 8, 1), 0.35),
    ('RD', date(2025, 6, 30), 0.75), ('RD', date(2025, 7, 1), 0.80), ('RD', date(2026, 7, 1), 0.90),
    ('RD', date(2027, 7, 1), 1.00),
    ('HEDF', date(2025, 6, 30), 2.00), ('HENF', date(2025, 6, 30), 2.50),
    ('HEDF', date(2026, 7, 1), 2.15), ('HENF', date(2026, 7, 1), 2.65), ('RNDF', date(2026, 7, 1), 1.25),
])
def test_factores_por_fecha_ley_2466(tipo, fecha, factor):
    assert m.factor_hora(tipo, fecha) == pytest.approx(factor)


def test_jornada_nocturna_desde_las_19_horas():
    assert m.hora_inicio_nocturna(date(2025, 12, 24)) == 21
    assert m.hora_inicio_nocturna(date(2025, 12, 25)) == 19


def test_hora_extra_festiva_julio_2026():
    # 10 HEDF el 2-ago-2026: salario 2.100.000 / 210 = 10.000 la hora × 2,15
    assert m.valor_novedad('HEDF', 10, 2100000, SMMLV, date(2026, 8, 2)) == pytest.approx(215000)


# ---------------------------------------------------------------- días
@pytest.mark.parametrize('inicio, fin, dias', [
    (date(2026, 2, 1), date(2026, 2, 28), 30),
    (date(2026, 2, 16), date(2026, 2, 28), 15),
    (date(2024, 2, 1), date(2024, 2, 29), 30),
    (date(2026, 1, 1), date(2026, 1, 31), 30),
    (date(2026, 7, 1), date(2026, 7, 15), 15),
])
def test_dias_360_febrero_cuenta_30(inicio, fin, dias):
    assert m.dias_360(inicio, fin) == dias


def test_ingreso_a_mitad_de_mes():
    d, _ = uno(emp(fecha_ingreso=date(2026, 7, 11)))
    assert d['dias_trabajados'] == 20
    assert d['sueldo_basico'] == pytest.approx(SMMLV * 20 / 30, abs=0.01)


# ---------------------------------------------------------------- empleado con salario mínimo
def test_salario_minimo_mes_completo():
    d, r = uno(emp())
    assert d['sueldo_basico'] == pytest.approx(1750905)
    assert d['auxilio_transporte'] == pytest.approx(249095)
    assert d['total_devengado'] == pytest.approx(2000000)
    assert d['ibc'] == pytest.approx(1750905)
    assert d['salud_empleado'] == pytest.approx(70036.2)
    assert d['pension_empleado'] == pytest.approx(70036.2)
    assert d['fondo_solidaridad'] == 0
    assert d['retencion_fuente'] == 0
    assert d['neto_pagar'] == pytest.approx(1859927.6)
    # Empleador exonerado (Art. 114-1 ET): sin salud 8,5 %, ICBF ni SENA
    assert d['salud_empleador'] == 0 and d['icbf'] == 0 and d['sena'] == 0
    assert d['pension_empleador'] == pytest.approx(210108.6)
    assert d['arl'] == pytest.approx(9139.72)
    assert d['ccf'] == pytest.approx(70036.2)
    # Provisiones sobre salario + auxilio (cesantías y prima); vacaciones sin auxilio
    assert d['cesantias_provision'] == pytest.approx(166666.67)
    assert d['intereses_provision'] == pytest.approx(20000)
    assert d['prima_provision'] == pytest.approx(166666.67)
    assert d['vacaciones_provision'] == pytest.approx(72954.38)
    assert r['resumen']['costo_total'] > d['total_devengado']


def test_sin_exoneracion_paga_salud_icbf_y_sena():
    d, _ = uno(emp(), params={**PARAMS, 'exonerado_114_1': False})
    assert d['salud_empleador'] == pytest.approx(148826.93)
    assert d['icbf'] == pytest.approx(52527.15)
    assert d['sena'] == pytest.approx(35018.1)


def test_quincena():
    q1 = {**JULIO, 'numero_periodo': 1, 'fecha_fin': date(2026, 7, 15)}
    d, _ = uno(emp(), periodo=q1)
    assert d['dias_trabajados'] == 15
    assert d['sueldo_basico'] == pytest.approx(875452.5)
    assert d['auxilio_transporte'] == pytest.approx(124547.5)
    assert d['ibc'] == pytest.approx(875452.5)


# ---------------------------------------------------------------- IBC, FSP y retención
def test_salario_10_millones_fsp_y_retencion():
    d, _ = uno(emp(salario=10_000_000))
    assert d['auxilio_transporte'] == 0
    assert d['fondo_solidaridad'] == pytest.approx(100000)  # 1 % entre 4 y 16 SMMLV
    # Base: 10.000.000 - 900.000 = 9.100.000; 25 % exento = 2.275.000 → 6.825.000
    # (6.825.000 - 95 UVT) × 19 % = 351.399,30
    assert d['retencion_fuente'] == pytest.approx(351399.30, abs=0.01)
    assert d['salud_empleador'] == 0  # devenga < 10 SMMLV


def test_fsp_quincenal_usa_el_ibc_mensual():
    q1 = {**JULIO, 'numero_periodo': 1, 'fecha_fin': date(2026, 7, 15)}
    d, _ = uno(emp(salario=8_000_000), periodo=q1)  # 4,57 SMMLV al mes
    assert d['fondo_solidaridad'] == pytest.approx(40000)  # 1 % de 4.000.000


def test_tope_de_25_smmlv():
    d, _ = uno(emp(salario=50_000_000))
    assert d['ibc'] == pytest.approx(25 * SMMLV)
    assert d['fondo_solidaridad'] == pytest.approx(25 * SMMLV * 0.02)


def test_salario_integral():
    d, _ = uno(emp(salario=25_000_000, salario_integral=True))
    assert d['ibc'] == pytest.approx(17_500_000)
    assert d['auxilio_transporte'] == 0
    assert d['cesantias_provision'] == 0 and d['prima_provision'] == 0
    assert d['vacaciones_provision'] == pytest.approx(25_000_000 * 15 / 360, abs=0.01)
    assert d['salud_empleador'] == pytest.approx(17_500_000 * 0.085)  # ≥ 10 SMMLV: sin exoneración


def test_regla_40_pagos_no_salariales():
    # Salario 2.000.000 + bonificación no salarial 2.000.000: el 40 % de 4M es 1,6M;
    # los 400.000 que sobran entran al IBC (Ley 1393/2010 art. 30).
    d, _ = uno(emp(salario=2_000_000), [{'empleado_id': 1, 'tipo_novedad': 'BONIF_NS', 'cantidad': 1, 'valor_total': 2_000_000}])
    assert d['ibc'] == pytest.approx(2_400_000)
    assert d['total_devengado'] == pytest.approx(2_000_000 + 2_000_000 + 249095)


def test_retencion_con_deducciones_y_limite_global():
    pasos = m.depurar_base_retencion(20_000_000, 1_800_000, UVT, {
        'dependientes': True, 'intereses_vivienda': 5_000_000, 'medicina_prepagada': 1_000_000,
    })
    assert pasos['dependientes'] == pytest.approx(32 * UVT)
    assert pasos['intereses_vivienda'] == pytest.approx(5_000_000)
    assert pasos['medicina_prepagada'] == pytest.approx(16 * UVT)
    assert pasos['limite_global'] == pytest.approx(1340 / 12 * UVT)
    assert pasos['beneficios_aplicados'] == pytest.approx(1340 / 12 * UVT)
    assert pasos['base_gravable'] == pytest.approx(18_200_000 - 1340 / 12 * UVT)


def test_retencion_sin_deducciones_igual_que_antes():
    # Compatibilidad con la firma anterior (ingreso, incr, uvt, tabla).
    assert m.calcular_retencion_fuente(10_000_000, 900_000, UVT, m.TABLA_RETENCION_ART_383) == pytest.approx(351399.30, abs=0.01)


# ---------------------------------------------------------------- novedades
def test_incapacidad_general_dos_tercios_con_piso():
    d = m.desglose_incapacidad(3_000_000, 5, 'INCAPACIDAD_GEN', SMMLV)
    assert d['valor'] == pytest.approx(333333.33, abs=0.01)
    assert d['empresa'] == pytest.approx(133333.33, abs=0.01)
    assert d['cobrar'] == pytest.approx(200000, abs=0.01)
    piso = m.desglose_incapacidad(SMMLV, 5, 'INCAPACIDAD_GEN', SMMLV)
    assert piso['valor'] == pytest.approx(SMMLV / 30 * 5)


def test_novedades_en_el_detalle():
    novedades = [
        {'empleado_id': 1, 'tipo_novedad': 'HED', 'cantidad': 4, 'valor_total': 50000},
        {'empleado_id': 1, 'tipo_novedad': 'RN', 'cantidad': 8, 'valor_total': 20000},
        {'empleado_id': 1, 'tipo_novedad': 'COMISION', 'cantidad': 1, 'valor_total': 300000},
        {'empleado_id': 1, 'tipo_novedad': 'PRESTAMO', 'cantidad': 1, 'valor_total': 100000},
        {'empleado_id': 1, 'tipo_novedad': 'VACACIONES', 'cantidad': 6, 'valor_total': 350181},
    ]
    d, _ = uno(emp(), novedades)
    assert d['horas_extras'] == pytest.approx(70000)  # extras + recargos (compatibilidad)
    assert d['recargos'] == pytest.approx(20000)
    assert d['comisiones'] == pytest.approx(300000)
    assert d['prestamos'] == pytest.approx(100000)
    assert d['licencias'] == pytest.approx(350181)
    assert d['sueldo_basico'] == pytest.approx(SMMLV * 24 / 30)
    assert d['auxilio_transporte'] == pytest.approx(AUX * 24 / 30)  # sin auxilio en vacaciones
    assert d['total_deducido'] == pytest.approx(d['salud_empleado'] + d['pension_empleado'] + 100000)


def test_novedades_que_exceden_los_dias_avisan():
    d, r = uno(emp(), [{'empleado_id': 1, 'tipo_novedad': 'LICENCIA_NR', 'cantidad': 40, 'valor_total': 0}])
    assert d['sueldo_basico'] == 0
    assert any('exceden' in a['mensaje'] for a in r['alertas'])


# ---------------------------------------------------------------- contratistas
def test_contratista_bajo_cotiza_sobre_un_smmlv_y_no_se_descuenta():
    d, _ = uno(emp(salario=1_500_000, tipo_vinculacion='CONTRATISTA'))
    c = d['calculo']
    assert c['ibc'] == pytest.approx(SMMLV)
    assert c['pila']['salud'] == pytest.approx(218863.13)
    assert c['pila']['pension'] == pytest.approx(280144.8)
    assert d['salud_empleado'] == 0 and d['pension_empleado'] == 0 and d['fondo_solidaridad'] == 0
    assert d['retencion_fuente'] == 0
    assert d['neto_pagar'] == pytest.approx(1_500_000)
    assert d['total_deducido'] == pytest.approx(d['total_devengado'] - d['neto_pagar'])


def test_contratista_tabla_383():
    d, _ = uno(emp(salario=8_000_000, tipo_vinculacion='CONTRATISTA'))
    # IBC 3.200.000 → salud 400.000 + pensión 512.000; neto 7.088.000; 25 % → 5.316.000
    assert d['retencion_fuente'] == pytest.approx((5_316_000 - 95 * UVT) * 0.19, abs=0.01)
    assert d['neto_pagar'] == pytest.approx(8_000_000 - d['retencion_fuente'])


@pytest.mark.parametrize('honorarios, concepto, declarante, esperado', [
    (8_000_000, 'HONORARIOS', False, 800_000),      # 10 %
    (30_000_000, 'HONORARIOS', False, 3_300_000),   # contrato > 3.300 UVT → 11 %
    (8_000_000, 'SERVICIOS', True, 320_000),        # 4 % declarante
    (8_000_000, 'SERVICIOS', False, 480_000),       # 6 % no declarante
])
def test_contratista_articulo_392(honorarios, concepto, declarante, esperado):
    d, _ = uno(emp(salario=honorarios, tipo_vinculacion='CONTRATISTA', ret_contrata_2_o_mas=True,
                   ret_concepto=concepto, ret_declarante=declarante))
    assert d['retencion_fuente'] == pytest.approx(esperado)


def test_contratista_fsp_desde_4_smmlv():
    ss = m.calcular_ss_contratista(20_000_000, 0.522, SMMLV)  # IBC 8.000.000 = 4,57 SMMLV
    assert ss['fsp'] == pytest.approx(80000)


def test_contratista_arl_v_la_paga_la_empresa():
    d, r = uno(emp(salario=8_000_000, tipo_vinculacion='CONTRATISTA', nivel_arl='V'))
    assert d['arl'] == pytest.approx(3_200_000 * 0.0696)
    assert d['calculo']['pila']['arl'] == 0


# ---------------------------------------------------------------- aprendiz SENA
def test_aprendiz_lectiva_sin_descuentos_y_salud_de_la_empresa():
    d, _ = uno(emp(salario=SMMLV * 0.75, tipo_vinculacion='APRENDIZ_SENA', aprendiz_etapa='LECTIVA'))
    assert d['salud_empleado'] == 0 and d['pension_empleado'] == 0
    assert d['salud_empleador'] == pytest.approx(SMMLV * 0.125)
    assert d['pension_empleador'] == 0
    assert d['auxilio_transporte'] == 0


def test_aprendiz_productiva_como_dependiente():
    d, _ = uno(emp(salario=SMMLV, tipo_vinculacion='APRENDIZ_SENA', aprendiz_etapa='PRODUCTIVA'))
    assert d['salud_empleado'] == pytest.approx(70036.2)
    assert d['pension_empleador'] == pytest.approx(210108.6)
    assert d['auxilio_transporte'] == pytest.approx(AUX)


# ---------------------------------------------------------------- contrato del escritorio
def test_detalle_conserva_las_claves_que_usa_el_escritorio():
    d, r = uno(emp())
    for clave in ('empleado_id', 'dias_trabajados', 'sueldo_basico', 'auxilio_transporte', 'horas_extras',
                  'total_devengado', 'salud_empleado', 'pension_empleado', 'fondo_solidaridad',
                  'retencion_fuente', 'total_deducido', 'neto_pagar'):
        assert clave in d
    assert {'empleados', 'contratistas', 'total_devengado', 'total_neto'} <= set(r['resumen'])
    assert r['motor_version'] == m.MOTOR_VERSION


# ---------------------------------------------------------------- liquidación definitiva
EMP_LIQ = emp(salario=2_000_000, fecha_ingreso=date(2025, 3, 1))


def test_liquidacion_por_renuncia_sin_indemnizacion():
    r = m.liquidar_contrato(EMP_LIQ, date(2026, 11, 15), 'RENUNCIA', PARAMS)
    base = 2_000_000 + AUX
    assert r['dias_liquidacion'] == 315
    assert r['cesantias'] == pytest.approx(base * 315 / 360, abs=0.01)
    assert r['intereses_cesantias'] == pytest.approx(base * 315 / 360 * 315 * 0.12 / 360, abs=0.01)
    assert r['prima_servicios'] == pytest.approx(base * 135 / 360, abs=0.01)
    assert r['vacaciones'] == pytest.approx(2_000_000 / 30 * 13.125, abs=0.01)
    assert r['indemnizacion'] == 0


def test_liquidacion_despido_sin_justa_causa():
    r = m.liquidar_contrato(EMP_LIQ, date(2026, 11, 15), 'DESPIDO_INJUSTO', PARAMS)
    # 615 días: 30 días el primer año + 20 × 255/360
    assert r['indemnizacion'] == pytest.approx(2_000_000 / 30 * (30 + 20 * 255 / 360), abs=0.01)


def test_liquidacion_rechaza_contratistas_y_fechas_invalidas():
    with pytest.raises(ValueError):
        m.liquidar_contrato(emp(tipo_vinculacion='CONTRATISTA'), date(2026, 11, 15), 'RENUNCIA', PARAMS)
    with pytest.raises(ValueError):
        m.liquidar_contrato(EMP_LIQ, date(2024, 1, 1), 'RENUNCIA', PARAMS)


def test_liquidacion_con_ajustes_del_usuario():
    r = m.liquidar_contrato(EMP_LIQ, date(2026, 11, 15), 'RENUNCIA', PARAMS,
                            dias_vacaciones_pendientes=20, salarios_pendientes=1_000_000, deducciones_pendientes=200_000)
    assert r['vacaciones'] == pytest.approx(2_000_000 / 30 * 20, abs=0.01)
    assert r['total_pagar'] == pytest.approx(
        r['cesantias'] + r['intereses_cesantias'] + r['prima_servicios'] + r['vacaciones'] + 1_000_000 - 200_000, abs=0.02)


def test_aviso_reforma_pensional_desde_abril_2027():
    periodo = {'anio': 2027, 'fecha_inicio': date(2027, 4, 1), 'fecha_fin': date(2027, 4, 30)}
    alertas = m.alertas_parametros(periodo, {'salario_minimo': 1847205, 'auxilio_transporte': 262795, 'uvt': 55256})
    assert any('Ley 2381' in a['mensaje'] for a in alertas)
