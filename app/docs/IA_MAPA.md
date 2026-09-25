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

**Capacidades registradas: 47**

## Caja

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `anulaciones_pos` | Cuántas notas de crédito POS se emitieron en un período y por cuánto; no incluye web ni escritorio. | `anulaciones pos` · `ventas anuladas pos` · `notas de credito pos` · `ventas anuladas del mostrador` | periodo | Panel | A · cualquiera | pos |
| `caja_estado` | Estado de la caja: turno abierto, cuánto efectivo debería haber y los últimos cuadres con faltantes o sobrantes. | `en caja` · `arqueo` · `cierre de caja` · `cuadre de caja` | — | Panel | A · cualquiera | caja · módulo caja |
| `metodos_pago` | Con qué le pagan los clientes: efectivo, tarjeta, transferencias, y cuánto pesa cada medio. | `metodos de pago` · `formas de pago` · `me estan pagando` · `como me pagan` · `cuanto en efectivo` · `efectivo o tarjeta` | periodo | Panel | A · cualquiera | pos |

## Catalogo_publico

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `buscar_productos` | Busca productos del catálogo público por nombre o categoría, con precio y disponibilidad. | `tienen` · `tienes` · `venden` · `cuanto vale` · `cuanto cuesta` · `precio de` · `busco` · `estoy buscando` · `necesito` | texto, limite | Público | A · cualquiera | cualquiera del panel · módulo ai_public |
| `categorias_publicas` | Qué categorías de producto maneja la tienda. | `que venden` · `que productos manejan` · `que categorias` · `que puedo comprar` | — | Público | A · cualquiera | cualquiera del panel · módulo ai_public |
| `como_comprar` | Cómo se compra en este sitio: tienda en línea o por contacto. | `como compro` · `como puedo comprar` · `como hago el pedido` · `puedo comprar en linea` · `como pido` | — | Público | A · cualquiera | cualquiera del panel · módulo ai_public |
| `datos_del_negocio` | Dirección, teléfono, WhatsApp, correo y horario del negocio. | `donde quedan` · `donde estan` · `direccion` · `telefono` · `whatsapp` · `como los contacto` · `a que hora` · `horario` · `abren` | — | Público | A · cualquiera | cualquiera del panel · módulo ai_public |
| `servicios_publicos` | Servicios que presta el negocio, según su sitio. | `que servicios` · `prestan servicio` · `hacen mantenimiento` · `hacen instalacion` · `tienen servicio de` · `tienen servicio` · `ofrecen` | — | Público | A · cualquiera | cualquiera del panel · módulo ai_public |

## Clientes

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `cliente_historial` | Historial de compras de UN cliente por su nombre: cuántas veces compró, cuánto, cuándo fue la última vez y qué se lleva. | `que ha comprado` · `historial de` · `compras de` | cliente | Panel | A · cualquiera | orders |
| `segmentos_clientes` | Agrupa a los clientes en segmentos (fieles, nuevos, en riesgo, ocasionales) con análisis estadístico, para saber a quién cuidar o recuperar. | `segmentos` · `tipos de clientes` · `clientes frecuentes` · `agrupar clientes` · `clientes ocasionales` | — | Panel | B · mejor con el bueno | cualquiera del panel |
| `top_clientes` | Clientes que más han comprado. | `mejores clientes` · `quien compra mas` · `clientes que mas compran` · `top de clientes` | limite | Panel | A · cualquiera | cualquiera del panel |

## Comercial

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `cartera_pendiente` | Cartera por cobrar: qué cotizaciones aprobadas y cuentas de cobro están aprobadas pero todavía no las han pagado, cuánto suman, quién debe y qué está vencido. | `cuanto me deben` · `quien me debe` · `cartera` · `por cobrar` · `sin cobrar` · `pendiente de pago` | — | Panel | A · cualquiera | billing · módulo billing |
| `cotizaciones_estado` | Cotizaciones de un período: cuántas, por cuánto, cuántas se aprobaron y cuáles llevan días sin respuesta. | `cotizaciones` · `cuantas cotizaciones` · `cotizaciones aprobadas` · `cotizaciones sin respuesta` | periodo | Panel | A · cualquiera | quotes · módulo quotes |
| `crm_pipeline` | Negocios y oportunidades en curso del CRM: cuánto hay por etapa, cuánto se espera cerrar, ganados y perdidos, y qué cierra pronto. | `oportunidades` · `pipeline` · `negocios en curso` · `embudo` · `negocios puedo cerrar` · `puedo cerrar` | — | Panel | B · mejor con el bueno | crm · módulo crm |
| `crm_seguimiento` | A quién hay que atender hoy: tareas vencidas o del día por responsable y clientes sin contacto hace más de un mes. | `tareas pendientes` · `tengo que llamar` · `a quien llamar` · `seguimiento` · `tareas vencidas` · `que tengo que hacer hoy` | — | Panel | A · cualquiera | crm · módulo crm |
| `cuentas_cobro_periodo` | Cuentas de cobro emitidas en un período, a qué clientes y cuáles siguen sin pagarse. | `cuentas de cobro` · `cuentas emitidas` | periodo | Panel | A · cualquiera | billing · módulo billing |
| `resenas_estado` | Reseñas de los clientes: calificación promedio, cuáles faltan por aprobar o responder y los productos peor calificados. | `resenas` · `calificaciones` · `que opinan los clientes` · `estrellas` · `comentarios de los clientes` | — | Panel | A · cualquiera | content |

## Documentos

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `documentos_internos` | Busca en los documentos internos que escribió el dueño —procedimientos, políticas, manuales, instructivos— lo que responde la pregunta: cómo se hace algo o qué dice una política interna. | `procedimiento` · `procedimientos` · `protocolo` · `politica de` · `politicas de` · `politica del` · `manual de` · `manual del` · `segun el manual` · `reglamento` · `instructivo` · `documento interno` · `documentos internos` | texto | Panel | A · cualquiera | ai_assistant |

## Finanzas

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `finanzas_periodo` | Ingresos, egresos y UTILIDAD (ganancia) de un período, con los gastos por concepto y la comparación con el período anterior. | `ingresos y egresos` · `cuanto gane` · `cuanta ganancia` · `utilidad del` · `balance del` · `gastos del` · `cuanto gaste` | periodo | Panel | A · cualquiera | accounting · módulo accounting |
| `margenes_productos` | Cuánto deja cada producto (precio menos costo): los más y menos rentables y los vendidos por debajo del costo. | `margen` · `rentabilidad` · `dejan mas ganancia` · `deja mas ganancia` · `cual deja mas` · `utilidad por producto` | periodo, limite | Panel | B · mejor con el bueno | accounting |

## General

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `alertas_negocio` | Qué conviene atender HOY: stock agotado, caja sin cerrar, mesas abiertas, pedidos sin despachar, tareas vencidas, ventas anormales y demás avisos. | `que debo atender` · `alertas` · `que esta mal` · `que revisar hoy` · `que necesita mi atencion` | — | Panel | B · mejor con el bueno | cualquiera del panel |
| `calidad_datos` | Qué le falta a los datos del negocio para que la IA y los reportes sirvan mejor: ventas sin cliente identificado, productos sin costo, catálogo incompleto. | `calidad de datos` · `datos incompletos` · `que falta por llenar` · `datos me faltan` · `falta por completar` | — | Panel | A · cualquiera | cualquiera del panel |
| `conteo_general` | Números generales: productos, categorías, clientes, pedidos. | `numeros generales` · `resumen general` · `cuantos productos tengo` · `cuantos clientes tengo` | — | Panel | A · cualquiera | cualquiera del panel |

## Inventario

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `catalogo_pendiente` | Qué falta por completar en el catálogo (sin descripción, imagen o categoría). | `le falta a mi catalogo` · `falta a mi catalogo` · `catalogo incompleto` · `sin descripcion` · `sin imagen` · `productos sin foto` | — | Panel | A · cualquiera | cualquiera del panel |
| `inventario_por_categoria` | Productos, unidades y agotados por categoría; valor del stock a precio de venta. | `inventario por categoria` · `stock por categoria` · `existencias por categoria` · `agotados por categoria` | — | Panel | A · cualquiera | inventory |
| `inventario_sin_rotacion` | SOLO los productos que no se venden hace meses: cuáles son y cuánta plata está detenida o dormida en ellos. | `no se estan vendiendo` · `no se venden` · `no se vende` · `sin rotacion` · `productos quietos` · `lleva sin venderse` · `plata parada` | — | Panel | B · mejor con el bueno | inventory |
| `movimientos_inventario` | Movimientos de inventario de un período: entradas, salidas y ajustes, con sus motivos (mermas, daños, correcciones). | `movimientos de inventario` · `entradas y salidas` · `ajustes de inventario` | periodo | Panel | A · cualquiera | inventory |
| `producto_detalle` | Ficha de UN producto por su nombre: precio, stock, cuánto se vendió en 90 días, cuándo fue su última venta, si se agota pronto y cómo lo califican. | `como va el producto` · `ficha del producto` · `detalle del producto` | producto | Panel | A · cualquiera | inventory |
| `productos_bajo_stock` | Productos con stock bajo o agotados (parámetro: umbral). | `stock bajo` · `bajo stock` · `se esta agotando` · `se me esta acabando` · `estan agotados` · `productos agotados` · `agotado` · `sin existencias` · `queda poco` | umbral | Panel | A · cualquiera | cualquiera del panel |
| `resumen_inventario` | Cuánto vale TODO el inventario y cuántas unidades hay en total (sin distinguir si rotan o no). | `vale todo mi inventario` · `vale mi inventario` · `vale el inventario` · `valor del inventario` · `cuantas unidades tengo` · `cuanta plata tengo en inventario` | — | Panel | A · cualquiera | cualquiera del panel |
| `sugerencia_reorden` | Qué comprar/reponer pronto: productos que se agotan según su ritmo de venta, con cantidad sugerida. | `que debo comprar` · `que tengo que comprar` · `que reponer` · `que pedir` · `reorden` · `que se va a agotar` | — | Panel | B · mejor con el bueno | cualquiera del panel |

## Nomina

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `nomina_empleado` | Datos de pago de UN empleado por su nombre: cargo, antigüedad, salario base, su última liquidación y sus provisiones. | `cuanto gana` · `salario de` · `sueldo de` | empleado | Panel | A · cualquiera | payroll · **sensible: nomina** · módulo payroll |
| `nomina_resumen` | Cuánto cuesta la nómina en un período: devengado, deducciones, neto pagado, aportes del empleador, provisiones y costo por cargo. | `nomina` · `planilla` · `cuanto pago de sueldos` | periodo | Panel | A · cualquiera | payroll · **sensible: nomina** · módulo payroll |

## Operacion

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `cupones_desempeno` | Cupones de descuento: cuántos se usaron, cuánto descuento se entregó y cuáles son los más usados. | `cupones` · `codigos de descuento` · `promociones` | periodo | Panel | A · cualquiera | coupons · módulo coupons |
| `deseos_demanda` | Productos que los clientes guardan en su lista de deseos, sobre todo los agotados: demanda que se está perdiendo. | `lista de deseos` · `favoritos` · `lo que quieren los clientes` | — | Panel | A · cualquiera | wishlist · módulo wishlist |
| `fe_pendiente` | Facturación electrónica: qué ventas ya tienen factura y cuáles no (solo consulta, no emite nada). | `facturacion electronica` · `facturas sin enviar` · `dian` | periodo | Panel | A · cualquiera | facturacion_electronica · módulo facturacion_electronica |
| `soporte_estado` | Tickets de soporte: abiertos, sin respuesta del negocio y los más antiguos. | `tickets` · `soporte` · `reclamos` · `pqr` | — | Panel | A · cualquiera | support · módulo support |

## Pedidos

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `pedidos_estado` | Pedidos de la tienda web por estado de pago y envío, y los pagados que llevan más de 48 horas sin despachar. | `estado de los pedidos` · `van los pedidos` · `cuantos pedidos` · `los pedidos de` · `pedidos del` | periodo | Panel | A · cualquiera | orders |
| `pedidos_por_despachar` | Pedidos web pagados pendientes de enviar. | `por despachar` · `falta despachar` · `pedidos pendientes de envio` · `que tengo que enviar` | — | Panel | A · cualquiera | cualquiera del panel |

## Restaurante

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `restaurante_ahora` | Cómo está el salón AHORA: mesas ocupadas o libres, cuentas abiertas, cuánto llevan consumido y cuáles se demoran. | `las mesas` · `mesas abiertas` · `como va el salon` · `mesas ocupadas` | — | Panel | A · cualquiera | restaurant_tables · módulo restaurant_tables |
| `restaurante_desempeno` | Cómo le fue al restaurante en un período: mesas atendidas, ticket por mesa y por persona, duración, horas pico, platos más pedidos y anulaciones. | `le fue al restaurante` · `rotacion de mesas` · `desempeno del restaurante` · `ventas del restaurante` | periodo | Panel | A · cualquiera | restaurant_tables · módulo restaurant_tables |

## Ventas

| Función | Qué responde | Se dispara con | Parámetros | Canal | Motor | Permiso |
|---|---|---|---|---|---|---|
| `comparativo_ventas` | Compara cantidad y monto de ventas confirmadas de los tres canales con el período anterior de igual duración. | `compara mis ventas` · `comparacion de ventas` · `comparar ventas` · `crecieron mis ventas` · `cayeron mis ventas` · `variacion de ventas` | periodo | Panel | A · cualquiera | cualquiera del panel |
| `patron_horario` | A qué horas y qué días de la semana se vende más o menos. | `a que hora vendo` · `a que hora se vende` · `mejor hora` · `mejores horas` · `que dia se vende mas` · `mejor dia` · `horario de mas ventas` | periodo | Panel | A · cualquiera | cualquiera del panel |
| `tendencia_ventas` | Tendencia de las ventas en el tiempo: si suben, bajan o están estables, qué tan confiable es (R²), proyección de 7 días y mejor día de la semana. | `tendencia` · `van subiendo` · `van bajando` · `estoy vendiendo mas` · `estoy vendiendo menos` · `como vamos` · `proyeccion` | — | Panel | B · mejor con el bueno | cualquiera del panel |
| `ticket_promedio` | Valor promedio por venta confirmada en los tres canales, distinto de la utilidad. | `ticket promedio` · `valor promedio por venta` · `promedio por venta` · `venta promedio` | periodo | Panel | A · cualquiera | cualquiera del panel |
| `top_productos` | Productos más vendidos en un período. | `que se vende mas` · `producto mas vendido` · `productos mas vendidos` · `mas vendidos` · `lo que mas se vende` · `top de productos` | periodo, limite | Panel | A · cualquiera | cualquiera del panel |
| `ventas_periodo` | Ventas e ingresos de un período (hoy, ayer, semana, mes, año o fechas). | `cuanto vendi` · `cuanto vendimos` · `cuanto se vendio` · `cuanto he vendido` · `ventas de` · `ventas del` · `total de ventas` · `cuanto facture` · `como estuvieron las ventas` · `ingresos de` | periodo | Panel | A · cualquiera | cualquiera del panel |

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
- «¿Cuánto me deben?» → `cartera_pendiente`
- «¿Qué está vencido sin cobrar?» → `cartera_pendiente`
- «¿Cómo van mis cotizaciones?» → `cotizaciones_estado`
- «¿Cómo va el pipeline?» → `crm_pipeline`
- «¿Qué negocios puedo cerrar este mes?» → `crm_pipeline`
- «¿A quién tengo que llamar hoy?» → `crm_seguimiento`
- «¿Cuántas cuentas de cobro emití este mes?» → `cuentas_cobro_periodo`
- «¿Qué opinan los clientes de mis productos?» → `resenas_estado`
- «¿Cuál es el procedimiento para abrir el local?» → `documentos_internos`
- «¿Qué dice la política de cambios?» → `documentos_internos`
- «Muéstrame el protocolo de bioseguridad» → `documentos_internos`
- «¿Cuánto gané este mes?» → `finanzas_periodo`
- «¿Cuáles fueron mis gastos del mes pasado?» → `finanzas_periodo`
- «¿Qué productos me dejan más ganancia?» → `margenes_productos`
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
