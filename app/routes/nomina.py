from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from database import get_db_cursor
from nomina_engine import *
from helpers import get_data_app

nomina_bp = Blueprint('nomina', __name__, url_prefix='/admin/nomina')

@nomina_bp.context_processor
def inject_common_data():
    return dict(datosApp=get_data_app())

@nomina_bp.route('/')
def nomina_dashboard():
    with get_db_cursor(dict_cursor=True) as cur:
        # 1. Empleados Activos
        cur.execute("SELECT COUNT(*) as total FROM nomina_empleados WHERE activo = TRUE")
        active_employees = cur.fetchone()['total']
        
        # 2. Total Nómina último periodo calculado
        cur.execute("""
            SELECT SUM(neto_pagar) as total 
            FROM nomina_detalle 
            WHERE periodo_id = (
                SELECT id FROM nomina_periodos 
                WHERE estado = 'calculada' 
                ORDER BY id DESC LIMIT 1
            )
        """)
        last_payroll_row = cur.fetchone()
        last_payroll_total = last_payroll_row['total'] if last_payroll_row and last_payroll_row['total'] else 0
        
        # 3. Novedades del mes actual
        cur.execute("""
            SELECT COUNT(*) as total 
            FROM nomina_novedades 
            WHERE EXTRACT(MONTH FROM created_at) = EXTRACT(MONTH FROM CURRENT_DATE)
            AND EXTRACT(YEAR FROM created_at) = EXTRACT(YEAR FROM CURRENT_DATE)
        """)
        novedades_month = cur.fetchone()['total']

    return render_template('nomina_dashboard.html', 
                           active_employees=active_employees,
                           last_payroll_total=last_payroll_total,
                           novedades_month=novedades_month)

@nomina_bp.route('/parametros')
def parametros_lista():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_parametros ORDER BY anio DESC")
        params = cur.fetchall()
    return render_template('nomina_parametros.html', params=params)

@nomina_bp.route('/parametros/crear', methods=['GET', 'POST'])
def parametros_crear():
    if request.method == 'POST':
        anio = request.form.get('anio')
        salario = request.form.get('salario_minimo')
        auxilio = request.form.get('auxilio_transporte')
        uvt = request.form.get('uvt')
        
        # Guardar en DB
        try:
            with get_db_cursor() as cur:
                # 1. Parametros Generales
                cur.execute("""
                    INSERT INTO nomina_parametros (anio, salario_minimo, auxilio_transporte, uvt)
                    VALUES (%s, %s, %s, %s)
                """, (anio, salario, auxilio, uvt))
                
                # 2. Insertar defaults para otras tablas si no existen (simplificado)
                # En un caso real, el formulario deberia pedir todos los datos o copiar del año anterior
                
            flash('Parámetros creados exitosamente.', 'success')
            return redirect(url_for('nomina.parametros_lista'))
        except Exception as e:
            flash(f'Error al crear parámetros: {str(e)}', 'danger')
            
    return render_template('nomina_parametros_form.html', modo='crear')

@nomina_bp.route('/parametros/editar/<int:anio>', methods=['GET', 'POST'])
def parametros_editar(anio):
    if request.method == 'POST':
        salario = request.form.get('salario_minimo')
        auxilio = request.form.get('auxilio_transporte')
        uvt = request.form.get('uvt')
        
        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE nomina_parametros 
                    SET salario_minimo=%s, auxilio_transporte=%s, uvt=%s
                    WHERE anio=%s
                """, (salario, auxilio, uvt, anio))
            flash('Parámetros actualizados.', 'success')
            return redirect(url_for('nomina.parametros_lista'))
        except Exception as e:
             flash(f'Error al actualizar: {str(e)}', 'danger')
             
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_parametros WHERE anio = %s", (anio,))
        param = cur.fetchone()
        
    return render_template('nomina_parametros_form.html', modo='editar', p=param)

@nomina_bp.route('/empleados')
def empleados_lista():
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_empleados ORDER BY apellidos, nombres")
        empleados = cur.fetchall()
    return render_template('nomina_empleados.html', empleados=empleados)

@nomina_bp.route('/empleados/crear', methods=['GET', 'POST'])
def empleado_crear():
    if request.method == 'POST':
        # Recoger datos del form
        f = request.form
        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO nomina_empleados (
                        tipo_documento, numero_documento, nombres, apellidos, email, telefono, direccion,
                        fecha_ingreso, tipo_vinculacion, cargo, salario_base, nivel_arl,
                        banco, tipo_cuenta, numero_cuenta,
                        eps, fondo_pension, fondo_cesantias
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    f.get('tipo_documento'), f.get('numero_documento'), f.get('nombres'), f.get('apellidos'),
                    f.get('email'), f.get('telefono'), f.get('direccion'),
                    f.get('fecha_ingreso'), f.get('tipo_vinculacion'), f.get('cargo'), f.get('salario_base'), f.get('nivel_arl'),
                    f.get('banco'), f.get('tipo_cuenta'), f.get('numero_cuenta'),
                    f.get('eps'), f.get('fondo_pension'), f.get('fondo_cesantias')
                ))
            flash('Empleado creado exitosamente.', 'success')
            return redirect(url_for('nomina.empleados_lista'))
        except Exception as e:
            flash(f'Error al crear empleado: {str(e)}', 'danger')
            
    return render_template('nomina_empleado_form.html', modo='crear')

@nomina_bp.route('/empleados/editar/<int:id>', methods=['GET', 'POST'])
def empleado_editar(id):
    if request.method == 'POST':
        f = request.form
        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE nomina_empleados SET
                        tipo_documento=%s, numero_documento=%s, nombres=%s, apellidos=%s, email=%s, telefono=%s, direccion=%s,
                        fecha_ingreso=%s, tipo_vinculacion=%s, cargo=%s, salario_base=%s, nivel_arl=%s,
                        banco=%s, tipo_cuenta=%s, numero_cuenta=%s,
                        eps=%s, fondo_pension=%s, fondo_cesantias=%s
                    WHERE id=%s
                """, (
                    f.get('tipo_documento'), f.get('numero_documento'), f.get('nombres'), f.get('apellidos'),
                    f.get('email'), f.get('telefono'), f.get('direccion'),
                    f.get('fecha_ingreso'), f.get('tipo_vinculacion'), f.get('cargo'), f.get('salario_base'), f.get('nivel_arl'),
                    f.get('banco'), f.get('tipo_cuenta'), f.get('numero_cuenta'),
                    f.get('eps'), f.get('fondo_pension'), f.get('fondo_cesantias'),
                    id
                ))
            flash('Empleado actualizado exitosamente.', 'success')
            return redirect(url_for('nomina.empleados_lista'))
        except Exception as e:
             flash(f'Error al actualizar empleado: {str(e)}', 'danger')

    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_empleados WHERE id = %s", (id,))
        empleado = cur.fetchone()
        
    return render_template('nomina_empleado_form.html', modo='editar', e=empleado)

@nomina_bp.route('/empleados/ver/<int:id>')
def empleado_ver(id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_empleados WHERE id = %s", (id,))
        empleado = cur.fetchone()
    return render_template('nomina_empleado_ver.html', e=empleado)

@nomina_bp.route('/contratistas')
def contratistas_lista():
    with get_db_cursor(dict_cursor=True) as cur:
        # Obtener solo contratistas
        cur.execute("""
            SELECT e.*, 
                   EXISTS(
                       SELECT 1 FROM nomina_contratistas_pila p 
                       WHERE p.empleado_id = e.id 
                       AND EXTRACT(MONTH FROM p.fecha_pago) = EXTRACT(MONTH FROM CURRENT_DATE)
                       AND EXTRACT(YEAR FROM p.fecha_pago) = EXTRACT(YEAR FROM CURRENT_DATE)
                   ) as pila_verificada
            FROM nomina_empleados e 
            WHERE e.tipo_vinculacion = 'CONTRATISTA'
            ORDER BY e.apellidos, e.nombres
        """)
        contratistas = cur.fetchall()
    return render_template('nomina_contratistas.html', contratistas=contratistas)

@nomina_bp.route('/contratistas/pila/<int:id>', methods=['POST'])
def subir_pila(id):
    numero_planilla = request.form.get('numero_planilla')
    fecha_pago = request.form.get('fecha_pago')
    valor_pagado = request.form.get('valor_pagado')
    
    # En un caso real, aqui manejariamos la subida del archivo evidencia
    
    try:
        with get_db_cursor() as cur:
            # Determinar periodo actual (simplificado al mes actual)
            # Idealmente se enlaza con nomina_periodos activo
            cur.execute("""
                INSERT INTO nomina_contratistas_pila 
                (empleado_id, numero_planilla, fecha_pago, valor_pagado, verificado)
                VALUES (%s, %s, %s, %s, TRUE)
            """, (id, numero_planilla, fecha_pago, valor_pagado))
            
        flash('Soporte PILA registrado correctamente.', 'success')
    except Exception as e:
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
                    INSERT INTO nomina_periodos (anio, mes, numero_periodo, fecha_inicio, fecha_fin, observaciones)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (f.get('anio'), f.get('mes'), f.get('numero_periodo'), f.get('fecha_inicio'), f.get('fecha_fin'), f.get('observaciones')))
            flash('Periodo creado exitosamente.', 'success')
            return redirect(url_for('nomina.periodos_lista'))
        except Exception as e:
            flash(f'Error al crear periodo: {str(e)}', 'danger')
            
    return render_template('nomina_periodo_form.html')

@nomina_bp.route('/periodos/<int:id>')
def periodo_ver(id):
    with get_db_cursor(dict_cursor=True) as cur:
        # Info periodo
        cur.execute("SELECT * FROM nomina_periodos WHERE id = %s", (id,))
        periodo = cur.fetchone()
        
        # Detalle nomina
        cur.execute("""
            SELECT nd.*, e.nombres, e.apellidos, e.numero_documento, e.cargo
            FROM nomina_detalle nd
            JOIN nomina_empleados e ON nd.empleado_id = e.id
            WHERE nd.periodo_id = %s
        """, (id,))
        detalles = cur.fetchall()
        
    return render_template('nomina_periodo_detalle.html', p=periodo, detalles=detalles)

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
        
    return render_template('nomina_desprendible.html', p=periodo, e=empleado, d=detalle)

@nomina_bp.route('/periodos/<int:id>/calcular', methods=['POST'])
def periodo_calcular(id):
    try:
        # Lógica de cálculo masivo
        # 1. Obtener periodo y parametros
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM nomina_periodos WHERE id = %s", (id,))
            periodo = cur.fetchone()
            
            cur.execute("SELECT * FROM nomina_parametros WHERE anio = %s", (periodo['anio'],))
            params = cur.fetchone()
            
            if not params:
                flash(f"Error: No se encontraron parámetros de nómina para el año {periodo['anio']}. Por favor créelos primero en la sección de Parámetros.", "danger")
                return redirect(url_for('nomina.periodos_lista'))

            # Parametros necesarios (simplificado, deberian cargarse todos)
            smmlv = float(params['salario_minimo'])
            aux_transporte = float(params['auxilio_transporte'])
            uvt = float(params['uvt'])
            
            # 2. Obtener empleados activos
            cur.execute("SELECT * FROM nomina_empleados WHERE activo = TRUE AND tipo_vinculacion != 'CONTRATISTA'")
            empleados = cur.fetchall()
            
            for e in empleados:
                # 3. Calcular para cada empleado
                # Dias trabajados (simplificado a 15 o 30)
                dias_trabajados = 15 if periodo['numero_periodo'] in [1, 2] else 30
                
                # Devengados
                basico = (float(e['salario_base']) / 30) * dias_trabajados
                aux_trans = calcular_auxilio_transporte(float(e['salario_base']), smmlv, aux_transporte)
                if periodo['numero_periodo'] in [1, 2]: aux_trans /= 2 # Ajuste si es quincenal
                
                # Novedades (Extras, Recargos) - TODO: Leer de tabla novedades
                extras = 0 
                
                total_devengado = basico + aux_trans + extras
                
                # Deducciones
                # Salud/Pension
                base_ss = total_devengado - aux_trans
                salud_emp, pension_emp = calcular_salud_pension(base_ss, 4, 4)
                
                # Fondo Solidaridad
                fsp = calcular_fondo_solidaridad(base_ss, smmlv)
                
                # Retencion (solo si aplica, simplificado)
                retencion = 0
                
                total_deducido = salud_emp + pension_emp + fsp + retencion
                neto = total_devengado - total_deducido
                
                # 4. Guardar/Actualizar en base de datos
                # Borrar calculo previo si existe
                cur.execute("DELETE FROM nomina_detalle WHERE periodo_id=%s AND empleado_id=%s", (id, e['id']))
                
                cur.execute("""
                    INSERT INTO nomina_detalle (
                        periodo_id, empleado_id, dias_trabajados,
                        sueldo_basico, auxilio_transporte, horas_extras, total_devengado,
                        salud_empleado, pension_empleado, fondo_solidaridad, retencion_fuente, total_deducido,
                        neto_pagar
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    id, e['id'], dias_trabajados,
                    basico, aux_trans, extras, total_devengado,
                    salud_emp, pension_emp, fsp, retencion, total_deducido,
                    neto
                ))
            
            # Actualizar estado periodo
            cur.execute("UPDATE nomina_periodos SET estado='calculada' WHERE id=%s", (id,))
            
        flash('Cálculo de nómina realizado exitosamente.', 'success')
    except Exception as e:
        flash(f'Error en el cálculo: {str(e)}', 'danger')
        
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
        periodo_id = request.form.get('periodo_id')
        empleado_id = request.form.get('empleado_id')
        tipo = request.form.get('tipo_novedad')
        cantidad = float(request.form.get('cantidad'))
        fecha = request.form.get('fecha_novedad')
        observacion = request.form.get('observacion')
        
        try:
            with get_db_cursor() as cur:
                # 1. Obtener datos del empleado y periodo
                cur.execute("SELECT salario_base FROM nomina_empleados WHERE id = %s", (empleado_id,))
                emp = cur.fetchone()
                if not emp: raise Exception("Empleado no encontrado")
                salario = float(emp[0]) # index 0 for tuple cursor, or use dict_cursor? standard cursor is tuple by default in typical usage unless specified
                
                cur.execute("SELECT anio FROM nomina_periodos WHERE id = %s", (periodo_id,))
                per = cur.fetchone()
                anio = per[0]
                
                cur.execute("SELECT salario_minimo FROM nomina_parametros WHERE anio = %s", (anio,))
                param = cur.fetchone()
                if not param: raise Exception("Parámetros del año no encontrados")
                smmlv = float(param[0])

                # 2. Calcular valor
                valor_total = 0
                
                if tipo in ['HED', 'HEN', 'HEDF', 'HENF', 'RN', 'RD']:
                    valor_hora = calcular_valor_hora(salario)
                    valor_total = calcular_horas_extras(valor_hora, tipo, cantidad)
                elif 'INCAPACIDAD' in tipo or 'LICENCIA' in tipo:
                    # Asumimos que cantidad son dias
                    valor_total = calcular_incapacidad(salario, cantidad, tipo, smmlv)
                else:
                    # Otros / Bonificaciones manuales?
                    # Si tiene un campo valor unitario, se podria usar.
                    if request.form.get('valor_total'):
                        valor_total = float(request.form.get('valor_total'))
                        
                # 3. Insertar
                cur.execute("""
                    INSERT INTO nomina_novedades 
                    (periodo_id, empleado_id, tipo_novedad, cantidad, valor_total, fecha_novedad, observacion)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (periodo_id, empleado_id, tipo, cantidad, valor_total, fecha, observacion))
                
            flash('Novedad registrada exitosamente.', 'success')
            return redirect(url_for('nomina.novedades_lista'))
            
        except Exception as e:
            flash(f'Error al registrar novedad: {str(e)}', 'danger')
    
    # GET: Prepare form data
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT id, nombres, apellidos FROM nomina_empleados WHERE activo = TRUE ORDER BY apellidos")
        empleados = cur.fetchall()
        
        # Periodos activos o abiertos (estado borrador)
        cur.execute("SELECT * FROM nomina_periodos WHERE estado = 'borrador' ORDER BY id DESC")
        periodos = cur.fetchall()
        
    return render_template('nomina_novedad_form.html', empleados=empleados, periodos=periodos)

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
    if request.method == 'POST':
        empleado_id = request.form.get('empleado_id')
        fecha_retiro = request.form.get('fecha_retiro')
        motivo = request.form.get('motivo_retiro')
        
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                # 1. Obtener datos empleado
                cur.execute("SELECT * FROM nomina_empleados WHERE id=%s", (empleado_id,))
                e = cur.fetchone()
                
                # Obtener año de los parámetros (del año de retiro)
                anio_retiro = datetime.strptime(fecha_retiro, '%Y-%m-%d').year
                cur.execute("SELECT * FROM nomina_parametros WHERE anio=%s", (anio_retiro,))
                params = cur.fetchone()
                
                if not params:
                    flash(f"Error: No se encontraron parámetros de nómina para el año {anio_retiro}. Por favor créelos primero.", "danger")
                    return redirect(url_for('nomina.liquidaciones_lista'))
                
                smmlv = params['salario_minimo']
                
                # 2. Calcular indemnización (Simplificado)
                indemnizacion = calcular_indemnizacion(
                    e['salario_base'], e['tipo_vinculacion'], e['fecha_ingreso'], 
                    datetime.strptime(fecha_retiro, '%Y-%m-%d').date(), smmlv
                )
                
                # 3. Calcular prestaciones (Simplificado - debería usar días proporcionales reales)
                # Asumimos 180 días proporcionales para el ejemplo
                dias_prop = 180 
                cesantias = (e['salario_base'] * dias_prop) / 360
                intereses = (cesantias * dias_prop * 0.12) / 360
                prima = (e['salario_base'] * dias_prop) / 360
                vacaciones = (e['salario_base'] * dias_prop) / 720
                
                total = cesantias + intereses + prima + vacaciones + indemnizacion
                
                # 4. Guardar
                cur.execute("""
                    INSERT INTO nomina_liquidaciones (
                        empleado_id, fecha_retiro, motivo_retiro, 
                        dias_liquidacion, salario_base_liquidacion,
                        cesantias, intereses_cesantias, prima_servicios, vacaciones, indemnizacion, 
                        total_pagar
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    empleado_id, fecha_retiro, motivo,
                    dias_prop, e['salario_base'],
                    cesantias, intereses, prima, vacaciones, indemnizacion,
                    total
                ))
                
                # Marcar empleado inactivo
                cur.execute("UPDATE nomina_empleados SET activo=FALSE, fecha_retiro=%s WHERE id=%s", (fecha_retiro, empleado_id))
                
            flash('Liquidación generada exitosamente.', 'success')
            return redirect(url_for('nomina.liquidaciones_lista'))
            
        except Exception as ex:
             flash(f'Error al generar liquidación: {str(ex)}', 'danger')
             
    # GET: Formulario
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT * FROM nomina_empleados WHERE activo = TRUE ORDER BY nombres, apellidos")
        empleados = cur.fetchall()
        
    return render_template('nomina_liquidacion_form.html', empleados=empleados)

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
    return render_template('nomina_liquidacion_ver.html', l=liq)
