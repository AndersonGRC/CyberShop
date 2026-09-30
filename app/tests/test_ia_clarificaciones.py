"""Aclaraciones y normalización deterministas, sin modelo ni base de datos."""

import pytest

import services.ia_datos as ia_datos  # noqa: F401  - registra capacidades
from services.ia.clarificaciones import (
    instrucciones_para_catalogo, normalizar_params_consulta, pregunta_faltante,
)
from services.ia.registro import REGISTRO


@pytest.mark.parametrize('code,campo,pregunta,nombre', [
    ('cliente_historial', 'cliente', '¿Qué ha comprado Ana Pérez?', 'Ana Pérez'),
    ('producto_detalle', 'producto', '¿Cómo va el producto Camiseta Azul?', 'Camiseta Azul'),
    ('nomina_empleado', 'empleado', '¿Cuál es la nómina de José Luis?', 'José Luis'),
])
def test_cada_ficha_pide_su_identidad_real(code, campo, pregunta, nombre):
    h = REGISTRO[code]
    assert pregunta_faltante(h, {}, pregunta)
    assert pregunta_faltante(h, {campo: 'Nombre inventado'}, pregunta)
    assert pregunta_faltante(h, {campo: campo}, pregunta)
    assert pregunta_faltante(h, {campo: nombre}, pregunta) is None


def test_seguimiento_solo_usa_preguntas_previas_no_respuestas_del_asistente():
    h = REGISTRO['cliente_historial']
    historial = [{'pregunta': '¿Qué ha comprado Ana Pérez?',
                  'respuesta': 'La clienta es Beatriz López.'}]
    assert pregunta_faltante(h, {'cliente': 'Ana Pérez'}, '¿Y de ella?', historial) is None
    assert pregunta_faltante(h, {'cliente': 'Beatriz López'}, '¿Y de ella?', historial)
    assert pregunta_faltante(h, {'cliente': 'Ana Pérez'}, 'Consulta un historial nuevo', historial)


@pytest.mark.parametrize('code', [
    'ventas_periodo', 'finanzas_periodo', 'ticket_promedio', 'nomina_resumen',
    'pedidos_estado', 'proveedores', 'top_productos',
])
def test_omision_de_periodo_no_usa_defaults_heterogeneos(code):
    h = REGISTRO[code]
    assert normalizar_params_consulta(h, {}, 'Dame el resumen') == {'periodo': 'todo'}
    assert normalizar_params_consulta(h, {'periodo': 'mes'}, 'Dame el resumen') == {
        'periodo': 'todo'}
    assert pregunta_faltante(h, {}, 'Dame el resumen') is None


def test_comparativo_sin_periodo_conserva_ventana_finita():
    h = REGISTRO['comparativo_ventas']
    assert normalizar_params_consulta(h, {}, 'Compara mis ventas') == {'periodo': 'mes'}
    assert pregunta_faltante(h, {}, 'Compara mis ventas con el período anterior') is None


def test_periodo_explicito_gana_al_default_del_modelo_y_seguimiento():
    h = REGISTRO['finanzas_periodo']
    assert normalizar_params_consulta(h, {'periodo': 'mes'}, '¿Cuánto gané anteayer?') == {
        'periodo': 'anteayer'}
    assert normalizar_params_consulta(h,
                                      {'desde': '2020-01-01', 'hasta': '2020-01-31'},
                                      '¿Cuánto gané anteayer?') == {'periodo': 'anteayer'}
    historial = [{'pregunta': '¿Cuánto vendí el mes pasado?', 'respuesta': '$20'}]
    assert normalizar_params_consulta(h, {}, '¿Y la utilidad?', historial) == {
        'periodo': 'mes_anterior'}


def test_comparacion_de_dos_ventanas_no_se_aplana_a_una():
    h = REGISTRO['ventas_periodo']
    pregunta = 'Compara mis ventas de este mes y del mes pasado'
    assert normalizar_params_consulta(h, {'periodo': 'mes'}, pregunta) == {'periodo': 'mes'}
    assert normalizar_params_consulta(h, {'periodo': 'mes_anterior'}, pregunta) == {
        'periodo': 'mes_anterior'}
    assert pregunta_faltante(h, {'periodo': 'mes'}, pregunta) is None
    assert pregunta_faltante(h, {'periodo': 'mes_anterior'}, pregunta) is None
    assert pregunta_faltante(h, {'periodo': 'ayer'}, pregunta)


def test_comparacion_implicita_con_mes_pasado_conserva_mes_actual():
    h = REGISTRO['ventas_periodo']
    pregunta = '¿Vendí más que el mes pasado?'
    assert normalizar_params_consulta(h, {'periodo': 'mes'}, pregunta) == {'periodo': 'mes'}
    assert normalizar_params_consulta(h, {'periodo': 'mes_anterior'}, pregunta) == {
        'periodo': 'mes_anterior'}
    assert pregunta_faltante(h, {'periodo': 'mes'}, pregunta) is None


def test_comparar_con_mes_pasado_conserva_mes_actual():
    h = REGISTRO['ventas_periodo']
    pregunta = 'Quiero comparar con el mes pasado'
    assert normalizar_params_consulta(h, {'periodo': 'mes'}, pregunta) == {'periodo': 'mes'}
    assert pregunta_faltante(h, {'periodo': 'mes'}, pregunta) is None


def test_rango_parcial_pide_ambas_fechas():
    h = REGISTRO['ventas_periodo']
    assert pregunta_faltante(h, {'desde': '2026-08-01'}, 'Ventas en agosto de 2026')


@pytest.mark.parametrize('pregunta', [
    '¿Cuánto vendí en los últimos días?',
    '¿Cuánto vendí recientemente?',
    '¿Cuánto vendí en agosto de 2026?',
    '¿Cuánto vendí en los últimos 14 días?',
    '¿Cuánto vendí en la última quincena?',
    '¿Cuánto vendí el año pasado?',
    '¿Cuánto vendí la semana antepasada?',
    '¿Cuánto vendí hace 2 semanas?',
])
def test_tiempo_vago_o_fecha_especifica_sin_rango_pide_aclaracion(pregunta):
    h = REGISTRO['ventas_periodo']
    assert pregunta_faltante(h, {'periodo': 'mes'}, pregunta)


def test_rango_valido_se_conserva_y_rango_roto_se_aclara():
    h = REGISTRO['ventas_periodo']
    q = '¿Cuánto vendí en agosto de 2026?'
    valido = {'desde': '2026-08-01', 'hasta': '2026-08-31'}
    assert normalizar_params_consulta(h, valido, q) == valido
    assert pregunta_faltante(h, valido, q) is None
    assert pregunta_faltante(h, {'desde': '2026-08-31', 'hasta': '2026-08-01'}, q)
    assert pregunta_faltante(h, {'desde': '2026-08-99'}, q)


def test_catalogo_solo_menciona_los_procesos_permitidos():
    texto = instrucciones_para_catalogo([REGISTRO['cliente_historial'], REGISTRO['ventas_periodo']])
    assert 'cliente_historial requiere «cliente»' in texto
    assert 'nomina_empleado' not in texto
    assert 'producto_detalle' not in texto
    assert 'comparativo_ventas usa «mes»' in texto
