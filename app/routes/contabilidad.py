"""
routes/contabilidad.py — Módulo de contabilidad: ingresos, egresos y cierres.

MIGRACIÓN A NUEVO CLIENTE — ejecutar el script antes de activar este módulo:
    python migrate_contabilidad.py

Retenciones / impuestos soportados (solo ingresos):
  - Retención en la Fuente : 3.5 / 6 / 11 / 15 % o personalizado
  - IVA cobrado            : 5 / 19 % o personalizado (referencia, no es ingreso)
  - ReteIVA                : 15 % del IVA (retención sobre IVA)
  - ReteICA                : por municipio (0.4 – 1 % o personalizado)

  monto_bruto  = valor base del servicio/producto
  monto        = neto real recibido = monto_bruto − retefuente − reteiva − reteica
  total_retenciones = retefuente_monto + reteiva_monto + reteica_monto

Plantillas: gastos/ingresos recurrentes que se generan en un clic al inicio del mes.

INTEGRACIÓN AUTOMÁTICA: billing.py, admin.py (POS) y payments.py llaman a
`registrar_movimiento()` al confirmar pagos. Si no se quiere contabilidad automática
en un cliente, deshabilitar esas llamadas o dejar el try/except silencioso.
"""

import csv
import io
from datetime import date, timedelta

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, current_app as app, Response)

from database import get_db_cursor
from helpers import get_data_app
from security import rol_requerido, ADMIN_CONTADOR, ROL_SUPER_ADMIN

contabilidad_bp = Blueprint('contabilidad', __name__)


# ─────────────────────────────────────────────────────────
# HELPER PÚBLICO — llamado desde billing.py, admin.py, payments.py
# ─────────────────────────────────────────────────────────

def registrar_movimiento(tipo, categoria, descripcion, monto,
                          fecha=None, referencia_tipo=None, referencia_id=None,
                          usuario_id=None, notas=None, auto_generado=True):
    """Inserta un movimiento contable sin retenciones. No lanza excepciones."""
    if fecha is None:
        fecha = date.today()
    try:
        monto = float(monto or 0)
        if monto <= 0:
            return
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO contabilidad_movimientos
                    (tipo, categoria, descripcion, monto, monto_bruto, fecha,
                     referencia_tipo, referencia_id, notas, usuario_id, auto_generado)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (tipo, categoria, descripcion, monto, monto,
                  fecha, referencia_tipo, referencia_id, notas, usuario_id, auto_generado))
    except Exception as e:
        try:
            app.logger.warning(f"registrar_movimiento falló: {e}")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────

CATEGORIAS_INGRESO = [
    ('cuenta_cobro',  'Cuenta de cobro'),
    ('venta_pos',     'Venta POS'),
    ('venta_restaurante', 'Venta restaurante'),
    ('pedido_online', 'Pedido online'),
    ('honorarios',    'Honorarios'),
    ('otro_ingreso',  'Otro ingreso'),
]
CATEGORIAS_EGRESO = [
    ('nomina',      'Nómina / pagos empleados'),
    ('proveedor',   'Proveedor / insumos'),
    ('arriendo',    'Arriendo'),
    ('servicios',   'Servicios / utilities'),
    ('marketing',   'Marketing / publicidad'),
    ('impuestos',   'Impuestos / obligaciones'),
    ('prestamos',   'Préstamos / cuotas'),
    ('anulacion_pos', 'Anulación venta POS'),
    ('anulacion_restaurante', 'Anulación venta restaurante'),
    ('otro_egreso', 'Otro egreso'),
]
ALL_CATEGORIAS = dict(CATEGORIAS_INGRESO + CATEGORIAS_EGRESO)

TASAS_RETEFUENTE = [('0','0'), ('3.5','3.5'), ('6','6'), ('11','11'), ('15','15')]
TASAS_IVA        = [('0','0'), ('5','5'), ('19','19')]
TASAS_RETEIVA    = [('15','15')]
TASAS_RETEICA    = [('0','0'), ('0.4','0.4'), ('0.6','0.6'), ('0.8','0.8'), ('1','1')]


def _label(cat):
    return ALL_CATEGORIAS.get(cat, cat.replace('_', ' ').title())


def _parse_pct(val):
    try:
        return float(str(val).replace(',', '.') or '0')
    except (ValueError, TypeError):
        return 0.0


def _calcular_impuestos(bruto, rtefte_pct, iva_pct, reteiva_pct, rteica_pct):
    """Devuelve dict con todos los montos calculados."""
    bruto = float(bruto or 0)
    rtefte  = round(bruto * _parse_pct(rtefte_pct)  / 100, 2)
    iva     = round(bruto * _parse_pct(iva_pct)     / 100, 2)
    reteiva = round(iva   * _parse_pct(reteiva_pct) / 100, 2)
    rteica  = round(bruto * _parse_pct(rteica_pct)  / 100, 2)
    total_ret = rtefte + reteiva + rteica
    neto      = round(bruto - total_ret, 2)
    return {
        'retefuente_monto':  rtefte,
        'iva_monto':         iva,
        'reteiva_monto':     reteiva,
        'reteica_monto':     rteica,
        'total_retenciones': total_ret,
        'monto_neto':        neto,
    }


def _mes_fin(d):
    """Último día del mes de la fecha d."""
    if d.month == 12:
        return d.replace(day=31)
    return d.replace(month=d.month + 1, day=1) - timedelta(days=1)


# ─────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────

@contabilidad_bp.route('/admin/contabilidad')
@rol_requerido(ADMIN_CONTADOR)
def dashboard():
    datosApp = get_data_app()
    periodo  = request.args.get('periodo', 'mes')
    hoy      = date.today()

    if periodo == 'semana':
        fecha_ini     = hoy - timedelta(days=hoy.weekday())
        fecha_fin     = hoy
        label_periodo = 'Esta semana'
    elif periodo == 'mes_ant':
        primer_dia    = hoy.replace(day=1)
        fecha_fin     = primer_dia - timedelta(days=1)
        fecha_ini     = fecha_fin.replace(day=1)
        label_periodo = fecha_ini.strftime('%B %Y').capitalize()
    elif periodo == 'anio':
        fecha_ini     = hoy.replace(month=1, day=1)
        fecha_fin     = hoy
        label_periodo = f'Año {hoy.year}'
    else:  # mes
        fecha_ini     = hoy.replace(day=1)
        fecha_fin     = hoy
        label_periodo = hoy.strftime('%B %Y').capitalize()

    stats = {
        'ingresos': 0, 'ingresos_bruto': 0, 'retenciones': 0,
        'retefuente': 0, 'iva': 0, 'reteiva': 0, 'reteica': 0,
        'egresos': 0, 'saldo': 0, 'num_ingresos': 0, 'num_egresos': 0,
    }
    ultimos          = []
    chart_labels     = []
    chart_ingresos   = []
    chart_egresos    = []
    por_categoria    = []
    pendientes_plantillas = 0

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # KPIs del período
            cur.execute("""
                SELECT tipo,
                       COALESCE(SUM(monto),0)                AS total_neto,
                       COALESCE(SUM(monto_bruto),0)          AS total_bruto,
                       COALESCE(SUM(total_retenciones),0)    AS total_ret,
                       COALESCE(SUM(retefuente_monto),0)     AS rtefte,
                       COALESCE(SUM(iva_monto),0)            AS iva,
                       COALESCE(SUM(reteiva_monto),0)        AS reteiva,
                       COALESCE(SUM(reteica_monto),0)        AS rteica,
                       COUNT(*)                              AS cnt
                FROM contabilidad_movimientos
                WHERE fecha BETWEEN %s AND %s
                GROUP BY tipo
            """, (fecha_ini, fecha_fin))
            for r in cur.fetchall():
                if r['tipo'] == 'ingreso':
                    stats['ingresos']       = float(r['total_neto'])
                    stats['ingresos_bruto'] = float(r['total_bruto'])
                    stats['retenciones']    = float(r['total_ret'])
                    stats['retefuente']     = float(r['rtefte'])
                    stats['iva']            = float(r['iva'])
                    stats['reteiva']        = float(r['reteiva'])
                    stats['reteica']        = float(r['rteica'])
                    stats['num_ingresos']   = r['cnt']
                else:
                    stats['egresos']    = float(r['total_neto'])
                    stats['num_egresos'] = r['cnt']
            stats['saldo'] = stats['ingresos'] - stats['egresos']

            # Últimos 10
            cur.execute("""
                SELECT m.*, u.nombre AS usuario_nombre
                FROM contabilidad_movimientos m
                LEFT JOIN usuarios u ON u.id = m.usuario_id
                ORDER BY m.fecha DESC, m.created_at DESC
                LIMIT 10
            """)
            ultimos = cur.fetchall()

            # Gráfico mensual (últimos 6 meses)
            cur.execute("""
                SELECT TO_CHAR(fecha,'YYYY-MM') AS mes, tipo,
                       COALESCE(SUM(monto),0) AS total
                FROM contabilidad_movimientos
                WHERE fecha >= (DATE_TRUNC('month', NOW()) - INTERVAL '5 months')
                GROUP BY mes, tipo ORDER BY mes
            """)
            meses_data = {}
            for r in cur.fetchall():
                meses_data.setdefault(r['mes'], {'ingreso': 0, 'egreso': 0})
                meses_data[r['mes']][r['tipo']] = float(r['total'])
            nombres_mes = ['','Ene','Feb','Mar','Abr','May','Jun',
                           'Jul','Ago','Sep','Oct','Nov','Dic']
            for mk in sorted(meses_data):
                y, m_ = mk.split('-')
                chart_labels.append(f"{nombres_mes[int(m_)]} {y}")
                chart_ingresos.append(meses_data[mk]['ingreso'])
                chart_egresos.append(meses_data[mk]['egreso'])

            # Desglose por categoría
            cur.execute("""
                SELECT categoria, tipo,
                       COALESCE(SUM(monto),0) AS total, COUNT(*) AS cnt
                FROM contabilidad_movimientos
                WHERE fecha BETWEEN %s AND %s
                GROUP BY categoria, tipo ORDER BY total DESC
            """, (fecha_ini, fecha_fin))
            por_categoria = cur.fetchall()

            # Plantillas pendientes de generar este mes
            mes_ini = hoy.replace(day=1)
            try:
                cur.execute("""
                    SELECT COUNT(*) AS cnt FROM contabilidad_plantillas p
                    WHERE p.activo = TRUE
                      AND NOT EXISTS (
                          SELECT 1 FROM contabilidad_movimientos m
                          WHERE m.referencia_tipo = 'plantilla'
                            AND m.referencia_id = p.id
                            AND m.fecha >= %s
                      )
                """, (mes_ini,))
                row = cur.fetchone()
                pendientes_plantillas = int(row['cnt']) if row else 0
            except Exception:
                pass  # tabla puede no existir aún

    except Exception as e:
        app.logger.error(f"Error contabilidad dashboard: {e}")

    return render_template('contabilidad_dashboard.html',
                           datosApp=datosApp, stats=stats,
                           ultimos=ultimos,
                           chart_labels=chart_labels,
                           chart_ingresos=chart_ingresos,
                           chart_egresos=chart_egresos,
                           por_categoria=por_categoria,
                           pendientes_plantillas=pendientes_plantillas,
                           periodo=periodo, label_periodo=label_periodo,
                           fecha_ini=fecha_ini, fecha_fin=fecha_fin,
                           categorias_ingreso=CATEGORIAS_INGRESO,
                           categorias_egreso=CATEGORIAS_EGRESO,
                           label_cat=_label)


# ─────────────────────────────────────────────────────────
# MOVIMIENTOS
# ─────────────────────────────────────────────────────────

@contabilidad_bp.route('/admin/contabilidad/movimientos')
@rol_requerido(ADMIN_CONTADOR)
def movimientos():
    datosApp   = get_data_app()
    tipo_f     = request.args.get('tipo', 'todos')
    cat_f      = request.args.get('categoria', '')
    desde_f    = request.args.get('desde', '')
    hasta_f    = request.args.get('hasta', '')
    buscar_f   = request.args.get('buscar', '').strip()
    page       = max(1, int(request.args.get('page', 1)))
    por_pagina = 30

    movs = []
    total_count = total_ingresos = total_egresos = total_retenciones = 0

    conditions, params = [], []
    if tipo_f in ('ingreso', 'egreso'):
        conditions.append("m.tipo = %s"); params.append(tipo_f)
    if cat_f:
        conditions.append("m.categoria = %s"); params.append(cat_f)
    if desde_f:
        conditions.append("m.fecha >= %s"); params.append(desde_f)
    if hasta_f:
        conditions.append("m.fecha <= %s"); params.append(hasta_f)
    if buscar_f:
        conditions.append("m.descripcion ILIKE %s"); params.append(f'%{buscar_f}%')
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(f"""
                SELECT COUNT(*) AS cnt,
                       COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto      ELSE 0 END),0) AS ing,
                       COALESCE(SUM(CASE WHEN tipo='egreso'  THEN monto      ELSE 0 END),0) AS egr,
                       COALESCE(SUM(CASE WHEN tipo='ingreso' THEN total_retenciones ELSE 0 END),0) AS ret
                FROM contabilidad_movimientos m {where}
            """, params)
            row = cur.fetchone()
            total_count       = row['cnt']
            total_ingresos    = float(row['ing'])
            total_egresos     = float(row['egr'])
            total_retenciones = float(row['ret'])

            offset = (page - 1) * por_pagina
            cur.execute(f"""
                SELECT m.*, u.nombre AS usuario_nombre
                FROM contabilidad_movimientos m
                LEFT JOIN usuarios u ON u.id = m.usuario_id
                {where}
                ORDER BY m.fecha DESC, m.created_at DESC
                LIMIT %s OFFSET %s
            """, params + [por_pagina, offset])
            movs = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error listando movimientos: {e}")

    total_pages = max(1, (total_count + por_pagina - 1) // por_pagina)

    return render_template('contabilidad_movimientos.html',
                           datosApp=datosApp, movs=movs,
                           total_count=total_count,
                           total_ingresos=total_ingresos,
                           total_egresos=total_egresos,
                           total_retenciones=total_retenciones,
                           page=page, total_pages=total_pages,
                           tipo_f=tipo_f, cat_f=cat_f,
                           desde_f=desde_f, hasta_f=hasta_f,
                           buscar_f=buscar_f,
                           categorias_ingreso=CATEGORIAS_INGRESO,
                           categorias_egreso=CATEGORIAS_EGRESO,
                           tasas_retefuente=TASAS_RETEFUENTE,
                           tasas_iva=TASAS_IVA,
                           tasas_reteica=TASAS_RETEICA,
                           label_cat=_label)


@contabilidad_bp.route('/admin/contabilidad/movimientos/nuevo', methods=['POST'])
@rol_requerido(ADMIN_CONTADOR)
def nuevo_movimiento():
    tipo        = request.form.get('tipo', '').strip()
    categoria   = request.form.get('categoria', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    fecha_str   = request.form.get('fecha', str(date.today()))
    notas       = request.form.get('notas', '').strip()

    if tipo not in ('ingreso', 'egreso') or not descripcion:
        flash('Tipo y descripción son obligatorios.', 'error')
        return redirect(request.referrer or url_for('contabilidad.movimientos'))

    try:
        bruto = float(request.form.get('monto_bruto', '0').replace(',', '.'))
        if bruto <= 0:
            raise ValueError
    except ValueError:
        flash('El monto debe ser mayor a cero.', 'error')
        return redirect(request.referrer or url_for('contabilidad.movimientos'))

    # Impuestos (solo para ingresos)
    if tipo == 'ingreso':
        rtefte_pct  = _parse_pct(request.form.get('retefuente_pct_val', '0'))
        iva_pct     = _parse_pct(request.form.get('iva_pct_val', '0'))
        reteiva_pct = _parse_pct(request.form.get('reteiva_pct_val', '0'))
        rteica_pct  = _parse_pct(request.form.get('reteica_pct_val', '0'))
    else:
        rtefte_pct = iva_pct = reteiva_pct = rteica_pct = 0.0

    calc = _calcular_impuestos(bruto, rtefte_pct, iva_pct, reteiva_pct, rteica_pct)
    monto_neto = calc['monto_neto'] if tipo == 'ingreso' else bruto

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO contabilidad_movimientos
                    (tipo, categoria, descripcion, monto_bruto, monto,
                     retefuente_pct, retefuente_monto,
                     iva_pct, iva_monto,
                     reteiva_pct, reteiva_monto,
                     reteica_pct, reteica_monto,
                     total_retenciones,
                     fecha, notas, usuario_id, auto_generado)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE)
            """, (tipo, categoria, descripcion, bruto, monto_neto,
                  rtefte_pct,  calc['retefuente_monto'],
                  iva_pct,     calc['iva_monto'],
                  reteiva_pct, calc['reteiva_monto'],
                  rteica_pct,  calc['reteica_monto'],
                  calc['total_retenciones'],
                  fecha_str, notas or None, session.get('usuario_id')))
        flash('Movimiento registrado correctamente.', 'success')
    except Exception as e:
        app.logger.error(f"Error guardando movimiento: {e}")
        flash('Error al registrar el movimiento.', 'error')

    # Redirigir de vuelta al origen (dashboard o movimientos)
    next_url = request.form.get('next') or url_for('contabilidad.movimientos')
    return redirect(next_url)


@contabilidad_bp.route('/admin/contabilidad/movimientos/<int:mov_id>/eliminar', methods=['POST'])
@rol_requerido(ADMIN_CONTADOR)
def eliminar_movimiento(mov_id):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT auto_generado FROM contabilidad_movimientos WHERE id=%s", (mov_id,))
            row = cur.fetchone()
            if not row:
                flash('Movimiento no encontrado.', 'warning')
            elif row['auto_generado']:
                if session.get('rol_id') == ROL_SUPER_ADMIN:
                    cur.execute("DELETE FROM contabilidad_movimientos WHERE id=%s", (mov_id,))
                    flash('Movimiento auto-generado eliminado por Super Admin.', 'success')
                else:
                    flash('Los movimientos automáticos (PayU/POS/Cuentas) no se pueden eliminar.', 'warning')
            else:
                cur.execute("DELETE FROM contabilidad_movimientos WHERE id=%s", (mov_id,))
                flash('Movimiento eliminado.', 'success')
    except Exception as e:
        app.logger.error(f"Error eliminando movimiento {mov_id}: {e}")
        flash('Error al eliminar.', 'error')
    return redirect(url_for('contabilidad.movimientos'))


# ─────────────────────────────────────────────────────────
# EXPORTAR CSV
# ─────────────────────────────────────────────────────────

@contabilidad_bp.route('/admin/contabilidad/exportar')
@rol_requerido(ADMIN_CONTADOR)
def exportar_movimientos():
    tipo_f   = request.args.get('tipo', 'todos')
    cat_f    = request.args.get('categoria', '')
    desde_f  = request.args.get('desde', '')
    hasta_f  = request.args.get('hasta', '')
    buscar_f = request.args.get('buscar', '').strip()

    conditions, params = [], []
    if tipo_f in ('ingreso', 'egreso'):
        conditions.append("tipo = %s"); params.append(tipo_f)
    if cat_f:
        conditions.append("categoria = %s"); params.append(cat_f)
    if desde_f:
        conditions.append("fecha >= %s"); params.append(desde_f)
    if hasta_f:
        conditions.append("fecha <= %s"); params.append(hasta_f)
    if buscar_f:
        conditions.append("descripcion ILIKE %s"); params.append(f'%{buscar_f}%')
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(f"""
                SELECT fecha, tipo, categoria, descripcion,
                       COALESCE(monto_bruto, monto) AS bruto,
                       COALESCE(retefuente_pct,0)   AS rtefte_pct,
                       COALESCE(retefuente_monto,0) AS rtefte_monto,
                       COALESCE(iva_pct,0)          AS iva_pct,
                       COALESCE(iva_monto,0)        AS iva_monto,
                       COALESCE(reteiva_pct,0)      AS reteiva_pct,
                       COALESCE(reteiva_monto,0)    AS reteiva_monto,
                       COALESCE(reteica_pct,0)      AS rteica_pct,
                       COALESCE(reteica_monto,0)    AS rteica_monto,
                       COALESCE(total_retenciones,0) AS total_ret,
                       monto AS neto,
                       notas, referencia_tipo, referencia_id, auto_generado
                FROM contabilidad_movimientos {where}
                ORDER BY fecha DESC, created_at DESC
            """, params)
            movs = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error exportando: {e}")
        flash('Error al exportar los movimientos.', 'error')
        return redirect(url_for('contabilidad.movimientos'))

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        'Fecha', 'Tipo', 'Categoría', 'Descripción',
        'Monto Bruto', 'RteFte %', 'RteFte $',
        'IVA %', 'IVA $', 'ReteIVA %', 'ReteIVA $',
        'ReteICA %', 'ReteICA $', 'Total Retenciones',
        'Neto Recibido', 'Notas', 'Origen', 'Ref ID', 'Auto-generado',
    ])
    for m in movs:
        writer.writerow([
            m['fecha'].strftime('%d/%m/%Y') if m['fecha'] else '',
            m['tipo'],
            _label(m['categoria']),
            m['descripcion'],
            str(m['bruto']).replace('.', ','),
            str(m['rtefte_pct']).replace('.', ','),
            str(m['rtefte_monto']).replace('.', ','),
            str(m['iva_pct']).replace('.', ','),
            str(m['iva_monto']).replace('.', ','),
            str(m['reteiva_pct']).replace('.', ','),
            str(m['reteiva_monto']).replace('.', ','),
            str(m['rteica_pct']).replace('.', ','),
            str(m['rteica_monto']).replace('.', ','),
            str(m['total_ret']).replace('.', ','),
            str(m['neto']).replace('.', ','),
            m['notas'] or '',
            m['referencia_tipo'] or '',
            m['referencia_id'] or '',
            'Sí' if m['auto_generado'] else 'No',
        ])

    output.seek(0)
    filename = f"contabilidad_{date.today().strftime('%Y%m%d')}.csv"
    return Response(
        '\ufeff' + output.getvalue(),   # BOM para que Excel abra bien
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# ─────────────────────────────────────────────────────────
# PLANTILLAS (GASTOS/INGRESOS RECURRENTES)
# ─────────────────────────────────────────────────────────

@contabilidad_bp.route('/admin/contabilidad/plantillas', methods=['GET', 'POST'])
@rol_requerido(ADMIN_CONTADOR)
def plantillas():
    datosApp = get_data_app()

    if request.method == 'POST':
        tipo        = request.form.get('tipo', '').strip()
        categoria   = request.form.get('categoria', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        notas       = request.form.get('notas', '').strip()

        try:
            bruto = float(request.form.get('monto_bruto', '0').replace(',', '.'))
            if bruto <= 0:
                raise ValueError
        except ValueError:
            flash('El monto debe ser mayor a cero.', 'error')
            return redirect(url_for('contabilidad.plantillas'))

        if tipo not in ('ingreso', 'egreso') or not descripcion:
            flash('Tipo y descripción son obligatorios.', 'error')
            return redirect(url_for('contabilidad.plantillas'))

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO contabilidad_plantillas
                        (tipo, categoria, descripcion, monto_bruto, notas)
                    VALUES (%s, %s, %s, %s, %s)
                """, (tipo, categoria, descripcion, bruto, notas or None))
            flash('Plantilla creada. Aparecerá en la próxima generación mensual.', 'success')
        except Exception as e:
            app.logger.error(f"Error creando plantilla: {e}")
            flash('Error al crear la plantilla.', 'error')

        return redirect(url_for('contabilidad.plantillas'))

    lista = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT * FROM contabilidad_plantillas
                ORDER BY tipo DESC, categoria, descripcion
            """)
            lista = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando plantillas: {e}")
        flash('No se pudieron cargar las plantillas. Verifica la base de datos.', 'warning')

    return render_template('contabilidad_plantillas.html',
                           datosApp=datosApp, plantillas=lista,
                           categorias_ingreso=CATEGORIAS_INGRESO,
                           categorias_egreso=CATEGORIAS_EGRESO,
                           label_cat=_label)


@contabilidad_bp.route('/admin/contabilidad/plantillas/<int:p_id>/eliminar', methods=['POST'])
@rol_requerido(ADMIN_CONTADOR)
def eliminar_plantilla(p_id):
    try:
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM contabilidad_plantillas WHERE id = %s", (p_id,))
        flash('Plantilla eliminada.', 'success')
    except Exception as e:
        app.logger.error(f"Error eliminando plantilla {p_id}: {e}")
        flash('Error al eliminar la plantilla.', 'error')
    return redirect(url_for('contabilidad.plantillas'))


@contabilidad_bp.route('/admin/contabilidad/plantillas/<int:p_id>/toggle', methods=['POST'])
@rol_requerido(ADMIN_CONTADOR)
def toggle_plantilla(p_id):
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                UPDATE contabilidad_plantillas SET activo = NOT activo WHERE id = %s
                RETURNING activo
            """, (p_id,))
            row = cur.fetchone()
            estado = 'activada' if (row and row['activo']) else 'desactivada'
        flash(f'Plantilla {estado}.', 'success')
    except Exception as e:
        app.logger.error(f"Error toggling plantilla {p_id}: {e}")
        flash('Error al actualizar la plantilla.', 'error')
    return redirect(url_for('contabilidad.plantillas'))


@contabilidad_bp.route('/admin/contabilidad/plantillas/generar', methods=['POST'])
@rol_requerido(ADMIN_CONTADOR)
def generar_desde_plantillas():
    """Genera movimientos del mes actual desde plantillas activas. Evita duplicados."""
    hoy     = date.today()
    mes_ini = hoy.replace(day=1)
    mes_fin = _mes_fin(hoy)

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM contabilidad_plantillas WHERE activo = TRUE")
            activas = cur.fetchall()

        if not activas:
            flash('No hay plantillas activas configuradas.', 'warning')
            return redirect(url_for('contabilidad.plantillas'))

        generados   = 0
        ya_existian = 0

        for p in activas:
            # Anti-duplicado: ¿ya se generó esta plantilla este mes?
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("""
                    SELECT id FROM contabilidad_movimientos
                    WHERE referencia_tipo = 'plantilla'
                      AND referencia_id   = %s
                      AND fecha BETWEEN %s AND %s
                    LIMIT 1
                """, (p['id'], mes_ini, mes_fin))
                if cur.fetchone():
                    ya_existian += 1
                    continue

                # Insertar — auto_generado=FALSE para poder editar/borrar
                cur.execute("""
                    INSERT INTO contabilidad_movimientos
                        (tipo, categoria, descripcion, monto_bruto, monto, fecha,
                         notas, referencia_tipo, referencia_id, usuario_id, auto_generado)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'plantilla', %s, %s, FALSE)
                """, (p['tipo'], p['categoria'], p['descripcion'],
                      p['monto_bruto'], p['monto_bruto'],
                      hoy,
                      p['notas'] or None,
                      p['id'],
                      session.get('usuario_id')))
                generados += 1

        if generados == 0 and ya_existian > 0:
            flash(f'Todos los movimientos de este mes ya estaban registrados ({ya_existian}).', 'info')
        else:
            msg = f'{generados} movimiento{"s" if generados != 1 else ""} generado{"s" if generados != 1 else ""} para {hoy.strftime("%B %Y").capitalize()}'
            if ya_existian:
                msg += f' ({ya_existian} ya existían)'
            flash(msg + '.', 'success')

    except Exception as e:
        app.logger.error(f"Error generando desde plantillas: {e}")
        flash('Error al generar los movimientos. Verifica la base de datos.', 'error')

    return redirect(url_for('contabilidad.plantillas'))


# ─────────────────────────────────────────────────────────
# CIERRES
# ─────────────────────────────────────────────────────────

@contabilidad_bp.route('/admin/contabilidad/cierres')
@rol_requerido(ADMIN_CONTADOR)
def cierres():
    datosApp = get_data_app()
    lista = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT c.*, u.nombre AS usuario_nombre
                FROM contabilidad_cierres c
                LEFT JOIN usuarios u ON u.id = c.usuario_id
                ORDER BY c.fecha_fin DESC
            """)
            lista = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando cierres: {e}")
    return render_template('contabilidad_cierres.html', datosApp=datosApp, cierres=lista)


@contabilidad_bp.route('/admin/contabilidad/cierres/nuevo', methods=['POST'])
@rol_requerido(ADMIN_CONTADOR)
def nuevo_cierre():
    nombre     = request.form.get('nombre', '').strip()
    fecha_ini  = request.form.get('fecha_inicio', '')
    fecha_fin  = request.form.get('fecha_fin', '')
    notas      = request.form.get('notas', '').strip()
    usuario_id = session.get('usuario_id')

    if not nombre or not fecha_ini or not fecha_fin:
        flash('Nombre y rango de fechas son obligatorios.', 'error')
        return redirect(url_for('contabilidad.cierres'))

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto             ELSE 0 END),0) AS ing,
                    COALESCE(SUM(CASE WHEN tipo='egreso'  THEN monto             ELSE 0 END),0) AS egr,
                    COALESCE(SUM(CASE WHEN tipo='ingreso' THEN total_retenciones ELSE 0 END),0) AS ret,
                    COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto_bruto       ELSE 0 END),0) AS bruto
                FROM contabilidad_movimientos
                WHERE fecha BETWEEN %s AND %s
            """, (fecha_ini, fecha_fin))
            row = cur.fetchone()
            ing   = float(row['ing'])
            egr   = float(row['egr'])
            ret   = float(row['ret'])
            bruto = float(row['bruto'])
            sal   = ing - egr

            cur.execute("""
                INSERT INTO contabilidad_cierres
                    (nombre, fecha_inicio, fecha_fin,
                     total_ingresos, total_egresos, total_retenciones, saldo,
                     notas, usuario_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (nombre, fecha_ini, fecha_fin, ing, egr, ret, sal, notas or None, usuario_id))

        flash(
            f'Cierre "{nombre}" — '
            f'Bruto: ${bruto:,.0f} | Retenciones: ${ret:,.0f} | '
            f'Ingresos netos: ${ing:,.0f} | Egresos: ${egr:,.0f} | '
            f'Saldo: ${sal:,.0f}',
            'success'
        )
    except Exception as e:
        app.logger.error(f"Error creando cierre: {e}")
        flash('Error al crear el cierre.', 'error')
    return redirect(url_for('contabilidad.cierres'))


@contabilidad_bp.route('/admin/contabilidad/cierres/<int:cierre_id>/eliminar', methods=['POST'])
@rol_requerido(ADMIN_CONTADOR)
def eliminar_cierre(cierre_id):
    try:
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM contabilidad_cierres WHERE id=%s", (cierre_id,))
        flash('Cierre eliminado.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'error')
    return redirect(url_for('contabilidad.cierres'))
