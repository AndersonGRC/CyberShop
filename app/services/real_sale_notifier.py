"""
RealSaleNotifier — el ÚNICO lugar desde donde sale el evento Purchase hacia Meta.

Una venta real es un pedido que PayU confirmó como APROBADO en su webhook
firmado (/confirmacion-pago). La página de respuesta no avisa nada: se recarga,
el cliente puede cerrarla antes de que cargue y su URL se puede editar.

- Una sola vez por pedido: la fila de `ventas_reales_meta` se reclama en una
  sola sentencia (enviado_en) antes de enviar. Un reintento del webhook no
  vuelve a salir y, si Meta falla, la venta no se reenvía: es mejor perder un
  evento que contar una compra dos veces.
- Valor y productos: los del pedido guardado (monto_total y detalle_pedidos),
  nunca los de la URL.
- Solo clientes nuevos: en los planes, la primera compra. Renovaciones,
  reactivaciones y quien ya había pagado otro plan no salen; la prueba gratis
  que paga sí (es su primer pago). Los pedidos de productos no son planes.
- Para que Meta reconozca al comprador: el webhook llega desde el servidor de
  PayU, así que el navegador (IP, user-agent, cookies _fbp/_fbc) se guarda al
  salir hacia PayU. Correo, teléfono y nombre salen del pedido y meta_capi los
  envía cifrados (SHA-256).
- Solo en la tienda de CyberShop (meta_capi.is_enabled); los clientes ni
  siquiera crean la tabla.

Un test (tests/test_meta_purchase_unico.py) falla si el Purchase aparece en
cualquier otro archivo.
"""

import re

from flask import current_app, request, session

from database import _current_db_name, get_db_cursor
from services import meta_capi

EVENTO = 'Purchase'
# Un webhook viejo repetido (o un reintento tardío de PayU) no es una venta nueva.
MAX_DIAS_PEDIDO = 7

_DDL = """
CREATE TABLE IF NOT EXISTS ventas_reales_meta (
    referencia_pedido VARCHAR(100) PRIMARY KEY,
    usuario_id        INTEGER,
    client_ip         VARCHAR(64),
    user_agent        TEXT,
    fbp               VARCHAR(255),
    fbc               VARCHAR(255),
    url_origen        TEXT,
    creado_en         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    enviado_en        TIMESTAMP
);
"""
_TABLA_LISTA = set()      # BDs con la tabla ya verificada (por proceso)


def _asegurar_tabla(cur):
    clave = _current_db_name()
    if clave not in _TABLA_LISTA:
        cur.execute(_DDL)
        _TABLA_LISTA.add(clave)


def registrar_salida_a_payu(referencia):
    """Guarda el navegador del comprador cuando sale hacia PayU (antes del pago).
    Nunca rompe el checkout."""
    try:
        if not referencia or not meta_capi.is_enabled():
            return
        navegador = meta_capi.build_user_data(request)
        with get_db_cursor() as cur:
            _asegurar_tabla(cur)
            cur.execute("""
                INSERT INTO ventas_reales_meta
                    (referencia_pedido, usuario_id, client_ip, user_agent, fbp, fbc, url_origen)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (referencia_pedido) DO NOTHING
            """, (referencia, session.get('usuario_id'),
                  (navegador['client_ip_address'] or '')[:64] or None,
                  navegador['client_user_agent'], navegador['fbp'], navegador['fbc'],
                  request.referrer or request.url))
    except Exception as exc:  # noqa: BLE001 — Meta nunca frena un pago
        current_app.logger.warning(f"RealSaleNotifier salida a PayU {referencia}: {exc}")


def _telefono(valor):
    """Meta pide solo dígitos y con indicativo: 300 123 4567 → 573001234567."""
    digitos = re.sub(r'\D', '', valor or '')
    if len(digitos) == 10 and digitos.startswith('3'):
        digitos = '57' + digitos
    return digitos or None


def _ya_era_cliente(cur, referencia):
    """¿Este pago de un plan es de alguien que ya era cliente?

    - Una renovación (o la que reactiva una tienda suspendida) nunca es cliente
      nuevo, salvo que la tienda haya nacido como prueba gratis (referencia
      TRIAL-…): su primer pago es la conversión.
    - Ya era cliente si antes pagó (pedido APROBADO) otro plan de la misma
      tienda o con el mismo correo: otra tienda, una que canceló y vuelve.

    Solo mira pagos de otras filas, así que da lo mismo si procesar_compra_plan
    ya corrió (la conversión le quita es_trial al padre). Un pedido de
    productos no tiene plan: devuelve False."""
    cur.execute("SELECT to_regclass('plan_compras') IS NOT NULL AS hay")
    if not cur.fetchone()['hay']:
        return False
    cur.execute("""
        SELECT (esta.renovacion_de IS NOT NULL
                AND COALESCE(padre.referencia_pedido, '') NOT LIKE 'TRIAL-%%')
               OR EXISTS (
                   SELECT 1 FROM plan_compras antes
                   JOIN pedidos p ON p.referencia_pedido = antes.referencia_pedido
                   WHERE antes.id < esta.id AND p.estado_pago = 'APROBADO'
                     AND (COALESCE(antes.renovacion_de, antes.id) = COALESCE(esta.renovacion_de, esta.id)
                          OR LOWER(antes.buyer_email) = LOWER(esta.buyer_email))
               ) AS ya_era_cliente
        FROM plan_compras esta
        LEFT JOIN plan_compras padre ON padre.id = esta.renovacion_de
        WHERE esta.referencia_pedido = %s
    """, (referencia,))
    fila = cur.fetchone()
    return bool(fila and fila['ya_era_cliente'])


def notificar_venta(referencia):
    """Avisa a Meta una venta aprobada por PayU. True si salió el aviso."""
    try:
        if not referencia or not meta_capi.is_enabled():
            return False
        with get_db_cursor(dict_cursor=True) as cur:
            _asegurar_tabla(cur)
            cur.execute(f"""
                SELECT id, monto_total, cliente_email, cliente_telefono, cliente_nombre
                FROM pedidos
                WHERE referencia_pedido = %s AND estado_pago = 'APROBADO'
                  AND COALESCE(fecha_creacion, CURRENT_TIMESTAMP)
                      > CURRENT_TIMESTAMP - INTERVAL '{MAX_DIAS_PEDIDO} days'
            """, (referencia,))
            pedido = cur.fetchone()
            if not pedido or float(pedido['monto_total'] or 0) <= 0:
                return False
            if _ya_era_cliente(cur, referencia):
                current_app.logger.info(f"RealSaleNotifier {referencia}: renovación o cliente que ya "
                                        f"había pagado; no es una venta nueva para Meta")
                return False
            # Reclamo atómico: solo una petición obtiene la fila; las demás, nada.
            cur.execute("""
                INSERT INTO ventas_reales_meta (referencia_pedido, enviado_en)
                VALUES (%s, CURRENT_TIMESTAMP)
                ON CONFLICT (referencia_pedido) DO UPDATE SET enviado_en = CURRENT_TIMESTAMP
                    WHERE ventas_reales_meta.enviado_en IS NULL
                RETURNING usuario_id, client_ip, user_agent, fbp, fbc, url_origen
            """, (referencia,))
            navegador = cur.fetchone()
            if not navegador:
                return False                                  # ya se avisó
            cur.execute("""SELECT producto_nombre, cantidad, precio_unitario
                           FROM detalle_pedidos WHERE pedido_id = %s ORDER BY id""", (pedido['id'],))
            lineas = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 — Meta nunca frena el webhook
        current_app.logger.warning(f"RealSaleNotifier {referencia}: {exc}")
        return False

    nombre = (pedido['cliente_nombre'] or '').split()
    user_data = {
        'em': pedido['cliente_email'],
        'ph': _telefono(pedido['cliente_telefono']),
        'fn': nombre[0] if nombre else None,
        'ln': nombre[-1] if len(nombre) > 1 else None,
        'country': 'co',
        'external_id': str(navegador['usuario_id']) if navegador['usuario_id'] else None,
        'client_ip_address': navegador['client_ip'],
        'client_user_agent': navegador['user_agent'],
        'fbp': navegador['fbp'],
        'fbc': navegador['fbc'],
    }
    contenidos = [{'id': l['producto_nombre'], 'quantity': int(l['cantidad'] or 1),
                   'item_price': float(l['precio_unitario'] or 0)}
                  for l in lineas if l['producto_nombre']]
    custom_data = {'currency': 'COP', 'value': float(pedido['monto_total']), 'order_id': referencia}
    if contenidos:
        custom_data.update(content_type='product', contents=contenidos,
                           content_ids=[c['id'] for c in contenidos],
                           num_items=sum(c['quantity'] for c in contenidos))
    # Sin el navegador (pedido creado antes de este cambio) Meta rechaza un
    # evento «website»: va como venta registrada por el sistema.
    meta_capi.send_event_async(
        EVENTO, event_id=f'purchase-{referencia}', user_data=user_data,
        custom_data=custom_data, event_source_url=navegador['url_origen'] or request.host_url,
        action_source='website' if navegador['user_agent'] else 'system_generated',
    )
    return True
