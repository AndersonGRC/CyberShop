# app/nomina_engine.py

"""
Motor de cálculos de nómina colombiana.
Funciones puras sin dependencia de Flask o base de datos.
"""

from datetime import date, timedelta

def calcular_valor_hora(salario_base):
    """Calcula el valor de la hora ordinaria (30 días * 8 horas = 240 horas)."""
    return salario_base / 240

def calcular_horas_extras(valor_hora, tipo, cantidad):
    """
    Calcula el valor de horas extras y recargos.
    
    Tipos:
    - HED: Hora Extra Diurna (1.25)
    - HEN: Hora Extra Nocturna (1.75)
    - HEDF: Hora Extra Diurna Festiva (2.00)
    - HENF: Hora Extra Nocturna Festiva (2.50)
    - RN: Recargo Nocturno (0.35)
    - RD: Recargo Dominical/Festivo (0.75)
    """
    factores = {
        'HED': 1.25,
        'HEN': 1.75,
        'HEDF': 2.00,
        'HENF': 2.50,
        'RN': 0.35,
        'RD': 0.75
    }
    factor = factores.get(tipo, 1.0)
    return valor_hora * factor * cantidad

def calcular_auxilio_transporte(salario_base, smmlv, valor_auxilio):
    """
    Calcula auxilio de transporte.
    Se paga si el salario base <= 2 SMMLV.
    """
    if salario_base <= (2 * smmlv):
        return valor_auxilio
    return 0

def calcular_salud_pension(base_cotizacion, porcentaje_salud, porcentaje_pension):
    """
    Calcula aportes a seguridad social (Empleado).
    """
    salud = base_cotizacion * (porcentaje_salud / 100)
    pension = base_cotizacion * (porcentaje_pension / 100)
    return salud, pension

def calcular_fondo_solidaridad(base_cotizacion, smmlv):
    """
    Calcula Fondo de Solidaridad Pensional.
    
    Tablas:
    - < 4 SMMLV: 0%
    - 4 a < 16 SMMLV: 1%
    - 16 a < 17 SMMLV: 1.2%
    - 17 a < 18 SMMLV: 1.4%
    - 18 a < 19 SMMLV: 1.6%
    - 19 a < 20 SMMLV: 1.8%
    - >= 20 SMMLV: 2%
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
    """Calcula aporte ARL (100% Empleador)."""
    return base_cotizacion * (porcentaje_riesgo / 100)

def calcular_parafiscales(base_cotizacion, smmlv, porcentajes, es_exonerado):
    """
    Calcula Parafiscales (Caja, ICBF, SENA).
    Si es_exonerado (Ley 1607) y salario < 10 SMMLV:
    - No paga Salud (8.5%), ICBF (3%), SENA (2%).
    - Solo paga Caja (4%).
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
    Calcula provisiones mensuales de prestaciones sociales.
    """
    cesantias = base_prestaciones * (porcentajes['cesantias'] / 100)
    intereses = cesantias * (12 / 100) # 12% anual sobre el valor de cesantias
    prima = base_prestaciones * (porcentajes['prima'] / 100)
    vacaciones = base_prestaciones * (porcentajes['vacaciones'] / 100)
    
    return cesantias, intereses, prima, vacaciones

def calcular_retencion_fuente(ingreso_laboral, salud_pension_fsp, uvt_valor, tabla_retencion):
    """
    Calcula Retención en la Fuente (Procedimiento 1).
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
