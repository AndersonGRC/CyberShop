"""Nómina: costo del período y detalle por empleado.

ACCESO (decisión del dueño, 2026-09-15): solo super admin, propietario y
contador, con el módulo de nómina activo y permiso 'payroll'. El control vive en
acceso.py (sensible='nomina', que mira el rol BASE: un rol derivado de Empleado
no la ve aunque se le amplíen permisos) y cada consulta queda registrada en
ia_consultas con el empleado consultado.

NUNCA se devuelven datos personales que no hagan falta para hablar de pago:
documento, banco, número de cuenta, dirección, teléfono, correo, EPS ni fondos.
"""

from database import get_db_cursor
from helpers import formatear_moneda

from services.ia_datos.base import (
    _columnas, _existe, _periodo, cambio_pct, etiqueta_rango, rango_efectivo,
)

_MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
          'septiembre', 'octubre', 'noviembre', 'diciembre']


def _nombre_periodo(r):
    mes = _MESES[int(r['mes']) - 1] if r.get('mes') and 1 <= int(r['mes']) <= 12 else ''
    numero = f" (quincena {r['numero_periodo']})" if r.get('numero_periodo') else ''
    return f"{mes} {r['anio']}{numero}".strip()


def _totales_periodos(cur, ids):
    """Suma del detalle de nómina de esos períodos."""
    if not ids:
        return None
    cur.execute("""SELECT COUNT(DISTINCT empleado_id) AS empleados,
                          COALESCE(SUM(total_devengado), 0) AS devengado,
                          COALESCE(SUM(total_deducido), 0) AS deducido,
                          COALESCE(SUM(neto_pagar), 0) AS neto,
                          COALESCE(SUM(salud_empleador + pension_empleador + arl + sena + icbf + ccf), 0) AS aportes,
                          COALESCE(SUM(cesantias_provision + intereses_provision + prima_provision
                                       + vacaciones_provision), 0) AS provisiones,
                          COALESCE(SUM(horas_extras), 0) AS horas_extras,
                          COALESCE(SUM(incapacidades), 0) AS incapacidades
                   FROM nomina_detalle WHERE periodo_id = ANY(%s)""", (ids,))
    return cur.fetchone()


def _periodos_en_rango(cur, desde, hasta):
    cur.execute("""SELECT id, anio, mes, numero_periodo, fecha_inicio, fecha_fin, estado
                   FROM nomina_periodos
                   WHERE (%s::date IS NULL OR fecha_fin >= %s) AND fecha_fin <= %s
                   ORDER BY fecha_fin""", (desde, desde, hasta))
    return cur.fetchall()


def nomina_resumen(periodo='mes', **_):
    """Cuánto cuesta la nómina en un período: devengado, deducciones, neto,
    aportes del empleador y provisiones, con comparación contra el anterior."""
    p = _periodo(periodo)
    with get_db_cursor(dict_cursor=True) as cur:
        if not (_existe(cur, 'nomina_periodos') and _existe(cur, 'nomina_detalle')):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio todavía no liquida la nómina en el sistema.'}
        cur.execute("SELECT CURRENT_DATE AS hoy")
        hoy = cur.fetchone()['hoy']
        desde, hasta = rango_efectivo(hoy, p)
        periodos = _periodos_en_rango(cur, desde, hasta)
        if not periodos:
            return {'periodo': etiqueta_rango(desde, hasta), 'confiabilidad': 'insuficiente',
                    'conclusion': 'No hay períodos de nómina liquidados en ese rango.'}
        ids = [r['id'] for r in periodos]
        t = _totales_periodos(cur, ids)

        cur.execute("""SELECT COALESCE(NULLIF(TRIM(e.cargo), ''), 'Sin cargo') AS cargo,
                              COUNT(DISTINCT d.empleado_id) AS empleados,
                              COALESCE(SUM(d.total_devengado), 0) AS devengado
                       FROM nomina_detalle d JOIN nomina_empleados e ON e.id = d.empleado_id
                       WHERE d.periodo_id = ANY(%s) GROUP BY 1 ORDER BY devengado DESC""", (ids,))
        por_cargo = [{'cargo': r['cargo'], 'empleados': int(r['empleados']),
                      'devengado': formatear_moneda(float(r['devengado']))} for r in cur.fetchall()]

        # La nómina se liquida por períodos completos: comparar "el mismo tramo del mes
        # anterior" dejaría fuera la quincena o el mes ya liquidado. Se comparan los
        # períodos liquidados inmediatamente anteriores, en la misma cantidad.
        comparacion = None
        cur.execute("""SELECT id, anio, mes, numero_periodo, fecha_inicio, fecha_fin, estado
                       FROM nomina_periodos WHERE fecha_fin < %s
                       ORDER BY fecha_fin DESC LIMIT %s""", (periodos[0]['fecha_fin'], len(periodos)))
        anteriores = cur.fetchall()
        if anteriores:
            ta = _totales_periodos(cur, [r['id'] for r in anteriores])
            comparacion = {
                'periodo': ' y '.join(_nombre_periodo(r) for r in reversed(anteriores)),
                'costo_total': formatear_moneda(float(ta['devengado']) + float(ta['aportes'])),
                'empleados': int(ta['empleados']),
                'cambio_costo': cambio_pct(float(t['devengado']) + float(t['aportes']),
                                           float(ta['devengado']) + float(ta['aportes'])),
            }
        cur.execute("SELECT COUNT(*) AS n FROM nomina_empleados WHERE COALESCE(activo, TRUE)")
        activos = int(cur.fetchone()['n'] or 0)

    costo = float(t['devengado']) + float(t['aportes'])
    return {
        'periodo': etiqueta_rango(desde, hasta),
        'periodos_liquidados': [{'periodo': _nombre_periodo(r), 'estado': r['estado']} for r in periodos],
        'empleados_liquidados': int(t['empleados']), 'empleados_activos': activos,
        'devengado': formatear_moneda(float(t['devengado'])),
        'deducciones': formatear_moneda(float(t['deducido'])),
        'neto_pagado': formatear_moneda(float(t['neto'])),
        'aportes_del_empleador': formatear_moneda(float(t['aportes'])),
        'provisiones': formatear_moneda(float(t['provisiones'])),
        'costo_total_empleador': formatear_moneda(costo),
        'costo_promedio_por_empleado': formatear_moneda(costo / int(t['empleados'])) if int(t['empleados']) else None,
        'horas_extras': formatear_moneda(float(t['horas_extras'])),
        'incapacidades': formatear_moneda(float(t['incapacidades'])),
        'por_cargo': por_cargo,
        'comparacion': comparacion,
        'nota': ('El costo total es lo devengado más los aportes del empleador (salud, pensión, ARL y '
                 'parafiscales). Las provisiones (cesantías, prima, vacaciones) se muestran aparte.'),
    }


def nomina_empleado(empleado='', **_):
    """Detalle de UN empleado: cargo, antigüedad, sueldo y su última
    liquidación. Sin documento, banco, cuenta ni datos de contacto."""
    nombre = (empleado or '').strip()
    if len(nombre) < 3:
        return {'confiabilidad': 'insuficiente',
                'conclusion': 'Dime el nombre del empleado (al menos 3 letras).'}
    patron = f'%{nombre.lower()}%'
    with get_db_cursor(dict_cursor=True) as cur:
        if not _existe(cur, 'nomina_empleados'):
            return {'confiabilidad': 'insuficiente',
                    'conclusion': 'Este negocio todavía no tiene empleados cargados en nómina.'}
        cur.execute("""SELECT id, nombres, apellidos, cargo, salario_base, fecha_ingreso, fecha_retiro,
                              tipo_vinculacion, COALESCE(activo, TRUE) AS activo
                       FROM nomina_empleados
                       WHERE LOWER(nombres || ' ' || COALESCE(apellidos, '')) LIKE %s
                       ORDER BY nombres LIMIT 6""", (patron,))
        encontrados = cur.fetchall()
        if not encontrados:
            return {'empleado_buscado': nombre, 'confiabilidad': 'insuficiente',
                    'conclusion': f'No tengo ningún empleado que se llame «{nombre}».'}
        if len(encontrados) > 1:
            return {'empleado_buscado': nombre,
                    'varios_empleados_coinciden': [f"{e['nombres']} {e['apellidos'] or ''}".strip()
                                                   for e in encontrados],
                    'conclusion': 'Hay varios empleados con ese nombre: pregunta a cuál se refiere.'}
        e = encontrados[0]
        completo = f"{e['nombres']} {e['apellidos'] or ''}".strip()

        ultimo = None
        if _existe(cur, 'nomina_detalle') and _existe(cur, 'nomina_periodos'):
            cur.execute("""SELECT d.*, p.anio, p.mes, p.numero_periodo, p.fecha_fin
                           FROM nomina_detalle d JOIN nomina_periodos p ON p.id = d.periodo_id
                           WHERE d.empleado_id = %s ORDER BY p.fecha_fin DESC LIMIT 1""", (e['id'],))
            d = cur.fetchone()
            if d:
                ultimo = {
                    'periodo': _nombre_periodo(d),
                    'dias_trabajados': int(d['dias_trabajados'] or 0),
                    'devengado': formatear_moneda(float(d['total_devengado'] or 0)),
                    'deducciones': formatear_moneda(float(d['total_deducido'] or 0)),
                    'neto_pagado': formatear_moneda(float(d['neto_pagar'] or 0)),
                    'horas_extras': formatear_moneda(float(d['horas_extras'] or 0)),
                    'incapacidades': formatear_moneda(float(d['incapacidades'] or 0)),
                    'auxilio_transporte': formatear_moneda(float(d['auxilio_transporte'] or 0)),
                }
            cur.execute("""SELECT COUNT(*) AS n, COALESCE(SUM(neto_pagar), 0) AS neto,
                                  COALESCE(SUM(cesantias_provision + intereses_provision + prima_provision
                                               + vacaciones_provision), 0) AS provisiones
                           FROM nomina_detalle WHERE empleado_id = %s""", (e['id'],))
            acum = cur.fetchone()
        else:
            acum = {'n': 0, 'neto': 0, 'provisiones': 0}

        liquidacion = None
        if _existe(cur, 'nomina_liquidaciones'):
            cols = _columnas(cur, 'nomina_liquidaciones')
            if 'empleado_id' in cols:
                cur.execute("""SELECT fecha_retiro, motivo_retiro, total_pagar, estado
                               FROM nomina_liquidaciones WHERE empleado_id = %s
                               ORDER BY id DESC LIMIT 1""", (e['id'],))
                liq = cur.fetchone()
                if liq:
                    liquidacion = {'fecha_retiro': liq['fecha_retiro'].isoformat() if liq['fecha_retiro'] else None,
                                   'motivo': liq['motivo_retiro'],
                                   'total_liquidacion': formatear_moneda(float(liq['total_pagar'] or 0)),
                                   'estado': liq['estado']}
        cur.execute("SELECT CURRENT_DATE AS hoy")
        hoy = cur.fetchone()['hoy']

    ingreso = e['fecha_ingreso']
    antiguedad = round((hoy - ingreso).days / 365, 1) if ingreso else None
    return {
        'empleado': completo, 'cargo': e['cargo'], 'vinculacion': e['tipo_vinculacion'],
        'activo': bool(e['activo']),
        'fecha_ingreso': ingreso.isoformat() if ingreso else None,
        'antiguedad_anios': antiguedad,
        'fecha_retiro': e['fecha_retiro'].isoformat() if e['fecha_retiro'] else None,
        'salario_base': formatear_moneda(float(e['salario_base'] or 0)),
        'ultimo_periodo_liquidado': ultimo,
        'periodos_liquidados': int(acum['n'] or 0),
        'total_pagado_historico': formatear_moneda(float(acum['neto'] or 0)),
        'provisiones_acumuladas': formatear_moneda(float(acum['provisiones'] or 0)),
        'liquidacion': liquidacion,
        'nota': ('Información laboral de pago. No incluyo documento, banco, cuenta ni datos de '
                 'contacto, y esta consulta queda registrada.'),
    }
