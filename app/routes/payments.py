"""
routes/payments.py — Blueprint de pagos y procesamiento de ordenes.

Maneja todo el flujo de checkout: seleccion de metodo de pago,
creacion de orden en BD, redireccion a PayU, confirmacion webhook
y pagina de respuesta con polling automatico.
"""

import hashlib
import json
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import requests
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from flask import current_app as app

from database import get_db_connection, get_db_cursor
from helpers import get_common_data, generar_reference_code
payments_bp = Blueprint('payments', __name__)


_COLUMN_EXISTS_CACHE = {}


def _table_has_column(table_name, column_name):
    cache_key = (table_name, column_name)
    if cache_key in _COLUMN_EXISTS_CACHE:
        return _COLUMN_EXISTS_CACHE[cache_key]

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = %s
                LIMIT 1
            """, (table_name, column_name))
            exists = cur.fetchone() is not None
    except Exception:
        exists = False

    _COLUMN_EXISTS_CACHE[cache_key] = exists
    return exists


def _parse_facturar_electronicamente(value, default=False):
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in ('', 'none', 'null'):
        return default
    return normalized in ('1', 'true', 'si', 'sí', 'on', 'yes')


def csrf_exempt(f):
    """Marca una vista como exenta de protección CSRF."""
    f.csrf_exempt = True
    return f


def consultar_estado_real_payu(referencia):
    """Consulta el estado real de una transaccion en la API de reportes PayU.

    Realiza un POST al endpoint de reportes con el codigo de referencia
    y traduce el estado PayU a un codigo numerico interno.

    Args:
        referencia: Codigo de referencia del pedido (CYBERSHOP-...).

    Returns:
        String con el codigo de estado: '4' (aprobado), '6' (rechazado),
        '5' (expirado), '7' (pendiente/error).
    """
    try:
        is_sandbox = app.config.get('PAYU_ENV') == 'sandbox'
        url = "https://sandbox.api.payulatam.com/reports-api/4.0/service.cgi" if is_sandbox else "https://api.payulatam.com/reports-api/4.0/service.cgi"

        payload = {
            "test": is_sandbox,
            "language": "es",
            "command": "ORDER_DETAIL_BY_REFERENCE_CODE",
            "merchant": {
                "apiLogin": app.config['PAYU_API_LOGIN'],
                "apiKey": app.config['PAYU_API_KEY']
            },
            "details": {"referenceCode": referencia}
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        data = response.json()

        if data.get('code') == 'SUCCESS' and data.get('result'):
            payload_result = data['result'].get('payload')
            if payload_result:
                tx = payload_result[0]['transactions'][0]
                estado_payu = tx['transactionResponse']['state']
                mapa = {'APPROVED': '4', 'DECLINED': '6', 'EXPIRED': '5', 'PENDING': '7'}
                return mapa.get(estado_payu, '7')
    except Exception as e:
        app.logger.error(f"Error en Polling PayU: {e}")
    return '7'


@payments_bp.route('/metodos-pago')
def metodos_pago():
    """Muestra los metodos de pago disponibles con el resumen del carrito."""
    # Requerir autenticacion como cliente antes de continuar con la compra
    if not session.get('usuario_id'):
        session['login_next'] = url_for('payments.metodos_pago')
        flash('Inicia sesión o regístrate para continuar con tu compra.', 'info')
        return redirect(url_for('auth.login'))

    carrito = session.get('carritoPendiente', {'items': [], 'total': 0})

    # El frontend (Shoppingcar.js) solo envia id/cantidad por seguridad; aqui
    # enriquecemos cada item con el precio real desde BD para poder renderizar
    # el resumen en metodos_pago.html sin confiar en datos del cliente.
    try:
        items = carrito.get('items', []) or []
        ids_consultar = [int(i['id']) for i in items if i.get('id')]
        precios_bd = {}
        if ids_consultar:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute(
                    "SELECT id, precio FROM productos WHERE id = ANY(%s)",
                    (ids_consultar,)
                )
                precios_bd = {row['id']: float(row['precio']) for row in cur.fetchall()}

        total = 0
        for item in items:
            prod_id = item.get('id')
            cantidad = int(item.get('cantidad', 1) or 1)
            precio = precios_bd.get(int(prod_id), 0) if prod_id else float(item.get('precio', 0) or 0)
            item['precio'] = precio
            item['cantidad'] = cantidad
            total += precio * cantidad
        carrito['total'] = total
    except Exception as _e:
        app.logger.warning(f"Error enriqueciendo carrito en metodos_pago: {_e}")
        carrito.setdefault('total', 0)

    # Cargar datos del usuario para pre-llenar el formulario
    usuario = None
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                'SELECT nombre, email, telefono, direccion FROM usuarios WHERE id = %s',
                (session['usuario_id'],)
            )
            usuario = cur.fetchone()
    except Exception:
        pass

    datosApp = get_common_data()
    return render_template('metodos_pago.html', datosApp=datosApp, carrito=carrito, usuario=usuario)


@payments_bp.route('/crear-orden', methods=['POST'])
def crear_orden():
    """Crea una orden en la BD y redirige al gateway PayU.

    Lee los datos del comprador del formulario, inserta el pedido
    y sus detalles en la base de datos, genera la firma MD5 y
    renderiza el formulario de redireccion automatica a PayU.
    """
    nombre = request.form.get('buyerFullName')
    email = request.form.get('buyerEmail')
    tipo_doc = request.form.get('payerDocumentType')
    documento = request.form.get('payerDocument')
    telefono = request.form.get('buyerPhone')
    direccion = request.form.get('shippingAddress')
    ciudad = request.form.get('shippingCity')
    facturar_electronicamente = _parse_facturar_electronicamente(
        request.form.get('facturar_electronicamente'),
        default=False,
    )

    carrito = session.get('carritoPendiente', {})
    if not carrito or not carrito.get('items'):
        flash("Tu carrito está vacío o ha expirado.", "error")
        return redirect(url_for('public.productos'))

    referencia = generar_reference_code()

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # SECURITY C1+M4: Validar precios desde BD (nunca confiar en el cliente)
        # y bloquear filas con FOR UPDATE para prevenir race conditions de stock.
        total_calculado = 0
        items_validados = []

        for item in carrito['items']:
            prod_id   = item.get('id')
            prod_nombre = item.get('nombre', '')
            cantidad  = max(1, int(item.get('cantidad', 1)))

            if prod_id:
                cur.execute(
                    "SELECT id, nombre, precio, stock FROM productos WHERE id = %s FOR UPDATE",
                    (prod_id,)
                )
            else:
                cur.execute(
                    "SELECT id, nombre, precio, stock FROM productos WHERE nombre = %s FOR UPDATE",
                    (prod_nombre,)
                )
            prod_db = cur.fetchone()

            if not prod_db:
                conn.rollback()
                flash(f"Producto '{prod_nombre}' no encontrado.", "error")
                return redirect(url_for('public.carrito'))

            pid, nombre_db, precio_db, stock_db = prod_db

            if stock_db < cantidad:
                conn.rollback()
                flash(f"No hay suficiente stock para '{nombre_db}'.", "error")
                return redirect(url_for('public.carrito'))

            precio_real = float(precio_db)
            subtotal    = precio_real * cantidad
            total_calculado += subtotal
            items_validados.append({
                'id': pid, 'nombre': nombre_db,
                'precio': precio_real, 'cantidad': cantidad, 'subtotal': subtotal,
            })

        if total_calculado <= 0:
            conn.rollback()
            flash("El total del pedido no puede ser cero.", "error")
            return redirect(url_for('public.carrito'))

        # Aplicar cupón de descuento si existe
        cupon_id = None
        descuento_total = 0
        cupon_codigo = request.form.get('cupon_codigo', '').strip()
        if cupon_codigo:
            try:
                from routes.cupones import validar_cupon
                resultado_cupon = validar_cupon(cupon_codigo, total_calculado)
                if resultado_cupon:
                    cupon_id = resultado_cupon['id']
                    descuento_total = resultado_cupon['descuento_calculado']
            except Exception:
                pass

        total_amount = total_calculado - descuento_total

        order_columns = [
            'referencia_pedido', 'cliente_nombre', 'cliente_email',
            'cliente_tipo_documento', 'cliente_documento', 'cliente_telefono',
            'direccion_envio', 'ciudad', 'monto_total', 'estado_pago',
            'estado_envio'
        ]
        order_values = [
            referencia, nombre, email, tipo_doc, documento, telefono,
            direccion, ciudad, total_amount, 'PENDIENTE', 'ESPERA_PAGO'
        ]
        if _table_has_column('pedidos', 'cupon_id'):
            order_columns.append('cupon_id')
            order_values.append(cupon_id)
        if _table_has_column('pedidos', 'descuento_total'):
            order_columns.append('descuento_total')
            order_values.append(descuento_total)
        if _table_has_column('pedidos', 'facturar_electronicamente'):
            order_columns.append('facturar_electronicamente')
            order_values.append(facturar_electronicamente)

        cur.execute(f"""
            INSERT INTO pedidos ({", ".join(order_columns)})
            VALUES ({", ".join(["%s"] * len(order_columns))})
            RETURNING id
        """, tuple(order_values))

        pedido_id_generado = cur.fetchone()[0]

        for item in items_validados:
            cur.execute("""
                INSERT INTO detalle_pedidos (pedido_id, producto_nombre, cantidad, precio_unitario, subtotal)
                VALUES (%s, %s, %s, %s, %s)
            """, (pedido_id_generado, item['nombre'], item['cantidad'], item['precio'], item['subtotal']))

            cur.execute("UPDATE productos SET stock = stock - %s WHERE id = %s", (item['cantidad'], item['id']))

            cur.execute("SELECT stock FROM productos WHERE id = %s", (item['id'],))
            stock_nuevo = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO inventario_log (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, fecha)
                VALUES (%s, 'VENTA', %s, %s, %s, %s, CURRENT_TIMESTAMP)
            """, (item['id'], item['cantidad'], stock_nuevo + item['cantidad'], stock_nuevo, f"Pedido {referencia}"))

        conn.commit()
        cur.close()
        conn.close()

        # Registrar uso del cupón (fuera de la transacción principal)
        if cupon_id and descuento_total > 0:
            try:
                from routes.cupones import registrar_uso_cupon
                registrar_uso_cupon(cupon_id, pedido_id_generado, session.get('usuario_id'), descuento_total)
            except Exception as _ce:
                app.logger.warning(f"Error registrando uso cupón: {_ce}")

    except Exception as e:
        app.logger.error(f"Error BD Pedidos: {e}")
        flash("Error interno procesando pedido.", "error")
        return redirect(url_for('payments.metodos_pago'))

    merchant_id = app.config.get('PAYU_MERCHANT_ID')
    account_id = app.config.get('PAYU_ACCOUNT_ID', merchant_id)
    api_key = app.config.get('PAYU_API_KEY')
    payu_env = app.config.get('PAYU_ENV', 'sandbox')

    amount_dec = Decimal(total_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    amount_str = f"{amount_dec:.2f}"
    currency = 'COP'

    signature_raw = f"{api_key}~{merchant_id}~{referencia}~{amount_str}~{currency}"
    payu_signature = hashlib.md5(signature_raw.encode('utf-8')).hexdigest()

    payu_url = "https://sandbox.checkout.payulatam.com/ppp-web-gateway-payu/" if payu_env == "sandbox" else "https://checkout.payulatam.com/ppp-web-gateway-payu/"

    return render_template('redireccion_payu.html',
                           merchantId=merchant_id,
                           accountId=account_id,
                           description=f"Compra {referencia}",
                           referenceCode=referencia,
                           amount=amount_str,
                           currency=currency,
                           signature=payu_signature,
                           test="1" if payu_env == "sandbox" else "0",
                           buyerEmail=email,
                           buyerFullName=nombre,
                           payu_url=payu_url,
                           responseUrl=url_for('payments.respuesta_pago', _external=True),
                           confirmationUrl=url_for('payments.confirmacion_pago', _external=True))


@payments_bp.route('/confirmacion-pago', methods=['POST'])
@csrf_exempt
def confirmacion_pago():
    """Webhook de confirmacion de PayU (server-to-server).

    Recibe los datos de la transaccion, verifica la firma MD5
    y actualiza el estado del pedido en la base de datos.
    """
    try:
        data = request.form.to_dict()
        api_key = app.config.get('PAYU_API_KEY')
        merchant_id = data.get('merchant_id')
        reference_sale = data.get('reference_sale')
        value = data.get('value')
        currency = data.get('currency')
        state_pol = data.get('state_pol')
        sign_received = data.get('sign')

        try:
            val_dec = Decimal(value)
            if val_dec % 1 == 0:
                value_formatted = f"{val_dec:.1f}"
            else:
                if str(value).endswith('0') and '.' in str(value):
                    value_formatted = str(value).rstrip('0')
                else:
                    value_formatted = value
        except Exception:
            value_formatted = value

        msg = f"{api_key}~{merchant_id}~{reference_sale}~{value_formatted}~{currency}~{state_pol}"
        sign_local = hashlib.md5(msg.encode('utf-8')).hexdigest()

        # SECURITY C2: Rechazar webhook si la firma no coincide
        if sign_local != sign_received:
            app.logger.warning(f"Firma inválida en confirmación PayU para referencia {reference_sale}")
            return "Firma invalida", 400

        estado_bd = 'PENDIENTE'
        estado_envio_bd = 'ESPERA_PAGO'

        if state_pol == '4':
            estado_bd = 'APROBADO'
            estado_envio_bd = 'POR_DESPACHAR'
        elif state_pol in ['6', '5']:
            estado_bd = 'RECHAZADO' if state_pol == '6' else 'EXPIRADO'
            estado_envio_bd = 'CANCELADO'
            liberar_stock(reference_sale)

        transaccion_id = data.get('transaction_id')
        metodo = data.get('payment_method_name')

        conn = get_db_connection()
        cur = conn.cursor()

        # SECURITY M5: Verificar idempotencia — no procesar si ya fue APROBADO
        cur.execute("SELECT estado_pago FROM pedidos WHERE referencia_pedido = %s", (reference_sale,))
        row = cur.fetchone()
        if row and row[0] == 'APROBADO':
            cur.close()
            conn.close()
            app.logger.info(f"Webhook duplicado ignorado para referencia {reference_sale}")
            return "OK", 200

        cur.execute("""
            UPDATE pedidos
            SET estado_pago = %s, id_transaccion_payu = %s, metodo_pago = %s, estado_envio = %s
            WHERE referencia_pedido = %s
        """, (estado_bd, transaccion_id, metodo, estado_envio_bd, reference_sale))
        conn.commit()
        cur.close()
        conn.close()

        # Registrar en contabilidad si el pago fue aprobado
        if estado_bd == 'APROBADO':
            try:
                from routes.contabilidad import registrar_movimiento
                registrar_movimiento(
                    tipo='ingreso',
                    categoria='pedido_online',
                    descripcion=f"Pedido online {reference_sale}",
                    monto=float(value or 0),
                    referencia_tipo='pedido',
                    usuario_id=None,
                    auto_generado=True
                )
            except Exception as _e:
                app.logger.warning(f"Contabilidad confirmacion_pago: {_e}")

        # Notificación por email al cliente (solo si pago aprobado)
        if estado_bd == 'APROBADO':
            try:
                from helpers_email_templates import generar_email_confirmacion_pedido
                from helpers_gmail import enviar_email_gmail
                with get_db_cursor(dict_cursor=True) as _cur:
                    _cur.execute(
                        "SELECT * FROM pedidos WHERE referencia_pedido = %s",
                        (reference_sale,)
                    )
                    pedido_data = _cur.fetchone()
                    detalles_data = []
                    if pedido_data:
                        _cur.execute(
                            "SELECT * FROM detalle_pedidos WHERE pedido_id = %s",
                            (pedido_data['id'],)
                        )
                        detalles_data = _cur.fetchall()
                if pedido_data:
                    email_data = generar_email_confirmacion_pedido(pedido_data, detalles_data)
                    if email_data:
                        asunto, texto, html = email_data
                        enviar_email_gmail(pedido_data['cliente_email'], asunto, texto, html=html)
            except Exception as _ne:
                app.logger.warning(f"Email confirmación pedido: {_ne}")

        # Facturación electrónica automática (solo si módulo activo)
        if estado_bd == 'APROBADO':
            try:
                from routes.factura_electronica import emitir_factura_electronica, facturacion_habilitada
                if facturacion_habilitada():
                    with get_db_cursor(dict_cursor=True) as _cur:
                        if _table_has_column('pedidos', 'facturar_electronicamente'):
                            _cur.execute("""
                                SELECT id, COALESCE(facturar_electronicamente, FALSE) AS facturar_electronicamente
                                FROM pedidos
                                WHERE referencia_pedido = %s
                            """, (reference_sale,))
                        else:
                            _cur.execute("""
                                SELECT id, FALSE AS facturar_electronicamente
                                FROM pedidos
                                WHERE referencia_pedido = %s
                            """, (reference_sale,))
                        _row = _cur.fetchone()
                    if _row and _row['facturar_electronicamente']:
                        emitir_factura_electronica(_row['id'])
            except Exception as _fe:
                app.logger.warning(f"Facturación electrónica confirmacion_pago: {_fe}")

        return "OK", 200
    except Exception as e:
        app.logger.error(f"Error PayU Confirm: {e}")
        return "Error", 500


@payments_bp.route('/respuesta-pago')
def respuesta_pago():
    """Pagina de respuesta post-pago con polling automatico.

    Recibe los parametros de PayU via GET, consulta el estado real
    si esta pendiente (hasta 4 reintentos con 2s de espera), actualiza
    la BD y muestra el comprobante al usuario.
    """
    datosApp = get_common_data()
    estado_tx = request.args.get('transactionState')
    transaccion_id = request.args.get('transactionId')
    referencia = request.args.get('referenceCode')
    valor = request.args.get('TX_VALUE')
    moneda = request.args.get('currency')
    mensaje_pol = request.args.get('message')
    metodo = request.args.get('lapPaymentMethod')

    # Polling: 4 intentos (8 seg) si el estado es Pendiente
    if estado_tx == '7' or not estado_tx:
        for i in range(4):
            time.sleep(2)
            nuevo_estado = consultar_estado_real_payu(referencia)
            if nuevo_estado != '7':
                estado_tx = nuevo_estado
                if nuevo_estado == '6':
                    mensaje_pol = "Rechazada por entidad financiera"
                elif nuevo_estado == '4':
                    mensaje_pol = "Aprobada exitosamente"
                break

    estado_bd = 'PENDIENTE'
    estado_envio_bd = 'ESPERA_PAGO'
    datos_comprobante = {
        'estado': 'PENDIENTE', 'titulo': 'Validando Pago', 'id': transaccion_id,
        'referencia': referencia, 'monto': f"{valor} {moneda}", 'mensaje': mensaje_pol,
        'fecha': datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    if estado_tx == '4':
        estado_bd = 'APROBADO'
        estado_envio_bd = 'POR_DESPACHAR'
        datos_comprobante.update({'estado': 'APROBADO', 'titulo': '¡Transacción Exitosa!'})
        session.pop('carritoPendiente', None)
    elif estado_tx == '6':
        estado_bd = 'RECHAZADO'
        estado_envio_bd = 'CANCELADO'
        datos_comprobante.update({'estado': 'RECHAZADO', 'titulo': 'Transacción Rechazada'})
        liberar_stock(referencia)
    elif estado_tx == '7':
        datos_comprobante.update({'estado': 'PENDIENTE', 'titulo': 'Pago en Proceso'})
        session.pop('carritoPendiente', None)

    try:
        with get_db_cursor() as cur:
            cur.execute("""
                UPDATE pedidos
                SET estado_pago = %s, id_transaccion_payu = %s, metodo_pago = %s, estado_envio = %s
                WHERE referencia_pedido = %s AND estado_pago = 'PENDIENTE'
            """, (estado_bd, transaccion_id, metodo, estado_envio_bd, referencia))
    except Exception as e:
        app.logger.error(f"Error BD Respuesta: {e}")

    # Registrar en contabilidad si el pago fue aprobado
    if estado_bd == 'APROBADO':
        try:
            from routes.contabilidad import registrar_movimiento
            registrar_movimiento(
                tipo='ingreso',
                categoria='pedido_online',
                descripcion=f"Pedido online {referencia}",
                monto=float(valor or 0),
                referencia_tipo='pedido',
                usuario_id=session.get('usuario_id'),
                auto_generado=True
            )
        except Exception as _e:
            app.logger.warning(f"Contabilidad respuesta_pago: {_e}")

    return render_template('respuesta_pago.html', datosApp=datosApp, datos=datos_comprobante)


@payments_bp.route('/procesar-carrito', methods=['POST'])
@csrf_exempt
def procesar_carrito():
    """Recibe el carrito desde el frontend (JSON) y lo guarda en la sesion."""
    try:
        data = request.get_json()
        session['carritoPendiente'] = data
        return jsonify({"success": True})
    except Exception as e:
        app.logger.error(f"Error procesar_carrito: {e}")
        return jsonify({"success": False, "error": "Error interno"}), 500


def liberar_stock(referencia_pedido):
    """Devuelve el stock de los productos de un pedido cancelado/rechazado."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # Obtener items del pedido
            cur.execute("""
                SELECT dp.producto_nombre, dp.cantidad 
                FROM detalle_pedidos dp
                JOIN pedidos p ON dp.pedido_id = p.id
                WHERE p.referencia_pedido = %s
            """, (referencia_pedido,))
            items = cur.fetchall()
            
            for item in items:
                nombre = item['producto_nombre']
                cantidad = item['cantidad']
                
                # Devolver stock
                cur.execute("UPDATE productos SET stock = stock + %s WHERE nombre = %s", (cantidad, nombre))
                
                # Registrar log
                cur.execute("SELECT id, stock FROM productos WHERE nombre = %s", (nombre,))
                prod = cur.fetchone()
                if prod:
                    cur.execute("""
                        INSERT INTO inventario_log (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, fecha)
                        VALUES (%s, 'ENTRADA', %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    """, (prod['id'], cantidad, prod['stock'] - cantidad, prod['stock'], f"Liberación pedido {referencia_pedido}"))
                    
            app.logger.info(f"Stock liberado para pedido {referencia_pedido}")
    except Exception as e:
        app.logger.error(f"Error liberando stock: {e}")
