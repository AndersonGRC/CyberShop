# app/nomina_engine.py

"""
Motor de cálculos de nómina colombiana.

Contiene funciones puras (sin Flask ni base de datos) que aplican la
normativa laboral y tributaria vigente:

- Código Sustantivo del Trabajo (CST).
- Ley 100 de 1993 (Seguridad Social).
- Ley 1607 de 2012 (exoneración de aportes para salarios < 10 SMMLV).
- Ley 50 de 1990 (cesantías y prima de servicios).
- Ley 2101 de 2021 (reducción gradual de la jornada laboral).
- Estatuto Tributario, Art. 383 (retención en la fuente laboral).

Los porcentajes oficiales viven en `nomina_inteligente.py` para evitar
duplicación. Aquí se reciben como parámetros para que el motor sea
totalmente probable y reutilizable.
"""

from datetime import date, timedelta


# Base mensual de horas usada para calcular el valor hora ordinario.
# Históricamente 240 (30 días × 8 h). La Ley 2101/2021 redujo la jornada
# semanal pero mantuvo intacto el salario; en la práctica se sigue usando
# 240 h/mes como base contable, salvo pacto distinto entre las partes.
BASE_HORAS_MENSUAL = 240


# Recargos y horas extras — Art. 168 a 179 CST.
#   HED:  Hora Extra Diurna           (+25% sobre la hora ordinaria)
#   HEN:  Hora Extra Nocturna         (+75%)
#   HEDF: Hora Extra Diurna Festiva   (+100%)
#   HENF: Hora Extra Nocturna Festiva (+150%)
#   RN:   Recargo Nocturno            (+35% sobre la hora ordinaria)
#   RD:   Recargo Dominical/Festivo   (+75%)
FACTORES_HORAS_EXTRAS = {
    'HED': 1.25,
    'HEN': 1.75,
    'HEDF': 2.00,
    'HENF': 2.50,
    'RN': 0.35,
    'RD': 0.75,
}


def calcular_valor_hora(salario_base):
    """
    Valor de la hora ordinaria de trabajo.

    Fórmula: salario mensual / 240 horas (base contable estándar).
    """
    return salario_base / BASE_HORAS_MENSUAL


def calcular_horas_extras(valor_hora, tipo, cantidad):
    """
    Calcula el valor a pagar por horas extras o recargos.

    Args:
        valor_hora: valor de la hora ordinaria (ver `calcular_valor_hora`).
        tipo: código del recargo (HED, HEN, HEDF, HENF, RN, RD).
        cantidad: número de horas extra o de recargo.

    Returns:
        Valor en pesos a pagar por el concepto.
    """
    factor = FACTORES_HORAS_EXTRAS.get(tipo, 1.0)
    return valor_hora * factor * cantidad

def calcular_auxilio_transporte(salario_base, smmlv, valor_auxilio):
    """
    Auxilio de transporte (Ley 15 de 1959, Decreto 1258 de 1959).

    Se reconoce a quienes devenguen hasta dos (2) SMMLV. No es factor
    salarial pero sí entra en la base de prestaciones sociales (Art. 7
    Ley 1ª/1963).
    """
    if salario_base <= (2 * smmlv):
        return valor_auxilio
    return 0

def calcular_salud_pension(base_cotizacion, porcentaje_salud, porcentaje_pension):
    """
    Aportes del empleado a salud y pensión (Ley 100 de 1993).

    Por defecto los porcentajes son 4% y 4% sobre el IBC (Ingreso Base
    de Cotización), pero se pasan como parámetro para permitir tarifas
    especiales (servicio doméstico, regímenes excepcionales, etc.).
    """
    salud = base_cotizacion * (porcentaje_salud / 100)
    pension = base_cotizacion * (porcentaje_pension / 100)
    return salud, pension

def calcular_fondo_solidaridad(base_cotizacion, smmlv):
    """
    Fondo de Solidaridad Pensional (Art. 27 Ley 100/1993, Art. 8 Ley 797/2003).

    Aporte adicional a cargo del trabajador, calculado por tramos de SMMLV:

      < 4 SMMLV:        0%
      4 a < 16 SMMLV:   1.0%
      16 a < 17 SMMLV:  1.2%
      17 a < 18 SMMLV:  1.4%
      18 a < 19 SMMLV:  1.6%
      19 a < 20 SMMLV:  1.8%
      >= 20 SMMLV:      2.0%
    """
    if smmlv == 0: return 0
    veces_smmlv = base_cotizacion / smmlv
    
    porcentaje = 0
    if 4 <= veces_smmlv < 16:
        porcentaje = 1.0
    elif 16 <= veces_smmlv < 17:
        porcentaje = 1.2
    elif 17 <= veces_smmlv < 18:
        porcentaje = 1.4
    elif 18 <= veces_smmlv < 19:
        porcentaje = 1.6
    elif 19 <= veces_smmlv < 20:
        porcentaje = 1.8
    elif veces_smmlv >= 20:
        porcentaje = 2.0
        
    return base_cotizacion * (porcentaje / 100)

def calcular_arl(base_cotizacion, porcentaje_riesgo):
    """
    Aporte a Riesgos Laborales (Decreto 1295/1994).

    El 100% lo asume el empleador. La tarifa depende del nivel de riesgo
    de la actividad económica (I a V), entre 0.522% y 6.96%.
    """
    return base_cotizacion * (porcentaje_riesgo / 100)


def calcular_parafiscales(base_cotizacion, smmlv, porcentajes, es_exonerado):
    """
    Aportes parafiscales — Caja de Compensación, ICBF y SENA.

    Caja (Ley 21/1982):     4% — siempre se paga.
    ICBF (Ley 89/1988):     3% — exonerado por Ley 1607/2012 si la empresa
                                 es persona jurídica o natural empleadora
                                 de 2+ trabajadores y el salario del
                                 trabajador es inferior a 10 SMMLV.
    SENA (Ley 119/1994):    2% — misma exoneración que ICBF.
    Salud empleador (8.5%): se paga por fuera de esta función; aplica la
                            misma exoneración del Art. 114-1 ET.
    """
    caja = base_cotizacion * (porcentajes['ccf'] / 100)
    
    # Exoneración Ley 1607: Ingreso total < 10 SMMLV
    if es_exonerado and (base_cotizacion < (10 * smmlv)):
        icbf = 0
        sena = 0
    else:
        icbf = base_cotizacion * (porcentajes['icbf'] / 100)
        sena = base_cotizacion * (porcentajes['sena'] / 100)
        
    return caja, icbf, sena

def calcular_prestaciones(base_prestaciones, porcentajes):
    """
    Provisiones mensuales de prestaciones sociales (CST y Ley 50/1990).

    Porcentajes mensuales típicos sobre la base prestacional:
        cesantias:   8.33%  (Art. 249 CST — equivalente a 1 mes/año)
        prima:       8.33%  (Art. 306 CST — 30 días/año, dos pagos)
        vacaciones:  4.17%  (Art. 186 CST — 15 días hábiles/año)
        intereses:   12% anual sobre las cesantías (Ley 52/1975).
    """
    cesantias = base_prestaciones * (porcentajes['cesantias'] / 100)
    intereses = cesantias * (12 / 100)
    prima = base_prestaciones * (porcentajes['prima'] / 100)
    vacaciones = base_prestaciones * (porcentajes['vacaciones'] / 100)

    return cesantias, intereses, prima, vacaciones

def calcular_retencion_fuente(ingreso_laboral, salud_pension_fsp, uvt_valor, tabla_retencion):
    """
    Retención en la fuente por ingresos laborales — Procedimiento 1
    (Art. 383 y 388 del Estatuto Tributario).

    Pasos del cálculo:
      1. Base depurada = ingreso laboral - aportes obligatorios (salud,
         pensión, fondo de solidaridad).
      2. Renta exenta del 25% (Art. 206 num. 10 ET), con tope mensual
         de 790 UVT/12.
      3. Convertir base gravable a UVT y aplicar la tabla del Art. 383.
      4. Multiplicar la retención en UVT por el valor del UVT vigente.
    """
    # 1. Ingreso Neto
    base_depurada = ingreso_laboral - salud_pension_fsp
    if base_depurada < 0: base_depurada = 0

    # 2. Renta Exenta 25% (Art. 206 num. 10 ET)
    renta_exenta = base_depurada * 0.25

    # Tope mensual: 790 UVT año / 12 ≈ 65.83 UVT, valorizado al UVT vigente
    tope_renta_exenta = (790 / 12) * uvt_valor
    if renta_exenta > tope_renta_exenta:
        renta_exenta = tope_renta_exenta
        
    base_gravable_pesos = base_depurada - renta_exenta
    base_gravable_uvt = base_gravable_pesos / uvt_valor
    
    retencion_uvt = 0
    for rango in tabla_retencion:
        # rango estructure: {'rango_desde', 'rango_hasta', 'tarifa_marginal', 'uvt_mas', 'uvt_base'} 
        # asumiendo dict o objeto, aqui tratamos como dict para flexibilidad
        desde = rango['rango_desde']
        hasta = rango['rango_hasta']
        
        if desde <= base_gravable_uvt < hasta:
            tarifa = rango['tarifa_marginal']
            uvt_mas = rango['uvt_mas']
            uvt_base = rango['uvt_base']
            
            retencion_uvt = ((base_gravable_uvt - uvt_base) * (tarifa / 100)) + uvt_mas
            break
            
    return retencion_uvt * uvt_valor

def calcular_indemnizacion(salario, tipo_contrato, fecha_ingreso, fecha_retiro, smmlv, fecha_fin_contrato=None):
    """
    Calcula indemnización por despido sin justa causa (Art. 64 CST).

    INDEFINIDO:
      - Salario < 10 SMMLV → 30 días primer año + 20 días por cada año adicional (proporcional por fracción).
      - Salario >= 10 SMMLV → 20 días primer año + 15 días por cada año adicional (proporcional por fracción).
      - Si lleva menos de un año, se paga proporcional al tiempo servido (mínimo 30/20 días según el caso).

    FIJO:
      - Salarios correspondientes al tiempo que faltare para terminar el contrato.

    OBRA_LABOR:
      - Indemnización equivalente a los salarios del tiempo faltante, no inferior a 15 días.
    """
    if not fecha_ingreso or not fecha_retiro:
        return 0

    dias_laborados = dias_360(fecha_ingreso, fecha_retiro)
    valor_dia = salario / 30

    if tipo_contrato == 'INDEFINIDO':
        if salario < (10 * smmlv):
            dias_primer = 30
            dias_adicional = 20
        else:
            dias_primer = 20
            dias_adicional = 15

        if dias_laborados <= 360:
            # Proporcional al tiempo servido, con mínimo de "dias_primer" si lleva al menos un año.
            indemnizacion = valor_dia * dias_primer * (dias_laborados / 360)
        else:
            base_primero = valor_dia * dias_primer
            dias_restantes = dias_laborados - 360
            valor_restante = valor_dia * dias_adicional * (dias_restantes / 360)
            indemnizacion = base_primero + valor_restante
        return indemnizacion

    if tipo_contrato == 'FIJO':
        if not fecha_fin_contrato:
            return 0
        dias_faltantes = dias_360(fecha_retiro, fecha_fin_contrato)
        return max(0, valor_dia * dias_faltantes)

    if tipo_contrato == 'OBRA_LABOR':
        if not fecha_fin_contrato:
            return valor_dia * 15
        dias_faltantes = dias_360(fecha_retiro, fecha_fin_contrato)
        return max(valor_dia * 15, valor_dia * dias_faltantes)

    return 0

def dias_360(fecha_inicio, fecha_fin, inclusivo=True):
    """
    Calcula dias entre dos fechas usando base 360 (meses de 30 dias),
    estándar laboral colombiano. Por defecto incluye el día final.
    """
    if not fecha_inicio or not fecha_fin: return 0
    dias = (fecha_fin.year - fecha_inicio.year) * 360 + \
           (fecha_fin.month - fecha_inicio.month) * 30 + \
           (min(fecha_fin.day, 30) - min(fecha_inicio.day, 30))
    if inclusivo:
        dias += 1
    return max(0, dias)

def calcular_ss_contratista(honorarios_mensuales, nivel_riesgo_arl_pct):
    """
    Calcula seguridad social contratistas.
    Base cotización: 40% del valor mensual (Minimo 1 SMMLV).
    """
    # La logica de validacion de minimo 1 SMMLV debe hacerse fuera o pasar SMMLV
    base = honorarios_mensuales * 0.40
    
    salud = base * 0.125
    pension = base * 0.160
    arl = base * (nivel_riesgo_arl_pct / 100)
    
    return {
        'base': base,
        'salud': salud,
        'pension': pension,
        'arl': arl,
        'total': salud + pension + arl
    }

def calcular_incapacidad(salario_base, dias, tipo, smmlv):
    """
    Calcula el valor de una incapacidad/licencia.

    Enfermedad General (INCAPACIDAD_GEN):
      - Días 1-2 (Empleador): 100% del IBC
      - Días 3-90 (EPS):     66.67% del IBC, mínimo 1 SMMLV/día
      - Días 91-180 (EPS/Fondo): 50% del IBC, mínimo 1 SMMLV/día
    Accidente/Enfermedad Laboral (ARL): 100% desde día 1.
    Licencias maternidad/paternidad/luto: 100%.
    Licencia no remunerada: 0.
    """
    if dias <= 0:
        return 0

    valor_dia = salario_base / 30
    smmlv_dia = (smmlv / 30) if smmlv else 0
    valor_total = 0

    if tipo == 'INCAPACIDAD_GEN':
        dias_restantes = dias

        # Días 1-2: empleador, 100%
        tramo = min(2, dias_restantes)
        valor_total += valor_dia * tramo
        dias_restantes -= tramo

        # Días 3-90: EPS, 2/3
        if dias_restantes > 0:
            tramo = min(88, dias_restantes)
            tarifa = max(valor_dia * (2 / 3), smmlv_dia)
            valor_total += tarifa * tramo
            dias_restantes -= tramo

        # Días 91-180: EPS/Fondo, 50%
        if dias_restantes > 0:
            tramo = min(90, dias_restantes)
            tarifa = max(valor_dia * 0.5, smmlv_dia)
            valor_total += tarifa * tramo

    elif tipo in ['INCAPACIDAD_LAB', 'LICENCIA_MAT', 'LICENCIA_PAT', 'LICENCIA_LUTO']:
        valor_total = valor_dia * dias

    elif tipo == 'LICENCIA_NR':
        valor_total = 0

    return valor_total
