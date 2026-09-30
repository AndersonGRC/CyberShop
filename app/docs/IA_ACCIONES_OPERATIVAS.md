# Acciones operativas del Asistente IA (panel)

Versión de código: 1.4.3.0. Estado: implementado localmente, **apagado por
cliente y sin despliegue verificado**. No forma parte del catálogo de 48 consultas de solo
lectura ni del chat público; la separación evita que una respuesta informativa
pueda disparar una escritura.

La actualización del código y de la migración por cliente se explica en
[IA_ACTUALIZACION_CLIENTES.md](IA_ACTUALIZACION_CLIENTES.md). El botón no
publica por sí solo los cambios del panel maestro ni activa este módulo.

## Mapa de funciones

| Acción | Ejemplos de palabras clave | Datos obligatorios | Permiso al confirmar | Escritura fija |
| --- | --- | --- | --- | --- |
| `ajustar_inventario` | «fijar stock», «cuadrar inventario», «ajustar existencias» | ID, nombre o referencia exacta del producto; **stock final** entero no negativo; motivo concreto | `inventory.operar` | Actualiza `productos.stock` y crea `inventario_log` en la misma transacción. |
| `crear_contacto` | «crear contacto», «agregar contacto», «registrar contacto» | Nombre y tipo: cliente, proveedor, lead o socio | `crm.operar` | Inserta solo campos permitidos en `crm_contactos`. |
| `editar_contacto` | «editar contacto», «cambiar contacto», «actualizar contacto» | ID, o nombre/correo/teléfono como lo diga la persona (búsqueda por parecido); campos y nuevos valores | `crm.operar` | Actualiza solo campos permitidos, tras comparar el registro con la vista previa. |
| `eliminar_contacto` | «eliminar», «borrar», «desactivar», «archivar» contacto | ID o nombre (búsqueda por parecido) | `crm.eliminar` | Desactiva (`activo=FALSE`); no borra ventas ni otros registros. |
| `reactivar_contacto` | «reactivar», «activar de nuevo», «restaurar», «recuperar» contacto | ID o nombre de un contacto **desactivado** | `crm.operar` | `activo=TRUE` si no hay otro activo con el mismo nombre o correo. |
| `crear_producto` | «crea/agrega/registra el producto…» | Nombre, precio de venta y categoría existente; opcionales: referencia, descripción, costo, stock inicial | `inventory.operar` | Inserta en `productos` sin foto; referencia `IA-…` si no se da; stock inicial con rastro en `inventario_log`. |
| `editar_producto` | «cambia/sube/baja el precio…», «edita el producto…» | Producto (por parecido) y cambios: nombre, precio, costo, descripción, categoría, stock mínimo | `inventory.operar` | Actualiza esos campos. **Nunca** la referencia (llave del escritorio) ni el stock. |
| `archivar_producto` / `reactivar_producto` | «archiva/desactiva/oculta», «reactiva/restaura» el producto | Producto | `inventory.eliminar` / `inventory.operar` | `active` (y `visible_en_ecommerce`) FALSE/TRUE, como el panel. Sin la columna `active`, no se hace desde la IA. |
| `movimiento_inventario` | «entraron 10 gaseosas», «se dañaron 2 tortas», «llegaron 5 unidades» | Producto, cantidad y dirección (sale del verbo); motivo opcional | `inventory.operar` | Suma o resta al stock, nunca por debajo de cero, con rastro en `inventario_log`. |
| `crear_categoria` / `renombrar_categoria` | «crea la categoría…», «renombra la categoría X a Y» | Nombre (≤50) / categoría actual y nombre nuevo | `inventory.operar` | Inserta o renombra en `generos` sin duplicar; al renombrar «toca» sus productos para que el escritorio refresque el nombre. |
| `crear_tarea` | «recuérdame llamar a…», «crea una tarea para…» | Contacto (por parecido o escrito en la frase), qué hay que hacer; opcionales: fecha («mañana», «el viernes», «15 de octubre») y prioridad (de «urgente», «importante») | `crm.operar` | Inserta en `crm_tareas`. **No** envía correo ni crea evento de Google Calendar (la vista previa lo dice). |
| `completar_tarea` / `reabrir_tarea` / `editar_tarea` | «marca como hecha la tarea…», «reabre…», «aplaza la tarea… al lunes» | Tarea (por palabras del título o del contacto); cambios: título, fecha, prioridad | `crm.operar` | Cambia `estado`/`completada_en` o los campos dichos. Nunca se borra una tarea. |
| `registrar_actividad` | «registra una llamada con…», «anota que visité a…» | Contacto y asunto; el tipo (llamada, visita, reunión, correo, whatsapp, nota) sale del verbo, si no «otro» | `crm.operar` | Inserta en `crm_actividades` con fecha = ahora. Son historial: no se editan. |
| `crear_oportunidad` / `editar_oportunidad` | «crea una oportunidad con… por 3 millones», «cambia el monto de la oportunidad…» | Contacto, título; opcionales monto (como lo dijo: «3 millones», «2.500.000») y fecha de cierre | `crm.operar` | Inserta/actualiza `crm_oportunidades`; etapa inicial Prospecto. |
| `mover_oportunidad` | «ganamos el negocio de…», «pasa la oportunidad a negociación», «perdimos…» | Oportunidad y etapa (de las palabras) | `crm.operar` | Cambia `etapa`; ganada/perdida ⇒ probabilidad 100/0 y fecha de cierre real, como el CRM. «Perdida» es el cierre: no hay borrado. |
| `aprobar_resena` | «aprueba/publica la reseña de…» | Reseña por aprobar (cliente, producto o ID); si no dice cuál, se listan las pendientes | `content.operar` | `aprobado = TRUE`: queda visible en la página del producto. La IA **no** rechaza reseñas (en el panel, rechazar la borra). |
| `responder_resena` | «responde la reseña de Ana: ¡Gracias!» | Reseña y el texto **literal** (tras «:», entre comillas o como respuesta a «¿Qué respuesta publico?») | `content.operar` | `respuesta` (≤1.500) + `respuesta_fecha`. El modelo nunca redacta el texto público; no se vacía una respuesta. |
| `cerrar_ticket` / `reabrir_ticket` | «cierra el ticket 12», «marca como resuelto el ticket del cargador», «reabre el ticket…» | Ticket (asunto, cliente o ID); si no dice cuál, se listan | `support.operar` + `soporte_habilitado` | `estado` cerrado/abierto y `fecha_actualizado`. **No** responde tickets ni envía correos. |

Reseñas y soporte en `services/ia_acciones_atencion.py` (fase 4, 1.4.3.0). Estas
órdenes se reconocen solo si EMPIEZAN por el verbo junto al objeto («Responde la
reseña…», «Cierra el ticket…»): el texto de una respuesta puede decir cualquier
cosa sin volverse otra orden, y «crea una tarea para responder la reseña» sigue
siendo una tarea. Las reseñas no tienen interruptor propio (la pantalla del panel
solo exige el cargo): las cubre el flag de Acciones IA y el permiso `content`.

Lógica del CRM en `services/ia_acciones_crm.py` (fase 3, 1.4.2.0): las fechas las
calcula el servidor, nunca el modelo; prioridad, tipo de actividad y etapa salen de
las palabras de la persona. Si el modelo pide el contacto pero su nombre completo
está escrito en la frase («…visité a Distribuidora Andes y…»), se toma de ahí. Al
confirmar se compara con la vista previa (una oportunidad movida por otra persona
rechaza la acción). Consulta relacionada sin confirmación: `tareas_pendientes`.

Lógica del catálogo en `services/ia_acciones_catalogo.py` (fase 2, 1.4.1.0). Al
confirmar se compara con la vista previa; el stock solo cuenta en los
movimientos (una venta no invalida un cambio de precio). No hay ningún DELETE.

Consulta de solo lectura relacionada (sin confirmación): `buscar_contactos`
(permiso `crm`, solo local) muestra contactos con su ID, correo y teléfono.

### Encontrar el registro como lo nombra la persona (1.4.0.0)

Caso real (Panadería Nicol's, 28-sep): tras crear «Cybershop», «edita el contacto
de Cybershop Proveedor Tecnológico…» respondía «No encontré ese contacto» porque
se exigía el nombre exacto. Ahora `services/ia/buscador.py` busca por ID;
teléfono, correo o nombre exactos; todas las palabras (sin tildes, en singular);
o las que más coinciden. Si hay un candidato claro lo usa (la vista previa lo
muestra con su ID); si hay varios, la IA lista «ID 36 · Distribuidora Qwandes ·
proveedor; ID 37 · Qwandes Tech · cliente» y la respuesta «37» elige ese ID.

- **«El que acabo de crear».** Si la última acción ejecutada por la misma persona
  (≤15 min, leída en el servidor) fue sobre un contacto y el siguiente mensaje
  trae un dato de contacto sin «?» («está ubicado en Bogotá»), se propone editar
  ese contacto.
- **Identidad sin depender del modelo.** Si Qwen pide el contacto en «Desactiva el
  contacto Cybershop», el nombre se toma literalmente de la frase; el ID elegido
  de una lista manda sobre un nombre ambiguo.
- **Teléfonos.** Se comparan por número completo dicho por la persona (se admite
  el indicativo 57), nunca pegando dígitos vecinos. Un teléfono que no tenga 7, 10
  o 12 dígitos no se bloquea, pero la vista previa muestra un aviso.

El detector de palabras solo decide que la frase parece una orden. Antes de
llamar al modelo se comprueban la función solicitada, el módulo y el permiso,
para no gastar el respaldo de pago en solicitudes no autorizadas. El modelo
convierte la frase en un candidato JSON de **tipos cerrados** o pide
aclaración. No puede generar SQL ni autorizar la escritura. Si hay un posible
duplicado o el modelo devuelve algo inválido, se rechaza la propuesta. Para
inventario no se infiere un stock final a partir de «suma tres» o «cuadra»: se
pide el valor final.

El intérprete recibe la orden y el historial en un bloque JSON delimitado. Un
objetivo, ID, stock final, motivo o campo de contacto propuesto por el modelo
debe poder encontrarse en texto escrito por la persona (orden actual o sus
preguntas anteriores), **no** en respuestas previas de la IA. Si no se puede
fundamentar, pide una aclaración y no guarda una propuesta.

**Si falta un dato o hay varios registros con el mismo nombre** (versión 1.3.1.0),
la acción no se rechaza: la IA pregunta lo que falta (`AccionAclarar`) y la acción
queda abierta en el chat, con un aviso «Completando la acción…» y un botón
Cancelar. La siguiente respuesta («proveedor», «el motivo es conteo físico») se
une a la orden original (`ia_acciones.combinar`) y todo se vuelve a validar desde
cero: permiso, tipo, datos y la misma confirmación con botón. Escribir otra orden,
«cancelar» o una pregunta de datos con «?» deja la acción de lado. El modelo que
interpreta la orden recibe también la conversación reciente, marcada como
contexto: así entiende «créalo como proveedor» después de hablar de un negocio.

## Contrato de seguridad

1. Solo el panel web autenticado usa estas acciones; el escritorio, el chat
   público y procesos automáticos no tienen una ruta para ejecutarlas.
2. El maestro `admin.cybershopcol.com` controla el interruptor `ai_actions`
   (`cliente_config.ia_acciones_habilitadas`) **por cliente**. Está apagado por
   defecto incluso al aplicar plan Ultra. También se exige que estén activos
   el Asistente IA y el módulo del dato (`inventory` o `crm`). Esos flags se
   leen sin caché al confirmar, junto con la matriz actual de permisos. El
   cargo necesita tanto `ver` como `operar`/`eliminar` en el módulo del dato.
3. La IA muestra ID, registro y antes/después. Solo una pulsación explícita en
   «Confirmar y ejecutar» envía el UUID de la propuesta. Escribir «sí» en el
   chat nunca confirma. La propuesta vence a los 10 minutos.
4. La propuesta, su auditoría y la operación residen en la **misma base del
   cliente activo**. El UUID está ligado además al usuario y al nombre de esa
   base; el cuerpo HTTP no acepta un `tenant_id` ni un nombre de base. La
   confirmación bloquea la propuesta y el registro, comprueba si cambió, y
   ejecuta con una sola transacción. Un reintento devuelve el resultado ya
   guardado, sin repetir la escritura. Tras decidir se borra el payload del
   borrador; queda el resumen/resultado para auditoría local. El maestro muestra
   las últimas 20 decisiones de la base seleccionada, sin copiar sus registros
   a una tabla compartida.
5. Las consultas de escritura son parametrizadas y las columnas editables son
   una lista blanca. El modelo solo recibe la frase de la persona, no un volcado
   de la base. La interpretación de acciones exige un motor no-nube: no envía la
   orden ni su historial al respaldo Anthropic. Si ese motor no está listo,
   no se propone ni ejecuta ningún cambio.

Esto es aislamiento **a nivel de aplicación**. Sigue pendiente el cierre P0
del informe `AUDITORIA_IA_MULTITENANT_2026-09.md`: usuarios de sistema y roles
PostgreSQL independientes por cliente, con prueba de conexión cruzada negada.

## Habilitación controlada

1. Aplicar `CyberShopAdmin/migrations/tenant/0015_ia_acciones_pendientes.sql`
   solo en la base del cliente canario mediante el migrador del maestro.
2. Confirmar que `ai_assistant`, `inventory`/`crm` y los permisos del rol están
   configurados para ese cliente. En el maestro, activar explícitamente
   «Acciones operativas con IA».
3. Probar primero en una base de pruebas: crear, editar, desactivar contacto y
   ajustar stock, además de caducidad, cancelación, doble clic, cambio
   concurrente y denegación entre dos clientes. No probar con datos reales ni
   habilitar masivamente sin esos resultados.
4. Si hace falta revertir, desactivar `ai_actions` desde el maestro. Las
   propuestas pendientes dejan de poder confirmarse; no se elimina la tabla ni
   la auditoría. Las operaciones ya confirmadas requieren reversión de negocio
   (reactivar el contacto exige una recuperación administrativa; stock, un
   movimiento inverso documentado).

## Próximos agentes candidatos (aún no implementados)

| Prioridad | Funciones | Regla adicional antes de desarrollar |
| --- | --- | --- |
| Alta | Crear tareas y actividades CRM; asignar responsable; fusionar duplicados | Agenda, identidad de responsable y política de fusión sin pérdida de historial. |
| Alta | Registrar entrada/salida de inventario por lote; conteo de múltiples productos | Motivo, unidad, almacén, registro por línea y aprobación de diferencias grandes. |
| Media | Cambiar estado de pedido; preparar cotización; respuesta de soporte | Máquina de estados, validación de pago/entrega y vista previa de mensajes externos. |
| Media | Crear producto; editar precios o descuentos | Referencia única, impuestos, margen mínimo, vigencia y aprobación reforzada. |
| Restringida | Pagos, contabilidad, nómina, facturación DIAN, borrados físicos | Flujo de doble aprobación, conciliación, obligaciones legales e idempotencia externa; no reutilizar la confirmación simple. |

Una función nueva necesita: caso de uso preciso, esquema/validadores,
permisos `operar` o `eliminar`, vista previa exacta, control de concurrencia,
auditoría, reversión y pruebas por tenant antes de añadir disparadores.
