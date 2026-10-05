"""Mapa de intenciones: con qué palabras se pide cada capacidad.

Es una tabla corrida a propósito: aquí se lee de un vistazo QUÉ FUNCIÓN se
ejecuta con QUÉ PALABRAS, en qué canal y con qué motor. La otra mitad de la
declaración (qué consulta y qué permisos exige) vive junto a la función, en
`services/ia_datos/__init__.py`. `services/ia/registro.py` une las dos y falla
si se desfasan.

  disparadores  frases que enrutan SIN gastar modelo. Se comparan sin tildes,
                en minúsculas, como frase contenida en la pregunta. Poner las
                más específicas: entre dos que casen, gana la más larga.
  ejemplos      preguntas reales; alimentan el mapa y las pruebas del enrutador.
  canales       'panel' = dentro del admin (manda la matriz de permisos).
                'publico' = visitante anónimo del sitio. LISTA BLANCA: nada es
                público si no se declara aquí.
  motor         'A' cualquier motor sirve · 'B' se luce con el modelo bueno,
                pero degrada sin él · 'C' exige el profundo (no degrada).

Una capacidad puede tener `disparadores` vacíos: significa que no hay forma
confiable de reconocerla por palabras y se deja en manos del modelo. Se declara
igual, para que aparezca en el mapa.
"""

PANEL = ('panel',)
PUBLICO = ('publico',)

INTENCIONES = {
    # ── Servicio Técnico ──────────────────────────────────────
    'taller_estado': {
        'disparadores': ('como esta el taller', 'equipos en el taller', 'que hay en el taller',
                         'equipos listos', 'listos para entregar', 'equipos por entregar',
                         'ordenes de servicio', 'ordenes abiertas del taller', 'equipos en reparacion',
                         'carga de los tecnicos', 'entregas atrasadas'),
        'ejemplos': ('¿Cómo está el taller?', '¿Qué equipos están listos para entregar?',
                     '¿Hay entregas atrasadas?'),
        'canales': PANEL, 'motor': 'A',
    },
    'taller_seguimientos': {
        'disparadores': ('seguimientos del taller', 'clientes del taller por contactar',
                         'a quien llamar del taller', 'seguimiento de clientes del taller',
                         'calificaciones bajas', 'clientes inconformes', 'pendientes del taller'),
        'ejemplos': ('¿Qué seguimientos del taller tengo pendientes?',
                     '¿Hay calificaciones bajas de los clientes?'),
        'canales': PANEL, 'motor': 'A',
    },
    'taller_orden': {
        'disparadores': ('como va la orden', 'estado de la orden', 'detalle de la orden',
                         'que paso con la orden', 'informacion de la orden'),
        'ejemplos': ('¿Cómo va la orden OS-000012?', '¿Estado de la orden de Laura Gómez?'),
        'canales': PANEL, 'motor': 'A',
    },
    'taller_equipo_historial': {
        'disparadores': ('que equipos tiene', 'equipos del cliente', 'historial del equipo',
                         'ficha del equipo de', 'equipo con serial', 'equipo con imei'),
        'ejemplos': ('¿Qué equipos tiene Laura Gómez?', '¿Historial del equipo con serial PF3ABC12?'),
        'canales': PANEL, 'motor': 'A',
    },
    'taller_desempeno': {
        'disparadores': ('desempeno del taller', 'como le fue al taller', 'cuantas reparaciones',
                         'reparaciones del mes', 'satisfaccion de los clientes del taller',
                         'tiempo de reparacion', 'cuanto cobro el taller', 'ingresos del taller'),
        'ejemplos': ('¿Cómo le fue al taller este mes?', '¿Cuántas reparaciones hicimos el mes pasado?'),
        'canales': PANEL, 'motor': 'B',
    },

    # ── Ventas ────────────────────────────────────────────────
    'ventas_periodo': {
        'disparadores': ('cuanto vendi', 'cuanto vendimos', 'cuanto se vendio', 'cuanto he vendido',
                         'ventas de', 'ventas del', 'total de ventas', 'cuanto facture',
                         'como estuvieron las ventas', 'ingresos de'),
        'ejemplos': ('¿Cuánto vendí hoy?', '¿Cuánto vendimos el mes pasado?',
                     '¿Cómo estuvieron las ventas esta semana?'),
        'canales': PANEL, 'motor': 'A',
    },
    'comparativo_ventas': {
        'disparadores': ('compara mis ventas', 'comparacion de ventas', 'comparar ventas',
                         'crecieron mis ventas', 'cayeron mis ventas', 'variacion de ventas'),
        'ejemplos': ('¿Crecieron mis ventas este mes?', 'Compara mis ventas con el período anterior'),
        'canales': PANEL, 'motor': 'A',
    },
    'ticket_promedio': {
        'disparadores': ('ticket promedio', 'valor promedio por venta', 'promedio por venta',
                         'venta promedio'),
        'ejemplos': ('¿Cuál fue mi ticket promedio este mes?',),
        'canales': PANEL, 'motor': 'A',
    },
    'top_productos': {
        'disparadores': ('que se vende mas', 'producto mas vendido', 'productos mas vendidos',
                         'mas vendidos', 'lo que mas se vende', 'top de productos'),
        'ejemplos': ('¿Qué es lo que más se vende?', '¿Cuáles fueron los 5 más vendidos del mes?'),
        'canales': PANEL, 'motor': 'A',
    },
    'top_clientes': {
        'disparadores': ('mejores clientes', 'quien compra mas', 'clientes que mas compran',
                         'top de clientes'),
        'ejemplos': ('¿Quiénes son mis mejores clientes?',),
        'canales': PANEL, 'motor': 'A',
    },
    'patron_horario': {
        'disparadores': ('a que hora vendo', 'a que hora se vende', 'mejor hora', 'mejores horas',
                         'que dia se vende mas', 'mejor dia', 'horario de mas ventas'),
        'ejemplos': ('¿A qué hora vendo más?', '¿Cuál es mi mejor día de la semana?'),
        'canales': PANEL, 'motor': 'A',
    },
    'tendencia_ventas': {
        'disparadores': ('tendencia', 'van subiendo', 'van bajando', 'estoy vendiendo mas',
                         'estoy vendiendo menos', 'como vamos', 'proyeccion'),
        'ejemplos': ('¿Las ventas van subiendo o bajando?', '¿Cómo vamos este mes?'),
        'canales': PANEL, 'motor': 'B',
    },
    'segmentos_clientes': {
        'disparadores': ('segmentos', 'tipos de clientes', 'clientes frecuentes',
                         'agrupar clientes', 'clientes ocasionales'),
        'ejemplos': ('¿Qué tipos de clientes tengo?',),
        'canales': PANEL, 'motor': 'B',
    },
    'conteo_general': {
        'disparadores': ('numeros generales', 'resumen general', 'cuantos productos tengo',
                         'cuantos clientes tengo'),
        'ejemplos': ('Dame los números generales del negocio',),
        'canales': PANEL, 'motor': 'A',
    },
    'pedidos_por_despachar': {
        'disparadores': ('por despachar', 'falta despachar', 'pedidos pendientes de envio',
                         'que tengo que enviar'),
        'ejemplos': ('¿Qué pedidos tengo por despachar?',),
        'canales': PANEL, 'motor': 'A',
    },
    'pedidos_estado': {
        'disparadores': ('estado de los pedidos', 'van los pedidos', 'cuantos pedidos',
                         'los pedidos de', 'pedidos del'),
        'ejemplos': ('¿Cómo van los pedidos de este mes?',),
        'canales': PANEL, 'motor': 'A',
    },

    # ── Inventario ────────────────────────────────────────────
    'productos_bajo_stock': {
        'disparadores': ('stock bajo', 'bajo stock', 'se esta agotando', 'se me esta acabando',
                         'estan agotados', 'productos agotados', 'agotado',
                         'sin existencias', 'queda poco'),
        'ejemplos': ('¿Qué productos están agotados?', '¿Qué se me está acabando?'),
        'canales': PANEL, 'motor': 'A',
    },
    'sugerencia_reorden': {
        'disparadores': ('que debo comprar', 'que tengo que comprar', 'que reponer', 'que pedir',
                         'reorden', 'que se va a agotar'),
        'ejemplos': ('¿Qué debo comprar esta semana?',),
        'canales': PANEL, 'motor': 'B',
    },
    'catalogo_pendiente': {
        'disparadores': ('le falta a mi catalogo', 'falta a mi catalogo', 'catalogo incompleto',
                         'sin descripcion', 'sin imagen', 'productos sin foto'),
        'ejemplos': ('¿Qué le falta a mi catálogo?',),
        'canales': PANEL, 'motor': 'A',
    },
    'resumen_inventario': {
        'disparadores': ('vale todo mi inventario', 'vale mi inventario', 'vale el inventario',
                         'valor del inventario', 'cuantas unidades tengo',
                         'cuanta plata tengo en inventario'),
        'ejemplos': ('¿Cuánto vale todo mi inventario?',),
        'canales': PANEL, 'motor': 'A',
    },
    'inventario_por_categoria': {
        'disparadores': ('inventario por categoria', 'stock por categoria',
                         'existencias por categoria', 'agotados por categoria'),
        'ejemplos': ('¿Cómo está mi inventario por categoría?',),
        'canales': PANEL, 'motor': 'A',
    },
    'inventario_sin_rotacion': {
        'disparadores': ('no se estan vendiendo', 'no se venden', 'no se vende', 'sin rotacion',
                         'productos quietos', 'lleva sin venderse', 'plata parada'),
        'ejemplos': ('¿Qué productos no se están vendiendo?',),
        'canales': PANEL, 'motor': 'B',
    },
    'movimientos_inventario': {
        'disparadores': ('movimientos de inventario', 'entradas y salidas', 'ajustes de inventario'),
        'ejemplos': ('¿Qué movimientos de inventario hubo este mes?',),
        'canales': PANEL, 'motor': 'A',
    },
    'producto_detalle': {
        # Necesita el nombre del producto: el enrutador solo la usa si lo puede extraer.
        'disparadores': ('como va el producto', 'ficha del producto', 'detalle del producto'),
        'ejemplos': ('¿Cómo va el producto Camiseta Azul?',),
        'canales': PANEL, 'motor': 'A',
    },

    # ── Finanzas ──────────────────────────────────────────────
    'finanzas_periodo': {
        'disparadores': ('ingresos y egresos', 'cuanto gane', 'cuanta ganancia', 'utilidad del',
                         'balance del', 'gastos del', 'cuanto gaste'),
        'ejemplos': ('¿Cuánto gané este mes?', '¿Cuáles fueron mis gastos del mes pasado?'),
        'canales': PANEL, 'motor': 'A',
    },
    'proveedores': {
        'disparadores': ('proveedores', 'proveedor', 'a quien le compro', 'a quien le compramos',
                         'pagos a proveedores', 'mis proveedores'),
        'ejemplos': ('¿Quiénes son mis proveedores?', '¿Cuánto les pagué a los proveedores este mes?'),
        'canales': PANEL, 'motor': 'A',
    },
    'margenes_productos': {
        'disparadores': ('margen', 'rentabilidad', 'dejan mas ganancia', 'deja mas ganancia',
                         'cual deja mas', 'utilidad por producto'),
        'ejemplos': ('¿Qué productos me dejan más ganancia?',),
        'canales': PANEL, 'motor': 'B',
    },

    # ── Caja ──────────────────────────────────────────────────
    'caja_estado': {
        'disparadores': ('en caja', 'arqueo', 'cierre de caja', 'cuadre de caja'),
        'ejemplos': ('¿Cuánto hay en caja?', '¿Cómo va el arqueo de hoy?'),
        'canales': PANEL, 'motor': 'A',
    },
    'metodos_pago': {
        'disparadores': ('metodos de pago', 'formas de pago', 'me estan pagando', 'como me pagan',
                         'cuanto en efectivo', 'efectivo o tarjeta'),
        'ejemplos': ('¿Cómo me están pagando los clientes?',),
        'canales': PANEL, 'motor': 'A',
    },
    'anulaciones_pos': {
        'disparadores': ('anulaciones pos', 'ventas anuladas pos',
                         'notas de credito pos', 'ventas anuladas del mostrador'),
        'ejemplos': ('¿Cuántas anulaciones POS hubo este mes?',),
        'canales': PANEL, 'motor': 'A',
    },

    # ── Clientes ──────────────────────────────────────────────
    'cliente_historial': {
        # Necesita el nombre del cliente.
        'disparadores': ('que ha comprado', 'historial de', 'compras de'),
        'ejemplos': ('¿Qué ha comprado Ana Pérez?',),
        'canales': PANEL, 'motor': 'A',
    },

    # ── Comercial ─────────────────────────────────────────────
    'crm_pipeline': {
        'disparadores': ('oportunidades', 'pipeline', 'negocios en curso', 'embudo',
                         'negocios puedo cerrar', 'puedo cerrar'),
        'ejemplos': ('¿Cómo va el pipeline?', '¿Qué negocios puedo cerrar este mes?'),
        'canales': PANEL, 'motor': 'B',
    },
    'crm_seguimiento': {
        'disparadores': ('tareas pendientes', 'tengo que llamar', 'a quien llamar', 'seguimiento',
                         'tareas vencidas', 'que tengo que hacer hoy'),
        'ejemplos': ('¿A quién tengo que llamar hoy?',),
        'canales': PANEL, 'motor': 'A',
    },
    'tareas_pendientes': {
        'disparadores': ('mis tareas', 'tareas pendientes con id', 'lista de tareas',
                         'que tareas tengo', 'muestrame las tareas', 'tareas por hacer'),
        'ejemplos': ('¿Qué tareas tengo?', 'Muéstrame las tareas pendientes'),
        'canales': PANEL, 'motor': 'A',
    },
    'buscar_contactos': {
        'disparadores': ('busca el contacto', 'buscar contacto', 'buscar el contacto',
                         'datos del contacto', 'ficha del contacto', 'id del contacto',
                         'mis contactos', 'lista de contactos', 'muestrame los contactos',
                         'telefono del contacto', 'correo del contacto'),
        'ejemplos': ('Busca el contacto Cybershop', '¿Cuál es el ID del contacto Andes?'),
        'canales': PANEL, 'motor': 'A',
    },
    'cotizaciones_estado': {
        'disparadores': ('cotizaciones', 'cuantas cotizaciones', 'cotizaciones aprobadas',
                         'cotizaciones sin respuesta', 'cotizaciones pendientes', 'cotizaciones rechazadas',
                         'cuanto he cotizado', 'cuanto cotice', 'cuanto cotizamos', 'cuanto hemos cotizado',
                         'monto cotizado', 'tasa de aprobacion', 'cotizacion mas grande',
                         'cotizaciones mas grandes', 'le he cotizado mas', 'le cotizo mas',
                         'presupuestos', 'propuestas enviadas', 'propuestas comerciales'),
        'ejemplos': ('¿Cómo van mis cotizaciones?', '¿Cuánto he cotizado este año?',
                     '¿Cuántos presupuestos envié este mes?', '¿Cuál fue la cotización más grande del mes?'),
        'canales': PANEL, 'motor': 'A',
    },
    'cotizacion_detalle': {
        'disparadores': ('la cotizacion de', 'la cotizacion', 'cotizacion numero', 'cotizacion de',
                         'le cotizamos a', 'le cotice a', 'el presupuesto de', 'la propuesta de'),
        'ejemplos': ('¿Qué le cotizamos a Juan Pérez?', 'Muéstrame la cotización COT 0000000012',
                     '¿Ya me aprobaron la cotización de Juan Pérez?', '¿Cuánto fue la cotización 15?'),
        'canales': PANEL, 'motor': 'A',
    },
    'cuentas_cobro_periodo': {
        'disparadores': ('cuentas de cobro', 'cuentas emitidas', 'cuantas cuentas de cobro',
                         'facture en cuentas de cobro', 'honorarios', 'cuentas de cobro que hice',
                         'pase cuentas de cobro'),
        'ejemplos': ('¿Cuántas cuentas de cobro emití este mes?', '¿Cuánto facturé en cuentas de cobro este año?',
                     '¿Cuánto he facturado en honorarios este año?'),
        'canales': PANEL, 'motor': 'A',
    },
    'cuenta_cobro_detalle': {
        'disparadores': ('la cuenta de cobro de', 'la cuenta de cobro', 'cuenta de cobro de',
                         'cuenta de cobro numero', 'la cuenta cc'),
        'ejemplos': ('Muéstrame la cuenta de cobro de María López', '¿Ya pagaron la cuenta de cobro CC-0007?'),
        'canales': PANEL, 'motor': 'A',
    },
    'cartera_pendiente': {
        'disparadores': ('cuanto me deben', 'quien me debe', 'quienes me deben', 'me deben', 'cartera',
                         'por cobrar', 'sin cobrar', 'pendiente de pago', 'pendientes de pago',
                         'no me han pagado', 'no han pagado', 'no me pagan', 'morosos', 'en mora', 'deudores',
                         'facturas vencidas', 'cuentas vencidas', 'facturas estan vencidas',
                         'cuentas estan vencidas', 'cobros vencidos', 'pagos pendientes', 'lo que me deben'),
        'ejemplos': ('¿Cuánto me deben?', '¿Qué está vencido sin cobrar?', '¿Quiénes no me han pagado?',
                     '¿Qué clientes están morosos?'),
        'canales': PANEL, 'motor': 'A',
    },
    'cobros_recibidos': {
        'disparadores': ('cuanto cobre', 'cuanto he cobrado', 'cuanto hemos cobrado', 'cuanto me pagaron',
                         'cuanto nos pagaron', 'pagos recibidos', 'pagos que recibi', 'que pagos recibi',
                         'quien me pago', 'quienes me pagaron', 'cuanto recaude', 'recaudo del'),
        'ejemplos': ('¿Cuánto cobré este mes?', '¿Cuánto me pagaron esta semana?', '¿Qué pagos recibí este mes?'),
        'canales': PANEL, 'motor': 'A',
    },
    'resenas_estado': {
        'disparadores': ('resenas', 'calificaciones', 'que opinan los clientes', 'estrellas',
                         'comentarios de los clientes'),
        'ejemplos': ('¿Qué opinan los clientes de mis productos?',),
        'canales': PANEL, 'motor': 'A',
    },

    # ── Operación ─────────────────────────────────────────────
    'cupones_desempeno': {
        'disparadores': ('cupones', 'codigos de descuento', 'promociones'),
        'ejemplos': ('¿Cómo van los cupones?',),
        'canales': PANEL, 'motor': 'A',
    },
    'deseos_demanda': {
        'disparadores': ('lista de deseos', 'favoritos', 'lo que quieren los clientes'),
        'ejemplos': ('¿Qué están guardando en favoritos?',),
        'canales': PANEL, 'motor': 'A',
    },
    'soporte_estado': {
        'disparadores': ('tickets', 'soporte', 'reclamos', 'pqr'),
        'ejemplos': ('¿Cómo va el soporte?',),
        'canales': PANEL, 'motor': 'A',
    },
    'fe_pendiente': {
        'disparadores': ('facturacion electronica', 'facturas sin enviar', 'dian'),
        'ejemplos': ('¿Qué ventas me faltan por facturar a la DIAN?',),
        'canales': PANEL, 'motor': 'A',
    },

    # ── Restaurante ───────────────────────────────────────────
    'restaurante_ahora': {
        'disparadores': ('las mesas', 'mesas abiertas', 'como va el salon', 'mesas ocupadas'),
        'ejemplos': ('¿Cómo van las mesas?',),
        'canales': PANEL, 'motor': 'A',
    },
    'restaurante_desempeno': {
        'disparadores': ('le fue al restaurante', 'rotacion de mesas', 'desempeno del restaurante',
                         'ventas del restaurante'),
        'ejemplos': ('¿Cómo le fue al restaurante esta semana?',),
        'canales': PANEL, 'motor': 'A',
    },

    # ── Nómina (sensible: solo dueño y contador) ──────────────
    'nomina_resumen': {
        'disparadores': ('nomina', 'planilla', 'cuanto pago de sueldos'),
        'ejemplos': ('¿Cuánto pagué de nómina este mes?',),
        'canales': PANEL, 'motor': 'A',
    },
    'nomina_empleado': {
        # Necesita el nombre del empleado.
        'disparadores': ('cuanto gana', 'salario de', 'sueldo de'),
        'ejemplos': ('¿Cuánto gana Juan Gómez?',),
        'canales': PANEL, 'motor': 'A',
    },

    # ── Documentos internos (los escribe el dueño; nunca públicos) ─
    'documentos_internos': {
        # Necesita el tema: lo que viene después de la frase disparadora.
        'disparadores': ('procedimiento', 'procedimientos', 'protocolo', 'politica de',
                         'politicas de', 'politica del', 'manual de', 'manual del',
                         'segun el manual', 'reglamento', 'instructivo',
                         'documento interno', 'documentos internos'),
        'ejemplos': ('¿Cuál es el procedimiento para abrir el local?',
                     '¿Qué dice la política de cambios?',
                     'Muéstrame el protocolo de bioseguridad'),
        'canales': PANEL, 'motor': 'A',
    },

    # ── General ───────────────────────────────────────────────
    'alertas_negocio': {
        'disparadores': ('que debo atender', 'alertas', 'que esta mal', 'que revisar hoy',
                         'que necesita mi atencion'),
        'ejemplos': ('¿Qué debo atender hoy?',),
        'canales': PANEL, 'motor': 'B',
    },
    'calidad_datos': {
        'disparadores': ('calidad de datos', 'datos incompletos', 'que falta por llenar',
                         'datos me faltan', 'falta por completar'),
        'ejemplos': ('¿Qué datos me faltan por completar?',),
        'canales': PANEL, 'motor': 'A',
    },
    # ── Sitio público (módulo ai_public) ──────────────────────
    # Lo ÚNICO que ve un visitante anónimo. El canal está declarado aquí y en
    # ninguna otra parte: si no dice 'publico', no se expone.
    'buscar_productos': {
        'disparadores': ('tienen', 'tienes', 'venden', 'cuanto vale', 'cuanto cuesta',
                         'precio de', 'busco', 'estoy buscando', 'necesito',
                         'quiero comprar', 'quisiera comprar', 'me gustaria comprar',
                         'necesito comprar', 'quiero', 'quisiera'),
        'ejemplos': ('¿Tienen gaseosa?', '¿Cuánto vale el jugo natural?', 'Busco una camiseta'),
        'canales': PUBLICO, 'motor': 'A',
    },
    'categorias_publicas': {
        'disparadores': ('que venden', 'que productos manejan', 'que categorias',
                         'que puedo comprar'),
        'ejemplos': ('¿Qué productos manejan?', '¿Qué venden?'),
        'canales': PUBLICO, 'motor': 'A',
    },
    'servicios_publicos': {
        'disparadores': ('que servicios', 'prestan servicio', 'hacen mantenimiento',
                         'hacen instalacion', 'tienen servicio de', 'tienen servicio',
                         'ofrecen'),
        'ejemplos': ('¿Qué servicios prestan?', '¿Hacen mantenimiento?'),
        'canales': PUBLICO, 'motor': 'A',
    },
    'datos_del_negocio': {
        'disparadores': ('donde quedan', 'donde estan', 'direccion', 'telefono', 'whatsapp',
                         'como los contacto', 'a que hora', 'horario', 'abren'),
        'ejemplos': ('¿Dónde quedan?', '¿Cuál es el teléfono?', '¿A qué hora abren?'),
        'canales': PUBLICO, 'motor': 'A',
    },
    'como_comprar': {
        'disparadores': ('como compro', 'como puedo comprar', 'como hago el pedido', 'como comprar',
                         'como se compra', 'como hago una compra',
                         'puedo comprar en linea', 'como pido'),
        'ejemplos': ('¿Cómo compro?', '¿Puedo comprar en línea?'),
        'canales': PUBLICO, 'motor': 'A',
    },
}
