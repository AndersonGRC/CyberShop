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
    carrito_json = request.args.get('carrito')
    if carrito_json:
        try:
            session['carritoPendiente'] = json.loads(carrito_json)
        except Exception as e:
            app.logger.warning(f"Error parsing cart: {e}")

    carrito = session.get('carritoPendiente', {'items': [], 'total': 0})

    if 'total' not in carrito or carrito['total'] == 0:
        try:
            carrito['total'] = sum(float(item.get('precio', 0)) * int(item.get('cantidad', 1)) for item in carrito['items'])
        except Exception:
            carrito['total'] = 0

    datosApp = get_common_data()
    return render_template('metodos_pago.html', datosApp=datosApp, carrito=carrito)


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

    carrito = session.get('carritoPendiente', {})
    if not carrito or not carrito.get('items'):
        flash("Tu carrito está vacío o ha expirado.", "error")
        return redirect(url_for('public.productos'))

    total_amount = carrito.get('total', 0)
    referencia = generar_reference_code()

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pedidos
            (referencia_pedido, cliente_nombre, cliente_email,
             cliente_tipo_documento, cliente_documento, cliente_telefono,
             direccion_envio, ciudad, monto_total, estado_pago, estado_envio)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDIENTE', 'ESPERA_PAGO')
            RETURNING id
        """, (referencia, nombre, email, tipo_doc, documento, telefono, direccion, ciudad, total_amount))

        pedido_id_generado = cur.fetchone()[0]

        # Validar stock primero
        for item in carrito['items']:
            prod_nombre = item.get('nombre')
            cantidad = int(item.get('cantidad', 1))
            cur.execute("SELECT stock FROM productos WHERE nombre = %s", (prod_nombre,))
            res = cur.fetchone()
            if not res or res[0] < cantidad:
                conn.rollback()
                flash(f"No hay suficiente stock para el producto {prod_nombre}", "error")
                return redirect(url_for('public.carrito'))

        for item in carrito['items']:
            prod_nombre = item.get('nombre')
            cantidad = int(item.get('cantidad', 1))
            precio = float(item.get('precio', 0))
            subtotal = precio * cantidad
            cur.execute("""
                INSERT INTO detalle_pedidos (pedido_id, producto_nombre, cantidad, precio_unitario, subtotal)
                VALUES (%s, %s, %s, %s, %s)
            """, (pedido_id_generado, prod_nombre, cantidad, precio, subtotal))

            # Actualizar stock
            cur.execute("UPDATE productos SET stock = stock - %s WHERE nombre = %s", (cantidad, prod_nombre))
            
            # Registrar en log de inventario (VENTA)
            # Primero obtener ID y stock actual/nuevo para el log
            cur.execute("SELECT id, stock FROM productos WHERE nombre = %s", (prod_nombre,))
            res_prod = cur.fetchone()
            if res_prod:
                pid = res_prod[0]
                stock_current = res_prod[1] # Ya esta actualizado
                stock_before = stock_current + cantidad
                
                # Usuario NULL o sistema (podriamos usar un ID fijo para 'Web')
                cur.execute("""
                    INSERT INTO inventario_log (producto_id, tipo, cantidad, stock_anterior, stock_nuevo, motivo, fecha)
                    VALUES (%s, 'VENTA', %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (pid, cantidad, stock_before, stock_current, f"Pedido {referencia}"))

        conn.commit()
        cur.close()
        conn.close()

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

        if sign_local != sign_received:
            app.logger.warning("Firma inválida en confirmación PayU")

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
        cur.execute("""
            UPDATE pedidos
            SET estado_pago = %s, id_transaccion_payu = %s, metodo_pago = %s, estado_envio = %s
            WHERE referencia_pedido = %s
        """, (estado_bd, transaccion_id, metodo, estado_envio_bd, reference_sale))
        conn.commit()
        cur.close()
        conn.close()
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
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE pedidos
            SET estado_pago = %s, id_transaccion_payu = %s, metodo_pago = %s, estado_envio = %s
            WHERE referencia_pedido = %s
        """, (estado_bd, transaccion_id, metodo, estado_envio_bd, referencia))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        app.logger.error(f"Error BD Respuesta: {e}")

    return render_template('respuesta_pago.html', datosApp=datosApp, datos=datos_comprobante)


@payments_bp.route('/procesar-carrito', methods=['POST'])
def procesar_carrito():
    """Recibe el carrito desde el frontend (JSON) y lo guarda en la sesion."""
    try:
        data = request.get_json()
        session['carritoPendiente'] = data
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@payments_bp.route('/debug-session')
def debug_session():
    """Endpoint de depuracion para ver el contenido de la sesion."""
    return jsonify({
        'carritoPendiente': session.get('carritoPendiente'),
        'session_keys': list(session.keys())
    })
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
