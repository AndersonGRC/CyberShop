# Acciones operativas del Asistente IA (panel)

Versión de código: 1.1.0.0. Estado: implementado localmente, **apagado por
cliente y sin despliegue verificado**. No forma parte del catálogo de 46 consultas de solo
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
| `editar_contacto` | «editar contacto», «cambiar contacto», «actualizar contacto» | ID o nombre exacto; campos y nuevos valores | `crm.operar` | Actualiza solo campos permitidos, tras comparar el registro con la vista previa. |
| `eliminar_contacto` | «eliminar contacto», «borrar contacto» | ID o nombre exacto | `crm.eliminar` | Desactiva (`activo=FALSE`); no borra ventas ni otros registros. |

El detector de palabras solo decide que la frase parece una orden. Antes de
llamar al modelo se comprueban la función solicitada, el módulo y el permiso,
para no gastar el respaldo de pago en solicitudes no autorizadas. El modelo
convierte la frase en un candidato JSON de **cuatro tipos cerrados** o pide
aclaración. No puede generar SQL ni autorizar la escritura. Si falta un dato,
hay varios registros con el mismo nombre, existe posible duplicado o el modelo
devuelve algo inválido, se rechaza la propuesta. Para inventario no se infiere
un stock final a partir de «suma tres» o «cuadra»: se pide el valor final.

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
   de la base. Si el respaldo Anthropic de emergencia entra en el chat del
   panel según su política, esa frase podría enviarse al proveedor; cada
   cliente debe decidir si acepta ese tratamiento de datos personales.

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
