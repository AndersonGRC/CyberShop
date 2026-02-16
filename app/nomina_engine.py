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
    
    # 2. Renta Exenta 25%
    renta_exenta = base_depurada * 0.25
    
    # Tope mensual aprox 790 UVT / 12 ~ 65 UVT (simplificado, usar valor exacto si disponible)
    tope_renta_exenta = 2300000 
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

def calcular_indemnizacion(salario, tipo_contrato, fecha_ingreso, fecha_retiro, smmlv):
    """
    Calcula indemnización por despido sin justa causa (Art 64 CST).
    """
    indemnizacion = 0
    dias_laborados = dias_360(fecha_ingreso, fecha_retiro)
    anios_laborados = dias_laborados / 360
    
    if tipo_contrato in ['FIJO', 'OBRA_LABOR']:
        # Salarios correspondientes al tiempo que faltare
        # Suponemos que falta hasta fin de contrato.
        # Si no hay fecha fin, esta funcion no puede calcular exacto para FIJO sin ese dato.
        # Asumiremos INDEFINIDO si no tiene esa logica, o 0.
        pass
    
    elif tipo_contrato == 'INDEFINIDO':
        if salario < (10 * smmlv):
            # 30 dias primer año, 20 dias subsiguientes
            if anios_laborados <= 1:
                indemnizacion = (salario / 30) * 30 * (dias_laborados / 360) # Proporcional o 30 dias fijo? Ley dice 30 dias por primer año.
                if dias_laborados < 360: indemnizacion = (salario/30) * 30 # Minimo 30 dias si es completo? No, es proporcional.
                indemnizacion = salario # Si lleva menos de un año, suele pagarse 30 días, pero revisemos jurisprudencia. CST: "30 dias de salario cuando t <= 1 año"
            else:
                top_primero = salario # 30 dias
                dias_restantes = dias_laborados - 360
                valor_restante = (salario / 30) * 20 * (dias_restantes / 360)
                indemnizacion = top_primero + valor_restante
        else:
             # 20 dias primer año, 15 dias subsiguientes
            if anios_laborados <= 1:
                indemnizacion = salario * (20/30)
            else:
                top_primero = salario * (20/30)
                dias_restantes = dias_laborados - 360
                valor_restante = (salario / 30) * 15 * (dias_restantes / 360)
                indemnizacion = top_primero + valor_restante
                
    return indemnizacion

def dias_360(fecha_inicio, fecha_fin):
    """Calcula dias entre dos fechas usando base 360 (meses de 30 dias)."""
    if not fecha_inicio or not fecha_fin: return 0
    dias = (fecha_fin.year - fecha_inicio.year) * 360 + \
           (fecha_fin.month - fecha_inicio.month) * 30 + \
           (min(fecha_fin.day, 30) - min(fecha_inicio.day, 30))
    # Ajuste inclusivo (+1 dia) si se requiere contar el dia final como trabajado
    return dias + 1

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
    Calcula el valor de una incapacidad.
    
    Reglas Generales (Referencia):
    - Enfermedad General:
        - Días 1-2: 100% (Empleador)
        - Días 3-90: 66.66% (EPS)
        - Días 91-180: 50% (EPS/Fondo Pensiones)
    - Enfermedad Laboral / Accidente Trabajo: 100% (ARL)
    - Licencia Maternidad / Paternidad: 100% (EPS)
    """
    valor_dia = salario_base / 30
    valor_total = 0
    
    if tipo == 'INCAPACIDAD_GEN':
        # Simplificación: Asumimos que "dias" es el total acumulado o el tramo actual.
        # Para ser precisos, se debería saber el día de inicio acumulado.
        # Aquí asumiremos que es un tramo único para efectos de cálculo simple.
        
        # Si dias <= 2, todo al 100%
        if dias <= 2:
            valor_total = valor_dia * dias
        else:
            # Primeros 2 dias al 100%
            valor_total += valor_dia * 2
            
            # Restante al 66.66%
            # TODO: Validar si pasa de 90 días en un futuro
            dias_restantes = dias - 2
            valor_total += (valor_dia * 0.6666) * dias_restantes
            
    elif tipo in ['INCAPACIDAD_LAB', 'LICENCIA_MAT', 'LICENCIA_PAT', 'LICENCIA_LUTO']:
        # 100%
        valor_total = valor_dia * dias
        
    elif tipo == 'LICENCIA_NR':
        # No Remunerada
        valor_total = 0
        
    else:
        # Por defecto 100% o 0? Asumamos 0 si no se conoce
        valor_total = 0
        
    return valor_total
