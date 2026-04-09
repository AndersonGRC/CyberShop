"""
routes/cupones.py — Blueprint de gestion de cupones de descuento.

Rutas admin: CRUD de cupones.
Ruta publica: validacion AJAX de codigo de cupon.
"""

from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask import current_app as app

from database import get_db_cursor
from helpers import get_data_app
from security import rol_requerido, ADMIN_STAFF

cupones_bp = Blueprint('cupones', __name__)


# ─────────────────────────────────────────────────────────
# Admin CRUD
# ─────────────────────────────────────────────────────────

@cupones_bp.route('/admin/cupones')
@rol_requerido(ADMIN_STAFF)
def gestion_cupones():
    """Lista todos los cupones con filtro por estado."""
    datosApp = get_data_app()
    filtro = request.args.get('filtro', 'todos')
    cupones = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            if filtro == 'activo':
                cur.execute("SELECT * FROM cupones WHERE estado = 'activo' ORDER BY fecha_creacion DESC")
            elif filtro == 'inactivo':
                cur.execute("SELECT * FROM cupones WHERE estado = 'inactivo' ORDER BY fecha_creacion DESC")
            elif filtro == 'agotado':
                cur.execute("SELECT * FROM cupones WHERE estado = 'agotado' ORDER BY fecha_creacion DESC")
            else:
                cur.execute("SELECT * FROM cupones ORDER BY fecha_creacion DESC")
            cupones = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error listando cupones: {e}")
    return render_template('gestion_cupones.html', datosApp=datosApp, cupones=cupones, filtro=filtro)


@cupones_bp.route('/admin/cupones/crear', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def crear_cupon():
    """Formulario para crear un nuevo cupon."""
    datosApp = get_data_app()
    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip().upper()
        descripcion = request.form.get('descripcion', '').strip()
        tipo = request.form.get('tipo')  # 'porcentaje' | 'monto_fijo'
        valor = request.form.get('valor', 0)
        minimo_orden = request.form.get('minimo_orden', 0) or 0
        maximo_descuento = request.form.get('maximo_descuento') or None
        limite_usos = request.form.get('limite_usos') or None
        fecha_inicio = request.form.get('fecha_inicio') or None
        fecha_fin = request.form.get('fecha_fin') or None

        if not codigo or not tipo or not valor:
            flash('Código, tipo y valor son obligatorios.', 'error')
            return render_template('cupon_form.html', datosApp=datosApp, cupon=None, modo='crear')

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    INSERT INTO cupones
                    (codigo, descripcion, tipo, valor, minimo_orden, maximo_descuento,
                     limite_usos, fecha_inicio, fecha_fin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (codigo, descripcion, tipo, valor, minimo_orden,
                      maximo_descuento, limite_usos, fecha_inicio, fecha_fin))
            flash(f'Cupón {codigo} creado exitosamente.', 'success')
            return redirect(url_for('cupones.gestion_cupones'))
        except Exception as e:
            if 'unique' in str(e).lower():
                flash(f'El código {codigo} ya existe.', 'error')
            else:
                app.logger.error(f"Error creando cupón: {e}")
                flash('Error al crear el cupón.', 'error')

    return render_template('cupon_form.html', datosApp=datosApp, cupon=None, modo='crear')


@cupones_bp.route('/admin/cupones/editar/<int:id>', methods=['GET', 'POST'])
@rol_requerido(ADMIN_STAFF)
def editar_cupon(id):
    """Formulario para editar un cupon existente."""
    datosApp = get_data_app()
    cupon = None
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM cupones WHERE id = %s", (id,))
            cupon = cur.fetchone()
    except Exception:
        pass

    if not cupon:
        flash('Cupón no encontrado.', 'error')
        return redirect(url_for('cupones.gestion_cupones'))

    if request.method == 'POST':
        codigo = request.form.get('codigo', '').strip().upper()
        descripcion = request.form.get('descripcion', '').strip()
        tipo = request.form.get('tipo')
        valor = request.form.get('valor', 0)
        minimo_orden = request.form.get('minimo_orden', 0) or 0
        maximo_descuento = request.form.get('maximo_descuento') or None
        limite_usos = request.form.get('limite_usos') or None
        estado = request.form.get('estado', 'activo')
        fecha_inicio = request.form.get('fecha_inicio') or None
        fecha_fin = request.form.get('fecha_fin') or None

        try:
            with get_db_cursor() as cur:
                cur.execute("""
                    UPDATE cupones SET
                        codigo = %s, descripcion = %s, tipo = %s, valor = %s,
                        minimo_orden = %s, maximo_descuento = %s, limite_usos = %s,
                        estado = %s, fecha_inicio = %s, fecha_fin = %s
                    WHERE id = %s
                """, (codigo, descripcion, tipo, valor, minimo_orden,
                      maximo_descuento, limite_usos, estado, fecha_inicio, fecha_fin, id))
            flash('Cupón actualizado.', 'success')
            return redirect(url_for('cupones.gestion_cupones'))
        except Exception as e:
            app.logger.error(f"Error editando cupón: {e}")
            flash('Error al actualizar el cupón.', 'error')

    return render_template('cupon_form.html', datosApp=datosApp, cupon=cupon, modo='editar')


@cupones_bp.route('/admin/cupones/eliminar/<int:id>', methods=['POST'])
@rol_requerido(ADMIN_STAFF)
def eliminar_cupon(id):
    """Elimina un cupon."""
    try:
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM cupones WHERE id = %s", (id,))
        flash('Cupón eliminado.', 'success')
    except Exception as e:
        app.logger.error(f"Error eliminando cupón: {e}")
        flash('Error al eliminar el cupón.', 'error')
    return redirect(url_for('cupones.gestion_cupones'))


# ─────────────────────────────────────────────────────────
# Validacion publica (AJAX)
# ─────────────────────────────────────────────────────────

def validar_cupon(codigo, subtotal):
    """Valida un cupon y retorna dict con info o None si invalido.

    Args:
        codigo: codigo del cupon
        subtotal: monto total del carrito antes de descuento

    Returns:
        dict con keys: id, codigo, tipo, valor, descuento_calculado
        o None si el cupon no es valido
    """
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM cupones WHERE codigo = %s", (codigo.upper(),))
            cupon = cur.fetchone()
    except Exception:
        return None

    if not cupon:
        return None

    if cupon['estado'] != 'activo':
        return None

    now = datetime.now()
    if cupon['fecha_inicio'] and now < cupon['fecha_inicio']:
        return None
    if cupon['fecha_fin'] and now > cupon['fecha_fin']:
        return None

    if cupon['limite_usos'] and cupon['usos_actual'] >= cupon['limite_usos']:
        return None

    if cupon['minimo_orden'] and float(subtotal) < float(cupon['minimo_orden']):
        return None

    descuento = calcular_descuento(cupon, subtotal)

    return {
        'id': cupon['id'],
        'codigo': cupon['codigo'],
        'tipo': cupon['tipo'],
        'valor': float(cupon['valor']),
        'descuento_calculado': descuento,
        'descripcion': cupon['descripcion'] or '',
    }


def calcular_descuento(cupon, subtotal):
    """Calcula el descuento segun tipo de cupon.

    Returns:
        float con el monto del descuento
    """
    subtotal = float(subtotal)
    valor = float(cupon['valor'])

    if cupon['tipo'] == 'porcentaje':
        descuento = subtotal * (valor / 100)
        if cupon['maximo_descuento']:
            descuento = min(descuento, float(cupon['maximo_descuento']))
    else:  # monto_fijo
        descuento = min(valor, subtotal)

    return round(descuento, 2)


def registrar_uso_cupon(cupon_id, pedido_id, usuario_id, descuento):
    """Registra el uso de un cupon e incrementa contador."""
    try:
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO cupones_uso (cupon_id, pedido_id, usuario_id, descuento_aplicado)
                VALUES (%s, %s, %s, %s)
            """, (cupon_id, pedido_id, usuario_id, descuento))
            cur.execute("""
                UPDATE cupones SET usos_actual = usos_actual + 1 WHERE id = %s
            """, (cupon_id,))
            # Agotar si alcanzó límite
            cur.execute("""
                UPDATE cupones SET estado = 'agotado'
                WHERE id = %s AND limite_usos IS NOT NULL AND usos_actual >= limite_usos
            """, (cupon_id,))
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Error registrando uso de cupón: {e}")


@cupones_bp.route('/api/validar-cupon', methods=['POST'])
def api_validar_cupon():
    """Endpoint AJAX para validar un cupon desde el frontend."""
    if not session.get('usuario_id'):
        return jsonify({'valid': False, 'error': 'Debes iniciar sesión.'}), 401

    data = request.get_json(silent=True) or {}
    codigo = data.get('codigo', '').strip()
    subtotal = data.get('subtotal', 0)

    if not codigo:
        return jsonify({'valid': False, 'error': 'Ingresa un código de cupón.'})

    resultado = validar_cupon(codigo, subtotal)
    if not resultado:
        return jsonify({'valid': False, 'error': 'Cupón inválido, expirado o no aplicable.'})

    from helpers import formatear_moneda
    return jsonify({
        'valid': True,
        'codigo': resultado['codigo'],
        'tipo': resultado['tipo'],
        'valor': resultado['valor'],
        'descuento': resultado['descuento_calculado'],
        'descuento_formateado': formatear_moneda(resultado['descuento_calculado']),
        'descripcion': resultado['descripcion'],
    })
