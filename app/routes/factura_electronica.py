"""
factura_electronica.py — Integración de CyberShop con el microservicio DIAN.

Este módulo es el único punto de contacto entre CyberShop y el microservicio
de facturación. NO contiene lógica tributaria ni XML — todo eso vive en
/var/www/FacturacionDIAN/.

Feature flag: el módulo solo opera si la configuración central de módulos lo
mantiene activo. Se conserva compatibilidad con cliente_config.facturacion_electronica.
Clientes sin el módulo contratado verán la ruta /admin/facturacion-dian bloqueada
y los flujos de pago NO intentarán facturar.

Uso desde payments.py (después de confirmar pago aprobado):
    from routes.factura_electronica import emitir_factura_electronica, facturacion_habilitada

    if facturacion_habilitada():
        resultado = emitir_factura_electronica(pedido_id)

Variables de entorno requeridas en .cybershop.conf:
    DIAN_SERVICE_URL=http://127.0.0.1:5003/api/v1
    DIAN_API_KEY=<api_key asignado al tenant CyberShop>
"""

import os
import logging
import requests
from database import get_db_cursor
from tenant_features import MODULE_FACTURACION_ELECTRONICA, is_module_active

logger = logging.getLogger(__name__)

DIAN_SERVICE_URL = os.getenv('DIAN_SERVICE_URL', 'http://127.0.0.1:5003/api/v1')
DIAN_API_KEY     = os.getenv('DIAN_API_KEY', '')

# Mapeo tipo de documento CyberShop → código DIAN
TIPO_DOC_MAP = {
    'CC':   'CC',
    'NIT':  'NIT',
    'CE':   'CE',
    'PASS': 'PA',
    'TI':   'TI',
    'RC':   'CC',   # fallback
}

# Mapeo método de pago CyberShop → código UBL 2.1
METODO_PAGO_MAP = {
    'CARD':         '48',   # Tarjeta crédito/débito
    'PSE':          '20',   # Transferencia bancaria (PSE)
    'CASH':         '10',   # Efectivo
    'EFECTIVO':     '10',
    'PAYU':         '48',   # PayU → tarjeta
    'CREDIT_CARD':  '48',
    'DEBIT_CARD':   '48',
    'TRANSFERENCIA': '20',
}

# Mapa de municipios Colombia (los más comunes)
# Si la ciudad no está en el mapa se usa Bogotá (11001) como fallback
MUNICIPIO_MAP = {
    'bogota': '11001', 'bogotá': '11001',
    'medellin': '05001', 'medellín': '05001',
    'cali': '76001',
    'barranquilla': '08001',
    'cartagena': '13001',
    'bucaramanga': '68001',
    'cucuta': '54001', 'cúcuta': '54001',
    'manizales': '17001',
    'pereira': '66001',
    'santa marta': '47001',
}


def facturacion_habilitada() -> bool:
    """Retorna True si el módulo de Facturación Electrónica está activo."""
    return is_module_active(MODULE_FACTURACION_ELECTRONICA)


def _municipio_codigo(ciudad: str) -> str:
    """Mapea nombre de ciudad al código de municipio DIAN. Bogotá por defecto."""
    if not ciudad:
        return '11001'
    return MUNICIPIO_MAP.get(ciudad.lower().strip(), '11001')


def construir_json_generico(pedido_id: int) -> dict | None:
    """
    Lee un pedido de CyberShop y lo convierte al formato JSON genérico
    esperado por el microservicio DIAN.

    Returns:
        Dict con la estructura del microservicio, o None si el pedido no existe.
    """
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """SELECT p.referencia_pedido,
                      p.cliente_nombre,
                      p.cliente_email,
                      p.cliente_tipo_documento,
                      p.cliente_documento,
                      p.cliente_telefono,
                      p.direccion_envio,
                      p.ciudad,
                      p.metodo_pago,
                      p.monto_total,
                      p.factura_dian_id
               FROM pedidos p
               WHERE p.id = %s""",
            (pedido_id,)
        )
        pedido = cur.fetchone()

        if not pedido:
            return None

        cur.execute(
            """SELECT dp.producto_nombre,
                      dp.cantidad,
                      dp.precio_unitario,
                      dp.subtotal
               FROM detalle_pedidos dp
               WHERE dp.pedido_id = %s
               ORDER BY dp.id""",
            (pedido_id,)
        )
        items_db = cur.fetchall()

    pedido = dict(pedido)

    tipo_doc = TIPO_DOC_MAP.get(
        str(pedido.get('cliente_tipo_documento') or 'CC').upper(), 'CC'
    )
    numero_doc = pedido.get('cliente_documento') or '0'

    items = []
    for item in items_db:
        item = dict(item)
        items.append({
            "descripcion":     item['producto_nombre'],
            "cantidad":        int(item['cantidad']),
            "precio_unitario": float(item['precio_unitario']),
            "descuento":       0,
            "codigo_unidad":   "EA",
            "impuesto_iva":    19,  # IVA estándar Colombia
        })

    metodo_pago = METODO_PAGO_MAP.get(
        str(pedido.get('metodo_pago', '')).upper(), '48'
    )

    return {
        "referencia_pedido": pedido['referencia_pedido'],
        "cliente": {
            "tipo_persona":     "natural",
            "tipo_documento":   tipo_doc,
            "numero_documento": numero_doc,
            "nombre":           pedido.get('cliente_nombre') or 'Consumidor Final',
            "email":            pedido.get('cliente_email') or '',
            "telefono":         pedido.get('cliente_telefono') or '',
            "direccion":        pedido.get('direccion_envio') or '',
            "municipio_codigo": _municipio_codigo(pedido.get('ciudad')),
        },
        "items":       items,
        "metodo_pago": metodo_pago,
        "moneda":      "COP",
        "notas":       f"Pedido CyberShop #{pedido_id}",
    }


def construir_json_pos(venta_id: int) -> dict | None:
    """
    Lee una venta POS y la convierte al formato JSON genérico esperado
    por el microservicio DIAN.

    Returns:
        Dict con la estructura del microservicio, o None si la venta no existe.
    """
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(
            """SELECT v.numero_venta,
                      v.cliente_nombre,
                      v.cliente_documento,
                      v.cliente_telefono,
                      v.metodo_pago,
                      v.total,
                      v.factura_dian_id
               FROM ventas_pos v
               WHERE v.id = %s""",
            (venta_id,)
        )
        venta = cur.fetchone()

        if not venta:
            return None

        cur.execute(
            """SELECT d.descripcion,
                      d.cantidad,
                      d.precio_unitario,
                      d.subtotal
               FROM detalle_venta_pos d
               WHERE d.venta_id = %s
               ORDER BY d.id""",
            (venta_id,)
        )
        items_db = cur.fetchall()

    venta = dict(venta)

    items = []
    for item in items_db:
        item = dict(item)
        items.append({
            "descripcion":     item['descripcion'],
            "cantidad":        int(item['cantidad']),
            "precio_unitario": float(item['precio_unitario']),
            "descuento":       0,
            "codigo_unidad":   "EA",
            "impuesto_iva":    19,
        })

    metodo_pago = METODO_PAGO_MAP.get(
        str(venta.get('metodo_pago', '')).upper(), '10'  # efectivo por defecto en POS
    )

    return {
        "referencia_pedido": venta['numero_venta'],
        "cliente": {
            "tipo_persona":     "natural",
            "tipo_documento":   "CC",
            "numero_documento": venta.get('cliente_documento') or '0',
            "nombre":           venta.get('cliente_nombre') or 'Consumidor Final',
            "email":            '',
            "telefono":         venta.get('cliente_telefono') or '',
            "direccion":        '',
            "municipio_codigo": '11001',
        },
        "items":       items,
        "metodo_pago": metodo_pago,
        "moneda":      "COP",
        "notas":       f"Venta POS #{venta_id}",
    }


def emitir_factura_electronica(pedido_id: int) -> dict:
    """
    Envía la factura del pedido al microservicio DIAN.

    El microservicio responde 202 INMEDIATAMENTE con estado PENDIENTE.
    El procesamiento real (XML + firma + DIAN) ocurre en background.

    Es idempotente: si el pedido ya tiene factura_dian_id asignado, retorna
    el id existente sin reenviar.

    Returns:
        Dict con {"id": "uuid", "estado": "PENDIENTE"} o {"error": ...}
    """
    if not DIAN_API_KEY:
        logger.warning("DIAN_API_KEY no configurada — facturación electrónica desactivada")
        return {"error": "Facturación electrónica no configurada"}

    # Guard idempotente: no reenviar si ya tiene factura
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT factura_dian_id FROM pedidos WHERE id = %s", (pedido_id,)
            )
            row = cur.fetchone()
            if row and row['factura_dian_id']:
                logger.info(f"Pedido {pedido_id} ya tiene factura {row['factura_dian_id']}, se omite reenvío")
                return {"id": str(row['factura_dian_id']), "estado": "YA_EMITIDA"}
    except Exception as e:
        logger.warning(f"No se pudo verificar factura_dian_id para pedido {pedido_id}: {e}")

    payload = construir_json_generico(pedido_id)
    if not payload:
        logger.error(f"Pedido {pedido_id} no encontrado para facturación")
        return {"error": f"Pedido {pedido_id} no encontrado"}

    try:
        resp = requests.post(
            f"{DIAN_SERVICE_URL}/facturas",
            json=payload,
            headers={
                "X-API-Key":    DIAN_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        resultado = resp.json()

        _guardar_factura_id_en_pedido(pedido_id, resultado.get('id'))

        logger.info(
            f"Factura encolada para pedido {pedido_id}: "
            f"id={resultado.get('id')}, estado={resultado.get('estado')}"
        )
        return resultado

    except requests.exceptions.Timeout:
        logger.error(f"Timeout al enviar factura del pedido {pedido_id} al microservicio DIAN")
        return {"error": "Timeout al conectar con el servicio de facturación"}

    except requests.exceptions.ConnectionError:
        logger.error(f"No se pudo conectar al microservicio DIAN para pedido {pedido_id}")
        return {"error": "Servicio de facturación no disponible"}

    except requests.exceptions.HTTPError as e:
        logger.error(f"Error HTTP del microservicio DIAN para pedido {pedido_id}: {e}")
        return {"error": f"Error del servicio de facturación: {e}"}

    except Exception as e:
        logger.error(f"Error inesperado al facturar pedido {pedido_id}: {e}")
        return {"error": str(e)}


def emitir_factura_pos(venta_id: int) -> dict:
    """
    Envía la factura de una venta POS al microservicio DIAN.

    Es idempotente: si la venta ya tiene factura_dian_id asignado, retorna
    el id existente sin reenviar.

    Returns:
        Dict con {"id": "uuid", "estado": "PENDIENTE"} o {"error": ...}
    """
    if not DIAN_API_KEY:
        logger.warning("DIAN_API_KEY no configurada — facturación electrónica desactivada")
        return {"error": "Facturación electrónica no configurada"}

    # Guard idempotente
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                "SELECT factura_dian_id FROM ventas_pos WHERE id = %s", (venta_id,)
            )
            row = cur.fetchone()
            if row and row['factura_dian_id']:
                logger.info(f"Venta POS {venta_id} ya tiene factura {row['factura_dian_id']}, se omite reenvío")
                return {"id": str(row['factura_dian_id']), "estado": "YA_EMITIDA"}
    except Exception as e:
        logger.warning(f"No se pudo verificar factura_dian_id para venta POS {venta_id}: {e}")

    payload = construir_json_pos(venta_id)
    if not payload:
        logger.error(f"Venta POS {venta_id} no encontrada para facturación")
        return {"error": f"Venta POS {venta_id} no encontrada"}

    try:
        resp = requests.post(
            f"{DIAN_SERVICE_URL}/facturas",
            json=payload,
            headers={
                "X-API-Key":    DIAN_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        resultado = resp.json()

        _guardar_factura_id_en_venta_pos(venta_id, resultado.get('id'))

        logger.info(
            f"Factura encolada para venta POS {venta_id}: "
            f"id={resultado.get('id')}, estado={resultado.get('estado')}"
        )
        return resultado

    except requests.exceptions.Timeout:
        logger.error(f"Timeout al enviar factura de venta POS {venta_id}")
        return {"error": "Timeout al conectar con el servicio de facturación"}

    except requests.exceptions.ConnectionError:
        logger.error(f"No se pudo conectar al microservicio DIAN para venta POS {venta_id}")
        return {"error": "Servicio de facturación no disponible"}

    except requests.exceptions.HTTPError as e:
        logger.error(f"Error HTTP del microservicio DIAN para venta POS {venta_id}: {e}")
        return {"error": f"Error del servicio de facturación: {e}"}

    except Exception as e:
        logger.error(f"Error inesperado al facturar venta POS {venta_id}: {e}")
        return {"error": str(e)}


def consultar_estado_factura(factura_id: str) -> dict:
    """
    Consulta el estado de una factura en el microservicio DIAN.
    Útil para mostrar al cliente el CUFE y número de factura una vez procesada.
    """
    if not DIAN_API_KEY:
        return {"error": "Facturación electrónica no configurada"}

    try:
        resp = requests.get(
            f"{DIAN_SERVICE_URL}/facturas/{factura_id}/estado",
            headers={"X-API-Key": DIAN_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error consultando estado de factura {factura_id}: {e}")
        return {"error": str(e)}


def _guardar_factura_id_en_pedido(pedido_id: int, factura_dian_id: str):
    """Guarda el UUID de factura DIAN en la tabla pedidos."""
    if not factura_dian_id:
        return
    try:
        with get_db_cursor() as cur:
            cur.execute(
                "UPDATE pedidos SET factura_dian_id = %s WHERE id = %s",
                (factura_dian_id, pedido_id)
            )
    except Exception as e:
        logger.warning(
            f"No se pudo guardar factura_dian_id en pedido {pedido_id}: {e}. "
            "Ejecutar: ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS factura_dian_id UUID;"
        )


def _guardar_factura_id_en_venta_pos(venta_id: int, factura_dian_id: str):
    """Guarda el UUID de factura DIAN en la tabla ventas_pos."""
    if not factura_dian_id:
        return
    try:
        with get_db_cursor() as cur:
            cur.execute(
                "UPDATE ventas_pos SET factura_dian_id = %s WHERE id = %s",
                (factura_dian_id, venta_id)
            )
    except Exception as e:
        logger.warning(
            f"No se pudo guardar factura_dian_id en venta POS {venta_id}: {e}. "
            "Ejecutar: ALTER TABLE ventas_pos ADD COLUMN IF NOT EXISTS factura_dian_id UUID;"
        )
