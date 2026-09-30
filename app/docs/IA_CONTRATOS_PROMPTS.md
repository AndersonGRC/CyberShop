# Contrato actual de los dos chats de IA

Revisión del código local: 28/09/2026. Este documento describe la implementación,
**no certifica un despliegue** ni el aislamiento físico de PostgreSQL en producción.
El catálogo detallado de funciones y frases está en [IA_MAPA.md](IA_MAPA.md).

| Superficie | Datos y funciones | Escrituras | Respaldo externo |
| --- | --- | --- | --- |
| Chat público (`/chat/mensaje`) | Solo cinco capacidades públicas, catálogo visible, FAQ y textos publicados del cliente activo. | Ninguna. | Deshabilitado por defecto; si se habilita, únicamente recibe contexto público. |
| Asistente IA del panel (`/admin/ia/chat` y `chat-stream`) | Catálogo de lectura filtrado por canal, módulo y permiso del cargo; máximo tres consultas por pregunta. | Cuatro acciones operativas separadas: ajustar inventario y crear, editar o desactivar contactos. Requieren propuesta, vista previa y clic explícito en **Confirmar y ejecutar**. | Según configuración, espera por caída del PC; con PC encendido pero modelo frío puede usar un puente temporal. Nómina, documentos internos y la interpretación de acciones no salen a Anthropic. |

## Estructura de prompts y límites de confianza

1. Las reglas del sistema definen el canal, los límites de información y el
   formato. El nombre/tono configurables del negocio, la pregunta, el historial,
   las referencias web y los textos de fuentes se entregan **como datos**,
   delimitados y acotados; no pueden ampliar permisos ni cambiar instrucciones.
2. La selección de funciones del panel solo acepta códigos y parámetros JSON
   del catálogo permitido. El servidor revalida el permiso antes de ejecutar
   SQL fijo en la base efectiva de ese cliente. El modelo no escribe SQL. Una
   consulta de nómina puede seleccionarse si el cargo está autorizado, pero su
   resultado solo se redacta localmente o se entrega sin modelo.
3. El chat público nunca ve herramientas internas. Los hechos de productos y
   negocio vienen de consultas o textos publicados; el modelo solo redacta. Si
   el validador detecta cifras, promociones, plazos o stock no respaldados por
   el texto base, se entrega la respuesta determinista. En compatibilidad técnica puede
   usar conocimiento general, pero no inventar precios ni promociones.
4. En el panel, si una redacción introduce un número o porcentaje ausente del
   resultado SQL, se muestra el resultado autorizado sin redacción. Para poder
   verificar antes de mostrarlo, las respuestas del modelo con datos se emiten
   al terminar la generación, conservando latidos SSE durante la espera.
5. El historial puede venir del navegador. El motor local lo trata como
   contexto no confiable; a la nube **no** se envían respuestas anteriores ni
   nombres de herramientas, solo preguntas previas de turnos no marcados como
   locales. Eso evita que una etiqueta falsificada exponga una respuesta de
   nómina. Una pregunta previa escrita por el usuario aún puede contener datos
   sensibles: no se debe prometer que el historial es anónimo.
6. La caché del chat público incluye la base, el identificador del cliente, la
   versión del prompt, la pregunta, la configuración y las fuentes/referencias.
   Al editar, despublicar o borrar una FAQ se intenta reindexar únicamente su
   fila (o el grupo FAQ al crear), dentro de la base del cliente activo; el panel
   avisa si el reindexado falla.

## Aclaraciones y continuidad por proceso

- El panel presenta al selector únicamente los procesos de lectura permitidos
  para el cargo, cada uno con su descripción y parámetros registrados. Antes
  de consultar, el servidor valida los parámetros de **todos** los procesos
  elegidos. Si falta el cliente en `cliente_historial`, el producto en
  `producto_detalle` o el empleado en `nomina_empleado`, pregunta por esa
  identidad sin inventarla ni ejecutar una consulta parcial. El siguiente
  mensaje puede completar la pregunta anterior, pero una respuesta previa de
  la IA no autoriza por sí sola una identidad.
- Los períodos explícitos prevalecen sobre un período inventado por el
  selector. Sin período se usa el histórico, salvo el comparativo de ventas,
  que requiere una ventana finita. Para fechas ambiguas o rangos incompletos
  se solicitan inicio y fin; una comparación conserva sus ventanas separadas.
  La redacción recibe los procesos y filtros validados junto a los resultados
  para responder cada parte sin cruzar cifras ni períodos.
- El chat público tiene instrucciones de respuesta específicas para catálogo,
  categorías, servicios, datos del negocio, compra, FAQ y compatibilidad.
  Puede pedir una referencia o modelo faltante para volver a buscar **en el
  mismo cliente**. Si falta un dato que el negocio no ha publicado, lo dice y
  ofrece el canal de contacto publicado en vez de inventarlo.
- Cada una de las cuatro acciones operativas tiene un contrato de extracción
  propio. La IA solo puede proponer campos que la persona haya expresado; si
  falta producto, stock final, motivo, contacto, tipo o valor de cambio, el
  servidor formula una pregunta puntual. La propuesta no escribe nada hasta
  la confirmación explícita en el panel.

## Seguridad operativa y validación pendiente

- El chat público no expone las acciones de escritura. En el panel, escribir
  «sí» no confirma: hace falta el botón y un UUID de propuesta vigente. Cuando
  un motor no-nube no está disponible, la interpretación de estas acciones falla
  sin cambiar registros; no se envía la orden a Anthropic. Objetivo, stock final,
  motivo y campos propuestos deben estar en texto escrito por la persona, no
  solo en una respuesta previa del asistente.
- La comprobación de cifras detecta **números nuevos**, no todas las mentiras
  semánticas (por ejemplo, intercambiar dos valores ya presentes o escribir un
  número con palabras). Para decisiones económicas o cambios de inventario, la
  fuente de verdad sigue siendo la consulta y la vista previa de confirmación.
- Las pruebas unitarias con dobles verifican permisos, canal, historia filtrada,
  caché, regresiones de FAQ y caída a datos verificados. Falta ejecutar los casos
  de integración de FAQ y aislamiento con PostgreSQL en un entorno de pruebas
  con dos clientes; la base local de este equipo no conecta. Las bases separadas
  tampoco sustituyen roles PostgreSQL exclusivos por cliente: véase
  [AUDITORIA_IA_MULTITENANT_2026-09.md](AUDITORIA_IA_MULTITENANT_2026-09.md).
- Nada de esta revisión activa funciones, cambia credenciales ni publica código.
  Para actualizar clientes, seguir
  [IA_ACTUALIZACION_CLIENTES.md](IA_ACTUALIZACION_CLIENTES.md) con canario,
  migraciones y verificación por cliente desde `admin.cybershopcol.com`.
