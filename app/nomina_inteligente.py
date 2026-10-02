"""
Capa de nómina colombiana usada por las rutas.

Toda la matemática vive en `nomina_engine` (funciones puras, idénticas en el
escritorio). Este módulo conserva los nombres que ya usan las rutas y la
sincronización del escritorio, y expone las tablas normativas de referencia.
"""

from __future__ import annotations

from typing import Any

from nomina_engine import (  # noqa: F401  (re-exportados para compatibilidad)
    ARL_NIVELES,
    CATALOGO_NOVEDADES,
    JORNADA_LEY_2101,
    MOTOR_VERSION,
    PARAMETROS_OFICIALES_NOMINA,
    TABLA_RETENCION_ART_383,
    TIPOS_EXTRAS,
    TIPOS_LICENCIAS_NO_REMUNERADAS,
    TIPOS_LICENCIAS_REMUNERADAS,
    TIPOS_SOPORTADOS,
    jornada_semanal,
    horas_mes,
    factores_horas_extras,
    hora_inicio_nocturna,
    liquidar_periodo,
)


# Porcentajes de aportes a Seguridad Social (Ley 100 de 1993).
APORTES_SEGURIDAD_SOCIAL = {
    "salud_empleado": 4.0,        # Art. 204 Ley 100
    "salud_empleador": 8.5,       # Exonerado (Art. 114-1 ET) si devenga < 10 SMMLV
    "pension_empleado": 4.0,      # Art. 20 Ley 100
    "pension_empleador": 12.0,    # Art. 20 Ley 100
    "arl_minimo": 0.522,          # Riesgo I (Decreto 1295/1994)
    "arl_maximo": 6.96,           # Riesgo V (Decreto 1295/1994)
}


# Aportes parafiscales (Ley 21/1982, Ley 27/1974, Ley 89/1988).
APORTES_PARAFISCALES = {
    "caja_compensacion": 4.0,     # Siempre se paga
    "icbf": 3.0,                  # Exonerado (Art. 114-1 ET) si devenga < 10 SMMLV
    "sena": 2.0,                  # Exonerado (Art. 114-1 ET) si devenga < 10 SMMLV
}


# Provisiones de prestaciones sociales mensuales (CST).
PROVISIONES_PRESTACIONES = {
    "cesantias": 8.33,            # Art. 249 CST: 1 mes de salario por año
    "intereses_cesantias": 12.0,  # Ley 52/1975: 12% anual sobre cesantías
    "prima_servicios": 8.33,      # Art. 306 CST: 30 días al año (30 jun + 20 dic)
    "vacaciones": 4.17,           # Art. 186 CST: 15 días hábiles por año
}


def obtener_referencia_normativa(anio: int) -> dict[str, Any] | None:
    """Parámetros oficiales (o proyectados) de un año, para formularios."""
    if not anio:
        return None
    referencia = PARAMETROS_OFICIALES_NOMINA.get(int(anio))
    if not referencia:
        return None
    return {
        **referencia,
        "anio": int(anio),
        "jornada_semanal": JORNADA_LEY_2101.get(int(anio), 42),
    }


def calcular_nomina_periodo_inteligente(
    periodo: dict[str, Any],
    params: dict[str, Any],
    empleados: list[Any],
    novedades: list[Any],
) -> dict[str, Any]:
    """Liquida el periodo con el motor único (`nomina_engine.liquidar_periodo`)."""
    return liquidar_periodo(periodo, params, empleados, novedades)
