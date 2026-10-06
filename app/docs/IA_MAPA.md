# Mapa del Asistente IA

> **Generado**: no editar a mano. Sale de `services/ia/registro.py` +
> `services/ia/intenciones.py`. Para regenerarlo: `python tools/ia_mapa.py`.

Así decide el asistente qué hacer con una pregunta:

1. **Palabras clave** (`services/ia/enrutador.py`): si la pregunta contiene una de las frases
   de la columna «Se dispara con», se ejecuta esa función **sin gastar modelo**.
2. **Índice de textos** (RAG, `services/ia_rag/`): para preguntas de prosa —envíos, garantía,
   quiénes somos— se busca en los documentos del negocio.
3. **El modelo elige**: si nada de lo anterior aplica, se le muestra el catálogo y responde
   con un JSON indicando qué función usar. **Nunca escribe SQL.**

En todos los casos, los datos los pone la consulta: el modelo solo redacta con lo que recibe.

**Capacidades registradas: 60**

## Caja

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `anulaciones_pos` | Cuántas notas de crédito POS se emitieron en un período y por cuánto; no incluye web ni escritorio. | `se anularon` · `ventas anuladas` · `anulaciones del pos` · `ventas que se anularon` · `anulaciones pos` · `ventas anuladas pos` · `notas de credito pos` · `ventas anuladas del mostrador` | periodo | Panel | A · cualquiera | pos |
| `caja_estado` | Estado de la caja: turno abierto, cuánto efectivo debería haber y los últimos cuadres con faltantes o sobrantes. | `en la caja` · `la caja` · `cerraron la caja` · `cerro la caja` · `caja abierta` · `turno de caja` · `deberia haber en caja` · `en caja` · `arqueo` · `cierre de caja` · `cuadre de caja` | — | Panel | A · cualquiera | caja · módulo caja |
| `metodos_pago` | Con qué le pagan los clientes: efectivo, tarjeta, transferencias, y cuánto pesa cada medio. | `cuanto entro en efectivo` · `por transferencia` · `por nequi` · `por daviplata` · `con tarjeta` · `en efectivo y` · `metodos de pago` · `formas de pago` · `me estan pagando` · `como me pagan` · `cuanto en efectivo` · `efectivo o tarjeta` | periodo | Panel | A · cualquiera | pos |

## Catalogo_publico

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `buscar_productos` | Busca productos del catálogo público por nombre o categoría, con precio y disponibilidad. | `manejan` · `tendran` · `consiguen` · `tienen` · `tienes` · `venden` · `cuanto vale` · `cuanto cuesta` · `precio de` · `busco` · `estoy buscando` · `necesito` · `quiero comprar` · `quisiera comprar` · `me gustaria comprar` · `necesito comprar` · `quiero` · `quisiera` | texto, limite | Público | A · cualquiera | cualquiera del panel · módulo ai_public |
| `categorias_publicas` | Qué categorías de producto maneja la tienda. | `que venden` · `que productos manejan` · `que categorias` · `que puedo comprar` | — | Público | A · cualquiera | cualquiera del panel · módulo ai_public |
| `como_comprar` | Cómo se compra en este sitio: tienda en línea o por contacto. | `hago un pedido` · `hacer un pedido` · `como hago un pedido` · `como compro` · `como puedo comprar` · `como hago el pedido` · `como comprar` · `como se compra` · `como hago una compra` · `puedo comprar en linea` · `como pido` | — | Público | A · cualquiera | cualquiera del panel · módulo ai_public |
| `datos_del_negocio` | Dirección, teléfono, WhatsApp, correo y horario del negocio. | `donde quedan` · `donde estan` · `direccion` · `telefono` · `whatsapp` · `como los contacto` · `a que hora` · `horario` · `abren` | — | Público | A · cualquiera | cualquiera del panel · módulo ai_public |
| `servicios_publicos` | Servicios que presta el negocio, según su sitio. | `reparan` · `arreglan` · `reparacion de` · `arreglo de` · `hacen reparacion` · `revisan` · `que servicios` · `prestan servicio` · `hacen mantenimiento` · `hacen instalacion` · `tienen servicio de` · `tienen servicio` · `ofrecen` | — | Público | A · cualquiera | cualquiera del panel · módulo ai_public |

## Clientes

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `cliente_historial` | Historial de compras de UN cliente por su nombre: cuántas veces compró, cuánto, cuándo fue la última vez y qué se lleva. | `que ha comprado` · `historial de` · `compras de` | cliente | Panel | A · cualquiera | orders |
| `segmentos_clientes` | Agrupa a los clientes en segmentos (fieles, nuevos, en riesgo, ocasionales) con análisis estadístico, para saber a quién cuidar o recuperar. | `dejaron de comprar` · `clientes perdidos` · `clientes en riesgo` · `ya no compran` · `no han vuelto a comprar` · `segmentos` · `tipos de clientes` · `clientes frecuentes` · `agrupar clientes` · `clientes ocasionales` | — | Panel | B · mejor con el bueno | cualquiera del panel |
| `top_clientes` | Clientes que más han comprado. | `top 3 clientes` · `top 5 clientes` · `top 10 clientes` · `clientes top` · `quien me compra mas` · `quienes me compran mas` · `clientes que mas me compran` · `cliente que mas compra` · `mejores clientes` · `quien compra mas` · `clientes que mas compran` · `top de clientes` | limite | Panel | A · cualquiera | cualquiera del panel |

## Comercial

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `buscar_contactos` | Busca contactos del CRM (clientes, proveedores, leads, socios) por nombre, empresa, correo o teléfono y muestra su ID y datos de contacto. Sin nombre, los más recientes. | `busca el contacto` · `buscar contacto` · `buscar el contacto` · `datos del contacto` · `ficha del contacto` · `id del contacto` · `mis contactos` · `lista de contactos` · `muestrame los contactos` · `telefono del contacto` · `correo del contacto` | texto, limite | Panel | A · cualquiera | crm · módulo crm |
| `cartera_pendiente` | Cartera por cobrar (lo que le DEBEN): cotizaciones aprobadas y cuentas de cobro que todavía no han pagado, cuánto suman, quién debe (deudores, morosos) y qué está vencido y hace cuántos días. | `cuanto me deben` · `quien me debe` · `quienes me deben` · `me deben` · `cartera` · `por cobrar` · `sin cobrar` · `pendiente de pago` · `pendientes de pago` · `no me han pagado` · `no han pagado` · `no me pagan` · `morosos` · `en mora` · `deudores` · `facturas vencidas` · `cuentas vencidas` · `facturas estan vencidas` · `cuentas estan vencidas` · `cobros vencidos` · `pagos pendientes` · `lo que me deben` | — | Panel | A · cualquiera | billing · módulo billing |
| `cobros_recibidos` | Lo que de verdad le PAGARON en un período (dinero recibido): cotizaciones y cuentas de cobro marcadas como pagadas, por fecha de pago, quién pagó y los últimos pagos. No es lo que le deben (eso es cartera_pendiente) ni las ventas de la tienda. | `recibi en pagos` · `cuanto recibi` · `pagos que me hicieron` · `me han pagado` · `cuanto cobre` · `cuanto he cobrado` · `cuanto hemos cobrado` · `cuanto me pagaron` · `cuanto nos pagaron` · `pagos recibidos` · `pagos que recibi` · `que pagos recibi` · `quien me pago` · `quienes me pagaron` · `cuanto recaude` · `recaudo del` | periodo | Panel | A · cualquiera | billing · módulo billing |
| `cotizacion_detalle` | UNA cotización por su número (COT 0000000012 o 12) o las cotizaciones de UN cliente por su nombre: qué incluye, por cuánto, si la aprobaron o rechazaron, días sin respuesta y si ya la pagaron. | `la cotizacion de` · `la cotizacion` · `cotizacion numero` · `cotizacion de` · `le cotizamos a` · `le cotice a` · `el presupuesto de` · `la propuesta de` | texto | Panel | A · cualquiera | quotes · módulo quotes |
| `cotizaciones_estado` | Resumen de las cotizaciones (presupuestos, propuestas) de un período: cuántas y por cuánto se cotizó, cuántas se aprobaron, rechazaron o siguen pendientes, tasa de aprobación, las más grandes, a qué clientes se les cotiza más y cuáles llevan días sin respuesta. Para UNA cotización usa cotizacion_detalle. | `cotizaciones` · `cuantas cotizaciones` · `cotizaciones aprobadas` · `cotizaciones sin respuesta` · `cotizaciones pendientes` · `cotizaciones rechazadas` · `cuanto he cotizado` · `cuanto cotice` · `cuanto cotizamos` · `cuanto hemos cotizado` · `monto cotizado` · `tasa de aprobacion` · `cotizacion mas grande` · `cotizaciones mas grandes` · `le he cotizado mas` · `le cotizo mas` · `presupuestos` · `propuestas enviadas` · `propuestas comerciales` | periodo | Panel | A · cualquiera | quotes · módulo quotes |
| `crm_pipeline` | Negocios y oportunidades en curso del CRM: cuánto hay por etapa, cuánto se espera cerrar, ganados y perdidos, y qué cierra pronto. | `negocios tengo en curso` · `negocios abiertos` · `ventas en proceso` · `negocios por cerrar` · `oportunidades` · `pipeline` · `negocios en curso` · `embudo` · `negocios puedo cerrar` · `puedo cerrar` | — | Panel | B · mejor con el bueno | crm · módulo crm |
| `crm_seguimiento` | A quién hay que atender hoy: tareas vencidas o del día por responsable y clientes sin contacto hace más de un mes. | `tareas pendientes` · `tengo que llamar` · `a quien llamar` · `seguimiento` · `tareas vencidas` · `que tengo que hacer hoy` | — | Panel | A · cualquiera | crm · módulo crm |
| `cuenta_cobro_detalle` | UNA cuenta de cobro por su número (CC-0007) o las cuentas de cobro de UN cliente por su nombre: labores cobradas, valor, si ya la pagaron, cuándo vence y cuántos días de mora lleva. | `la cuenta de cobro de` · `la cuenta de cobro` · `cuenta de cobro de` · `cuenta de cobro numero` · `la cuenta cc` | texto | Panel | A · cualquiera | billing · módulo billing |
| `cuentas_cobro_periodo` | Resumen de las cuentas de cobro (honorarios, cobros a clientes) emitidas en un período: cuántas, por cuánto, a qué clientes y cuánto de eso sigue sin pagarse. Para UNA cuenta usa cuenta_cobro_detalle. | `cuentas de cobro` · `cuentas emitidas` · `cuantas cuentas de cobro` · `facture en cuentas de cobro` · `honorarios` · `cuentas de cobro que hice` · `pase cuentas de cobro` | periodo | Panel | A · cualquiera | billing · módulo billing |
| `resenas_estado` | Reseñas de los clientes: calificación promedio, cuáles faltan por aprobar o responder y los productos peor calificados. | `me califican` · `que dicen los clientes` · `calificacion de mis productos` · `opiniones de los clientes` · `resenas` · `calificaciones` · `que opinan los clientes` · `estrellas` · `comentarios de los clientes` | — | Panel | A · cualquiera | content |
| `tareas_pendientes` | Tareas pendientes del CRM con su ID, contacto, prioridad y fecha de vencimiento (primero las vencidas), para completarlas o cambiarlas. | `mis tareas` · `tareas pendientes con id` · `lista de tareas` · `que tareas tengo` · `muestrame las tareas` · `tareas por hacer` | limite | Panel | A · cualquiera | crm · módulo crm |

## Documentos

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `documentos_internos` | Busca en los documentos internos que escribió el dueño —procedimientos, políticas, manuales, instructivos— lo que responde la pregunta: cómo se hace algo o qué dice una política interna. | `procedimiento` · `procedimientos` · `protocolo` · `politica de` · `politicas de` · `politica del` · `manual de` · `manual del` · `segun el manual` · `reglamento` · `instructivo` · `documento interno` · `documentos internos` | texto | Panel | A · cualquiera | ai_assistant |

## Finanzas

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `finanzas_periodo` | Ingresos, egresos y UTILIDAD (ganancia) de un período, con los gastos por concepto y la comparación con el período anterior. | `cuanta utilidad` · `utilidad dejo` · `cuanto deje de utilidad` · `se me fue la plata` · `en que se fue la plata` · `en que gaste` · `ganando o perdiendo` · `estoy ganando` · `estoy perdiendo` · `me quedo de ganancia` · `cuanto me quedo` · `ganancia del` · `cuanto me queda libre` · `ingresos y egresos` · `cuanto gane` · `cuanta ganancia` · `utilidad del` · `balance del` · `gastos del` · `cuanto gaste` | periodo | Panel | A · cualquiera | accounting · módulo accounting |
| `margenes_productos` | Cuánto deja cada producto (precio menos costo): los más y menos rentables y los vendidos por debajo del costo. | `margen` · `rentabilidad` · `dejan mas ganancia` · `deja mas ganancia` · `cual deja mas` · `utilidad por producto` | periodo, limite | Panel | B · mejor con el bueno | accounting |
| `proveedores` | Proveedores del negocio: a quién le compra (contactos de tipo proveedor del CRM) y cuánto les ha pagado según la contabilidad, con los últimos pagos. | `proveedores` · `proveedor` · `a quien le compro` · `a quien le compramos` · `pagos a proveedores` · `mis proveedores` | periodo, limite | Panel | A · cualquiera | accounting · módulo accounting |

## General

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `alertas_negocio` | Qué conviene atender HOY: stock agotado, caja sin cerrar, mesas abiertas, pedidos sin despachar, tareas vencidas, ventas anormales y demás avisos. | `algo urgente` · `que es urgente` · `que hay pendiente hoy` · `hay algo pendiente` · `que me toca revisar` · `que debo atender` · `alertas` · `que esta mal` · `que revisar hoy` · `que necesita mi atencion` | — | Panel | B · mejor con el bueno | cualquiera del panel |
| `calidad_datos` | Qué le falta a los datos del negocio para que la IA y los reportes sirvan mejor: ventas sin cliente identificado, productos sin costo, catálogo incompleto. | `calidad de datos` · `datos incompletos` · `que falta por llenar` · `datos me faltan` · `falta por completar` | — | Panel | A · cualquiera | cualquiera del panel |
| `conteo_general` | Números generales: productos, categorías, clientes, pedidos. | `numeros generales` · `resumen general` · `cuantos productos tengo` · `cuantos clientes tengo` | — | Panel | A · cualquiera | cualquiera del panel |

## Inventario

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `catalogo_pendiente` | Qué falta por completar en el catálogo (sin descripción, imagen o categoría). | `no tienen foto` · `sin fotos` · `no tienen imagen` · `no tienen descripcion` · `productos incompletos` · `le falta a mi catalogo` · `falta a mi catalogo` · `catalogo incompleto` · `sin descripcion` · `sin imagen` · `productos sin foto` | — | Panel | A · cualquiera | cualquiera del panel |
| `inventario_por_categoria` | Productos, unidades y agotados por categoría; valor del stock a precio de venta. | `inventario por categoria` · `stock por categoria` · `existencias por categoria` · `agotados por categoria` | — | Panel | A · cualquiera | inventory |
| `inventario_sin_rotacion` | SOLO los productos que no se venden hace meses: cuáles son y cuánta plata está detenida o dormida en ellos. | `estancado` · `estancados` · `estancada` · `mercancia parada` · `no salen` · `productos parados` · `quieto` · `quieta` · `sin venderse` · `mercancia quieta` · `no se mueve` · `no rota` · `no se han vendido` · `no se estan vendiendo` · `no se venden` · `no se vende` · `sin rotacion` · `productos quietos` · `lleva sin venderse` · `plata parada` | — | Panel | B · mejor con el bueno | inventory |
| `movimientos_inventario` | Movimientos de inventario de un período: entradas, salidas y ajustes, con sus motivos (mermas, daños, correcciones). | `movimientos de inventario` · `entradas y salidas` · `ajustes de inventario` | periodo | Panel | A · cualquiera | inventory |
| `producto_detalle` | Ficha de UN producto por su nombre: precio, stock, cuánto se vendió en 90 días, cuándo fue su última venta, si se agota pronto y cómo lo califican. | `como va el producto` · `ficha del producto` · `detalle del producto` | producto | Panel | A · cualquiera | inventory |
| `productos_bajo_stock` | Productos con stock bajo o agotados (parámetro: umbral). | `falta en inventario` · `hace falta en inventario` · `falta en bodega` · `se acabaron` · `se acabo` · `poco stock` · `pocas unidades` · `sin stock` · `quedan pocos` · `que me queda poco` · `stock bajo` · `bajo stock` · `se esta agotando` · `se me esta acabando` · `estan agotados` · `productos agotados` · `agotado` · `sin existencias` · `queda poco` | umbral | Panel | A · cualquiera | cualquiera del panel |
| `resumen_inventario` | Cuánto vale TODO el inventario y cuántas unidades hay en total (sin distinguir si rotan o no). | `plata tengo en mercancia` · `plata en mercancia` · `vale la mercancia` · `cuanto tengo en mercancia` · `valor de la mercancia` · `vale todo mi inventario` · `vale mi inventario` · `vale el inventario` · `valor del inventario` · `cuantas unidades tengo` · `cuanta plata tengo en inventario` | — | Panel | A · cualquiera | cualquiera del panel |
| `sugerencia_reorden` | Qué comprar/reponer pronto: productos que se agotan según su ritmo de venta, con cantidad sugerida. | `lista de compras` · `compras para el proveedor` · `pedido al proveedor` · `toca pedir` · `pedir al proveedor` · `que pido` · `que toca comprar` · `que hay que pedir` · `que debo pedir` · `que debo comprar` · `que tengo que comprar` · `que reponer` · `que pedir` · `reorden` · `que se va a agotar` | — | Panel | B · mejor con el bueno | cualquiera del panel |

## Nomina

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `nomina_empleado` | Datos de pago de UN empleado por su nombre: cargo, antigüedad, salario base, su última liquidación y sus provisiones. | `cuanto le pago a` · `le pago a` · `cuanto se le paga a` · `cuanto gana` · `salario de` · `sueldo de` | empleado | Panel | A · cualquiera | payroll · **sensible: nomina** · módulo payroll |
| `nomina_resumen` | Cuánto cuesta la nómina en un período: devengado, deducciones, neto pagado, aportes del empleador, provisiones y costo por cargo. | `cuestan los empleados` · `cuanto me cuestan los empleados` · `costo de los empleados` · `pago a los empleados` · `costo de la nomina` · `nomina` · `planilla` · `cuanto pago de sueldos` | periodo | Panel | A · cualquiera | payroll · **sensible: nomina** · módulo payroll |

## Operacion

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `cupones_desempeno` | Cupones de descuento: cuántos se usaron, cuánto descuento se entregó y cuáles son los más usados. | `cupones` · `codigos de descuento` · `promociones` | periodo | Panel | A · cualquiera | coupons · módulo coupons |
| `deseos_demanda` | Productos que los clientes guardan en su lista de deseos, sobre todo los agotados: demanda que se está perdiendo. | `lista de deseos` · `favoritos` · `lo que quieren los clientes` | — | Panel | A · cualquiera | wishlist · módulo wishlist |
| `fe_pendiente` | Facturación electrónica: qué ventas ya tienen factura y cuáles no (solo consulta, no emite nada). | `factura electronica` · `sin factura` · `no tienen factura` · `facturas electronicas` · `facturacion electronica` · `facturas sin enviar` · `dian` | periodo | Panel | A · cualquiera | facturacion_electronica · módulo facturacion_electronica |
| `soporte_estado` | Tickets de soporte: abiertos, sin respuesta del negocio y los más antiguos. | `tickets` · `soporte` · `reclamos` · `pqr` | — | Panel | A · cualquiera | support · módulo support |

## Pedidos

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `pedidos_estado` | Pedidos de la tienda web por estado de pago y envío, y los pagados que llevan más de 48 horas sin despachar. | `estado de los pedidos` · `van los pedidos` · `cuantos pedidos` · `los pedidos de` · `pedidos del` | periodo | Panel | A · cualquiera | orders |
| `pedidos_por_despachar` | Pedidos web pagados pendientes de enviar. | `por mandar` · `faltan por despachar` · `sin despachar` · `faltan por enviar` · `falta por enviar` · `por enviar` · `pendiente por enviar` · `pedidos sin enviar` · `por despachar` · `falta despachar` · `pedidos pendientes de envio` · `que tengo que enviar` | — | Panel | A · cualquiera | cualquiera del panel |

## Restaurante

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `restaurante_ahora` | Cómo está el salón AHORA: mesas ocupadas o libres, cuentas abiertas, cuánto llevan consumido y cuáles se demoran. | `mesas hay ocupadas` · `mesas hay libres` · `mesas hay abiertas` · `mesas estan ocupadas` · `mesas libres` · `mesas estan libres` · `como esta el salon` · `las mesas` · `mesas abiertas` · `como va el salon` · `mesas ocupadas` | — | Panel | A · cualquiera | restaurant_tables · módulo restaurant_tables |
| `restaurante_desempeno` | Cómo le fue al restaurante en un período: mesas atendidas, ticket por mesa y por persona, duración, horas pico, platos más pedidos y anulaciones. | `plato mas pedido` · `platos mas pedidos` · `lo que mas piden en el restaurante` · `plato que mas se vende` · `le fue al restaurante` · `rotacion de mesas` · `desempeno del restaurante` · `ventas del restaurante` | periodo | Panel | A · cualquiera | restaurant_tables · módulo restaurant_tables |

## Servicio_tecnico

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `taller_casos` | Historial de casos del servicio técnico: qué equipo se atendió, qué falla o novedad tuvo y cómo se solucionó. Busca por cliente, marca, modelo, serial, tipo de equipo (computador, celular…) o por la falla (pantalla, no carga, virus…). Sin texto: los últimos casos atendidos. | `que novedad tuvo` · `que falla tuvo` · `que problema tuvo` · `que le paso al` · `que le paso a la` · `como se soluciono` · `como solucionamos` · `como se arreglo` · `cual fue la solucion` · `casos del taller` · `equipos con problema de` · `equipos con falla de` · `computadores con` · `celulares con` · `cual fue el ultimo` · `que equipos atendimos` · `que computadores atendimos` · `que celulares atendimos` · `equipos atendidos` · `casos atendidos` · `historial de casos` | texto, limite | Panel | A · cualquiera | servicio_tecnico · módulo servicio_tecnico |
| `taller_desempeno` | Cómo le fue al servicio técnico en un período: órdenes recibidas y entregadas, días de reparación, lo cobrado, equipos más atendidos, aprobación de cotizaciones y satisfacción de los clientes. | `desempeno del taller` · `como le fue al taller` · `cuantas reparaciones` · `reparaciones del mes` · `satisfaccion de los clientes del taller` · `tiempo de reparacion` · `cuanto cobro el taller` · `ingresos del taller` | periodo | Panel | B · mejor con el bueno | servicio_tecnico · módulo servicio_tecnico |
| `taller_equipo_historial` | Equipos de UN cliente por su nombre, o el equipo de un serial o IMEI: características, piezas cambiadas, próximas revisiones, mejoras sugeridas e historial de reparaciones. | `que equipos tiene` · `equipos del cliente` · `historial del equipo` · `ficha del equipo de` · `equipo con serial` · `equipo con imei` | texto | Panel | A · cualquiera | servicio_tecnico · módulo servicio_tecnico |
| `taller_estado` | Servicio técnico AHORA: equipos en el taller por estado, listos para entregar, entregas prometidas vencidas, órdenes sin técnico y carga de cada técnico. | `pendientes en el taller` · `pendiente el tecnico` · `tiene pendiente el tecnico` · `equipos pendientes` · `hay en reparacion` · `equipos hay en el taller` · `cuantos equipos tengo en el taller` · `que equipos estan listos` · `como esta el taller` · `equipos en el taller` · `que hay en el taller` · `equipos listos` · `listos para entregar` · `equipos por entregar` · `ordenes de servicio` · `ordenes abiertas del taller` · `equipos en reparacion` · `carga de los tecnicos` · `entregas atrasadas` | limite | Panel | A · cualquiera | servicio_tecnico · módulo servicio_tecnico |
| `taller_fallas_frecuentes` | Qué se daña más en el taller y cómo se soluciona: fallas, piezas y soluciones más comunes, días por tipo de falla y equipos o marcas con más casos (solo cifras, sin clientes). | `lo que mas se dana` · `mas se danan` · `se dana mas` · `fallas mas comunes` · `fallas frecuentes` · `problemas mas comunes` · `que se dana mas` · `reparaciones mas comunes` · `que falla mas` · `piezas que mas se cambian` · `soluciones mas usadas` | periodo | Panel | A · cualquiera | servicio_tecnico · módulo servicio_tecnico |
| `taller_orden` | Detalle de UNA orden de servicio técnico por su número (OS-000012) o las órdenes de un cliente: estado, equipo, falla, diagnóstico, valores, fechas y últimos movimientos. | `como va la orden` · `estado de la orden` · `detalle de la orden` · `que paso con la orden` · `informacion de la orden` | texto | Panel | A · cualquiera | servicio_tecnico · módulo servicio_tecnico |
| `taller_seguimientos` | A quién hay que contactar hoy en el servicio técnico: cotizaciones sin respuesta, equipos listos sin recoger, preguntar cómo le fue al cliente, garantías, mantenimientos y calificaciones bajas. | `seguimientos del taller` · `clientes del taller por contactar` · `a quien llamar del taller` · `seguimiento de clientes del taller` · `calificaciones bajas` · `clientes inconformes` · `pendientes del taller` | limite | Panel | A · cualquiera | servicio_tecnico · módulo servicio_tecnico |

## Ventas

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `comparativo_ventas` | Compara cantidad y monto de ventas confirmadas de los tres canales con el período anterior de igual duración. | `como vamos frente al` · `como vamos comparado con` · `frente al mes pasado` · `frente al mes anterior` · `comparado con el mes` · `contra el mes pasado` · `comparar las ventas` · `compara las ventas` · `vendi mas que` · `vendi menos que` · `vendimos mas que` · `vendimos menos que` · `subieron o bajaron las ventas` · `ventas frente al` · `ventas comparadas con` · `compara mis ventas` · `comparacion de ventas` · `comparar ventas` · `crecieron mis ventas` · `cayeron mis ventas` · `variacion de ventas` | periodo | Panel | A · cualquiera | cualquiera del panel |
| `patron_horario` | A qué horas y qué días de la semana se vende más o menos. | `mas los fines de semana` · `fines de semana` · `fin de semana` · `dia de la semana se vende` · `que dia se vende` · `horas pico` · `hora pico` · `dias de mas venta` · `a que horas se vende` · `a que hora vendo` · `a que hora se vende` · `mejor hora` · `mejores horas` · `que dia se vende mas` · `mejor dia` · `horario de mas ventas` | periodo | Panel | A · cualquiera | cualquiera del panel |
| `tendencia_ventas` | Tendencia de las ventas en el tiempo: si suben, bajan o están estables, qué tan confiable es (R²), proyección de 7 días y mejor día de la semana. | `como voy en ventas` · `como voy` · `como van mis ventas` · `para donde van las ventas` · `tendencia` · `van subiendo` · `van bajando` · `estoy vendiendo mas` · `estoy vendiendo menos` · `como vamos` · `proyeccion` | — | Panel | B · mejor con el bueno | cualquiera del panel |
| `ticket_promedio` | Valor promedio por venta confirmada en los tres canales, distinto de la utilidad. | `gasta en promedio` · `en promedio cada cliente` · `promedio por compra` · `compra en promedio` · `compra promedio` · `ticket promedio` · `valor promedio por venta` · `promedio por venta` · `venta promedio` | periodo | Panel | A · cualquiera | cualquiera del panel |
| `top_productos` | Productos más vendidos en un período. | `top 3 productos` · `top 5 productos` · `top 10 productos` · `top 20 productos` · `mejores productos` · `productos top` · `producto estrella` · `productos estrella` · `lo que mas sale` · `que mas sale` · `lo mas vendido` · `que se vende mejor` · `lo que mas me compran` · `que se vende mas` · `producto mas vendido` · `productos mas vendidos` · `mas vendidos` · `lo que mas se vende` · `top de productos` | periodo, limite | Panel | A · cualquiera | cualquiera del panel |
| `ventas_periodo` | Ventas e ingresos de un período (hoy, ayer, semana, mes, año o fechas). | `lo que vendi` · `lo que vendimos` · `lo que se vendio` · `ventas hoy` · `ventas ayer` · `ventas esta semana` · `ventas este mes` · `en ventas` · `cuanta plata entro` · `plata entro` · `cuanto entro` · `llevo vendido` · `total vendido` · `cuanto llevo en ventas` · `cuanto se ha vendido` · `como van las ventas` · `cuanto vendi` · `cuanto vendimos` · `cuanto se vendio` · `cuanto he vendido` · `ventas de` · `ventas del` · `total de ventas` · `cuanto facture` · `como estuvieron las ventas` · `ingresos de` | periodo | Panel | A · cualquiera | cualquiera del panel |

## Preguntas de ejemplo

Las usa la prueba del enrutador: cada una debe caer en su función.

- «¿Cuántas anulaciones POS hubo este mes?» → `anulaciones_pos`
- «¿Cuánto hay en caja?» → `caja_estado`
- «¿Cómo va el arqueo de hoy?» → `caja_estado`
- «¿Cómo me están pagando los clientes?» → `metodos_pago`
- «¿Tienen gaseosa?» → `buscar_productos`
- «¿Cuánto vale el jugo natural?» → `buscar_productos`
- «Busco una camiseta» → `buscar_productos`
- «¿Qué productos manejan?» → `categorias_publicas`
- «¿Qué venden?» → `categorias_publicas`
- «¿Cómo compro?» → `como_comprar`
- «¿Puedo comprar en línea?» → `como_comprar`
- «¿Dónde quedan?» → `datos_del_negocio`
- «¿Cuál es el teléfono?» → `datos_del_negocio`
- «¿A qué hora abren?» → `datos_del_negocio`
- «¿Qué servicios prestan?» → `servicios_publicos`
- «¿Hacen mantenimiento?» → `servicios_publicos`
- «¿Qué ha comprado Ana Pérez?» → `cliente_historial`
- «¿Qué tipos de clientes tengo?» → `segmentos_clientes`
- «¿Quiénes son mis mejores clientes?» → `top_clientes`
- «Busca el contacto Cybershop» → `buscar_contactos`
- «¿Cuál es el ID del contacto Andes?» → `buscar_contactos`
- «¿Cuánto me deben?» → `cartera_pendiente`
- «¿Qué está vencido sin cobrar?» → `cartera_pendiente`
- «¿Quiénes no me han pagado?» → `cartera_pendiente`
- «¿Qué clientes están morosos?» → `cartera_pendiente`
- «¿Cuánto cobré este mes?» → `cobros_recibidos`
- «¿Cuánto me pagaron esta semana?» → `cobros_recibidos`
- «¿Qué pagos recibí este mes?» → `cobros_recibidos`
- «¿Qué le cotizamos a Juan Pérez?» → `cotizacion_detalle`
- «Muéstrame la cotización COT 0000000012» → `cotizacion_detalle`
- «¿Ya me aprobaron la cotización de Juan Pérez?» → `cotizacion_detalle`
- «¿Cuánto fue la cotización 15?» → `cotizacion_detalle`
- «¿Cómo van mis cotizaciones?» → `cotizaciones_estado`
- «¿Cuánto he cotizado este año?» → `cotizaciones_estado`
- «¿Cuántos presupuestos envié este mes?» → `cotizaciones_estado`
- «¿Cuál fue la cotización más grande del mes?» → `cotizaciones_estado`
- «¿Cómo va el pipeline?» → `crm_pipeline`
- «¿Qué negocios puedo cerrar este mes?» → `crm_pipeline`
- «¿A quién tengo que llamar hoy?» → `crm_seguimiento`
- «Muéstrame la cuenta de cobro de María López» → `cuenta_cobro_detalle`
- «¿Ya pagaron la cuenta de cobro CC-0007?» → `cuenta_cobro_detalle`
- «¿Cuántas cuentas de cobro emití este mes?» → `cuentas_cobro_periodo`
- «¿Cuánto facturé en cuentas de cobro este año?» → `cuentas_cobro_periodo`
- «¿Cuánto he facturado en honorarios este año?» → `cuentas_cobro_periodo`
- «¿Qué opinan los clientes de mis productos?» → `resenas_estado`
- «¿Qué tareas tengo?» → `tareas_pendientes`
- «Muéstrame las tareas pendientes» → `tareas_pendientes`
- «¿Cuál es el procedimiento para abrir el local?» → `documentos_internos`
- «¿Qué dice la política de cambios?» → `documentos_internos`
- «Muéstrame el protocolo de bioseguridad» → `documentos_internos`
- «¿Cuánto gané este mes?» → `finanzas_periodo`
- «¿Cuáles fueron mis gastos del mes pasado?» → `finanzas_periodo`
- «¿Qué productos me dejan más ganancia?» → `margenes_productos`
- «¿Quiénes son mis proveedores?» → `proveedores`
- «¿Cuánto les pagué a los proveedores este mes?» → `proveedores`
- «¿Qué debo atender hoy?» → `alertas_negocio`
- «¿Qué datos me faltan por completar?» → `calidad_datos`
- «Dame los números generales del negocio» → `conteo_general`
- «¿Qué le falta a mi catálogo?» → `catalogo_pendiente`
- «¿Cómo está mi inventario por categoría?» → `inventario_por_categoria`
- «¿Qué productos no se están vendiendo?» → `inventario_sin_rotacion`
- «¿Qué movimientos de inventario hubo este mes?» → `movimientos_inventario`
- «¿Cómo va el producto Camiseta Azul?» → `producto_detalle`
- «¿Qué productos están agotados?» → `productos_bajo_stock`
- «¿Qué se me está acabando?» → `productos_bajo_stock`
- «¿Cuánto vale todo mi inventario?» → `resumen_inventario`
- «¿Qué debo comprar esta semana?» → `sugerencia_reorden`
- «¿Cuánto gana Juan Gómez?» → `nomina_empleado`
- «¿Cuánto pagué de nómina este mes?» → `nomina_resumen`
- «¿Cómo van los cupones?» → `cupones_desempeno`
- «¿Qué están guardando en favoritos?» → `deseos_demanda`
- «¿Qué ventas me faltan por facturar a la DIAN?» → `fe_pendiente`
- «¿Cómo va el soporte?» → `soporte_estado`
- «¿Cómo van los pedidos de este mes?» → `pedidos_estado`
- «¿Qué pedidos tengo por despachar?» → `pedidos_por_despachar`
- «¿Cómo van las mesas?» → `restaurante_ahora`
- «¿Cómo le fue al restaurante esta semana?» → `restaurante_desempeno`
- «¿Qué novedad tuvo el portátil de Laura Gómez?» → `taller_casos`
- «¿Cómo se solucionó lo de la pantalla del Samsung?» → `taller_casos`
- «¿Qué computadores atendimos?» → `taller_casos`
- «¿Equipos con problema de virus?» → `taller_casos`
- «¿Cómo le fue al taller este mes?» → `taller_desempeno`
- «¿Cuántas reparaciones hicimos el mes pasado?» → `taller_desempeno`
- «¿Qué equipos tiene Laura Gómez?» → `taller_equipo_historial`
- «¿Historial del equipo con serial PF3ABC12?» → `taller_equipo_historial`
- «¿Cómo está el taller?» → `taller_estado`
- «¿Qué equipos están listos para entregar?» → `taller_estado`
- «¿Hay entregas atrasadas?» → `taller_estado`
- «¿Cuáles son las fallas más comunes?» → `taller_fallas_frecuentes`
- «¿Qué se daña más en los equipos?» → `taller_fallas_frecuentes`
- «¿Cómo va la orden OS-000012?» → `taller_orden`
- «¿Estado de la orden de Laura Gómez?» → `taller_orden`
- «¿Qué seguimientos del taller tengo pendientes?» → `taller_seguimientos`
- «¿Hay calificaciones bajas de los clientes?» → `taller_seguimientos`
- «¿Crecieron mis ventas este mes?» → `comparativo_ventas`
- «Compara mis ventas con el período anterior» → `comparativo_ventas`
- «¿A qué hora vendo más?» → `patron_horario`
- «¿Cuál es mi mejor día de la semana?» → `patron_horario`
- «¿Las ventas van subiendo o bajando?» → `tendencia_ventas`
- «¿Cómo vamos este mes?» → `tendencia_ventas`
- «¿Cuál fue mi ticket promedio este mes?» → `ticket_promedio`
- «¿Qué es lo que más se vende?» → `top_productos`
- «¿Cuáles fueron los 5 más vendidos del mes?» → `top_productos`
- «¿Cuánto vendí hoy?» → `ventas_periodo`
- «¿Cuánto vendimos el mes pasado?» → `ventas_periodo`
- «¿Cómo estuvieron las ventas esta semana?» → `ventas_periodo`
