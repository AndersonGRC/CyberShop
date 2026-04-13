"""
routes/restaurant_tables.py - Modulo pluggable de mesas restaurante.

Separa:
 - Construccion del plano de mesas
 - Atencion operativa del salon
 - Reportes y anulaciones de ventas
"""

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask import current_app as app
from flask import session, flash

from helpers import get_data_app, get_data_restaurant_operator
from security import (
    ADMIN_STAFF,
    ADMIN_CONTADOR,
    ROL_SUPER_ADMIN,
    ROL_MESERO,
    ROL_CAJERO,
    RESTAURANT_OPERATIONAL,
    RESTAURANT_CHARGE,
    RESTAURANT_CANCEL,
    rol_requerido,
)
from services.restaurant_tables_service import (
    ACCOUNTING_STATUSES,
    CONSUMPTION_STATES,
    PAYMENT_METHODS,
    TABLE_STATES,
    add_consumption,
    cancel_closed_order,
    cancel_open_table_order,
    close_table_order,
    delete_table_layout,
    get_product_catalog,
    list_floor_tables,
    list_restaurant_reports,
    update_consumption_state,
    update_table_state,
    upsert_table_layout,
)
from tenant_features import (
    MODULE_RESTAURANT_TABLES,
    list_modules_for_tenant,
    list_tenants,
    module_required,
    set_tenant_module_state,
)

restaurant_tables_bp = Blueprint('restaurant_tables', __name__)
# Acceso de lectura general (constructor, reportes): staff + contador
RESTAURANT_ACCESS = ADMIN_STAFF + [role for role in ADMIN_CONTADOR if role not in ADMIN_STAFF]
# Acceso operativo (atender mesas, tomar pedidos): incluye mesero y cajero
RESTAURANT_SERVICE_ACCESS = list(set(RESTAURANT_ACCESS + RESTAURANT_OPERATIONAL))


def _json_error(message, status=400):
    return jsonify({'success': False, 'error': message}), status


def _serialize_products():
    products = []
    for item in get_product_catalog():
        product = dict(item)
        product['precio'] = float(product.get('precio') or 0)
        product['stock'] = int(product.get('stock') or 0)
        products.append(product)
    return products


def _restaurant_context(*, view_mode, page_title, page_description, area=None, report_filters=None):
    current_role = session.get('rol_id')
    if current_role in (ROL_MESERO, ROL_CAJERO):
        datosApp = get_data_restaurant_operator(can_view_reports=current_role != ROL_MESERO)
    else:
        datosApp = get_data_app()

    floor_data = list_floor_tables(area=area)
    report_data = None
    if view_mode == 'reports':
        report_data = list_restaurant_reports(report_filters or request.args.to_dict())

    return {
        'datosApp': datosApp,
        'floor_data': floor_data,
        'products': _serialize_products() if view_mode == 'service' else [],
        'table_states': TABLE_STATES,
        'consumption_states': CONSUMPTION_STATES,
        'payment_methods': PAYMENT_METHODS,
        'accounting_statuses': ACCOUNTING_STATUSES,
        'report_data': report_data,
        'view_mode': view_mode,
        'page_title': page_title,
        'page_description': page_description,
        'current_user_role': current_role,
        'can_charge_tables': current_role in RESTAURANT_CHARGE,
        'can_cancel_tables': current_role in RESTAURANT_CANCEL,
        'is_waiter_only': current_role == ROL_MESERO,
}


@restaurant_tables_bp.route('/admin/restaurante/panel')
@rol_requerido(RESTAURANT_SERVICE_ACCESS)
@module_required(MODULE_RESTAURANT_TABLES)
def waiter_panel():
    current_role = session.get('rol_id')
    return render_template(
        'restaurant_waiter_panel.html',
        datosApp=get_data_restaurant_operator(can_view_reports=current_role != ROL_MESERO),
        page_title='Panel Operativo',
        page_description='Accesos rápidos para atender mesas, cobrar cuentas y continuar el turno.',
        can_view_reports=current_role != ROL_MESERO,
    )


@restaurant_tables_bp.route('/admin/restaurante/mesas')
@rol_requerido(RESTAURANT_SERVICE_ACCESS)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_tables_dashboard():
    current_role = session.get('rol_id')
    if current_role in (ROL_MESERO, ROL_CAJERO):
        return redirect(url_for('restaurant_tables.waiter_panel'))
    return redirect(url_for('restaurant_tables.restaurant_tables_service'))


@restaurant_tables_bp.route('/admin/restaurante/mesas/construccion')
@rol_requerido(RESTAURANT_ACCESS)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_tables_builder():
    return render_template(
        'restaurant_tables.html',
        **_restaurant_context(
            view_mode='builder',
            page_title='Constructor de Mesas',
            page_description='Crea el plano del restaurante con presets rápidos, click para ubicar y arrastre con snap a grilla.',
            area=request.args.get('area', '').strip() or None,
        ),
    )


@restaurant_tables_bp.route('/admin/restaurante/mesas/atencion')
@rol_requerido(RESTAURANT_SERVICE_ACCESS)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_tables_service():
    return render_template(
        'restaurant_tables.html',
        **_restaurant_context(
            view_mode='service',
            page_title='Atender Mesas',
            page_description='Toca una mesa para ver su cuenta, agregar platos y cobrar.',
            area=request.args.get('area', '').strip() or None,
        ),
    )


@restaurant_tables_bp.route('/admin/restaurante/mesas/reportes')
@rol_requerido(RESTAURANT_ACCESS)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_tables_reports():
    try:
        context = _restaurant_context(
            view_mode='reports',
            page_title='Reportes de Mesas',
            page_description='Consulta ventas cerradas, anulaciones, sincronización contable y desempeño operativo por mesa.',
            report_filters=request.args.to_dict(),
        )
    except Exception as exc:
        flash(str(exc), 'error')
        return redirect(url_for('restaurant_tables.restaurant_tables_reports'))

    return render_template('restaurant_tables.html', **context)


@restaurant_tables_bp.route('/admin/restaurante/mesas/data')
@rol_requerido(RESTAURANT_SERVICE_ACCESS)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_tables_data():
    return jsonify({
        'success': True,
        **list_floor_tables(area=request.args.get('area', '').strip() or None),
    })


@restaurant_tables_bp.route('/admin/restaurante/mesas/layout', methods=['POST'])
@rol_requerido(RESTAURANT_ACCESS)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_tables_layout_save():
    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        table_id = upsert_table_layout(session.get('usuario_id'), payload)
        return jsonify({'success': True, 'table_id': table_id})
    except Exception as exc:
        app.logger.error(f'Error guardando layout de mesas: {exc}')
        return _json_error(str(exc), 400)


@restaurant_tables_bp.route('/admin/restaurante/mesas/<int:table_id>', methods=['DELETE'])
@rol_requerido(RESTAURANT_ACCESS)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_tables_layout_delete(table_id):
    try:
        result = delete_table_layout(table_id)
        return jsonify({'success': True, **result})
    except Exception as exc:
        app.logger.error(f'Error eliminando mesa del layout: {exc}')
        return _json_error(str(exc), 400)


@restaurant_tables_bp.route('/admin/restaurante/mesas/<int:table_id>/estado', methods=['POST'])
@rol_requerido(RESTAURANT_OPERATIONAL)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_table_state_change(table_id):
    payload = request.get_json(silent=True) or request.form.to_dict()
    nuevo_estado = (payload.get('estado') or '').strip()
    if nuevo_estado == 'libre' and session.get('rol_id') not in RESTAURANT_CANCEL:
        return _json_error('Solo un cajero o administrador puede liberar mesas.', 403)
    try:
        update_table_state(table_id, nuevo_estado)
        return jsonify({'success': True})
    except Exception as exc:
        return _json_error(str(exc), 400)


@restaurant_tables_bp.route('/admin/restaurante/mesas/<int:table_id>/consumos', methods=['POST'])
@rol_requerido(RESTAURANT_OPERATIONAL)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_table_add_consumption(table_id):
    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        result = add_consumption(session.get('usuario_id'), table_id, payload)
        return jsonify({'success': True, **result})
    except Exception as exc:
        return _json_error(str(exc), 400)


@restaurant_tables_bp.route('/admin/restaurante/consumos/<int:consumption_id>/estado', methods=['POST'])
@rol_requerido(RESTAURANT_OPERATIONAL)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_consumption_state_change(consumption_id):
    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        total = update_consumption_state(
            consumption_id,
            (payload.get('estado') or '').strip(),
        )
        return jsonify({'success': True, 'total_acumulado': total})
    except Exception as exc:
        return _json_error(str(exc), 400)


@restaurant_tables_bp.route('/admin/restaurante/mesas/<int:table_id>/cerrar', methods=['POST'])
@rol_requerido(RESTAURANT_CHARGE)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_table_close(table_id):
    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        result = close_table_order(session.get('usuario_id'), table_id, payload)
        return jsonify({'success': True, **result})
    except Exception as exc:
        return _json_error(str(exc), 400)


@restaurant_tables_bp.route('/admin/restaurante/mesas/<int:table_id>/cancelar', methods=['POST'])
@rol_requerido(RESTAURANT_CANCEL)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_table_cancel_open(table_id):
    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        result = cancel_open_table_order(session.get('usuario_id'), table_id, payload)
        return jsonify({'success': True, **result})
    except Exception as exc:
        return _json_error(str(exc), 400)


@restaurant_tables_bp.route('/admin/restaurante/ordenes/<int:order_id>/anular', methods=['POST'])
@rol_requerido(RESTAURANT_CANCEL)
@module_required(MODULE_RESTAURANT_TABLES)
def restaurant_closed_order_cancel(order_id):
    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        result = cancel_closed_order(session.get('usuario_id'), order_id, payload)
        return jsonify({'success': True, **result})
    except Exception as exc:
        return _json_error(str(exc), 400)


@restaurant_tables_bp.route('/admin/saas/modulos')
@rol_requerido(ROL_SUPER_ADMIN)
def saas_modules_admin():
    datosApp = get_data_app()
    tenants = list_tenants()
    if not tenants:
        return render_template(
            'tenant_modules.html',
            datosApp=datosApp,
            tenants=[],
            modules=[],
            selected_tenant_id=None,
        )

    try:
        requested_tenant_id = int(request.args.get('tenant_id') or tenants[0]['id'])
    except (TypeError, ValueError):
        requested_tenant_id = tenants[0]['id']

    modules = list_modules_for_tenant(requested_tenant_id)
    return render_template(
        'tenant_modules.html',
        datosApp=datosApp,
        tenants=tenants,
        modules=modules,
        selected_tenant_id=requested_tenant_id,
    )


@restaurant_tables_bp.route('/admin/saas/modulos/<int:tenant_id>', methods=['POST'])
@rol_requerido(ROL_SUPER_ADMIN)
def saas_modules_admin_save(tenant_id):
    modules = list_modules_for_tenant(tenant_id)
    if not modules:
        flash('No fue posible cargar módulos para el tenant seleccionado.', 'error')
        return redirect(url_for('restaurant_tables.saas_modules_admin', tenant_id=tenant_id))

    updated = 0
    for module in modules:
        desired_state = request.form.get(f'module_{module["code"]}') == 'true'
        if set_tenant_module_state(tenant_id, module['code'], desired_state):
            updated += 1

    flash(f'Suscripción actualizada. Módulos procesados: {updated}.', 'success')
    return redirect(url_for('restaurant_tables.saas_modules_admin', tenant_id=tenant_id))
