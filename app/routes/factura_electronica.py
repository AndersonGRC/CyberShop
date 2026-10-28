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
from pathlib import Path

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
    # Medios de pago del POS y del cobro de mesas (metodos_pago_pos).
    'TARJETA':      '48',   # Tarjeta crédito/débito
    'NEQUI':        '20',   # Billetera digital = transferencia
    'DAVIPLATA':    '20',
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


def _table_has_column(table_name: str, column_name: str) -> bool:
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
            return cur.fetchone() is not None
    except Exception:
        return False


def _tipo_columna(table_name: str, column_name: str) -> str | None:
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = %s
                LIMIT 1
            """, (table_name, column_name))
            fila = cur.fetchone()
            return fila['data_type'] if fila else None
    except Exception:
        return None


def columna_fe(tabla: str) -> str | None:
    """Columna donde `tabla` guarda el id (UUID) de su documento DIAN, o None.

    Las bases nuevas no la traían en cotizaciones, cuentas de cobro ni mesas, y
    algunas heredadas la tienen como número (no cabe un UUID): ahí la migración
    0026 agrega `factura_dian_uuid` en vez de cambiar el tipo de la existente.
    """
    if _tipo_columna(tabla, 'factura_dian_id') in ('uuid', 'text', 'character varying'):
        return 'factura_dian_id'
    if _table_has_column(tabla, 'factura_dian_uuid'):
        return 'factura_dian_uuid'
    return None


def sql_columnas_fe(tabla: str) -> str:
    """Fragmento de SELECT con `facturar_electronicamente` y `factura_dian_id`
    que nunca falla: si una columna no existe en esta base, sale NULL/FALSE.
    Antes, sin ellas, la lista completa de cotizaciones o cuentas salía vacía."""
    marca = ("COALESCE(facturar_electronicamente, FALSE) AS facturar_electronicamente"
             if _table_has_column(tabla, 'facturar_electronicamente')
             else "FALSE AS facturar_electronicamente")
    col = columna_fe(tabla)
    return f"{marca}, {col + '::text' if col else 'NULL'} AS factura_dian_id"


def facturacion_habilitada() -> bool:
    """Retorna True si el módulo de Facturación Electrónica está activo."""
    return is_module_active(MODULE_FACTURACION_ELECTRONICA)


def _municipio_codigo(ciudad: str) -> str:
    """Mapea nombre de ciudad al código de municipio DIAN. Bogotá por defecto."""
    if not ciudad:
        return '11001'
    return MUNICIPIO_MAP.get(ciudad.lower().strip(), '11001')


# Unidad de medida de CyberShop → código UNECE Rec 20 que espera la DIAN.
UNIDAD_DIAN_MAP = {
    'unidad': 'EA',  'docena': 'DZN', 'kilo': 'KGM',
    'gramo':  'GRM', 'libra':  'LBR', 'litro': 'LTR',
}

# En CyberShop el precio del producto es el precio FINAL: ni el carrito ni el POS
# suman IVA encima (`productos.impuesto` es metadato tributario, no entra en el
# cobro). El microservicio, en cambio, calcula total = base × (1 + iva), así que
# necesita saberlo para descomponer en vez de sumar.
#
# La descomposición la hace EL PORTAL, no aquí: solo él sabe si el emisor es
# responsable de IVA (régimen 48) y por tanto si el impuesto se aplica. Si
# dividiéramos aquí, un emisor de régimen 49 —al que el portal le fuerza IVA 0—
# terminaría facturando 19% por DEBAJO de lo cobrado. Este módulo no lleva
# lógica tributaria (ver docstring del archivo); solo declara el hecho.
# Conmutable por si algún cliente carga precios sin IVA.
FE_PRECIO_INCLUYE_IVA = os.getenv('FE_PRECIO_INCLUYE_IVA', 'true').lower() == 'true'


def _iva_pct(impuesto_raw) -> int:
    """`productos.impuesto` ('excluido'|'0'|'5'|'19') → porcentaje entero.

    'excluido' y cualquier valor desconocido → 0, que es el default de la
    columna (migración 0004). Así un tenant que nunca configuró IVA no factura
    un impuesto que jamás cobró (antes iba 19 fijo para todos los productos).
    """
    valor = str(impuesto_raw or '').strip().lower()
    return int(valor) if valor in ('0', '5', '19') else 0


def _unidad_dian(unidad_raw) -> str:
    return UNIDAD_DIAN_MAP.get(str(unidad_raw or '').strip().lower(), 'EA')


def _construir_items(filas, campo_desc: str) -> list:
    """Convierte líneas de venta al formato de ítems del microservicio.

    Preserva lo que REALMENTE se vendió: IVA real del producto, descuento
    implícito (cuando `subtotal` no cuadra con cantidad × precio), unidad de
    medida y código de referencia. Antes se mandaba descuento 0, IVA 19 y
    unidad EA fijos para todo, así que la factura no reflejaba la venta.
    """
    items = []
    for fila in filas:
        fila     = dict(fila)
        cantidad = int(fila.get('cantidad') or 1)
        iva      = _iva_pct(fila.get('impuesto'))
        precio   = float(fila.get('precio_unitario') or 0)

        # Descuento implícito: la diferencia entre el bruto y el subtotal real
        # de la línea. `subtotal` se leía de la BD y se descartaba.
        bruto     = precio * cantidad
        subtotal  = fila.get('subtotal')
        subtotal  = float(subtotal) if subtotal is not None else bruto
        descuento = max(0.0, round(bruto - subtotal, 2))

        item = {
            "descripcion":     fila.get(campo_desc) or 'Producto',
            "cantidad":        cantidad,
            "precio_unitario": precio,
            "descuento":       descuento,
            "codigo_unidad":   _unidad_dian(fila.get('unidad_medida')),
            "impuesto_iva":    iva,
            # El portal descompone base + IVA solo si el impuesto aplica.
            "precio_incluye_iva": FE_PRECIO_INCLUYE_IVA,
        }
        codigo = str(fila.get('referencia') or '').strip()
        if codigo:
            # xml_builder lo usa como SellersItemIdentification/ID; sin esto
            # todas las líneas salían como ITEM-001, ITEM-002…
            item["codigo"] = codigo
        items.append(item)
    return items


def _email_adquiriente(email_crudo) -> str:
    """Correo del comprador con respaldo. La DIAN rechaza la factura si va vacío.

    Cae al correo de contacto del negocio cuando la venta no capturó uno (típico
    en mostrador). Sin ninguno va vacío y el portal pide el correo del cliente:
    antes se ponía 'facturacion@empresa.co', un dominio ajeno que recibiría la
    factura de un desconocido si algún día se envía por correo.
    """
    email = str(email_crudo or '').strip()
    if '@' in email:
        return email
    try:
        from services.public_site_service import get_public_contact_destination_email
        email = (get_public_contact_destination_email() or '').strip()
    except Exception:
        email = ''
    return email if '@' in email else ''


def _documento_adquiriente(documento_crudo) -> str:
    """Documento del comprador. Consumidor final = 222222222222 (no '0')."""
    return str(documento_crudo or '').strip() or '222222222222'


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
                      p.monto_total
               FROM pedidos p
               WHERE p.id = %s""",
            (pedido_id,)
        )
        pedido = cur.fetchone()

        if not pedido:
            return None

        # `detalle_pedidos` no guarda producto_id, así que el IVA/unidad reales
        # se recuperan emparejando por nombre. Es lo único que hay; si el
        # producto ya no existe o cambió de nombre, los COALESCE dejan el
        # default seguro (sin IVA, unidad EA) en vez de inventar un 19%.
        tiene_iva = _table_has_column('productos', 'impuesto')
        sel_extra = (", pr.impuesto, pr.unidad_medida"
                     if tiene_iva else
                     ", 'excluido' AS impuesto, 'unidad' AS unidad_medida")
        cur.execute(
            f"""SELECT dp.producto_nombre,
                      dp.cantidad,
                      dp.precio_unitario,
                      dp.subtotal,
                      pr.referencia
                      {sel_extra}
               FROM detalle_pedidos dp
               LEFT JOIN LATERAL (
                   SELECT p2.* FROM productos p2
                   WHERE p2.nombre = dp.producto_nombre
                   ORDER BY p2.id LIMIT 1
               ) pr ON TRUE
               WHERE dp.pedido_id = %s
               ORDER BY dp.id""",
            (pedido_id,)
        )
        items_db = cur.fetchall()

    pedido = dict(pedido)

    tipo_doc = TIPO_DOC_MAP.get(
        str(pedido.get('cliente_tipo_documento') or 'CC').upper(), 'CC'
    )
    numero_doc = _documento_adquiriente(pedido.get('cliente_documento'))

    items = _construir_items(items_db, 'producto_nombre')

    metodo_pago = METODO_PAGO_MAP.get(
        str(pedido.get('metodo_pago', '')).upper(), '48'
    )

    return {
        "referencia_pedido": pedido['referencia_pedido'],
        "cliente": {
            # Una compra con NIT es una empresa: iba como persona natural.
            "tipo_persona":     "juridica" if tipo_doc == 'NIT' else "natural",
            "tipo_documento":   tipo_doc,
            "numero_documento": numero_doc,
            "nombre":           pedido.get('cliente_nombre') or 'Consumidor Final',
            "email":            _email_adquiriente(pedido.get('cliente_email')),
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
        # SELECT * a propósito: `cliente_email` y `cliente_tipo_doc` llegan con la
        # migración 0009 y puede que un tenant aún no la tenga aplicada. Con el
        # cursor de diccionario, las claves ausentes se resuelven con .get() -> None
        # en vez de reventar la consulta.
        cur.execute(
            """SELECT v.*
               FROM ventas_pos v
               WHERE v.id = %s""",
            (venta_id,)
        )
        venta = cur.fetchone()

        if not venta:
            return None

        # A diferencia de detalle_pedidos, aquí sí hay producto_id: el IVA y la
        # unidad reales salen por join directo (sin emparejar por nombre).
        tiene_iva = _table_has_column('productos', 'impuesto')
        sel_extra = (", pr.impuesto, pr.unidad_medida"
                     if tiene_iva else
                     ", 'excluido' AS impuesto, 'unidad' AS unidad_medida")
        cur.execute(
            f"""SELECT d.descripcion,
                      d.cantidad,
                      d.precio_unitario,
                      d.subtotal,
                      pr.referencia
                      {sel_extra}
               FROM detalle_venta_pos d
               LEFT JOIN productos pr ON pr.id = d.producto_id
               WHERE d.venta_id = %s
               ORDER BY d.id""",
            (venta_id,)
        )
        items_db = cur.fetchall()

    venta = dict(venta)

    items = _construir_items(items_db, 'descripcion')

    metodo_pago = METODO_PAGO_MAP.get(
        str(venta.get('metodo_pago', '')).upper(), '10'  # efectivo por defecto en POS
    )

    # Tipo de documento real del comprador. Antes iba 'CC' fijo, así que una venta
    # a una empresa con NIT se emitía como persona natural con cédula.
    tipo_doc = TIPO_DOC_MAP.get(
        str(venta.get('cliente_tipo_doc') or '').strip().upper(), 'CC'
    )

    email     = _email_adquiriente(venta.get('cliente_email'))
    documento = _documento_adquiriente(venta.get('cliente_documento'))

    return {
        "referencia_pedido": venta['numero_venta'],
        "cliente": {
            "tipo_persona":     "juridica" if tipo_doc == 'NIT' else "natural",
            "tipo_documento":   tipo_doc,
            "numero_documento": documento,
            "nombre":           venta.get('cliente_nombre') or 'Consumidor Final',
            "email":            email,
            "telefono":         venta.get('cliente_telefono') or '',
            "direccion":        '',
            "municipio_codigo": '11001',
        },
        "items":       items,
        "metodo_pago": metodo_pago,
        "moneda":      "COP",
        "notas":       f"Venta POS #{venta_id}",
    }


# ── Conexión con el portal tributario ───────────────────────────────────────

# Tablas de CyberShop que guardan el documento DIAN de su venta (factura_dian_id).
TABLAS_FE = ('pedidos', 'ventas_pos', 'restaurant_table_orders', 'cuentas_cobro', 'cotizaciones')

# Un documento reversado o rechazado no bloquea volver a facturar la misma venta.
ESTADOS_REEMITIBLES = ('CANCELADA', 'RECHAZADA')
MAX_REEMISIONES = 9


def _llave_compartida() -> str:
    """DIAN_API_KEY del .cybershop.conf compartido (la de la tienda operadora).

    Cada instancia lee ese archivo y solo lo sobrescribe con su propio env, así
    que una tienda sin llave propia HEREDA la de CyberShop. Saberlo evita que
    facture a nombre de otro negocio.
    """
    try:
        from dotenv import dotenv_values
        ruta = Path(__file__).resolve().parent.parent / '.cybershop.conf'
        return str(dotenv_values(ruta).get('DIAN_API_KEY') or '').strip()
    except Exception:
        return ''


def _base_del_conf() -> str:
    """DB_NAME del .cybershop.conf compartido: la base de la tienda operadora."""
    try:
        from dotenv import dotenv_values
        ruta = Path(__file__).resolve().parent.parent / '.cybershop.conf'
        return str(dotenv_values(ruta).get('DB_NAME') or '').strip()
    except Exception:
        return ''


def _es_tienda_operadora() -> bool:
    """La tienda dueña del .cybershop.conf (CyberShop, la dueña del portal).

    Se decide por su base de datos, que cada cliente tiene propia y no puede
    cambiar. No por una opción de su sitio (como el módulo Software POS), que el
    mismo cliente podría encender desde su panel.
    """
    try:
        from database import _current_db_name
        base = _base_del_conf()
        return bool(base) and base == _current_db_name()
    except Exception:
        return False


def enlace_portal_operador() -> dict | None:
    """La tienda operadora entra al portal como administrador general, como
    siempre: es la dueña del portal. Ningún cliente entra así (a ellos el portal
    les da un enlace solo de lo suyo, ver enlace_portal)."""
    master = os.getenv('DIAN_MASTER_KEY', '')
    if not master or not _es_tienda_operadora():
        return None
    import hashlib
    import hmac
    import time
    ts = int(time.time())
    token = hmac.new(master.encode(), f"{ts}:dian-autologin".encode(), hashlib.sha256).hexdigest()
    base = os.getenv('DIAN_UI_URL', '/ui').rstrip('/')
    return {'url': f"{base}/auto-login?token={token}&ts={ts}"}


def estado_conexion_local():
    """(ok, motivo) sin salir a la red: ¿esta tienda puede hablar con el portal?"""
    if not DIAN_API_KEY:
        return False, ('Tu facturación electrónica todavía no está conectada. '
                       'Pide a soporte CyberShop que la active con los datos de tu negocio.')
    compartida = _llave_compartida()
    if compartida and compartida == DIAN_API_KEY.strip() and not _es_tienda_operadora():
        return False, ('Tu facturación electrónica todavía no está conectada con el NIT de tu negocio. '
                       'Para que ninguna factura salga a nombre de otro, no se envía nada hasta que '
                       'soporte CyberShop la configure con tus datos.')
    return True, None


_CAMPOS_API = (
    (r'cliente\.email', 'el correo del cliente'),
    (r'cliente\.numero_documento', 'el número de documento del cliente'),
    (r'cliente\.tipo_documento', 'el tipo de documento del cliente'),
    (r'cliente\.tipo_persona', 'el tipo de persona del cliente'),
    (r'cliente\.nombre', 'el nombre del cliente'),
    (r'\.precio_unitario', ' (precio)'),
    (r'\.cantidad', ' (cantidad)'),
    (r'\.descripcion', ' (descripción)'),
    (r'\.impuesto_iva', ' (IVA)'),
)


def _traducir_campos(mensaje: str) -> str:
    """'cliente.email debe tener formato válido' → 'El correo del cliente debe…'."""
    import re
    texto = str(mensaje or '')
    texto = re.sub(r'items\[(\d+)\]', lambda m: f"el producto {int(m.group(1)) + 1}", texto)
    for patron, humano in _CAMPOS_API:
        texto = re.sub(patron, humano, texto)
    return texto[:1].upper() + texto[1:] if texto else texto


def _error_amigable(status=None, datos=None, exc=None) -> str:
    """Motivo de un fallo en palabras que entiende el dueño del negocio."""
    if isinstance(exc, requests.exceptions.Timeout):
        return ('El portal tributario tardó demasiado en responder. '
                'Intenta de nuevo en unos minutos.')
    if isinstance(exc, requests.exceptions.ConnectionError):
        return ('No hay conexión con el portal tributario en este momento. Intenta de nuevo '
                'en unos minutos; si sigue igual, avisa a soporte CyberShop.')
    if exc is not None:
        return 'Ocurrió un error inesperado al hablar con el portal tributario.'
    mensaje = datos.get('error') if isinstance(datos, dict) else ''
    if status in (401, 403):
        return ('El portal tributario rechazó la conexión de esta tienda (su llave no es '
                'válida o fue cambiada). Avisa a soporte CyberShop para que la revise.')
    if status == 404 and mensaje == 'Endpoint no encontrado':
        # Respuesta del propio portal a una ruta que su versión aún no tiene.
        return ('El portal tributario está desactualizado y todavía no tiene esta función. '
                'Hay que instalarle su versión nueva.')
    if status and status >= 500:
        return 'El portal tributario tuvo un error interno. Intenta de nuevo en unos minutos.'
    if mensaje:
        return _traducir_campos(mensaje)
    return f"El portal tributario respondió con un error (código {status})."


def _dian_call(metodo: str, ruta: str, *, payload=None, params=None,
               headers=None, timeout: int = 12) -> dict:
    """Llamada al portal con la llave de esta tienda.

    Devuelve SIEMPRE un dict: ante fallo, {'error': motivo en palabras simples,
    'status': código}, para que el panel lo muestre en vez de romperse. Nunca
    llama si la tienda no tiene llave propia (ver estado_conexion_local).
    """
    ok, motivo = estado_conexion_local()
    if not ok:
        return {'error': motivo, 'status': None}
    try:
        resp = requests.request(
            metodo, f"{DIAN_SERVICE_URL}{ruta}",
            headers={'X-API-Key': DIAN_API_KEY, **(headers or {})},
            json=payload, params=params, timeout=timeout,
        )
        try:
            datos = resp.json() if resp.content else {}
        except ValueError:
            datos = {}
        if resp.status_code >= 400:
            return {'error': _error_amigable(resp.status_code, datos), 'status': resp.status_code,
                    'detalle': str(datos.get('error') or '') if isinstance(datos, dict) else ''}
        return datos if isinstance(datos, dict) else {'items': datos}
    except Exception as e:
        logger.error(f"Error llamando al servicio DIAN {metodo} {ruta}: {e}")
        return {'error': _error_amigable(exc=e), 'status': None}


def informacion_conexion() -> dict:
    """A nombre de quién factura esta tienda y si la conexión responde.

    Usa /me del portal; si el portal aún no lo tiene (versión anterior), basta
    con que la política de envío responda para saber que la llave funciona.
    """
    datos = _dian_call('GET', '/me', timeout=8)
    if datos.get('status') == 404:
        politica = _dian_call('GET', '/config-envio', timeout=8)
        if politica.get('error'):
            return {'ok': False, 'error': politica['error']}
        return {'ok': True, 'sin_detalle': True}
    if datos.get('error'):
        return {'ok': False, 'error': datos['error']}
    return {'ok': True, **datos}


def enlace_portal() -> dict:
    """Enlace de 30 s al portal tributario, SOLO con los documentos de esta tienda.

    Antes se firmaba con la llave maestra del portal, que abre la vista de
    administrador con los datos de todos los clientes.
    """
    datos = _dian_call('GET', '/portal/token', timeout=8)
    # El 403 tiene dos causas que se resuelven distinto: la llave rechazada (lo
    # dice el mensaje de error general) o el acceso de la tienda apagado.
    if datos.get('status') == 403 and 'habilitado' in datos.get('detalle', '').lower():
        if _dian_call('GET', '/me', timeout=8).get('status') == 404:
            # Portal sin actualizar: su /portal/token responde «no habilitado» SIEMPRE
            # (no leía portal_activo), esté encendido o no.
            return {'error': ('El portal tributario está desactualizado y por eso no abre. '
                              'Hay que instalarle su versión nueva. Mientras tanto, tus facturas '
                              'las ves y gestionas aquí mismo, en esta bandeja.')}
        return {'error': ('El acceso de tu tienda al portal tributario está apagado. Lo enciende '
                          'el administrador del portal: datos del cliente → Portal Tributario → '
                          'Acceso al portal: Habilitado. Mientras tanto, tus facturas las ves y '
                          'gestionas aquí mismo, en esta bandeja.')}
    if datos.get('error'):
        return {'error': datos['error']}
    if not datos.get('url'):
        return {'error': 'El portal tributario no entregó el enlace de acceso.'}
    return {'url': datos['url']}


def consultar_estado_factura(factura_id: str) -> dict:
    """Estado, número y CUFE de un documento (útil una vez procesado)."""
    return _dian_call('GET', f"/facturas/{factura_id}/estado", timeout=10)


# ── Bandeja y política de envío (panel del cliente) ──────────────────────────

def listar_facturas_dian(estado: str = None, limite: int = 50) -> dict:
    """Documentos del tenant en el microservicio, recientes primero.

    Cada ítem trae `cancelable`, que el portal calcula en SQL: es TRUE mientras
    el documento no haya salido a la DIAN (dentro del plazo de gracia, o
    esperando aprobación manual).
    """
    params = {'limite': limite}
    if estado:
        params['estado'] = estado
    return _dian_call('GET', '/facturas', params=params)


def cancelar_factura_dian(factura_id: str) -> dict:
    """Reversa un documento que aún no se envió a la DIAN."""
    res = _dian_call('POST', f"/facturas/{factura_id}/cancelar")
    if not res.get('error'):
        desvincular_factura(factura_id)
    return res


def enviar_factura_ya(factura_id: str, usuario: str = '') -> dict:
    """Manda YA a la DIAN un documento en cola (aprobación manual o en espera)."""
    return _dian_call('POST', f"/facturas/{factura_id}/enviar",
                      headers={'X-Usuario': str(usuario or '')[:80]})


def descargar_pdf_factura(factura_id: str):
    """(contenido, nombre_archivo) del PDF de un documento aceptado, o {'error'}."""
    ok, motivo = estado_conexion_local()
    if not ok:
        return {'error': motivo}
    try:
        resp = requests.get(f"{DIAN_SERVICE_URL}/facturas/{factura_id}/pdf",
                            headers={'X-API-Key': DIAN_API_KEY}, timeout=20)
    except Exception as e:
        return {'error': _error_amigable(exc=e)}
    if resp.status_code == 404:
        return {'error': 'El PDF de este documento todavía no está disponible.'}
    if resp.status_code >= 400 or 'pdf' not in resp.headers.get('Content-Type', ''):
        try:
            datos = resp.json()
        except ValueError:
            datos = {}
        return {'error': _error_amigable(resp.status_code, datos)}
    import re
    nombre = re.search(r'filename="?([^";]+)', resp.headers.get('Content-Disposition', ''))
    return resp.content, (nombre.group(1) if nombre else f"factura-{factura_id}.pdf")


def obtener_politica_envio() -> dict:
    """Política de envío vigente: modo_aprobacion + grace_minutos."""
    return _dian_call('GET', '/config-envio')


def guardar_politica_envio(modo: str, grace_minutos: int) -> dict:
    return _dian_call('PUT', '/config-envio',
                      payload={'modo_aprobacion': modo,
                               'grace_minutos': grace_minutos})


# ============================================================================
# Emisión desde los módulos de dinero: pedidos en línea, POS, mesas, cuentas
# de cobro y cotizaciones. Mismo patrón: facturacion_habilitada() + flag por
# registro + idempotencia (factura_dian_id). Nada sale directo a la DIAN: el
# portal lo deja en cola según la política de envío del cliente (espera para
# reversar, o aprobación manual).
# ============================================================================

def _guardar_factura_id_tabla(tabla: str, registro_id: int, factura_dian_id: str):
    """Guarda el UUID del documento DIAN en la columna de `tabla` (tabla interna, no input).

    Sin columna (base sin la migración 0026) no se guarda, y no pasa nada grave:
    el portal tampoco duplica, porque reconoce la venta por su referencia.
    """
    if not factura_dian_id:
        return
    col = columna_fe(tabla)
    if not col:
        logger.warning(f"{tabla} no tiene dónde guardar el documento DIAN {factura_dian_id}: "
                       "falta la migración 0026 (Actualizar app).")
        return
    try:
        with get_db_cursor() as cur:
            cur.execute(f"UPDATE {tabla} SET {col} = %s WHERE id = %s",
                        (factura_dian_id, registro_id))
    except Exception as e:
        logger.warning(f"No se pudo guardar el documento DIAN en {tabla} {registro_id}: {e}")


def desvincular_factura(factura_dian_id: str):
    """Tras reversar, la venta deja de verse como facturada y se puede volver a
    facturar. El documento reversado sigue en el portal (no se borra nada)."""
    for tabla in TABLAS_FE:
        col = columna_fe(tabla)
        if not col:
            continue
        try:
            with get_db_cursor() as cur:
                cur.execute(f"UPDATE {tabla} SET {col} = NULL "
                            f"WHERE {col}::text = %s", (str(factura_dian_id),))
        except Exception as e:
            logger.warning(f"No se pudo desvincular {factura_dian_id} de {tabla}: {e}")


def _emitir_a_dian(tabla: str, registro_id: int, payload: dict | None) -> dict:
    """
    Envío genérico al microservicio DIAN, idempotente por {tabla}.factura_dian_id.
    `tabla` es una constante interna (no entrada del usuario). Devuelve dict
    {'id','estado'} o {'error': ...} — NUNCA lanza (no debe frenar el flujo de dinero).

    Si la venta ya tuvo un documento reversado o rechazado, el portal lo devuelve
    por su referencia; entonces se emite con la referencia «-R2», «-R3»…, para
    que corregir y volver a facturar sea posible sin tocar el documento anterior.
    """
    ok, motivo = estado_conexion_local()
    if not ok:
        logger.warning(f"FE {tabla} {registro_id}: {motivo}")
        return {"error": motivo}

    # Guard idempotente: si ya tiene factura, no reenviar
    col = columna_fe(tabla)
    if col:
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute(f"SELECT {col} AS doc FROM {tabla} WHERE id = %s", (registro_id,))
                row = cur.fetchone()
                if row and row['doc']:
                    return {"id": str(row['doc']), "estado": "YA_EMITIDA"}
        except Exception as e:
            logger.warning(f"No se pudo verificar el documento DIAN de {tabla} {registro_id}: {e}")

    if not payload:
        return {"error": f"No se encontró el registro {registro_id} para facturar"}

    referencia = str(payload.get('referencia_pedido') or f"{tabla}-{registro_id}")
    for intento in range(1, MAX_REEMISIONES + 1):
        payload['referencia_pedido'] = referencia if intento == 1 else f"{referencia}-R{intento}"
        resultado = _dian_call('POST', '/facturas', payload=payload, timeout=10)
        if resultado.get('error'):
            logger.error(f"FE {tabla} {registro_id}: {resultado['error']}")
            return {"error": resultado['error']}
        if resultado.get('estado') not in ESTADOS_REEMITIBLES:
            _guardar_factura_id_tabla(tabla, registro_id, resultado.get('id'))
            logger.info(f"Factura encolada para {tabla} {registro_id}: id={resultado.get('id')}")
            return resultado
    return {"error": "Esta venta ya se reversó demasiadas veces; revísala con soporte CyberShop."}


# ── Pedidos en línea y POS ───────────────────────────────────────────────────

def emitir_factura_electronica(pedido_id: int) -> dict:
    """Factura del pedido en línea (se llama al aprobarse el pago, si se pidió)."""
    return _emitir_a_dian('pedidos', pedido_id, construir_json_generico(pedido_id))


def emitir_factura_pos(venta_id: int) -> dict:
    """Factura de una venta POS marcada «Facturar electrónicamente»."""
    return _emitir_a_dian('ventas_pos', venta_id, construir_json_pos(venta_id))


# ── Restaurante (mesas) ──────────────────────────────────────────────────────

def construir_json_restaurante(order_id: int) -> dict | None:
    """Convierte una orden de mesa cerrada (restaurant_table_orders) al JSON DIAN."""
    with get_db_cursor(dict_cursor=True) as cur:
        # SELECT * a propósito: las columnas del adquiriente (cliente_tipo_doc,
        # cliente_documento, cliente_email, cliente_telefono) se agregan de forma
        # aditiva y puede que un tenant aún no las tenga. Con dict_cursor, las
        # claves ausentes se resuelven con .get() -> None en vez de reventar.
        cur.execute(
            """SELECT * FROM restaurant_table_orders WHERE id = %s""", (order_id,))
        orden = cur.fetchone()
        if not orden:
            return None
        tiene_iva = _table_has_column('productos', 'impuesto')
        sel_extra = (", pr.impuesto, pr.unidad_medida"
                     if tiene_iva else
                     ", 'excluido' AS impuesto, 'unidad' AS unidad_medida")
        cur.execute(
            f"""SELECT c.descripcion, c.cantidad, c.precio_unitario, c.subtotal,
                      pr.referencia {sel_extra}
               FROM restaurant_table_consumptions c
               LEFT JOIN productos pr ON pr.id = c.producto_id
               WHERE c.order_id = %s ORDER BY c.id""", (order_id,))
        items_db = cur.fetchall()

    orden = dict(orden)
    # Antes iba IVA 19 fijo para todo consumo: en un restaurante con productos
    # excluidos eso factura un impuesto que el comensal nunca pagó.
    items = _construir_items(items_db, 'descripcion')
    metodo = METODO_PAGO_MAP.get(str(orden.get('payment_method') or '').upper(), '10')

    # Adquiriente real capturado al cobrar (mismo criterio que el POS): tipo de
    # documento mapeado, email obligatorio para la DIAN (fallback al del negocio),
    # y documento por defecto 222222222222 (consumidor final).
    tipo_doc = TIPO_DOC_MAP.get(str(orden.get('cliente_tipo_doc') or '').strip().upper(), 'CC')
    email = _email_adquiriente(orden.get('cliente_email'))
    documento = _documento_adquiriente(orden.get('cliente_documento'))

    return {
        "referencia_pedido": f"REST-{order_id}",
        "cliente": {
            "tipo_persona":     "juridica" if tipo_doc == 'NIT' else "natural",
            "tipo_documento":   tipo_doc,
            "numero_documento": documento,
            "nombre":           orden.get('cliente_nombre') or 'Consumidor Final',
            "email":            email,
            "telefono":         orden.get('cliente_telefono') or '',
            "direccion":        "",
            "municipio_codigo": "11001",
        },
        "items": items, "metodo_pago": metodo, "moneda": "COP",
        "notas": f"Restaurante — orden de mesa #{order_id}",
    }


def emitir_factura_restaurante(order_id: int) -> dict:
    return _emitir_a_dian('restaurant_table_orders', order_id,
                          construir_json_restaurante(order_id))


# ── Cuenta de cobro ──────────────────────────────────────────────────────────

def construir_json_cuenta_cobro(cuenta_id: int) -> dict | None:
    """Convierte una cuenta de cobro (cuentas_cobro) al JSON DIAN."""
    with get_db_cursor(dict_cursor=True) as cur:
        # cliente_email es opcional según la antigüedad del tenant.
        sel_mail = (", cliente_email"
                    if _table_has_column('cuentas_cobro', 'cliente_email')
                    else ", NULL AS cliente_email")
        cur.execute(
            f"""SELECT consecutivo, cliente_nombre, cliente_nit, cliente_direccion,
                      cliente_telefono, cliente_ciudad, total
                      {sel_mail}
               FROM cuentas_cobro WHERE id = %s""", (cuenta_id,))
        cuenta = cur.fetchone()
        if not cuenta:
            return None
        cur.execute(
            """SELECT descripcion, valor FROM detalle_cuenta_cobro
               WHERE cuenta_id = %s ORDER BY id""", (cuenta_id,))
        items_db = cur.fetchall()

    cuenta = dict(cuenta)
    nit = (cuenta.get('cliente_nit') or '').strip()
    tipo_doc = 'NIT' if nit else 'CC'
    items = []
    for it in (dict(x) for x in items_db):
        items.append({
            "descripcion":     it.get('descripcion') or 'Servicio',
            "cantidad":        1,
            "precio_unitario": float(it.get('valor') or 0),
            "descuento":       0,
            "codigo_unidad":   "EA",
            "impuesto_iva":    0,   # honorarios de contratista: sin IVA por defecto
        })
    return {
        "referencia_pedido": cuenta.get('consecutivo') or f"CC-{cuenta_id}",
        "cliente": {
            "tipo_persona": "juridica" if tipo_doc == 'NIT' else "natural",
            "tipo_documento": tipo_doc,
            "numero_documento": _documento_adquiriente(nit),
            "nombre": cuenta.get('cliente_nombre') or 'Cliente',
            "email": _email_adquiriente(cuenta.get('cliente_email')),
            "telefono": cuenta.get('cliente_telefono') or '',
            "direccion": cuenta.get('cliente_direccion') or '',
            "municipio_codigo": _municipio_codigo(cuenta.get('cliente_ciudad')),
        },
        "items": items, "metodo_pago": "10", "moneda": "COP",
        "notas": f"Cuenta de cobro {cuenta.get('consecutivo') or cuenta_id}",
    }


def emitir_factura_cuenta_cobro(cuenta_id: int) -> dict:
    return _emitir_a_dian('cuentas_cobro', cuenta_id,
                          construir_json_cuenta_cobro(cuenta_id))


# ── Cotización aprobada ──────────────────────────────────────────────────────

def construir_json_cotizacion(cotizacion_id: int) -> dict | None:
    """Convierte una cotización (cotizaciones) al JSON DIAN."""
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute(
            # Opcionales según la antigüedad del tenant.
            f"""SELECT cliente_nombre, cliente_documento, cliente_direccion,
                      cliente_ciudad, cliente_telefono, total
                      {", cliente_email" if _table_has_column('cotizaciones', 'cliente_email') else ", NULL AS cliente_email"}
                      {", cliente_tipo_doc" if _table_has_column('cotizaciones', 'cliente_tipo_doc') else ", NULL AS cliente_tipo_doc"}
               FROM cotizaciones WHERE id = %s""", (cotizacion_id,))
        cot = cur.fetchone()
        if not cot:
            return None
        cur.execute(
            """SELECT descripcion, cantidad, precio_unitario, descuento_porc, iva_porc
               FROM detalle_cotizacion WHERE cotizacion_id = %s ORDER BY id""", (cotizacion_id,))
        items_db = cur.fetchall()

    cot = dict(cot)
    items = []
    for it in (dict(x) for x in items_db):
        cant = int(it.get('cantidad') or 1)
        precio = float(it.get('precio_unitario') or 0)
        desc_porc = float(it.get('descuento_porc') or 0)
        items.append({
            "descripcion":     it.get('descripcion') or 'Item',
            "cantidad":        cant,
            "precio_unitario": precio,
            "descuento":       round(cant * precio * desc_porc / 100, 2),
            "codigo_unidad":   "EA",
            "impuesto_iva":    float(it.get('iva_porc') or 0),
        })
    doc = _documento_adquiriente(cot.get('cliente_documento'))
    # El tipo de documento iba fijo en 'CC': una cotización a empresa salía como
    # persona natural con cédula. Si el tenant no tiene la columna, se mantiene
    # el comportamiento anterior (CC) en vez de adivinar.
    tipo_doc = TIPO_DOC_MAP.get(
        str(cot.get('cliente_tipo_doc') or '').strip().upper(), 'CC'
    )
    return {
        "referencia_pedido": f"COT-{cotizacion_id}",
        "cliente": {
            "tipo_persona": "juridica" if tipo_doc == 'NIT' else "natural",
            "tipo_documento": tipo_doc,
            "numero_documento": doc,
            "nombre": cot.get('cliente_nombre') or 'Cliente',
            "email": _email_adquiriente(cot.get('cliente_email')),
            "telefono": cot.get('cliente_telefono') or '',
            "direccion": cot.get('cliente_direccion') or '',
            "municipio_codigo": _municipio_codigo(cot.get('cliente_ciudad')),
        },
        "items": items, "metodo_pago": "48", "moneda": "COP",
        "notas": f"Cotización #{cotizacion_id} aprobada",
    }


def emitir_factura_cotizacion(cotizacion_id: int) -> dict:
    return _emitir_a_dian('cotizaciones', cotizacion_id,
                          construir_json_cotizacion(cotizacion_id))
