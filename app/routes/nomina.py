from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app
from database import get_db_cursor
from nomina_engine import *
from nomina_inteligente import (
    obtener_referencia_normativa,
    PARAMETROS_OFICIALES_NOMINA,
)
from helpers import get_data_app, formatear_moneda
from security import registrar_guard_permiso
from services import nomina_service

nomina_bp = Blueprint('nomina', __name__, url_prefix='/admin/nomina')

# PII/salarios: TODO el módulo exige sesión + permiso 'ver' de payroll según la
# matriz configurable del Propietario (recomendado: Admin y Contador). Guard
# único a nivel de blueprint: cualquier ruta nueva queda protegida por defecto.
registrar_guard_permiso(nomina_bp, 'payroll')


@nomina_bp.before_request
def _asegurar_esquema_nomina():
    # Columnas nuevas (aditivas) antes de leer o guardar formularios.
    nomina_service.asegurar_esquema()


@nomina_bp.context_processor
def inject_common_data():
    return dict(
        datosApp=get_data_app(),
        formatear_moneda=formatear_moneda,
    )

@nomina_bp.route('/')
def nomina_dashboard():
    from datetime import datetime as _dt
    meses_es = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']

    with get_db_cursor(dict_cursor=True) as cur:
        # 1. Empleados activos totales
        cur.execute("SELECT COUNT(*) AS total FROM nomina_empleados WHERE activo = TRUE")
        active_employees = cur.fetchone()['total']

        # 2. Contratistas activos
        cur.execute("""
            SELECT COUNT(*) AS total FROM nomina_empleados
            WHERE activo = TRUE AND tipo_vinculacion = 'CONTRATISTA'
        """)
        active_contractors = cur.fetchone()['total']

        # 3. Masa salarial mensual (suma salarios base activos)
        cur.execute("SELECT COALESCE(SUM(salario_base),0) AS total FROM nomina_empleados WHERE activo=TRUE")
        masa_salarial = float(cur.fetchone()['total'])

        # 4. Último período calculado con totales
        cur.execute("""
            SELECT p.*,
                   COALESCE(SUM(d.total_devengado),0) AS total_devengado,
                   COALESCE(SUM(d.total_deducido),0)  AS total_deducido,
                   COALESCE(SUM(d.neto_pagar),0)      AS neto_total,
                   COUNT(d.id)                         AS num_empleados
            FROM nomina_periodos p
            LEFT JOIN nomina_detalle d ON d.periodo_id = p.id
            WHERE p.estado IN ('calculada','aprobada','pagada')
            GROUP BY p.id
            ORDER BY p.id DESC LIMIT 1
        """)
        ultimo_periodo = cur.fetchone()
        last_payroll_total = float(ultimo_periodo['neto_total']) if ultimo_periodo else 0

        # 5. Novedades del mes
        cur.execute("""
            SELECT COUNT(*) AS total FROM nomina_novedades
            WHERE EXTRACT(MONTH FROM created_at)=EXTRACT(MONTH FROM CURRENT_DATE)
              AND EXTRACT(YEAR  FROM created_at)=EXTRACT(YEAR  FROM CURRENT_DATE)
        """)
        novedades_month = cur.fetchone()['total']

        # 6. Conteo de períodos por estado
        cur.execute("SELECT estado, COUNT(*) AS total FROM nomina_periodos GROUP BY estado")
        periodos_estado = {r['estado']: r['total'] for r in cur.fetchall()}
        periodos_borrador = periodos_estado.get('borrador', 0)

        # 7. Historial 6 últimos períodos para gráfica
        cur.execute("""
            SELECT p.id, p.anio, p.mes, p.numero_periodo, p.estado,
                   COALESCE(SUM(d.neto_pagar),0) AS neto_total
            FROM nomina_periodos p
            LEFT JOIN nomina_detalle d ON d.periodo_id = p.id
            GROUP BY p.id, p.anio, p.mes, p.numero_periodo, p.estado
            ORDER BY p.id DESC LIMIT 6
        """)
        raw_hist = list(reversed(cur.fetchall()))
        hist_max = max((float(r['neto_total']) for r in raw_hist), default=1) or 1
        hist_periodos = []
        for r in raw_hist:
            label = f"{meses_es[r['mes']-1]}/{str(r['anio'])[-2:]}"
            if r['numero_periodo']:
                label += f" Q{r['numero_periodo']}"
            hist_periodos.append({
                'label': label,
                'neto': float(r['neto_total']),
                'pct': round(float(r['neto_total']) / hist_max * 100, 1),
                'estado': r['estado'],
            })

        # 8. Top 5 empleados por salario
        cur.execute("""
            SELECT nombres, apellidos, cargo, salario_base, tipo_vinculacion
            FROM nomina_empleados WHERE activo=TRUE
            ORDER BY salario_base DESC LIMIT 5
        """)
        top_salarios = cur.fetchall()
        salario_max = float(top_salarios[0]['salario_base']) if top_salarios else 1

        # 9. Novedades por tipo (mes actual, top 6)
        cur.execute("""
            SELECT tipo_novedad, COUNT(*) AS total FROM nomina_novedades
            WHERE EXTRACT(MONTH FROM created_at)=EXTRACT(MONTH FROM CURRENT_DATE)
              AND EXTRACT(YEAR  FROM created_at)=EXTRACT(YEAR  FROM CURRENT_DATE)
            GROUP BY tipo_novedad ORDER BY total DESC LIMIT 6
        """)
        novedades_tipo = cur.fetchall()

    anio_actual = _dt.now().year
    referencia_actual = obtener_referencia_normativa(anio_actual)

    return render_template('nomina_dashboard.html',
        active_employees=active_employees,
        active_contractors=active_contractors,
        masa_salarial=masa_salarial,
        ultimo_periodo=ultimo_periodo,
        last_payroll_total=last_payroll_total,
        novedades_month=novedades_month,
        periodos_estado=periodos_estado,
        periodos_borrador=periodos_borrador,
        hist_periodos=hist_periodos,
        hist_max=hist_max,
        top_salarios=top_salarios,
        salario_max=salario_max,
        novedades_tipo=novedades_tipo,
        referencia=referencia_actual,
        anio_actual=anio_actual,
    )


@nomina_bp.route('/parametros')
def parametros_lista():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_parametros ORDER BY anio DESC")
        params = cur.fetchall()

    referencias = {
        anio: obtener_referencia_normativa(anio)
        for anio in PARAMETROS_OFICIALES_NOMINA
    }
    return render_template('nomina_parametros.html',
                           params=params,
                           referencias=referencias)

@nomina_bp.route('/parametros/crear', methods=['GET', 'POST'])
def parametros_crear():
    if request.method == 'POST':
        anio = request.form.get('anio')
        salario = request.form.get('salario_minimo')
        auxilio = request.form.get('auxilio_transporte')
        uvt = request.form.get('uvt')
        exonerado = request.form.get('exonerado_114_1') in ('1', 'on')

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO nomina_parametros (anio, salario_minimo, auxilio_transporte, uvt, exonerado_114_1)
                    VALUES (%s, %s, %s, %s, %s)
                """, (anio, salario, auxilio, uvt, exonerado))

            flash('Parámetros creados exitosamente.', 'success')
            return redirect(url_for('nomina.parametros_lista'))
        except Exception as e:
            flash(f'Error al crear parámetros: {str(e)}', 'danger')

    anio_sugerido = datetime.now().year
    referencia = obtener_referencia_normativa(anio_sugerido)
    return render_template('nomina_parametros_form.html',
                           modo='crear',
                           anio_sugerido=anio_sugerido,
                           referencia=referencia,
                           parametros_oficiales=PARAMETROS_OFICIALES_NOMINA)

@nomina_bp.route('/parametros/editar/<int:anio>', methods=['GET', 'POST'])
def parametros_editar(anio):
    if request.method == 'POST':
        salario = request.form.get('salario_minimo')
        auxilio = request.form.get('auxilio_transporte')
        uvt = request.form.get('uvt')
        exonerado = request.form.get('exonerado_114_1') in ('1', 'on')

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE nomina_parametros
                    SET salario_minimo=%s, auxilio_transporte=%s, uvt=%s, exonerado_114_1=%s
                    WHERE anio=%s
                """, (salario, auxilio, uvt, exonerado, anio))
            flash('Parámetros actualizados.', 'success')
            return redirect(url_for('nomina.parametros_lista'))
        except Exception as e:
             flash(f'Error al actualizar: {str(e)}', 'danger')
             
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_parametros WHERE anio = %s", (anio,))
        param = cur.fetchone()

    referencia = obtener_referencia_normativa(anio)
    return render_template('nomina_parametros_form.html',
                           modo='editar',
                           p=param,
                           referencia=referencia,
                           parametros_oficiales=PARAMETROS_OFICIALES_NOMINA)

@nomina_bp.route('/empleados')
def empleados_lista():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_empleados ORDER BY apellidos, nombres")
        empleados = cur.fetchall()
    return render_template('nomina_empleados.html', empleados=empleados)

_EMPLEADO_TEXTO = (
    'tipo_documento', 'numero_documento', 'nombres', 'apellidos', 'email', 'telefono', 'direccion',
    'fecha_ingreso', 'tipo_vinculacion', 'cargo', 'salario_base', 'nivel_arl',
    'banco', 'tipo_cuenta', 'numero_cuenta', 'eps', 'fondo_pension', 'fondo_cesantias',
    'fecha_fin_contrato', 'aprendiz_etapa', 'ret_concepto',
)
_EMPLEADO_BOOL = ('salario_integral', 'ret_dependientes', 'ret_declarante', 'ret_contrata_2_o_mas')
_EMPLEADO_DINERO = ('ret_intereses_vivienda', 'ret_medicina_prepagada', 'ret_aportes_voluntarios')


def _datos_empleado(f):
    """Columnas y valores del formulario de empleado, ya normalizados."""
    datos = {}
    for campo in _EMPLEADO_TEXTO:
        valor = (f.get(campo) or '').strip()
        datos[campo] = valor or None
    for campo in _EMPLEADO_BOOL:
        datos[campo] = f.get(campo) in ('1', 'on', 'true')
    for campo in _EMPLEADO_DINERO:
        try:
            datos[campo] = max(float((f.get(campo) or '0').replace(',', '.')), 0.0)
        except ValueError:
            datos[campo] = 0.0
    try:
        datos['salario_base'] = float((datos['salario_base'] or '').replace(',', '.'))
    except ValueError:
        raise ValueError('Escribe el salario u honorarios mensuales en números.')
    if datos['salario_base'] <= 0:
        raise ValueError('El salario u honorarios deben ser mayores a cero.')
    if datos['tipo_vinculacion'] != 'APRENDIZ_SENA':
        datos['aprendiz_etapa'] = None
    if datos['tipo_vinculacion'] not in ('INDEFINIDO', 'FIJO', 'OBRA_LABOR'):
        datos['salario_integral'] = False
    for campo in ('nombres', 'apellidos', 'numero_documento', 'fecha_ingreso', 'tipo_vinculacion'):
        if not datos[campo]:
            raise ValueError('Faltan datos obligatorios: documento, nombres, apellidos, vinculación y fecha de ingreso.')
    return datos


def _smmlv_actual():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT salario_minimo FROM nomina_parametros WHERE anio = %s", (datetime.now().year,))
        fila = cur.fetchone()
    if fila:
        return float(fila['salario_minimo'])
    ref = obtener_referencia_normativa(datetime.now().year)
    return float(ref['salario_minimo']) if ref else 0.0


@nomina_bp.route('/empleados/crear', methods=['GET', 'POST'])
def empleado_crear():
    if request.method == 'POST':
        try:
            datos = _datos_empleado(request.form)
            columnas = ', '.join(datos)
            with get_db_cursor() as cur:
                cur.execute(
                    f"INSERT INTO nomina_empleados ({columnas}) VALUES ({', '.join(['%s'] * len(datos))})",
                    tuple(datos.values()),
                )
            flash('Empleado creado exitosamente.', 'success')
            return redirect(url_for('nomina.empleados_lista'))
        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            current_app.logger.exception('nomina: error creando empleado')
            flash(f'Error al crear empleado: {str(e)}', 'danger')
        return render_template('nomina_empleado_form.html', modo='crear', e=request.form, smmlv=_smmlv_actual())

    return render_template('nomina_empleado_form.html', modo='crear', smmlv=_smmlv_actual())


@nomina_bp.route('/empleados/editar/<int:id>', methods=['GET', 'POST'])
def empleado_editar(id):
    if request.method == 'POST':
        try:
            datos = _datos_empleado(request.form)
            sets = ', '.join(f'{c} = %s' for c in datos)
            with get_db_cursor() as cur:
                cur.execute(f"UPDATE nomina_empleados SET {sets} WHERE id = %s", (*datos.values(), id))
            flash('Empleado actualizado exitosamente.', 'success')
            return redirect(url_for('nomina.empleados_lista'))
        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            current_app.logger.exception('nomina: error actualizando empleado %s', id)
            flash(f'Error al actualizar empleado: {str(e)}', 'danger')

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_empleados WHERE id = %s", (id,))
        empleado = cur.fetchone()

    return render_template('nomina_empleado_form.html', modo='editar', e=empleado, smmlv=_smmlv_actual())

@nomina_bp.route('/empleados/ver/<int:id>')
def empleado_ver(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_empleados WHERE id = %s", (id,))
        empleado = cur.fetchone()
    return render_template('nomina_empleado_ver.html', e=empleado)

def _pila_esperada(honorarios, nivel_arl, smmlv):
    """Seguridad social mensual que el contratista debe acreditar en la PILA."""
    ss = calcular_ss_contratista(float(honorarios or 0), porcentaje_arl(nivel_arl), smmlv)
    nivel = str(nivel_arl or 'I').upper()
    arl = 0.0 if nivel in ('IV', 'V') else ss['arl']
    return round(ss['salud'] + ss['pension'] + ss['fsp'] + arl, 2), round(ss['base'], 2)


@nomina_bp.route('/contratistas')
def contratistas_lista():
    smmlv = _smmlv_actual()
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT e.*,
                   (SELECT p.valor_pagado FROM nomina_contratistas_pila p
                     WHERE p.empleado_id = e.id
                       AND date_trunc('month', p.fecha_pago) = date_trunc('month', CURRENT_DATE)
                     ORDER BY p.id DESC LIMIT 1) AS pila_valor_mes,
                   EXISTS(
                       SELECT 1 FROM nomina_contratistas_pila p
                       WHERE p.empleado_id = e.id AND COALESCE(p.verificado, FALSE)
                         AND date_trunc('month', p.fecha_pago) = date_trunc('month', CURRENT_DATE)
                   ) AS pila_verificada
            FROM nomina_empleados e
            WHERE e.tipo_vinculacion = 'CONTRATISTA'
            ORDER BY e.activo DESC, e.apellidos, e.nombres
        """)
        contratistas = []
        for fila in cur.fetchall():
            c = dict(fila)
            c['pila_esperada'], c['ibc'] = _pila_esperada(c['salario_base'], c.get('nivel_arl'), smmlv)
            contratistas.append(c)
        cur.execute("SELECT id, anio, mes, numero_periodo, estado FROM nomina_periodos ORDER BY id DESC LIMIT 8")
        periodos = cur.fetchall()
    return render_template('nomina_contratistas.html', contratistas=contratistas, periodos=periodos, smmlv=smmlv)


@nomina_bp.route('/contratistas/pila/<int:id>', methods=['POST'])
def subir_pila(id):
    f = request.form
    numero_planilla = (f.get('numero_planilla') or '').strip()
    fecha_pago = f.get('fecha_pago') or None
    try:
        valor_pagado = float((f.get('valor_pagado') or '0').replace(',', '.'))
        periodo_id = int(f.get('periodo_id')) if f.get('periodo_id') else None
    except ValueError:
        flash('El valor pagado y el periodo deben ser números.', 'danger')
        return redirect(url_for('nomina.contratistas_lista'))
    if not numero_planilla or not fecha_pago or valor_pagado <= 0:
        flash('Escriba el número de planilla, la fecha de pago y el valor pagado.', 'danger')
        return redirect(url_for('nomina.contratistas_lista'))

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT nombres, salario_base, nivel_arl FROM nomina_empleados WHERE id = %s AND tipo_vinculacion = 'CONTRATISTA'",
                (id,),
            )
            contratista = cur.fetchone()
            if not contratista:
                raise ValueError('Contratista no encontrado.')
            esperada, _ = _pila_esperada(contratista['salario_base'], contratista['nivel_arl'], _smmlv_actual())
            # Tolerancia de $1.000 por redondeos del operador de PILA.
            completa = valor_pagado >= esperada - 1000
            cur.execute("""
                INSERT INTO nomina_contratistas_pila
                    (empleado_id, periodo_id, numero_planilla, fecha_pago, valor_pagado, verificado, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (id, periodo_id, numero_planilla, fecha_pago, valor_pagado, completa))
        if completa:
            flash(f"Planilla PILA de {contratista['nombres']} registrada y verificada.", 'success')
        else:
            flash(
                f"Planilla registrada, pero el valor pagado ({formatear_moneda(valor_pagado)}) es menor al esperado "
                f"({formatear_moneda(esperada)}). Quedó pendiente de verificación.",
                'warning',
            )
    except ValueError as e:
        flash(str(e), 'danger')
    except Exception as e:
        current_app.logger.exception('nomina: error registrando PILA')
        flash(f'Error al registrar PILA: {str(e)}', 'danger')

    return redirect(url_for('nomina.contratistas_lista'))


@nomina_bp.route('/periodos')
def periodos_lista():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_periodos ORDER BY id DESC")
        periodos = cur.fetchall()
    return render_template('nomina_periodos.html', periodos=periodos)

@nomina_bp.route('/periodos/crear', methods=['GET', 'POST'])
def periodo_crear():
    if request.method == 'POST':
        f = request.form
        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO nomina_periodos (anio, mes, numero_periodo, fecha_inicio, fecha_fin, observaciones, estado)
                    VALUES (%s, %s, %s, %s, %s, %s, 'borrador')
                """, (f.get('anio'), f.get('mes'), f.get('numero_periodo'), f.get('fecha_inicio'), f.get('fecha_fin'), f.get('observaciones')))
            flash('Periodo creado exitosamente.', 'success')
            return redirect(url_for('nomina.periodos_lista'))
        except Exception as e:
            flash(f'Error al crear periodo: {str(e)}', 'danger')
            
    return render_template('nomina_periodo_form.html')

@nomina_bp.route('/periodos/<int:id>')
def periodo_ver(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_periodos WHERE id = %s", (id,))
        periodo = cur.fetchone()
        if not periodo:
            flash('Periodo no encontrado.', 'warning')
            return redirect(url_for('nomina.periodos_lista'))

        cur.execute("""
            SELECT nd.*, e.nombres, e.apellidos, e.numero_documento,
                   e.cargo, e.tipo_vinculacion, e.nivel_arl
            FROM nomina_detalle nd
            JOIN nomina_empleados e ON nd.empleado_id = e.id
            WHERE nd.periodo_id = %s
            ORDER BY e.tipo_vinculacion, e.apellidos, e.nombres
        """, (id,))
        detalles = cur.fetchall()

        # PILA del contratista: la registrada para este periodo o, en registros
        # anteriores sin periodo, la pagada en el mes del periodo.
        cur.execute("""
            SELECT cp.empleado_id, BOOL_OR(COALESCE(cp.verificado, FALSE)) AS verificado,
                   SUM(COALESCE(cp.valor_pagado, 0)) AS valor_pagado
            FROM nomina_contratistas_pila cp
            WHERE cp.periodo_id = %s
               OR (cp.periodo_id IS NULL
                   AND date_trunc('month', cp.fecha_pago) = date_trunc('month', %s::date))
            GROUP BY cp.empleado_id
        """, (id, periodo['fecha_fin']))
        pila_status = {row['empleado_id']: dict(row) for row in cur.fetchall()}

    def total(campo):
        return sum(float(d[campo] or 0) for d in detalles if campo in d.keys())

    aportes = sum(total(c) for c in ('salud_empleador', 'pension_empleador', 'arl', 'ccf', 'icbf', 'sena'))
    provisiones = sum(total(c) for c in ('cesantias_provision', 'intereses_provision', 'prima_provision', 'vacaciones_provision'))
    resumen = {
        'devengado': total('total_devengado'),
        'deducido': total('total_deducido'),
        'neto': total('neto_pagar'),
        'aportes': aportes,
        'provisiones': provisiones,
        'costo': total('total_devengado') + aportes + provisiones,
        'ss_contratistas': total('ss_contratista') if 'ss_contratista' in (detalles[0].keys() if detalles else []) else 0,
    }
    return render_template('nomina_periodo_detalle.html',
                           p=periodo, detalles=detalles, pila_status=pila_status, resumen=resumen,
                           catalogo=CATALOGO_NOVEDADES)


@nomina_bp.route('/periodos/<int:id>/aprobar', methods=['POST'])
def periodo_aprobar(id):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT estado FROM nomina_periodos WHERE id = %s", (id,))
            periodo = cur.fetchone()
            if not periodo:
                flash('Periodo no encontrado.', 'danger')
                return redirect(url_for('nomina.periodos_lista'))
            if periodo['estado'] != 'calculada':
                flash('Solo se puede aprobar un periodo en estado "calculada".', 'warning')
                return redirect(url_for('nomina.periodo_ver', id=id))
            cur.execute("UPDATE nomina_periodos SET estado='aprobada' WHERE id=%s", (id,))
        flash('Periodo aprobado exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al aprobar el periodo: {str(e)}', 'danger')
    return redirect(url_for('nomina.periodo_ver', id=id))


@nomina_bp.route('/periodos/<int:id>/rechazar', methods=['POST'])
def periodo_rechazar(id):
    motivo = request.form.get('motivo', '').strip()
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT estado FROM nomina_periodos WHERE id = %s", (id,))
            periodo = cur.fetchone()
            if not periodo:
                flash('Periodo no encontrado.', 'danger')
                return redirect(url_for('nomina.periodos_lista'))
            if periodo['estado'] != 'calculada':
                flash('Solo se puede rechazar un periodo en estado "calculada".', 'warning')
                return redirect(url_for('nomina.periodo_ver', id=id))
            cur.execute("UPDATE nomina_periodos SET estado='rechazada' WHERE id=%s", (id,))
        mensaje = 'Periodo rechazado.'
        if motivo:
            mensaje += f' Motivo: {motivo}'
        flash(mensaje, 'warning')
    except Exception as e:
        flash(f'Error al rechazar el periodo: {str(e)}', 'danger')
    return redirect(url_for('nomina.periodo_ver', id=id))


@nomina_bp.route('/periodos/<int:periodo_id>/desprendible/<int:empleado_id>')
def periodo_desprendible(periodo_id, empleado_id):
    with get_db_cursor(dict_cursor=True) as cur:
        # Info Periodo
        cur.execute("SELECT * FROM nomina_periodos WHERE id = %s", (periodo_id,))
        periodo = cur.fetchone()
        
        # Info Empleado
        cur.execute("SELECT * FROM nomina_empleados WHERE id = %s", (empleado_id,))
        empleado = cur.fetchone()
        
        # Detalle Nómina
        cur.execute("""
            SELECT * FROM nomina_detalle 
            WHERE periodo_id = %s AND empleado_id = %s
        """, (periodo_id, empleado_id))
        detalle = cur.fetchone()

    if not periodo or not empleado:
        flash('No se encontró el periodo o la persona.', 'warning')
        return redirect(url_for('nomina.periodos_lista'))
    return render_template('nomina_desprendible.html', p=periodo, e=empleado, d=detalle)

@nomina_bp.route('/periodos/<int:id>/calcular', methods=['POST'])
def periodo_calcular(id):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            resultado = nomina_service.calcular_y_guardar_periodo(cur, id)
    except nomina_service.PeriodoBloqueado as e:
        flash(str(e), 'warning')
        return redirect(url_for('nomina.periodo_ver', id=id))
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('nomina.periodos_lista'))
    except Exception as e:
        current_app.logger.exception('nomina: error calculando el periodo %s', id)
        flash(f'Error en el cálculo: {str(e)}', 'danger')
        return redirect(url_for('nomina.periodo_ver', id=id))

    resumen = resultado.get('resumen', {})
    alertas = resultado.get('alertas', [])
    mensaje = (
        f"Nómina calculada: {resumen.get('empleados', 0)} empleados y "
        f"{resumen.get('contratistas', 0)} contratistas."
    )
    if alertas:
        mensaje += f" Revisa {len(alertas)} aviso(s) en el detalle del periodo."
    flash(mensaje, 'success')
    return redirect(url_for('nomina.periodo_ver', id=id))


@nomina_bp.route('/periodos/<int:id>/pagar', methods=['POST'])
def periodo_pagar(id):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            nomina_service.marcar_pagada(cur, id)
        flash('Periodo marcado como pagado. Ya no se puede modificar.', 'success')
    except ValueError as e:
        flash(str(e), 'warning')
    return redirect(url_for('nomina.periodo_ver', id=id))

@nomina_bp.route('/novedades')
def novedades_lista():
    with get_db_cursor(dict_cursor=True) as cur:
        # Listar novedades recientes
        cur.execute("""
            SELECT n.*, e.nombres, e.apellidos, p.anio, p.mes, p.numero_periodo
            FROM nomina_novedades n
            JOIN nomina_empleados e ON n.empleado_id = e.id
            JOIN nomina_periodos p ON n.periodo_id = p.id
            ORDER BY n.created_at DESC
        """)
        novedades = cur.fetchall()
    return render_template('nomina_novedades.html', novedades=novedades)

@nomina_bp.route('/novedades/crear', methods=['GET', 'POST'])
def novedades_crear():
    if request.method == 'POST':
        f = request.form
        tipo = (f.get('tipo_novedad') or '').strip().upper()
        info = CATALOGO_NOVEDADES.get(tipo)
        valor_escrito = (f.get('valor_total') or '').strip().replace(',', '.')
        try:
            periodo_id = int(f.get('periodo_id') or 0)
            empleado_id = int(f.get('empleado_id') or 0)
            cantidad = float((f.get('cantidad') or '0').replace(',', '.'))
            valor_manual = float(valor_escrito) if valor_escrito else None
        except ValueError:
            flash('Revisa el periodo, el empleado, la cantidad y el valor: hay un dato que no es un número.', 'danger')
            return redirect(url_for('nomina.novedades_crear'))

        if not info:
            flash('Elige un tipo de novedad de la lista.', 'danger')
            return redirect(url_for('nomina.novedades_crear'))
        if info['unidad'] == 'valor':
            cantidad = cantidad if cantidad > 0 else 1
            if not valor_manual or valor_manual <= 0:
                flash(f"Para «{info['nombre']}» escribe el valor en pesos.", 'danger')
                return redirect(url_for('nomina.novedades_crear'))
        elif cantidad <= 0:
            flash(f"Escribe cuántas {info['unidad']} corresponden a la novedad.", 'danger')
            return redirect(url_for('nomina.novedades_crear'))
        if valor_manual is not None and valor_manual < 0:
            flash('El valor no puede ser negativo.', 'danger')
            return redirect(url_for('nomina.novedades_crear'))

        fecha = f.get('fecha_novedad') or None
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                periodo = nomina_service.validar_periodo_editable(cur, periodo_id)
                cur.execute("SELECT salario_base FROM nomina_empleados WHERE id = %s", (empleado_id,))
                emp = cur.fetchone()
                if not emp:
                    raise ValueError('Empleado no encontrado.')
                cur.execute("SELECT salario_minimo FROM nomina_parametros WHERE anio = %s", (periodo['anio'],))
                param = cur.fetchone()
                if not param:
                    raise ValueError(f"No hay parámetros de nómina para {periodo['anio']}. Créelos primero.")

                if valor_manual is not None:
                    valor_total = valor_manual
                else:
                    valor_total = valor_novedad(
                        tipo, cantidad, float(emp['salario_base']), float(param['salario_minimo']),
                        fecha or periodo['fecha_fin'],
                    ) or 0.0

                cur.execute("""
                    INSERT INTO nomina_novedades
                        (periodo_id, empleado_id, tipo_novedad, cantidad, valor_total, fecha_novedad, observacion, valor_manual)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (periodo_id, empleado_id, tipo, cantidad, round(valor_total, 2), fecha,
                      f.get('observacion'), valor_manual is not None))
                nomina_service.marcar_para_recalculo(cur, periodo_id)

            flash(f"Novedad registrada: {info['nombre']} por {formatear_moneda(valor_total)}.", 'success')
            return redirect(url_for('nomina.novedades_lista'))
        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            current_app.logger.exception('nomina: error registrando novedad')
            flash(f'Error al registrar novedad: {str(e)}', 'danger')

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, nombres, apellidos, salario_base, tipo_vinculacion
            FROM nomina_empleados WHERE activo = TRUE ORDER BY apellidos, nombres
        """)
        empleados = cur.fetchall()
        cur.execute(
            "SELECT * FROM nomina_periodos WHERE estado IN %s ORDER BY id DESC",
            (nomina_service.ESTADOS_RECALCULABLES,),
        )
        periodos = cur.fetchall()

    return render_template(
        'nomina_novedad_form.html',
        empleados=empleados,
        periodos=periodos,
        catalogo=CATALOGO_NOVEDADES,
        factores=factores_horas_extras(),
        horas_mes_hoy=horas_mes(),
        hora_nocturna=hora_inicio_nocturna(),
    )


@nomina_bp.route('/novedades/valor')
def novedad_valor():
    """Vista previa del valor de una novedad (solo lectura, para el formulario)."""
    tipo = (request.args.get('tipo') or '').upper()
    try:
        empleado_id = int(request.args.get('empleado_id') or 0)
        cantidad = float((request.args.get('cantidad') or '0').replace(',', '.'))
    except ValueError:
        return jsonify(ok=False), 400
    fecha = request.args.get('fecha') or None
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT salario_base FROM nomina_empleados WHERE id = %s", (empleado_id,))
        emp = cur.fetchone()
        anio = int((fecha or str(datetime.now().year))[:4])
        cur.execute("SELECT salario_minimo FROM nomina_parametros WHERE anio = %s", (anio,))
        param = cur.fetchone()
    if not emp or tipo not in CATALOGO_NOVEDADES:
        return jsonify(ok=False), 404
    smmlv = float(param['salario_minimo']) if param else 0.0
    salario = float(emp['salario_base'])
    valor = valor_novedad(tipo, cantidad, salario, smmlv, fecha)
    respuesta = {'ok': True, 'manual': valor is None, 'valor': round(valor or 0, 2),
                 'valor_texto': formatear_moneda(valor or 0)}
    if tipo in TIPOS_EXTRAS:
        respuesta.update(factor=factor_hora(tipo, fecha), horas_mes=horas_mes(fecha),
                         valor_hora=round(calcular_valor_hora(salario, fecha), 2))
    if tipo in TIPOS_LICENCIAS_REMUNERADAS:
        d = desglose_incapacidad(salario, cantidad, tipo, smmlv)
        respuesta.update(empresa=round(d['empresa'], 2), cobrar=round(d['cobrar'], 2), entidad=d['entidad'])
    return jsonify(respuesta)

@nomina_bp.route('/liquidaciones')
def liquidaciones_lista():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT l.*, e.nombres, e.apellidos, e.numero_documento
            FROM nomina_liquidaciones l
            JOIN nomina_empleados e ON l.empleado_id = e.id
            ORDER BY l.created_at DESC
        """)
        liquidaciones = cur.fetchall()
    return render_template('nomina_liquidaciones.html', liquidaciones=liquidaciones)

@nomina_bp.route('/liquidaciones/crear', methods=['GET', 'POST'])
def liquidacion_crear():
    preview = None
    form = {}
    if request.method == 'POST':
        f = request.form
        form = f.to_dict()
        accion = f.get('accion') or 'previsualizar'
        motivo = (f.get('motivo_retiro') or '').upper()
        ajustes = {k: (f.get(k) or '').replace(',', '.') for k in
                   ('dias_vacaciones_pendientes', 'salarios_pendientes', 'deducciones_pendientes')}
        try:
            empleado_id = int(f.get('empleado_id') or 0)
            if motivo not in MOTIVOS_RETIRO:
                raise ValueError('Elige el motivo del retiro.')
            with get_db_cursor(dict_cursor=True) as cur:
                if accion == 'confirmar':
                    liquidacion_id, _ = nomina_service.guardar_liquidacion(
                        cur, empleado_id, f.get('fecha_retiro'), motivo, ajustes)
                else:
                    preview = nomina_service.preparar_liquidacion(
                        cur, empleado_id, f.get('fecha_retiro'), motivo, ajustes)
            if accion == 'confirmar':
                flash('Liquidación generada. El empleado quedó inactivo.', 'success')
                return redirect(url_for('nomina.liquidacion_ver', id=liquidacion_id))
        except ValueError as e:
            flash(str(e), 'danger')
            preview = None
        except Exception as e:
            current_app.logger.exception('nomina: error en la liquidación')
            flash(f'Error al generar la liquidación: {str(e)}', 'danger')
            preview = None

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT * FROM nomina_empleados
            WHERE activo = TRUE AND tipo_vinculacion <> 'CONTRATISTA'
            ORDER BY nombres, apellidos
        """)
        empleados = cur.fetchall()

    return render_template('nomina_liquidacion_form.html', empleados=empleados, preview=preview,
                           form=form, motivos=MOTIVOS_RETIRO)

@nomina_bp.route('/liquidaciones/ver/<int:id>')
def liquidacion_ver(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT l.*, e.nombres, e.apellidos, e.numero_documento, e.cargo, e.fecha_ingreso
            FROM nomina_liquidaciones l
            JOIN nomina_empleados e ON l.empleado_id = e.id
            WHERE l.id = %s
        """, (id,))
        liq = cur.fetchone()
    if not liq:
        flash('Liquidación no encontrada.', 'warning')
        return redirect(url_for('nomina.liquidaciones_lista'))
    return render_template('nomina_liquidacion_ver.html', l=liq, motivos=MOTIVOS_RETIRO)
