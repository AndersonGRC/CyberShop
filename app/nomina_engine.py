# app/nomina_engine.py

"""
Motor de cálculos de nómina colombiana.

Funciones puras (sin Flask, sin base de datos, sin pandas) que aplican la
normativa laboral y tributaria vigente. El escritorio usa una copia literal
de este archivo (CyberShopDesktop/nomina_calc.py) para liquidar offline con
EXACTAMENTE la misma matemática: si cambias algo aquí, cópialo allá.

Normas aplicadas:
- Código Sustantivo del Trabajo (CST): jornada, recargos, prestaciones,
  incapacidades (Art. 227), indemnización (Art. 64), salario integral (Art. 132).
- Ley 2101 de 2021: reducción gradual de la jornada (47 → 46 → 44 → 42 h).
- Ley 2466 de 2025: recargo dominical gradual (80 % → 90 % → 100 %), jornada
  nocturna desde las 19:00 y contrato de aprendizaje laboral especial.
- Ley 100 de 1993 y Ley 797 de 2003: salud, pensión y Fondo de Solidaridad.
- Ley 1393 de 2010, art. 30: pagos no salariales por encima del 40 %.
- Ley 21 de 1982, Ley 89 de 1988 y Art. 114-1 ET: parafiscales y exoneración.
- Estatuto Tributario: Art. 383 y 388 (retención laboral, procedimiento 1),
  Art. 387 (dependientes, vivienda, prepagada), Art. 126-1/126-4 (aportes
  voluntarios y AFC), Art. 206 num. 10 (25 % exento), Art. 336 (límite 40 % /
  1.340 UVT, Ley 2277 de 2022) y Art. 392 (honorarios y servicios).
- Ley 1955 de 2019, art. 244 y Decreto 1601 de 2022: seguridad social del
  contratista sobre el 40 % del valor mensual.
- Decreto 1072 de 2015: ARL de contratistas en riesgo IV y V a cargo del
  contratante.
"""

import calendar
from datetime import date, datetime


MOTOR_VERSION = "2026.10"


# =============================================================================
# Parámetros oficiales por año
# =============================================================================
# salario_minimo:     SMMLV.
# auxilio_transporte: para quien devengue hasta 2 SMMLV (Ley 15/1959).
# uvt:                Unidad de Valor Tributario (Art. 868 ET).
# estado:             "oficial" con decreto/resolución; "proyectado" si aún no.
PARAMETROS_OFICIALES_NOMINA = {
    2025: {
        "salario_minimo": 1423500.0,
        "auxilio_transporte": 200000.0,
        "uvt": 49799.0,
        "estado": "oficial",
        "fuente": "Decreto 1572 de 2024, Decreto 1573 de 2024 y Resolución DIAN 000193 de 2024",
    },
    2026: {
        "salario_minimo": 1750905.0,
        "auxilio_transporte": 249095.0,
        "uvt": 52374.0,
        "estado": "oficial",
        "fuente": "Decreto 159 de 2026, Decreto 1470 de 2025 y Resolución DIAN 000238 de 2025",
    },
    2027: {
        # Proyección con IPC esperado (~5,5 %) hasta que salgan los decretos
        # de fin de 2026. Actualizar en cuanto se publiquen.
        "salario_minimo": 1847205.0,
        "auxilio_transporte": 262795.0,
        "uvt": 55256.0,
        "estado": "proyectado",
        "fuente": "Proyección IPC 2026 (~5,5%). Pendiente decreto SMMLV 2027 y resolución UVT DIAN 2027.",
    },
}


# Jornada máxima semanal — Ley 2101 de 2021. Cada reducción rige desde el
# 15 de julio del año indicado.
TRAMOS_JORNADA_LEY_2101 = (
    (date(2023, 7, 15), 47),
    (date(2024, 7, 15), 46),
    (date(2025, 7, 15), 44),
    (date(2026, 7, 15), 42),
)

# Jornada vigente al cierre de cada año (referencia para pantallas).
JORNADA_LEY_2101 = {2023: 47, 2024: 46, 2025: 44, 2026: 42, 2027: 42}

# Ley 2466 de 2025: el trabajo nocturno empieza a las 19:00 (antes 21:00)
# desde el 25 de diciembre de 2025.
INICIO_NOCTURNA_19H = date(2025, 12, 25)

# Ley 2381 de 2024 (reforma pensional): Sentencia C-264 de 2026, rige desde
# el 1 de abril de 2027. Sus nuevos tramos del FSP no se cargan hasta que el
# Congreso corrija los artículos devueltos; mientras tanto se alerta.
INICIO_REFORMA_PENSIONAL = date(2027, 4, 1)


ARL_NIVELES = {
    "I": 0.522,
    "II": 1.044,
    "III": 2.436,
    "IV": 4.350,
    "V": 6.960,
}

TABLA_RETENCION_ART_383 = [
    {"rango_desde": 0, "rango_hasta": 95, "tarifa_marginal": 0.0, "uvt_mas": 0, "uvt_base": 0},
    {"rango_desde": 95, "rango_hasta": 150, "tarifa_marginal": 19.0, "uvt_mas": 0, "uvt_base": 95},
    {"rango_desde": 150, "rango_hasta": 360, "tarifa_marginal": 28.0, "uvt_mas": 10, "uvt_base": 150},
    {"rango_desde": 360, "rango_hasta": 640, "tarifa_marginal": 33.0, "uvt_mas": 69, "uvt_base": 360},
    {"rango_desde": 640, "rango_hasta": 945, "tarifa_marginal": 35.0, "uvt_mas": 162, "uvt_base": 640},
    {"rango_desde": 945, "rango_hasta": 2300, "tarifa_marginal": 37.0, "uvt_mas": 268, "uvt_base": 945},
    {"rango_desde": 2300, "rango_hasta": float("inf"), "tarifa_marginal": 39.0, "uvt_mas": 770, "uvt_base": 2300},
]

# Porcentajes de ley (Ley 100/1993, Ley 21/1982, Ley 89/1988).
SALUD_EMPLEADO = 4.0
SALUD_EMPLEADOR = 8.5
PENSION_EMPLEADO = 4.0
PENSION_EMPLEADOR = 12.0
CCF = 4.0
ICBF = 3.0
SENA = 2.0

# Contratistas (Ley 1955/2019 art. 244): IBC 40 % del valor mensual.
CONTRATISTA_IBC_PCT = 0.40
CONTRATISTA_SALUD = 12.5
CONTRATISTA_PENSION = 16.0

# Retención en la fuente (topes en UVT).
TOPE_DEPENDIENTES_UVT_MES = 32       # Art. 387 ET: 10 % del ingreso bruto
TOPE_VIVIENDA_UVT_MES = 100          # Art. 119 ET
TOPE_PREPAGADA_UVT_MES = 16          # Art. 387 ET
TOPE_VOLUNTARIOS_UVT_ANIO = 3800     # Art. 126-1 y 126-4 ET (30 % del ingreso)
TOPE_EXENTA_25_UVT_ANIO = 790        # Art. 206 num. 10 ET
TOPE_GLOBAL_UVT_ANIO = 1340          # Art. 336 ET (Ley 2277/2022)
LIMITE_GLOBAL_PCT = 0.40

# Art. 392 ET — Decreto 260/2001 y DUR 1625/2016.
HONORARIOS_UVT_TARIFA_11 = 3300      # contratos o pagos anuales > 3.300 UVT → 11 %
SERVICIOS_BASE_MINIMA_UVT = 4


# =============================================================================
# Catálogo de novedades
# =============================================================================
# grupo: dónde se acumula en el detalle; unidad: qué significa `cantidad`.
CATALOGO_NOVEDADES = {
    "HED": {"nombre": "Hora extra diurna", "grupo": "extras", "unidad": "horas"},
    "HEN": {"nombre": "Hora extra nocturna", "grupo": "extras", "unidad": "horas"},
    "HEDF": {"nombre": "Hora extra diurna dominical/festiva", "grupo": "extras", "unidad": "horas"},
    "HENF": {"nombre": "Hora extra nocturna dominical/festiva", "grupo": "extras", "unidad": "horas"},
    "RN": {"nombre": "Recargo nocturno", "grupo": "recargos", "unidad": "horas"},
    "RD": {"nombre": "Recargo dominical/festivo", "grupo": "recargos", "unidad": "horas"},
    "RNDF": {"nombre": "Recargo nocturno dominical/festivo", "grupo": "recargos", "unidad": "horas"},
    "INCAPACIDAD_GEN": {"nombre": "Incapacidad por enfermedad general", "grupo": "incapacidades", "unidad": "dias"},
    "INCAPACIDAD_LAB": {"nombre": "Incapacidad laboral (ARL)", "grupo": "incapacidades", "unidad": "dias"},
    "LICENCIA_MAT": {"nombre": "Licencia de maternidad", "grupo": "licencias", "unidad": "dias"},
    "LICENCIA_PAT": {"nombre": "Licencia de paternidad", "grupo": "licencias", "unidad": "dias"},
    "LICENCIA_LUTO": {"nombre": "Licencia de luto", "grupo": "licencias", "unidad": "dias"},
    "VACACIONES": {"nombre": "Vacaciones disfrutadas", "grupo": "licencias", "unidad": "dias"},
    "LICENCIA_NR": {"nombre": "Licencia no remunerada", "grupo": "ausencias", "unidad": "dias"},
    "BONIF_S": {"nombre": "Bonificación salarial", "grupo": "bonificaciones", "unidad": "valor"},
    "COMISION": {"nombre": "Comisión", "grupo": "comisiones", "unidad": "valor"},
    "BONIF_NS": {"nombre": "Bonificación no salarial", "grupo": "no_salarial", "unidad": "valor"},
    "PRESTAMO": {"nombre": "Descuento de préstamo", "grupo": "prestamos", "unidad": "valor"},
    "OTRA_DEDUCCION": {"nombre": "Otra deducción autorizada", "grupo": "otras_deducciones", "unidad": "valor"},
}

TIPOS_HORAS_EXTRAS = {"HED", "HEN", "HEDF", "HENF"}
TIPOS_RECARGOS = {"RN", "RD", "RNDF"}
TIPOS_EXTRAS = TIPOS_HORAS_EXTRAS | TIPOS_RECARGOS
TIPOS_INCAPACIDADES = {"INCAPACIDAD_GEN", "INCAPACIDAD_LAB"}
TIPOS_LICENCIAS_REMUNERADAS = TIPOS_INCAPACIDADES | {"LICENCIA_MAT", "LICENCIA_PAT", "LICENCIA_LUTO", "VACACIONES"}
TIPOS_LICENCIAS_NO_REMUNERADAS = {"LICENCIA_NR"}
TIPOS_DEDUCCIONES = {"PRESTAMO", "OTRA_DEDUCCION"}
TIPOS_CALCULABLES = TIPOS_EXTRAS | TIPOS_LICENCIAS_REMUNERADAS | TIPOS_LICENCIAS_NO_REMUNERADAS
TIPOS_SOPORTADOS = set(CATALOGO_NOVEDADES)


# =============================================================================
# Utilidades
# =============================================================================
def _to_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        resultado = float(value)
        if resultado != resultado:  # NaN
            return default
        return resultado
    except (TypeError, ValueError):
        return default


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "t", "si", "sí", "s", "on", "yes"}


def _to_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _money(value):
    return round(_to_float(value), 2)


def _alert(level, message, empleado_id=None):
    payload = {"nivel": level, "mensaje": message}
    if empleado_id is not None:
        payload["empleado_id"] = empleado_id
    return payload


def _hoy(fecha):
    return _to_date(fecha) or date.today()


# =============================================================================
# Jornada, valor hora y recargos
# =============================================================================
# Base histórica (48 h semanales × 30 / 6). Se conserva solo como referencia:
# el divisor vigente lo da `horas_mes(fecha)`.
BASE_HORAS_MENSUAL = 240


def jornada_semanal(fecha=None):
    """Horas semanales máximas vigentes en la fecha (Ley 2101/2021)."""
    fecha = _hoy(fecha)
    horas = 48
    for desde, valor in TRAMOS_JORNADA_LEY_2101:
        if fecha >= desde:
            horas = valor
    return horas


def horas_mes(fecha=None):
    """Divisor mensual para el valor hora: jornada semanal × 30 días / 6 días.
    48 h → 240 · 47 h → 235 · 46 h → 230 · 44 h → 220 · 42 h → 210."""
    return jornada_semanal(fecha) * 5


def hora_inicio_nocturna(fecha=None):
    """Hora en que empieza el trabajo nocturno (Ley 2466/2025): 19 o 21."""
    return 19 if _hoy(fecha) >= INICIO_NOCTURNA_19H else 21


def factor_recargo_dominical(fecha=None):
    """Recargo dominical/festivo (RD) por fecha — Ley 2466 de 2025 (gradual)."""
    fecha = _hoy(fecha)
    if fecha >= date(2027, 7, 1):
        return 1.00
    if fecha >= date(2026, 7, 1):
        return 0.90
    if fecha >= date(2025, 7, 1):
        return 0.80
    return 0.75


# Recargos y horas extras — Arts. 168 a 179 CST.
#   HED  hora extra diurna            1,25
#   HEN  hora extra nocturna          1,75
#   RN   recargo nocturno             0,35 (solo el recargo: la hora ya está en el salario)
#   RD   recargo dominical/festivo    rd(fecha)
#   HEDF hora extra diurna festiva    1,25 + rd(fecha)   (2,00 con rd 75 %)
#   HENF hora extra nocturna festiva  1,75 + rd(fecha)   (2,50 con rd 75 %)
#   RNDF recargo nocturno festivo     0,35 + rd(fecha)
_FACTORES_FIJOS = {"HED": 1.25, "HEN": 1.75, "RN": 0.35}
_FACTORES_FESTIVOS = {"HEDF": 1.25, "HENF": 1.75, "RNDF": 0.35, "RD": 0.0}

# Compatibilidad: valores con recargo dominical del 75 % (antes de jul-2025).
FACTORES_HORAS_EXTRAS = {"HED": 1.25, "HEN": 1.75, "HEDF": 2.00, "HENF": 2.50, "RN": 0.35, "RD": 0.75, "RNDF": 1.10}


def factor_hora(tipo, fecha=None):
    """Factor que multiplica el valor hora ordinario según tipo y fecha."""
    tipo = str(tipo or "").upper()
    if tipo in _FACTORES_FIJOS:
        return _FACTORES_FIJOS[tipo]
    if tipo in _FACTORES_FESTIVOS:
        return round(_FACTORES_FESTIVOS[tipo] + factor_recargo_dominical(fecha), 4)
    return 1.0


def factores_horas_extras(fecha=None):
    """Tabla de factores vigentes en la fecha (para pantallas y ayudas)."""
    return {tipo: factor_hora(tipo, fecha) for tipo in ("HED", "HEN", "HEDF", "HENF", "RN", "RD", "RNDF")}


def calcular_valor_hora(salario_base, fecha=None):
    """Valor de la hora ordinaria: salario mensual / horas_mes(fecha)."""
    return _to_float(salario_base) / horas_mes(fecha)


def calcular_horas_extras(valor_hora, tipo, cantidad, fecha=None):
    """Valor a pagar por horas extras o recargos en la fecha indicada."""
    return _to_float(valor_hora) * factor_hora(tipo, fecha) * _to_float(cantidad)


# =============================================================================
# Devengos básicos y seguridad social
# =============================================================================
def calcular_auxilio_transporte(salario_base, smmlv, valor_auxilio):
    """Auxilio de transporte (Ley 15 de 1959): hasta 2 SMMLV. No es salario
    para seguridad social, pero sí entra en la base de cesantías y prima."""
    if _to_float(salario_base) <= (2 * _to_float(smmlv)):
        return valor_auxilio
    return 0


def calcular_salud_pension(base_cotizacion, porcentaje_salud, porcentaje_pension):
    """Aportes del empleado a salud y pensión sobre el IBC (Ley 100 de 1993)."""
    salud = base_cotizacion * (porcentaje_salud / 100)
    pension = base_cotizacion * (porcentaje_pension / 100)
    return salud, pension


def porcentaje_fondo_solidaridad(veces_smmlv):
    """Tramos del FSP (Art. 27 Ley 100/1993, Art. 8 Ley 797/2003)."""
    if veces_smmlv < 4:
        return 0.0
    if veces_smmlv < 16:
        return 1.0
    if veces_smmlv < 17:
        return 1.2
    if veces_smmlv < 18:
        return 1.4
    if veces_smmlv < 19:
        return 1.6
    if veces_smmlv < 20:
        return 1.8
    return 2.0


def calcular_fondo_solidaridad(base_cotizacion, smmlv, base_mensual=None):
    """Fondo de Solidaridad Pensional a cargo del trabajador.

    El tramo se decide con el IBC MENSUAL (`base_mensual`); el porcentaje se
    aplica sobre la base del periodo. Sin `base_mensual` se asume que la base
    ya es mensual (compatibilidad)."""
    smmlv = _to_float(smmlv)
    if smmlv <= 0:
        return 0
    mensual = _to_float(base_mensual) if base_mensual is not None else _to_float(base_cotizacion)
    return _to_float(base_cotizacion) * (porcentaje_fondo_solidaridad(mensual / smmlv) / 100)


def calcular_arl(base_cotizacion, porcentaje_riesgo):
    """Aporte a Riesgos Laborales (Decreto 1295/1994), 100 % del empleador."""
    return base_cotizacion * (porcentaje_riesgo / 100)


def porcentaje_arl(nivel):
    return ARL_NIVELES.get(str(nivel or "I").strip().upper(), ARL_NIVELES["I"])


def calcular_parafiscales(base_cotizacion, smmlv, porcentajes, es_exonerado):
    """Caja (4 %), ICBF (3 %) y SENA (2 %). ICBF y SENA exonerados (Art. 114-1
    ET) para trabajadores que devenguen menos de 10 SMMLV cuando la empresa es
    persona jurídica o persona natural con 2 o más trabajadores."""
    caja = base_cotizacion * (porcentajes['ccf'] / 100)
    if es_exonerado and (base_cotizacion < (10 * smmlv)):
        icbf = 0
        sena = 0
    else:
        icbf = base_cotizacion * (porcentajes['icbf'] / 100)
        sena = base_cotizacion * (porcentajes['sena'] / 100)
    return caja, icbf, sena


def calcular_prestaciones(base_prestaciones, porcentajes):
    """Provisiones mensuales de prestaciones (CST y Ley 50/1990)."""
    cesantias = base_prestaciones * (porcentajes['cesantias'] / 100)
    intereses = cesantias * (12 / 100)
    prima = base_prestaciones * (porcentajes['prima'] / 100)
    vacaciones = base_prestaciones * (porcentajes['vacaciones'] / 100)
    return cesantias, intereses, prima, vacaciones


def calcular_ibc_empleado(salarial, no_salarial, smmlv, dias_cotizados, salario_integral=False, tiempo_completo=True):
    """IBC del periodo para seguridad social del trabajador dependiente.

    - Salario integral: 70 % del salario (Art. 132 CST, Art. 18 Ley 100).
    - Ley 1393/2010 art. 30: lo no salarial que supere el 40 % de la
      remuneración total se suma al IBC.
    - Piso: 1 SMMLV proporcional a los días cotizados (tiempo completo).
    - Tope: 25 SMMLV proporcional a los días cotizados.
    """
    salarial = _to_float(salarial)
    no_salarial = _to_float(no_salarial)
    smmlv = _to_float(smmlv)
    base = salarial * (0.70 if salario_integral else 1.0)
    total = salarial + no_salarial
    exceso_no_salarial = max(no_salarial - LIMITE_GLOBAL_PCT * total, 0.0) if total > 0 else 0.0
    base += exceso_no_salarial
    proporcion = max(_to_float(dias_cotizados), 0) / 30
    if smmlv > 0 and proporcion > 0:
        if tiempo_completo:
            base = max(base, smmlv * proporcion)
        base = min(base, 25 * smmlv * proporcion)
    if proporcion <= 0:
        base = 0.0
    return {"ibc": base, "exceso_no_salarial": exceso_no_salarial}


# =============================================================================
# Retención en la fuente
# =============================================================================
def retencion_tabla_383(base_gravable_pesos, uvt_valor, tabla_retencion=None):
    """Aplica la tabla del Art. 383 ET a una base MENSUAL en pesos."""
    uvt_valor = _to_float(uvt_valor)
    if uvt_valor <= 0 or base_gravable_pesos <= 0:
        return 0.0
    tabla = tabla_retencion or TABLA_RETENCION_ART_383
    base_uvt = base_gravable_pesos / uvt_valor
    for rango in tabla:
        if _to_float(rango['rango_desde']) <= base_uvt < _to_float(rango['rango_hasta'], float("inf")):
            retencion_uvt = ((base_uvt - _to_float(rango['uvt_base'])) * (_to_float(rango['tarifa_marginal']) / 100)) + _to_float(rango['uvt_mas'])
            return retencion_uvt * uvt_valor
    return 0.0


def depurar_base_retencion(ingreso_mensual, incr_mensual, uvt_valor, deducciones=None):
    """Depuración mensual de la base (procedimiento 1, Art. 388 ET).

    ingreso_mensual: pagos laborales (o honorarios) del mes.
    incr_mensual:    salud, pensión obligatoria y FSP (ingresos no constitutivos).
    deducciones:     dict con dependientes (bool), intereses_vivienda,
                     medicina_prepagada y aportes_voluntarios (valores del mes).
    Devuelve cada paso para poder explicarlo en pantalla.
    """
    uvt = _to_float(uvt_valor)
    d = deducciones or {}
    ingreso = max(_to_float(ingreso_mensual), 0.0)
    incr = max(_to_float(incr_mensual), 0.0)
    neto = max(ingreso - incr, 0.0)

    dependientes = min(0.10 * ingreso, TOPE_DEPENDIENTES_UVT_MES * uvt) if _to_bool(d.get("dependientes")) else 0.0
    vivienda = min(_to_float(d.get("intereses_vivienda")), TOPE_VIVIENDA_UVT_MES * uvt)
    prepagada = min(_to_float(d.get("medicina_prepagada")), TOPE_PREPAGADA_UVT_MES * uvt)
    total_deducciones = dependientes + vivienda + prepagada

    voluntarios = min(_to_float(d.get("aportes_voluntarios")), 0.30 * ingreso, TOPE_VOLUNTARIOS_UVT_ANIO / 12 * uvt)

    subtotal = max(neto - total_deducciones - voluntarios, 0.0)
    exenta_25 = min(subtotal * 0.25, TOPE_EXENTA_25_UVT_ANIO / 12 * uvt)

    beneficios = total_deducciones + voluntarios + exenta_25
    limite = min(LIMITE_GLOBAL_PCT * neto, TOPE_GLOBAL_UVT_ANIO / 12 * uvt)
    aplicados = min(beneficios, limite)
    base = max(neto - aplicados, 0.0)
    return {
        "ingreso": ingreso,
        "incr": incr,
        "neto": neto,
        "dependientes": dependientes,
        "intereses_vivienda": vivienda,
        "medicina_prepagada": prepagada,
        "aportes_voluntarios": voluntarios,
        "renta_exenta_25": exenta_25,
        "beneficios": beneficios,
        "limite_global": limite,
        "beneficios_aplicados": aplicados,
        "base_gravable": base,
        "base_gravable_uvt": (base / uvt) if uvt > 0 else 0.0,
    }


def calcular_retencion_fuente(ingreso_laboral, salud_pension_fsp, uvt_valor, tabla_retencion=None, deducciones=None):
    """Retención mensual por rentas de trabajo — procedimiento 1 (Art. 383 y
    388 ET), con deducciones, rentas exentas y el límite global del Art. 336."""
    if _to_float(uvt_valor) <= 0:
        return 0.0
    pasos = depurar_base_retencion(ingreso_laboral, salud_pension_fsp, uvt_valor, deducciones)
    return retencion_tabla_383(pasos["base_gravable"], uvt_valor, tabla_retencion)


def retencion_periodo(ingreso_periodo, incr_periodo, uvt, dias_periodo, deducciones=None, tabla_retencion=None):
    """Retención de un periodo (quincena o mes): se mensualiza, se calcula con
    la tabla mensual y se devuelve la parte proporcional. Las deducciones del
    empleado son valores MENSUALES y no se mensualizan."""
    if ingreso_periodo <= 0 or _to_float(uvt) <= 0 or dias_periodo <= 0:
        return 0.0, None
    factor = 30 / dias_periodo
    pasos = depurar_base_retencion(ingreso_periodo * factor, incr_periodo * factor, uvt, deducciones)
    mensual = retencion_tabla_383(pasos["base_gravable"], uvt, tabla_retencion)
    return mensual / factor, pasos


# =============================================================================
# Contratistas (prestación de servicios)
# =============================================================================
def calcular_ss_contratista(honorarios_mensuales, nivel_riesgo_arl_pct, smmlv=None):
    """Seguridad social que el contratista debe acreditar en la PILA.

    IBC = 40 % del valor mensual, mínimo 1 SMMLV y máximo 25 SMMLV
    (Ley 1955/2019 art. 244). Salud 12,5 %, pensión 16 %, FSP desde 4 SMMLV
    y ARL según el riesgo."""
    smmlv = _to_float(smmlv)
    base = _to_float(honorarios_mensuales) * CONTRATISTA_IBC_PCT
    if smmlv > 0 and base > 0:
        base = min(max(base, smmlv), 25 * smmlv)
    salud = base * CONTRATISTA_SALUD / 100
    pension = base * CONTRATISTA_PENSION / 100
    fsp = calcular_fondo_solidaridad(base, smmlv) if smmlv > 0 else 0.0
    arl = base * (_to_float(nivel_riesgo_arl_pct) / 100)
    return {
        'base': base,
        'salud': salud,
        'pension': pension,
        'fsp': fsp,
        'arl': arl,
        'total': salud + pension + fsp + arl,
    }


def calcular_retencion_contratista(honorarios_periodo, incr_periodo, uvt, dias_periodo, *,
                                   aplica_383=True, concepto="HONORARIOS", declarante=False,
                                   valor_anual=0.0, deducciones=None, tabla_retencion=None):
    """Retención al contratista persona natural.

    - Si NO ha contratado 2 o más trabajadores: tabla del Art. 383 (par. 2)
      con la seguridad social pagada como no constitutiva y el 25 % exento.
    - Si sí: Art. 392. Honorarios 10 % (11 % si el contrato o los pagos del año
      superan 3.300 UVT); servicios 4 % declarante / 6 % no declarante, con
      base mínima de 4 UVT.
    Devuelve (retención, explicación).
    """
    honorarios_periodo = _to_float(honorarios_periodo)
    uvt = _to_float(uvt)
    if honorarios_periodo <= 0 or uvt <= 0:
        return 0.0, {"norma": "Sin pago", "tarifa": 0}
    if aplica_383:
        valor, pasos = retencion_periodo(honorarios_periodo, incr_periodo, uvt, dias_periodo, deducciones, tabla_retencion)
        return valor, {"norma": "Art. 383 par. 2 ET (tabla de rentas de trabajo)", "pasos": pasos}
    concepto = str(concepto or "HONORARIOS").upper()
    if concepto == "SERVICIOS":
        if honorarios_periodo < SERVICIOS_BASE_MINIMA_UVT * uvt:
            return 0.0, {"norma": "Art. 392 ET — servicios por debajo de la base mínima (4 UVT)", "tarifa": 0}
        tarifa = 0.04 if declarante else 0.06
        return honorarios_periodo * tarifa, {"norma": "Art. 392 ET — servicios", "tarifa": tarifa}
    tarifa = 0.11 if _to_float(valor_anual) > HONORARIOS_UVT_TARIFA_11 * uvt else 0.10
    return honorarios_periodo * tarifa, {"norma": "Art. 392 ET — honorarios", "tarifa": tarifa}


# =============================================================================
# Incapacidades, licencias e indemnización
# =============================================================================
def desglose_incapacidad(salario_base, dias, tipo, smmlv):
    """Valor de una incapacidad o licencia y quién la asume.

    Enfermedad general (Art. 227 CST, Decreto 2943/2013, Decreto 1427/2022):
      - Días 1-2: a cargo del empleador, 66,67 %.
      - Días 3-90: EPS, 66,67 %. Días 91-180: 50 %.
      - Nunca por debajo de 1 SMMLV diario.
    Laboral (ARL): 100 % a cargo de la ARL.
    Maternidad y paternidad: 100 %, las paga la EPS.
    Luto (Ley 1280/2009) y vacaciones: 100 % a cargo del empleador.
    Licencia no remunerada: 0.
    """
    dias = max(_to_float(dias), 0.0)
    tipo = str(tipo or "").upper()
    valor_dia = _to_float(salario_base) / 30
    smmlv_dia = _to_float(smmlv) / 30 if smmlv else 0.0
    resultado = {"valor": 0.0, "empresa": 0.0, "cobrar": 0.0, "entidad": None}
    if dias <= 0:
        return resultado

    if tipo == "INCAPACIDAD_GEN":
        empresa = cobrar = 0.0
        restantes = dias
        tramos = ((2, 2 / 3, "empresa"), (88, 2 / 3, "eps"), (90, 0.5, "eps"))
        for limite, tasa, quien in tramos:
            if restantes <= 0:
                break
            tramo = min(limite, restantes)
            valor = max(valor_dia * tasa, smmlv_dia) * tramo
            if quien == "empresa":
                empresa += valor
            else:
                cobrar += valor
            restantes -= tramo
        resultado.update(valor=empresa + cobrar, empresa=empresa, cobrar=cobrar, entidad="EPS")
    elif tipo == "INCAPACIDAD_LAB":
        valor = valor_dia * dias
        resultado.update(valor=valor, cobrar=valor, entidad="ARL")
    elif tipo in ("LICENCIA_MAT", "LICENCIA_PAT"):
        valor = valor_dia * dias
        resultado.update(valor=valor, cobrar=valor, entidad="EPS")
    elif tipo in ("LICENCIA_LUTO", "VACACIONES"):
        valor = valor_dia * dias
        resultado.update(valor=valor, empresa=valor)
    return resultado


def calcular_incapacidad(salario_base, dias, tipo, smmlv):
    """Valor total de una incapacidad/licencia (ver `desglose_incapacidad`)."""
    return desglose_incapacidad(salario_base, dias, tipo, smmlv)["valor"]


def valor_novedad(tipo, cantidad, salario_base, smmlv, fecha=None):
    """Valor automático de una novedad calculable; None si el tipo exige que
    el usuario escriba el valor (bonificaciones, comisiones, deducciones)."""
    tipo = str(tipo or "").upper()
    if tipo in TIPOS_EXTRAS:
        return calcular_horas_extras(calcular_valor_hora(salario_base, fecha), tipo, cantidad, fecha)
    if tipo in TIPOS_LICENCIAS_REMUNERADAS:
        return calcular_incapacidad(salario_base, cantidad, tipo, smmlv)
    if tipo in TIPOS_LICENCIAS_NO_REMUNERADAS:
        return 0.0
    return None


def calcular_indemnizacion(salario, tipo_contrato, fecha_ingreso, fecha_retiro, smmlv, fecha_fin_contrato=None):
    """Indemnización por despido sin justa causa (Art. 64 CST).

    INDEFINIDO: < 10 SMMLV → 30 días el primer año + 20 por año adicional;
    ≥ 10 SMMLV → 20 + 15. Proporcional por fracción.
    FIJO: salarios del tiempo que falte para terminar el contrato.
    OBRA_LABOR: el tiempo faltante, no menos de 15 días.
    """
    if not fecha_ingreso or not fecha_retiro:
        return 0

    dias_laborados = dias_360(fecha_ingreso, fecha_retiro)
    valor_dia = salario / 30

    if tipo_contrato == 'INDEFINIDO':
        if salario < (10 * smmlv):
            dias_primer, dias_adicional = 30, 20
        else:
            dias_primer, dias_adicional = 20, 15
        if dias_laborados <= 360:
            return valor_dia * dias_primer * (dias_laborados / 360)
        return valor_dia * dias_primer + valor_dia * dias_adicional * ((dias_laborados - 360) / 360)

    if tipo_contrato == 'FIJO':
        if not fecha_fin_contrato:
            return 0
        return max(0, valor_dia * dias_360(fecha_retiro, fecha_fin_contrato, inclusivo=False))

    if tipo_contrato == 'OBRA_LABOR':
        if not fecha_fin_contrato:
            return valor_dia * 15
        return max(valor_dia * 15, valor_dia * dias_360(fecha_retiro, fecha_fin_contrato, inclusivo=False))

    return 0


def _es_ultimo_dia_mes(fecha):
    return fecha.day == calendar.monthrange(fecha.year, fecha.month)[1]


def dias_360(fecha_inicio, fecha_fin, inclusivo=True):
    """Días entre dos fechas con base 360 (meses de 30 días), estándar laboral
    colombiano. Incluye el día final por defecto. Un periodo que termina el
    último día del mes cuenta ese mes completo (febrero = 30 días)."""
    fecha_inicio = _to_date(fecha_inicio)
    fecha_fin = _to_date(fecha_fin)
    if not fecha_inicio or not fecha_fin:
        return 0
    dia_fin = 30 if _es_ultimo_dia_mes(fecha_fin) else min(fecha_fin.day, 30)
    dias = (fecha_fin.year - fecha_inicio.year) * 360 + \
           (fecha_fin.month - fecha_inicio.month) * 30 + \
           (dia_fin - min(fecha_inicio.day, 30))
    if inclusivo:
        dias += 1
    return max(0, dias)


# =============================================================================
# Liquidación del periodo
# =============================================================================
def dias_periodo(periodo):
    inicio = _to_date(periodo.get("fecha_inicio"))
    fin = _to_date(periodo.get("fecha_fin"))
    if inicio and fin:
        return dias_360(inicio, fin)
    return 15 if periodo.get("numero_periodo") in (1, 2) else 30


def dias_trabajados_en_periodo(empleado, fecha_inicio, fecha_fin, total_dias):
    """Días del periodo dentro de la relación laboral (ingreso y retiro)."""
    if not fecha_inicio or not fecha_fin:
        return total_dias
    ingreso = _to_date(empleado.get("fecha_ingreso"))
    retiro = _to_date(empleado.get("fecha_retiro"))
    if ingreso and ingreso > fecha_fin:
        return 0
    if retiro and retiro < fecha_inicio:
        return 0
    desde = ingreso if ingreso and ingreso > fecha_inicio else fecha_inicio
    hasta = retiro if retiro and retiro < fecha_fin else fecha_fin
    if desde == fecha_inicio and hasta == fecha_fin:
        return total_dias
    return min(dias_360(desde, hasta), total_dias)


def agrupar_novedades(novedades):
    """{empleado_id: {"cantidad_TIPO": x, "valor_total_TIPO": y}} y tipos vistos."""
    agregadas = {}
    tipos = set()
    for novedad in novedades or []:
        try:
            novedad = dict(novedad)
        except (TypeError, ValueError):
            continue
        empleado_id = int(_to_float(novedad.get("empleado_id"), 0))
        tipo = str(novedad.get("tipo_novedad") or "").strip().upper()
        if empleado_id <= 0 or not tipo:
            continue
        bucket = agregadas.setdefault(empleado_id, {})
        bucket[f"cantidad_{tipo}"] = bucket.get(f"cantidad_{tipo}", 0.0) + _to_float(novedad.get("cantidad"))
        bucket[f"valor_total_{tipo}"] = bucket.get(f"valor_total_{tipo}", 0.0) + _to_float(novedad.get("valor_total"))
        tipos.add(tipo)
    return agregadas, tipos


def alertas_parametros(periodo, params):
    """Compara los parámetros configurados con los oficiales del año."""
    anio = int(_to_float(periodo.get("anio"), 0))
    oficiales = PARAMETROS_OFICIALES_NOMINA.get(anio)
    alertas = []
    if oficiales:
        for clave, etiqueta in (("salario_minimo", "salario mínimo"), ("auxilio_transporte", "auxilio de transporte"), ("uvt", "UVT")):
            actual = _to_float(params.get(clave))
            oficial = _to_float(oficiales.get(clave))
            if abs(actual - oficial) > 1:
                alertas.append(_alert(
                    "warning",
                    f"El parámetro {etiqueta} {anio} no coincide con el valor oficial. "
                    f"Configurado: ${actual:,.0f}. Oficial: ${oficial:,.0f}. Fuente: {oficiales['fuente']}.",
                ))
    fin = _to_date(periodo.get("fecha_fin"))
    if fin and fin >= INICIO_REFORMA_PENSIONAL:
        alertas.append(_alert(
            "warning",
            "Desde el 1 de abril de 2027 rige la reforma pensional (Ley 2381 de 2024, Sentencia C-264 de 2026). "
            "Verifique los nuevos tramos del Fondo de Solidaridad y la distribución Colpensiones/AFP antes de aprobar.",
        ))
    return alertas


def _nombre(empleado):
    return f"{empleado.get('nombres', '') or ''} {empleado.get('apellidos', '') or ''}".strip() or f"Empleado {empleado.get('id')}"


def _deducciones_retencion(empleado):
    return {
        "dependientes": _to_bool(empleado.get("ret_dependientes")),
        "intereses_vivienda": _to_float(empleado.get("ret_intereses_vivienda")),
        "medicina_prepagada": _to_float(empleado.get("ret_medicina_prepagada")),
        "aportes_voluntarios": _to_float(empleado.get("ret_aportes_voluntarios")),
    }


def _detalle_vacio(empleado_id, dias):
    campos = (
        "sueldo_basico", "auxilio_transporte", "horas_extras", "recargos", "comisiones", "bonificaciones",
        "incapacidades", "licencias", "total_devengado", "salud_empleado", "pension_empleado",
        "fondo_solidaridad", "retencion_fuente", "prestamos", "otras_deducciones", "total_deducido",
        "neto_pagar", "salud_empleador", "pension_empleador", "arl", "sena", "icbf", "ccf",
        "cesantias_provision", "intereses_provision", "prima_provision", "vacaciones_provision",
        "ibc", "ss_contratista",
    )
    detalle = {campo: 0.0 for campo in campos}
    detalle.update(empleado_id=empleado_id, dias_trabajados=int(dias), calculo={})
    return detalle


def _liquidar_contratista(empleado, nov, ctx):
    empleado_id = int(_to_float(empleado.get("id"), 0))
    dias = ctx["dias_trabajados"]
    smmlv, uvt, dias_per = ctx["smmlv"], ctx["uvt"], ctx["dias_periodo"]
    honorarios_mes = _to_float(empleado.get("salario_base"))
    honorarios = honorarios_mes * (dias / 30) if dias else 0.0
    nivel = str(empleado.get("nivel_arl") or "I").strip().upper()
    alertas = []

    ss_mes = calcular_ss_contratista(honorarios_mes, porcentaje_arl(nivel), smmlv)
    proporcion = dias / 30 if dias else 0.0
    ss = {clave: valor * proporcion for clave, valor in ss_mes.items()}
    arl_empresa = 0.0
    arl_contratista = ss["arl"]
    if nivel in {"IV", "V"}:
        arl_empresa, arl_contratista = ss["arl"], 0.0
        alertas.append(_alert("info", f"{_nombre(empleado)}: ARL riesgo {nivel} a cargo de la empresa (Decreto 1072 de 2015).", empleado_id))
    if honorarios_mes and honorarios_mes * CONTRATISTA_IBC_PCT < smmlv:
        alertas.append(_alert(
            "info",
            f"{_nombre(empleado)}: el 40 % de sus honorarios es menor al SMMLV; cotiza sobre 1 SMMLV.",
            empleado_id,
        ))
    ss_pila = ss["salud"] + ss["pension"] + ss["fsp"] + arl_contratista

    aplica_383 = not _to_bool(empleado.get("ret_contrata_2_o_mas"))
    retencion, explicacion = calcular_retencion_contratista(
        honorarios, ss["salud"] + ss["pension"] + ss["fsp"], uvt, dias_per,
        aplica_383=aplica_383,
        concepto=empleado.get("ret_concepto") or "HONORARIOS",
        declarante=_to_bool(empleado.get("ret_declarante")),
        valor_anual=honorarios_mes * 12,
        deducciones=_deducciones_retencion(empleado),
    )
    prestamos = _to_float(nov.get("valor_total_PRESTAMO"))
    otras = _to_float(nov.get("valor_total_OTRA_DEDUCCION"))

    detalle = _detalle_vacio(empleado_id, dias)
    total_deducido = retencion + prestamos + otras
    detalle.update(
        sueldo_basico=_money(honorarios),
        total_devengado=_money(honorarios),
        retencion_fuente=_money(retencion),
        prestamos=_money(prestamos),
        otras_deducciones=_money(otras),
        total_deducido=_money(total_deducido),
        neto_pagar=_money(honorarios - total_deducido),
        arl=_money(arl_empresa),
        ibc=_money(ss["base"]),
        ss_contratista=_money(ss_pila),
        calculo={
            "tipo": "CONTRATISTA",
            "honorarios_mes": _money(honorarios_mes),
            "ibc": _money(ss["base"]),
            "pila": {
                "salud": _money(ss["salud"]), "pension": _money(ss["pension"]), "fsp": _money(ss["fsp"]),
                "arl": _money(arl_contratista), "total": _money(ss_pila),
            },
            "arl_empresa": _money(arl_empresa),
            "nivel_arl": nivel,
            "retencion": {"valor": _money(retencion), **{k: v for k, v in explicacion.items() if k != "pasos"}},
            "retencion_pasos": {k: _money(v) for k, v in (explicacion.get("pasos") or {}).items()},
            "nota": "La seguridad social la paga el contratista en su PILA; no se descuenta del pago.",
        },
    )
    return detalle, alertas


def _liquidar_empleado(empleado, nov, ctx):
    empleado_id = int(_to_float(empleado.get("id"), 0))
    dias = ctx["dias_trabajados"]
    smmlv, aux_valor, uvt, dias_per = ctx["smmlv"], ctx["aux_transporte"], ctx["uvt"], ctx["dias_periodo"]
    salario = _to_float(empleado.get("salario_base"))
    tipo_vinculacion = str(empleado.get("tipo_vinculacion") or "").upper()
    integral = _to_bool(empleado.get("salario_integral"))
    aprendiz = tipo_vinculacion == "APRENDIZ_SENA"
    etapa = str(empleado.get("aprendiz_etapa") or "LECTIVA").upper() if aprendiz else ""
    nivel = str(empleado.get("nivel_arl") or "I").strip().upper()
    nombre = _nombre(empleado)
    alertas = []

    def valor(tipos):
        return sum(_to_float(nov.get(f"valor_total_{t}")) for t in tipos)

    def cantidad(tipos):
        return sum(_to_float(nov.get(f"cantidad_{t}")) for t in tipos)

    dias_rem = cantidad(TIPOS_LICENCIAS_REMUNERADAS)
    dias_nr = cantidad(TIPOS_LICENCIAS_NO_REMUNERADAS)
    if dias_rem + dias_nr > dias:
        alertas.append(_alert(
            "warning",
            f"{nombre}: las novedades suman {dias_rem + dias_nr:.1f} días y exceden los {dias} días del periodo. "
            "El cálculo se limitó al máximo permitido.",
            empleado_id,
        ))
    dias_rem = min(dias_rem, dias)
    dias_nr = min(dias_nr, max(dias - dias_rem, 0))
    dias_basico = max(dias - dias_rem - dias_nr, 0)
    dias_cotizados = max(dias - dias_nr, 0)

    basico = salario * (dias_basico / 30) if dias_basico else 0.0
    horas_extras = valor(TIPOS_HORAS_EXTRAS)
    recargos = valor(TIPOS_RECARGOS)
    incapacidades = valor(TIPOS_INCAPACIDADES)
    licencias = valor({"LICENCIA_MAT", "LICENCIA_PAT", "LICENCIA_LUTO", "VACACIONES"})
    pagos_eps = incapacidades + valor({"LICENCIA_MAT", "LICENCIA_PAT"})
    comisiones = valor({"COMISION"})
    bonif_s = valor({"BONIF_S"})
    bonif_ns = valor({"BONIF_NS"})
    otros = sum(
        _to_float(v) for k, v in nov.items()
        if k.startswith("valor_total_") and k[len("valor_total_"):] not in TIPOS_SOPORTADOS
    )
    prestamos = valor({"PRESTAMO"})
    otras_deducciones = valor({"OTRA_DEDUCCION"})

    # Aprendiz SENA (Ley 2466/2025): lectiva 75 % SMMLV, productiva 100 % SMMLV.
    if aprendiz:
        minimo = smmlv * (0.75 if etapa == "LECTIVA" else 1.0)
        if salario < minimo - 1:
            alertas.append(_alert(
                "warning",
                f"{nombre}: el apoyo de sostenimiento (${salario:,.0f}) es menor al mínimo de la etapa "
                f"{etapa.lower()} (${minimo:,.0f}, Ley 2466 de 2025).",
                empleado_id,
            ))

    aplica_aux = not integral and not (aprendiz and etapa == "LECTIVA")
    aux_base = calcular_auxilio_transporte(salario, smmlv, aux_valor) if aplica_aux else 0.0
    aux = aux_base * (dias_basico / 30) if aux_base and dias_basico else 0.0

    salarial = basico + horas_extras + recargos + incapacidades + licencias + comisiones + bonif_s + otros
    total_devengado = salarial + bonif_ns + aux

    if not aprendiz:
        if salario < smmlv:
            alertas.append(_alert(
                "warning",
                f"{nombre}: el salario base (${salario:,.0f}) está por debajo del SMMLV (${smmlv:,.0f}). "
                "Revise si es tiempo parcial, suspensión o un dato mal cargado.",
                empleado_id,
            ))
        if integral and salario < 13 * smmlv:
            alertas.append(_alert(
                "warning",
                f"{nombre}: el salario integral debe ser de al menos 13 SMMLV (${13 * smmlv:,.0f}, Art. 132 CST).",
                empleado_id,
            ))
        for campo, texto in (("eps", "EPS"), ("fondo_pension", "fondo de pensión")):
            if not str(empleado.get(campo) or "").strip():
                alertas.append(_alert("warning", f"{nombre}: no tiene {texto} registrada.", empleado_id))
        if not integral and not str(empleado.get("fondo_cesantias") or "").strip():
            alertas.append(_alert("warning", f"{nombre}: no tiene fondo de cesantías registrado.", empleado_id))

    # ---- Seguridad social
    if aprendiz and etapa == "LECTIVA":
        # Salud y ARL a cargo plenamente de la empresa, sobre 1 SMMLV.
        ibc = smmlv * (dias_cotizados / 30)
        exceso = 0.0
        salud_emp = pension_emp = fsp = 0.0
        salud_er = ibc * (SALUD_EMPLEADO + SALUD_EMPLEADOR) / 100
        pension_er = 0.0
    else:
        calculo_ibc = calcular_ibc_empleado(salarial, bonif_ns, smmlv, dias_cotizados, integral, tiempo_completo=salario >= smmlv)
        ibc, exceso = calculo_ibc["ibc"], calculo_ibc["exceso_no_salarial"]
        salud_emp, pension_emp = calcular_salud_pension(ibc, SALUD_EMPLEADO, PENSION_EMPLEADO)
        ibc_mensual = ibc * 30 / dias_cotizados if dias_cotizados else 0.0
        fsp = calcular_fondo_solidaridad(ibc, smmlv, base_mensual=ibc_mensual)
        exonerado = ctx["exonerado"] and salario < 10 * smmlv
        salud_er = 0.0 if exonerado else ibc * SALUD_EMPLEADOR / 100
        pension_er = ibc * PENSION_EMPLEADOR / 100
    arl = calcular_arl(ibc, porcentaje_arl(nivel))

    # ---- Parafiscales (sobre la nómina salarial; no sobre incapacidades ni licencias EPS)
    if aprendiz and etapa == "LECTIVA":
        ccf = icbf = sena = 0.0
        base_parafiscal = 0.0
    else:
        base_parafiscal = max((salarial - pagos_eps) * (0.70 if integral else 1.0) + exceso, 0.0)
        exonerado = ctx["exonerado"] and salario < 10 * smmlv
        ccf = base_parafiscal * CCF / 100
        icbf = 0.0 if exonerado else base_parafiscal * ICBF / 100
        sena = 0.0 if exonerado else base_parafiscal * SENA / 100

    # ---- Provisiones de prestaciones
    if aprendiz and etapa == "LECTIVA":
        cesantias = intereses = prima = vacaciones = 0.0
    else:
        devengado_tiempo = salario * (dias_cotizados / 30)
        variables = horas_extras + recargos + comisiones + bonif_s + otros
        base_prestaciones = devengado_tiempo + variables + aux
        vacaciones = (devengado_tiempo + comisiones) * (15 / 360)
        if integral:
            cesantias = intereses = prima = 0.0
        else:
            cesantias = base_prestaciones / 12
            intereses = cesantias * 0.12
            prima = base_prestaciones / 12

    # ---- Retención en la fuente
    retencion, pasos = 0.0, None
    if not aprendiz:
        retencion, pasos = retencion_periodo(
            total_devengado, salud_emp + pension_emp + fsp, uvt, dias_per, _deducciones_retencion(empleado),
        )

    total_deducido = salud_emp + pension_emp + fsp + retencion + prestamos + otras_deducciones
    neto = total_devengado - total_deducido
    if neto < 0:
        alertas.append(_alert("danger", f"{nombre}: las deducciones superan lo devengado; revise préstamos y descuentos.", empleado_id))

    desglose_eps = {}
    for tipo in TIPOS_LICENCIAS_REMUNERADAS:
        dias_tipo = _to_float(nov.get(f"cantidad_{tipo}"))
        if dias_tipo > 0:
            d = desglose_incapacidad(salario, dias_tipo, tipo, smmlv)
            desglose_eps[tipo] = {k: (_money(v) if isinstance(v, float) else v) for k, v in d.items()}

    detalle = _detalle_vacio(empleado_id, dias)
    detalle.update(
        sueldo_basico=_money(basico),
        auxilio_transporte=_money(aux),
        # `horas_extras` conserva el total de extras + recargos (compatibilidad
        # con pantallas y escritorio); `recargos` informa la parte de recargos.
        horas_extras=_money(horas_extras + recargos),
        recargos=_money(recargos),
        comisiones=_money(comisiones),
        bonificaciones=_money(bonif_s + bonif_ns + otros),
        incapacidades=_money(incapacidades),
        licencias=_money(licencias),
        total_devengado=_money(total_devengado),
        salud_empleado=_money(salud_emp),
        pension_empleado=_money(pension_emp),
        fondo_solidaridad=_money(fsp),
        retencion_fuente=_money(retencion),
        prestamos=_money(prestamos),
        otras_deducciones=_money(otras_deducciones),
        total_deducido=_money(total_deducido),
        neto_pagar=_money(neto),
        salud_empleador=_money(salud_er),
        pension_empleador=_money(pension_er),
        arl=_money(arl),
        ccf=_money(ccf),
        icbf=_money(icbf),
        sena=_money(sena),
        cesantias_provision=_money(cesantias),
        intereses_provision=_money(intereses),
        prima_provision=_money(prima),
        vacaciones_provision=_money(vacaciones),
        ibc=_money(ibc),
        calculo={
            "tipo": "APRENDIZ_" + etapa if aprendiz else ("INTEGRAL" if integral else "EMPLEADO"),
            "salario_base": _money(salario),
            "dias": {"periodo": dias_per, "trabajados": dias, "basico": dias_basico,
                     "remunerados_novedad": dias_rem, "no_remunerados": dias_nr},
            "valor_hora": _money(calcular_valor_hora(salario, ctx["fecha_fin"])),
            "horas_mes": horas_mes(ctx["fecha_fin"]),
            "salarial": _money(salarial),
            "no_salarial": _money(bonif_ns),
            "exceso_no_salarial_40": _money(exceso),
            "ibc": _money(ibc),
            "fsp_pct": porcentaje_fondo_solidaridad((ibc * 30 / dias_cotizados / smmlv) if dias_cotizados and smmlv else 0),
            "exonerado_114_1": bool(ctx["exonerado"] and salario < 10 * smmlv),
            "base_parafiscal": _money(base_parafiscal),
            "nivel_arl": nivel,
            "incapacidades_licencias": desglose_eps,
            "retencion_pasos": {k: _money(v) for k, v in (pasos or {}).items()},
            "costo_empresa": _money(total_devengado + salud_er + pension_er + arl + ccf + icbf + sena
                                    + cesantias + intereses + prima + vacaciones),
        },
    )
    return detalle, alertas


_DEVENGOS = ("sueldo_basico", "auxilio_transporte", "horas_extras", "comisiones", "bonificaciones", "incapacidades", "licencias")
_DEDUCCIONES = ("salud_empleado", "pension_empleado", "fondo_solidaridad", "retencion_fuente", "prestamos", "otras_deducciones")


def _cuadrar(detalle):
    """Totales = suma exacta de los conceptos redondeados que se muestran, para
    que el desprendible cuadre al centavo."""
    detalle["total_devengado"] = _money(sum(detalle[c] for c in _DEVENGOS))
    detalle["total_deducido"] = _money(sum(detalle[c] for c in _DEDUCCIONES))
    detalle["neto_pagar"] = _money(detalle["total_devengado"] - detalle["total_deducido"])


def liquidar_periodo(periodo, params, empleados, novedades):
    """Liquida un periodo de nómina completo.

    periodo:   fecha_inicio, fecha_fin, anio, numero_periodo.
    params:    salario_minimo, auxilio_transporte, uvt y exonerado_114_1
               (True por defecto: persona jurídica o natural con 2+ empleados).
    empleados: registros de nomina_empleados.
    novedades: registros (individuales o agrupados) de nomina_novedades.

    Devuelve detalles por persona (columnas de nomina_detalle + `calculo` con
    la explicación), alertas, resumen, versión del motor y parámetros usados.
    """
    periodo = dict(periodo or {})
    params = dict(params or {})
    smmlv = _to_float(params.get("salario_minimo"))
    exonerado_param = params.get("exonerado_114_1")
    ctx = {
        "smmlv": smmlv,
        "aux_transporte": _to_float(params.get("auxilio_transporte")),
        "uvt": _to_float(params.get("uvt")),
        "exonerado": True if exonerado_param is None else _to_bool(exonerado_param),
        "fecha_inicio": _to_date(periodo.get("fecha_inicio")),
        "fecha_fin": _to_date(periodo.get("fecha_fin")),
        "dias_periodo": dias_periodo(periodo),
    }

    alertas = alertas_parametros(periodo, params)
    por_empleado, tipos = agrupar_novedades(novedades)
    for tipo in sorted(tipos - TIPOS_SOPORTADOS):
        alertas.append(_alert(
            "warning",
            f"La novedad {tipo} no tiene regla automática. Se tomó como devengado salarial manual.",
        ))

    detalles = []
    empleados_n = contratistas_n = 0
    for empleado in empleados or []:
        try:
            empleado = dict(empleado)
        except (TypeError, ValueError):
            continue
        empleado_id = int(_to_float(empleado.get("id"), 0))
        if empleado_id <= 0:
            continue
        ctx["dias_trabajados"] = dias_trabajados_en_periodo(empleado, ctx["fecha_inicio"], ctx["fecha_fin"], ctx["dias_periodo"])
        nov = por_empleado.get(empleado_id, {})
        if str(empleado.get("tipo_vinculacion") or "").upper() == "CONTRATISTA":
            contratistas_n += 1
            detalle, extra = _liquidar_contratista(empleado, nov, ctx)
        else:
            empleados_n += 1
            detalle, extra = _liquidar_empleado(empleado, nov, ctx)
        _cuadrar(detalle)
        detalles.append(detalle)
        alertas.extend(extra)

    aportes = sum(d["salud_empleador"] + d["pension_empleador"] + d["arl"] + d["ccf"] + d["icbf"] + d["sena"] for d in detalles)
    provisiones = sum(d["cesantias_provision"] + d["intereses_provision"] + d["prima_provision"] + d["vacaciones_provision"] for d in detalles)
    devengado = sum(d["total_devengado"] for d in detalles)
    resumen = {
        "empleados": empleados_n,
        "contratistas": contratistas_n,
        "total_devengado": _money(devengado),
        "total_deducido": _money(sum(d["total_deducido"] for d in detalles)),
        "total_neto": _money(sum(d["neto_pagar"] for d in detalles)),
        "aportes_empleador": _money(aportes),
        "provisiones": _money(provisiones),
        "costo_total": _money(devengado + aportes + provisiones),
    }
    parametros_usados = {
        "salario_minimo": smmlv,
        "auxilio_transporte": ctx["aux_transporte"],
        "uvt": ctx["uvt"],
        "exonerado_114_1": ctx["exonerado"],
        "horas_mes": horas_mes(ctx["fecha_fin"]),
        "recargo_dominical": factor_recargo_dominical(ctx["fecha_fin"]),
        "dias_periodo": ctx["dias_periodo"],
    }
    return {
        "detalles": detalles,
        "alertas": alertas,
        "resumen": resumen,
        "motor_version": MOTOR_VERSION,
        "parametros_usados": parametros_usados,
    }


# =============================================================================
# Liquidación definitiva del contrato
# =============================================================================
MOTIVOS_RETIRO = {
    "RENUNCIA": "Renuncia voluntaria",
    "TERMINACION_CONTRATO": "Terminación del plazo o de la obra",
    "MUTUO_ACUERDO": "Mutuo acuerdo",
    "DESPIDO_JUSTO": "Despido con justa causa",
    "DESPIDO_INJUSTO": "Despido sin justa causa",
}


def liquidar_contrato(empleado, fecha_retiro, motivo, params, *, promedio_variable=0.0,
                      dias_vacaciones_pendientes=None, dias_vacaciones_disfrutadas_anio=0.0,
                      salarios_pendientes=0.0, deducciones_pendientes=0.0):
    """Liquidación definitiva (prestaciones al retiro).

    - Cesantías (Art. 249 CST) e intereses (Ley 52/1975): del 1 de enero (o el
      ingreso) a la fecha de retiro.
    - Prima (Art. 306 CST): del semestre en curso.
    - Base: salario + promedio de lo variable + auxilio de transporte si gana
      hasta 2 SMMLV. Salario integral: sin cesantías ni prima.
    - Vacaciones (Art. 186 y 189 CST): días pendientes × salario / 30.
    - Indemnización (Art. 64 CST): SOLO en despido sin justa causa.
    """
    fecha_retiro = _to_date(fecha_retiro)
    ingreso = _to_date(empleado.get("fecha_ingreso"))
    smmlv = _to_float(params.get("salario_minimo"))
    aux_valor = _to_float(params.get("auxilio_transporte"))
    salario = _to_float(empleado.get("salario_base"))
    integral = _to_bool(empleado.get("salario_integral"))
    tipo = str(empleado.get("tipo_vinculacion") or "").upper()
    motivo = str(motivo or "").upper()
    alertas = []

    if not fecha_retiro or not ingreso:
        raise ValueError("Faltan la fecha de ingreso o la de retiro.")
    if fecha_retiro < ingreso:
        raise ValueError("La fecha de retiro no puede ser anterior a la fecha de ingreso.")
    if tipo == "CONTRATISTA":
        raise ValueError("Los contratistas no tienen prestaciones sociales: no se liquidan como empleados.")

    inicio_anio = max(ingreso, fecha_retiro.replace(month=1, day=1))
    inicio_semestre = max(ingreso, fecha_retiro.replace(month=1 if fecha_retiro.month <= 6 else 7, day=1))
    dias_anio = dias_360(inicio_anio, fecha_retiro)
    dias_semestre = dias_360(inicio_semestre, fecha_retiro)
    dias_total = dias_360(ingreso, fecha_retiro)

    variable = max(_to_float(promedio_variable), 0.0)
    aux = calcular_auxilio_transporte(salario, smmlv, aux_valor) if not integral else 0.0
    base_prestaciones = salario + variable + aux

    if integral:
        cesantias = intereses = prima = 0.0
    else:
        cesantias = base_prestaciones * dias_anio / 360
        intereses = cesantias * dias_anio * 0.12 / 360
        prima = base_prestaciones * dias_semestre / 360

    causadas_anio = dias_anio * 15 / 360
    if dias_vacaciones_pendientes is None:
        dias_vacaciones_pendientes = max(causadas_anio - _to_float(dias_vacaciones_disfrutadas_anio), 0.0)
    dias_vacaciones_pendientes = max(_to_float(dias_vacaciones_pendientes), 0.0)
    # Art. 192 CST: las vacaciones se pagan con el salario ordinario (sin horas
    # extras ni recargos dominicales).
    vacaciones = salario / 30 * dias_vacaciones_pendientes

    indemnizacion = 0.0
    if motivo == "DESPIDO_INJUSTO":
        indemnizacion = calcular_indemnizacion(
            salario, tipo, ingreso, fecha_retiro, smmlv, fecha_fin_contrato=_to_date(empleado.get("fecha_fin_contrato")),
        )
        if tipo in ("FIJO", "OBRA_LABOR") and not empleado.get("fecha_fin_contrato"):
            alertas.append(_alert("warning", "El contrato no tiene fecha de terminación registrada: la indemnización puede quedar incompleta."))

    if fecha_retiro.month == 1 or (fecha_retiro.month == 2 and fecha_retiro.day <= 14):
        if ingreso.year < fecha_retiro.year:
            alertas.append(_alert(
                "warning",
                "El retiro es antes del 14 de febrero: si las cesantías del año anterior no se consignaron al fondo, "
                "deben pagarse directamente al trabajador junto con sus intereses.",
            ))

    salarios_pendientes = max(_to_float(salarios_pendientes), 0.0)
    deducciones_pendientes = max(_to_float(deducciones_pendientes), 0.0)
    # El total es la suma de los valores redondeados que ve la persona.
    total = sum(_money(v) for v in (cesantias, intereses, prima, vacaciones, indemnizacion, salarios_pendientes)) \
        - _money(deducciones_pendientes)

    return {
        "dias_liquidacion": dias_anio,
        "dias_semestre": dias_semestre,
        "dias_total": dias_total,
        "salario_base_liquidacion": _money(salario),
        "base_prestaciones": _money(base_prestaciones),
        "promedio_variable": _money(variable),
        "auxilio_transporte": _money(aux),
        "cesantias": _money(cesantias),
        "intereses_cesantias": _money(intereses),
        "prima_servicios": _money(prima),
        "dias_vacaciones": round(dias_vacaciones_pendientes, 2),
        "vacaciones": _money(vacaciones),
        "indemnizacion": _money(indemnizacion),
        "salarios_pendientes": _money(salarios_pendientes),
        "deducciones_pendientes": _money(deducciones_pendientes),
        "total_pagar": _money(total),
        "motivo": motivo,
        "alertas": alertas,
    }
