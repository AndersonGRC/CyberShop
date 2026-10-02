"""Nómina: cálculo y guardado de periodos y liquidaciones.

Único punto que escribe resultados del motor (`nomina_engine`) en la base de
datos. Lo usan la web (`routes/nomina.py`) y la sincronización del escritorio
(`routes/api_sync.py`, op `calcular_periodo`).

Reglas de integridad:
- Los periodos aprobados o pagados NUNCA se recalculan ni cambian sus novedades.
- El esquema solo crece (ADD COLUMN IF NOT EXISTS) y tolera tablas ausentes.
- Cada periodo guarda la versión del motor y los parámetros con que se calculó.
"""

import json
import logging
from datetime import timedelta

import nomina_engine as motor

log = logging.getLogger(__name__)

ESTADOS_RECALCULABLES = ('borrador', 'calculada', 'rechazada')


class PeriodoBloqueado(ValueError):
    """El periodo ya está aprobado o pagado: no admite cambios."""


# ---------------------------------------------------------------------------
# Esquema (aditivo e idempotente)
# ---------------------------------------------------------------------------
_COLUMNAS_NUEVAS = {
    'nomina_empleados': {
        'salario_integral': 'BOOLEAN DEFAULT FALSE',
        'aprendiz_etapa': 'VARCHAR(12)',
        'fecha_fin_contrato': 'DATE',
        'ret_dependientes': 'BOOLEAN DEFAULT FALSE',
        'ret_intereses_vivienda': 'NUMERIC DEFAULT 0',
        'ret_medicina_prepagada': 'NUMERIC DEFAULT 0',
        'ret_aportes_voluntarios': 'NUMERIC DEFAULT 0',
        'ret_concepto': 'VARCHAR(20)',
        'ret_declarante': 'BOOLEAN DEFAULT FALSE',
        'ret_contrata_2_o_mas': 'BOOLEAN DEFAULT FALSE',
    },
    'nomina_detalle': {
        'ibc': 'NUMERIC',
        'ss_contratista': 'NUMERIC',
        'calculo': 'JSONB',
    },
    'nomina_periodos': {
        'motor_version': 'VARCHAR(20)',
        'parametros_usados': 'JSONB',
        'alertas': 'JSONB',
        'calculado_at': 'TIMESTAMP',
        'pagado_at': 'TIMESTAMP',
    },
    'nomina_novedades': {
        'valor_manual': 'BOOLEAN',
    },
    'nomina_parametros': {
        'exonerado_114_1': 'BOOLEAN DEFAULT TRUE',
    },
    'nomina_liquidaciones': {
        'detalle': 'JSONB',
    },
}

# Bases ya revisadas en este proceso (un proceso puede atender varios tenants).
_ESQUEMA_OK = set()


def _ampliar(cur):
    """Agrega solo las columnas que falten, cada tabla en su SAVEPOINT para que
    un fallo (tabla ausente, permisos) no aborte la transacción del llamador."""
    todo_ok = True
    for tabla, columnas in _COLUMNAS_NUEVAS.items():
        cur.execute("SAVEPOINT nomina_esquema")
        try:
            cur.execute("SELECT to_regclass(%s)", (tabla,))
            if cur.fetchone()[0]:
                existentes = _columnas(cur, tabla)
                for columna, ddl in columnas.items():
                    if columna not in existentes:
                        cur.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {columna} {ddl}")
            cur.execute("RELEASE SAVEPOINT nomina_esquema")
        except Exception:  # noqa: BLE001
            cur.execute("ROLLBACK TO SAVEPOINT nomina_esquema")
            todo_ok = False
            log.exception('nomina: no se pudo ampliar la tabla %s', tabla)
    return todo_ok


def asegurar_esquema(cur=None):
    """Agrega las columnas nuevas de nómina (una vez por base y proceso).

    Con `cur` usa la transacción del llamador (p. ej. la sincronización del
    escritorio, que trabaja sobre la base de su tenant); sin `cur` abre una
    conexión al tenant activo."""
    if cur is not None:
        clave = cur.connection.info.dbname
        if clave not in _ESQUEMA_OK and _ampliar(cur):
            _ESQUEMA_OK.add(clave)
        return
    from database import _current_db_name, get_db_cursor
    try:
        clave = _current_db_name()
    except Exception:  # noqa: BLE001
        clave = None
    if clave in _ESQUEMA_OK:
        return
    try:
        with get_db_cursor() as c:
            ok = _ampliar(c)
        if ok and clave:
            _ESQUEMA_OK.add(clave)
    except Exception:  # noqa: BLE001
        log.exception('nomina: no se pudo revisar el esquema')


def _columnas(cur, tabla):
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = current_schema()",
        (tabla,),
    )
    return {fila[0] for fila in cur.fetchall()}


def _json(valor):
    return json.dumps(valor, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Periodos
# ---------------------------------------------------------------------------
def _periodo(cur, periodo_id, bloquear=False):
    cur.execute(
        "SELECT * FROM nomina_periodos WHERE id = %s" + (" FOR UPDATE" if bloquear else ""),
        (periodo_id,),
    )
    fila = cur.fetchone()
    return dict(fila) if fila else None


def validar_periodo_editable(cur, periodo_id):
    """Lanza PeriodoBloqueado si el periodo está aprobado o pagado."""
    periodo = _periodo(cur, periodo_id)
    if not periodo:
        raise ValueError('Periodo no encontrado.')
    # Solo los estados abiertos admiten cambios; cualquier otro (aprobada,
    # pagada o uno desconocido) se trata como cerrado.
    if (periodo.get('estado') or 'borrador') not in ESTADOS_RECALCULABLES:
        raise PeriodoBloqueado(
            f'El periodo está {periodo["estado"]}: sus novedades ya no se pueden cambiar.'
        )
    return periodo


def marcar_para_recalculo(cur, periodo_id):
    """Una novedad cambió en un periodo ya calculado: vuelve a borrador para
    que nadie apruebe valores desactualizados."""
    cur.execute(
        "UPDATE nomina_periodos SET estado = 'borrador' WHERE id = %s AND estado IN ('calculada', 'rechazada')",
        (periodo_id,),
    )


def _parametros(cur, anio):
    cur.execute("SELECT * FROM nomina_parametros WHERE anio = %s", (anio,))
    fila = cur.fetchone()
    return dict(fila) if fila else None


def recalcular_valores_novedades(cur, periodo, smmlv):
    """Recalcula el valor de las novedades automáticas (horas extras, recargos,
    incapacidades y licencias) con el motor vigente, usando el salario actual
    y la fecha de cada novedad. Las que el usuario valoró a mano no se tocan.
    Devuelve cuántas cambiaron."""
    cur.execute(
        """
        SELECT n.id, UPPER(n.tipo_novedad) AS tipo, n.cantidad, n.valor_total, n.fecha_novedad,
               COALESCE(n.valor_manual, FALSE) AS valor_manual, e.salario_base
        FROM nomina_novedades n
        JOIN nomina_empleados e ON e.id = n.empleado_id
        WHERE n.periodo_id = %s
        """,
        (periodo['id'],),
    )
    cambios = 0
    for fila in cur.fetchall():
        if fila['valor_manual'] or fila['tipo'] not in motor.TIPOS_CALCULABLES:
            continue
        nuevo = motor.valor_novedad(
            fila['tipo'], fila['cantidad'], fila['salario_base'], smmlv,
            fila['fecha_novedad'] or periodo.get('fecha_fin'),
        )
        if nuevo is None:
            continue
        nuevo = round(nuevo, 2)
        if abs(nuevo - float(fila['valor_total'] or 0)) > 0.5:
            cur.execute("UPDATE nomina_novedades SET valor_total = %s WHERE id = %s", (nuevo, fila['id']))
            cambios += 1
    return cambios


_COLUMNAS_DETALLE = (
    'dias_trabajados', 'sueldo_basico', 'auxilio_transporte', 'horas_extras', 'recargos', 'comisiones',
    'bonificaciones', 'incapacidades', 'licencias', 'total_devengado', 'salud_empleado', 'pension_empleado',
    'fondo_solidaridad', 'retencion_fuente', 'prestamos', 'otras_deducciones', 'total_deducido', 'neto_pagar',
    'salud_empleador', 'pension_empleador', 'arl', 'sena', 'icbf', 'ccf', 'cesantias_provision',
    'intereses_provision', 'prima_provision', 'vacaciones_provision', 'ibc', 'ss_contratista', 'calculo',
)


def calcular_y_guardar_periodo(cur, periodo_id):
    """Calcula el periodo con el motor y reemplaza su detalle.

    `cur` debe ser un cursor de diccionario dentro de una transacción: si algo
    falla, la transacción completa se revierte y el detalle anterior queda.
    """
    asegurar_esquema(cur)
    periodo = _periodo(cur, periodo_id, bloquear=True)
    if not periodo:
        raise ValueError('Periodo no encontrado.')
    if periodo.get('estado') not in ESTADOS_RECALCULABLES:
        raise PeriodoBloqueado(f'No se puede recalcular un periodo en estado "{periodo.get("estado")}".')

    params = _parametros(cur, periodo['anio'])
    if not params:
        raise ValueError(
            f"No hay parámetros de nómina para el año {periodo['anio']}. Créelos primero en Parámetros."
        )

    recalcular_valores_novedades(cur, periodo, float(params['salario_minimo']))

    cur.execute("SELECT * FROM nomina_empleados WHERE activo = TRUE")
    empleados = [dict(fila) for fila in cur.fetchall()]
    cur.execute(
        """
        SELECT empleado_id, UPPER(tipo_novedad) AS tipo_novedad,
               COALESCE(SUM(cantidad), 0) AS cantidad, COALESCE(SUM(valor_total), 0) AS valor_total
        FROM nomina_novedades WHERE periodo_id = %s
        GROUP BY empleado_id, UPPER(tipo_novedad)
        """,
        (periodo_id,),
    )
    novedades = [dict(fila) for fila in cur.fetchall()]

    resultado = motor.liquidar_periodo(periodo, params, empleados, novedades)

    disponibles = _columnas(cur, 'nomina_detalle')
    columnas = [c for c in _COLUMNAS_DETALLE if c in disponibles]
    cur.execute("DELETE FROM nomina_detalle WHERE periodo_id = %s", (periodo_id,))
    for detalle in resultado['detalles']:
        valores = [_json(detalle.get(c) or {}) if c == 'calculo' else detalle.get(c, 0) for c in columnas]
        marcadores = ', '.join('%s::jsonb' if c == 'calculo' else '%s' for c in columnas)
        cur.execute(
            f"INSERT INTO nomina_detalle (periodo_id, empleado_id, {', '.join(columnas)}) "
            f"VALUES (%s, %s, {marcadores})",
            [periodo_id, detalle['empleado_id'], *valores],
        )

    columnas_periodo = _columnas(cur, 'nomina_periodos')
    sets, valores = ["estado = 'calculada'"], []
    if 'motor_version' in columnas_periodo:
        sets += ['motor_version = %s', 'parametros_usados = %s::jsonb', 'alertas = %s::jsonb', 'calculado_at = NOW()']
        valores += [resultado['motor_version'], _json(resultado['parametros_usados']), _json(resultado['alertas'])]
    cur.execute(f"UPDATE nomina_periodos SET {', '.join(sets)} WHERE id = %s", (*valores, periodo_id))
    return resultado


def marcar_pagada(cur, periodo_id):
    periodo = _periodo(cur, periodo_id, bloquear=True)
    if not periodo:
        raise ValueError('Periodo no encontrado.')
    if periodo.get('estado') != 'aprobada':
        raise ValueError('Solo se puede marcar como pagado un periodo aprobado.')
    sets = "estado = 'pagada'" + (", pagado_at = NOW()" if 'pagado_at' in _columnas(cur, 'nomina_periodos') else '')
    cur.execute(f"UPDATE nomina_periodos SET {sets} WHERE id = %s", (periodo_id,))


# ---------------------------------------------------------------------------
# Liquidación definitiva
# ---------------------------------------------------------------------------
def _promedio_variable(cur, empleado_id, fecha_retiro):
    """Promedio mensual de horas extras, recargos y comisiones del último año
    (periodos aprobados o pagados)."""
    desde = fecha_retiro - timedelta(days=365)
    cur.execute(
        """
        SELECT p.anio, p.mes,
               SUM(COALESCE(d.horas_extras, 0) + COALESCE(d.comisiones, 0)) AS variable
        FROM nomina_detalle d
        JOIN nomina_periodos p ON p.id = d.periodo_id
        WHERE d.empleado_id = %s AND p.estado IN ('aprobada', 'pagada')
          AND p.fecha_fin > %s AND p.fecha_inicio <= %s
        GROUP BY p.anio, p.mes
        """,
        (empleado_id, desde, fecha_retiro),
    )
    filas = cur.fetchall()
    if not filas:
        return 0.0
    return sum(float(f['variable'] or 0) for f in filas) / len(filas)


def _vacaciones_disfrutadas_anio(cur, empleado_id, fecha_retiro):
    cur.execute(
        """
        SELECT COALESCE(SUM(cantidad), 0) AS dias FROM nomina_novedades
        WHERE empleado_id = %s AND UPPER(tipo_novedad) = 'VACACIONES'
          AND COALESCE(fecha_novedad, created_at::date) BETWEEN %s AND %s
        """,
        (empleado_id, fecha_retiro.replace(month=1, day=1), fecha_retiro),
    )
    return float(cur.fetchone()['dias'] or 0)


def _salarios_pendientes_sugeridos(cur, empleado, fecha_retiro):
    """Días entre el último periodo liquidado del empleado y la fecha de retiro."""
    cur.execute(
        """
        SELECT MAX(p.fecha_fin) AS fin FROM nomina_detalle d
        JOIN nomina_periodos p ON p.id = d.periodo_id
        WHERE d.empleado_id = %s AND p.estado IN ('calculada', 'aprobada', 'pagada')
        """,
        (empleado['id'],),
    )
    fila = cur.fetchone()
    ultimo = fila['fin'] if fila else None
    desde = (ultimo + timedelta(days=1)) if ultimo else motor._to_date(empleado.get('fecha_ingreso'))
    if not desde or desde > fecha_retiro:
        return 0, 0.0
    dias = motor.dias_360(desde, fecha_retiro)
    return dias, round(float(empleado.get('salario_base') or 0) / 30 * dias, 2)


def preparar_liquidacion(cur, empleado_id, fecha_retiro, motivo, ajustes=None):
    """Calcula la liquidación SIN guardar (vista previa).

    ajustes: dias_vacaciones_pendientes, salarios_pendientes y
    deducciones_pendientes escritos por el usuario (opcionales)."""
    asegurar_esquema(cur)
    ajustes = ajustes or {}
    cur.execute("SELECT * FROM nomina_empleados WHERE id = %s", (empleado_id,))
    fila = cur.fetchone()
    if not fila:
        raise ValueError('Empleado no encontrado.')
    empleado = dict(fila)
    fecha_retiro = motor._to_date(fecha_retiro)
    if not fecha_retiro:
        raise ValueError('Escriba una fecha de retiro válida.')
    params = _parametros(cur, fecha_retiro.year)
    if not params:
        raise ValueError(f'No hay parámetros de nómina para {fecha_retiro.year}. Créelos primero en Parámetros.')

    dias_pend, salarios_sugeridos = _salarios_pendientes_sugeridos(cur, empleado, fecha_retiro)
    disfrutadas = _vacaciones_disfrutadas_anio(cur, empleado_id, fecha_retiro)

    def ajuste(clave):
        valor = ajustes.get(clave)
        return None if valor in (None, '') else float(valor)

    salarios = ajuste('salarios_pendientes')
    resultado = motor.liquidar_contrato(
        empleado, fecha_retiro, motivo, params,
        promedio_variable=_promedio_variable(cur, empleado_id, fecha_retiro),
        dias_vacaciones_pendientes=ajuste('dias_vacaciones_pendientes'),
        dias_vacaciones_disfrutadas_anio=disfrutadas,
        salarios_pendientes=salarios_sugeridos if salarios is None else salarios,
        deducciones_pendientes=ajuste('deducciones_pendientes') or 0.0,
    )
    resultado['sugerencias'] = {
        'dias_salario_pendiente': dias_pend,
        'salarios_pendientes': salarios_sugeridos,
        'vacaciones_disfrutadas_anio': disfrutadas,
    }
    resultado['empleado'] = {k: empleado.get(k) for k in ('id', 'nombres', 'apellidos', 'numero_documento', 'tipo_vinculacion', 'fecha_ingreso')}
    resultado['fecha_retiro'] = fecha_retiro
    return resultado


def guardar_liquidacion(cur, empleado_id, fecha_retiro, motivo, ajustes=None):
    """Guarda la liquidación y marca al empleado como inactivo (una sola vez)."""
    resultado = preparar_liquidacion(cur, empleado_id, fecha_retiro, motivo, ajustes)
    cur.execute("SELECT id FROM nomina_empleados WHERE id = %s FOR UPDATE", (empleado_id,))
    cur.execute(
        "SELECT id FROM nomina_liquidaciones WHERE empleado_id = %s AND COALESCE(estado, '') <> 'anulada'",
        (empleado_id,),
    )
    if cur.fetchone():
        raise ValueError('Este empleado ya tiene una liquidación registrada.')

    tiene_detalle = 'detalle' in _columnas(cur, 'nomina_liquidaciones')
    columnas = [
        'empleado_id', 'fecha_retiro', 'motivo_retiro', 'dias_liquidacion', 'salario_base_liquidacion',
        'cesantias', 'intereses_cesantias', 'prima_servicios', 'vacaciones', 'indemnizacion',
        'salarios_pendientes', 'deducciones_pendientes', 'total_pagar', 'estado',
    ]
    valores = [
        empleado_id, resultado['fecha_retiro'], motivo, resultado['dias_liquidacion'],
        resultado['salario_base_liquidacion'], resultado['cesantias'], resultado['intereses_cesantias'],
        resultado['prima_servicios'], resultado['vacaciones'], resultado['indemnizacion'],
        resultado['salarios_pendientes'], resultado['deducciones_pendientes'], resultado['total_pagar'], 'generada',
    ]
    marcadores = ['%s'] * len(columnas)
    if tiene_detalle:
        columnas.append('detalle')
        marcadores.append('%s::jsonb')
        valores.append(_json({k: v for k, v in resultado.items() if k not in ('empleado',)}))
    cur.execute(
        f"INSERT INTO nomina_liquidaciones ({', '.join(columnas)}) VALUES ({', '.join(marcadores)}) RETURNING id",
        valores,
    )
    liquidacion_id = cur.fetchone()['id']
    cur.execute(
        "UPDATE nomina_empleados SET activo = FALSE, fecha_retiro = %s WHERE id = %s",
        (resultado['fecha_retiro'], empleado_id),
    )
    return liquidacion_id, resultado
