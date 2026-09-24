# Auditoría local: IA, clientes y control maestro

Fecha: 2026-09-23. Alcance: código local de CyberShop y CyberShopAdmin, pruebas
con dobles; sin despliegue, sin llamadas de pago a Anthropic y sin afirmar una
certificación de producción. Dominio maestro confirmado: `admin.cybershopcol.com`.

## Qué está implementado

- El maestro aprovisiona una base PostgreSQL `cyber_t<ID>` y una instancia por
  cliente. El plano de control conserva metadatos y claves de sincronización;
  los datos operativos se consultan desde la base efectiva del request.
- El panel IA tiene 46 capacidades registradas, de solo lectura. Cada función
  ejecuta SQL fijo con parámetros validados; el modelo no genera SQL ni recibe
  una herramienta que el permiso del usuario no permita. Cinco capacidades
  son públicas; las cuatro nuevas son solo del panel.
- Las preguntas inequívocas del panel van por palabras clave a la función fija
  sin invocar un modelo. Si el PC está apagado, el usuario recibe los datos
  verificados sin redacción. Preguntas ambiguas, comparaciones o fechas no
  interpretadas siguen en el planificador, no se convierten en otra consulta.
- Anthropic queda apagado de fábrica: requiere clave y umbral mayor que cero.
  Solo se considera después de 180 segundos y tres sondeos HTTP fallidos del
  PC, con reloj separado por base. Las consultas simples ya resueltas por SQL
  no usan Anthropic. El chat público está excluido por defecto y solo puede
  activarse expresamente. El máximo configurado de salida se aplica aun si el
  llamador solicita más tokens. El contador debe estar disponible: si falla,
  no se envían nuevas llamadas.
- CyberShopAdmin ofrece configuración Anthropic por instancia, oculta la clave,
  registra quién cambió las integraciones sin registrar valores secretos y
  avisa que la instancia principal aún no lee ese archivo de configuración.

La frontera esperada de cada superficie es:

| Superficie | Puede consultar | No debe recibir |
| --- | --- | --- |
| Chat público del sitio de un cliente | Catálogo visible, servicios publicados, contacto, FAQ y enlaces públicos de **su** base. | Caja, ventas internas, cartera, nómina, clientes, llaves, datos de otros negocios. |
| Asistente IA del panel | Funciones fijas de ventas, inventario, pedidos, CRM, contabilidad y nómina, según módulo y permiso del rol, siempre en **su** base. | SQL arbitrario, datos de otra base, operaciones de escritura sin confirmación. |
| POS de escritorio / sync | Datos del cliente autenticado por `X-Sync-Key` y operaciones offline-first autorizadas. | Identidad procedente de una cookie web de otro cliente. |
| Maestro `admin.cybershopcol.com` | Alta, suspensión, plan, módulos, instancias, integraciones y auditoría. | Uso de las credenciales operativas de un cliente para consultar otro sin una tarea administrativa explícita. |

## Hallazgos que impiden afirmar aislamiento completo

| Prioridad | Hallazgo | Requisito de cierre |
| --- | --- | --- |
| P0 | Las instancias templadas usan `User=root` y, por defecto, `DB_USER=postgres`. Bases separadas no significan permisos SQL separados: el proceso comprometido de un cliente podría abrir otra base accesible a ese rol. | Usuario de sistema y rol PostgreSQL por cliente, privilegios limitados a su propia base, secretos distintos y prueba negativa de conexión cruzada. |
| P0 | La instancia principal usa `.cybershop.conf`, mientras el maestro guarda sus nuevos controles en `<slug>.env`; por ahora no surtirán efecto en ese cliente. | Vincular su unit/env real al maestro o implementar un adaptador seguro, con canario y rollback. |
| P0 | El umbral local de gasto Anthropic es estimado, no un límite duro: solicitudes concurrentes, redondeo de `NUMERIC(10,4)` y cambios futuros de precio pueden rebasarlo. | Mantener umbral inicial en US$0; usar además límites de gasto reales de organización/workspace en Anthropic, y diseñar reserva atómica/contabilidad de mayor precisión antes de prometer un tope exacto. |
| P0 | La clave Anthropic aparece en claro en el texto histórico adjunto a la conversación (no en los repositorios revisados). | Revocarla y generar otra; no reutilizar la expuesta. |
| P1 | No hubo prueba directa de las nuevas consultas contra `cyber_t002`: la conexión local de `psycopg2` falló antes de ejecutar SQL. | Canario de solo lectura en base de pruebas con esquema representativo y conciliación de cifras de ventas contra contabilidad. |
| P1 | Otras cachés de esquema (`routes/admin.py`, `payments.py`, `public.py`, `restaurant_tables_service.py`) siguen sin base de datos en su clave. Hoy las rutas web están pensadas para instancias separadas, pero una futura instancia multi-tenant podría mezclar decisiones de esquema. | Clave `(db_name, objeto)` o aislamiento estricto por proceso, más prueba con dos esquemas distintos. |
| P1 | El chat público tiene motor y lista blanca, pero aún faltan endpoints, widget, controles de tráfico y pantalla de FAQ (F6–F9 de `IA_ESTADO.md`). | Terminar esas fases antes de habilitar `ai_public` para visitantes. |
| P1 | El aviso de costo por correo se envía tras la primera llamada cobrada y solo si hay destinatarios configurados; no es una aprobación previa ni una alerta garantizada. | Probar destinatarios, entrega y alerta de umbrales; mostrar estado de gasto en el maestro. |

## Correcciones de esta pasada

1. JWT, login y refresh ya no pueden seleccionar otra base a través del dominio
   de una instancia; la excepción central de sync sigue autenticando por
   `X-Sync-Key`. La cookie web no prevalece sobre esa clave.
2. Cachés relevantes de permisos, módulos, marca, IA, alertas y bloqueo de nube
   se separaron por base de datos. Una migración fallida ya no se marca como
   aplicada durante la creación de un cliente.
3. Cuatro nuevas métricas de panel: comparación de ventas, ticket promedio,
   anulaciones POS e inventario por categoría. Una falla SQL de ventas ya no
   aparece como ventas de valor cero.
4. Preguntas públicas sobre envío o servicios no se confunden con la búsqueda
   de un producto; se consultan los textos publicados o la función de servicios.

## Próxima ampliación funcional

Mantener el chat público estrictamente informativo: catálogo visible, servicios,
contacto, horarios, FAQ y enlaces aprobados. Nunca ventas internas, caja,
contabilidad, nómina, datos de otros clientes ni SQL libre.

Para el Asistente IA del panel, la siguiente fase puede agregar consultas de
solo lectura sobre: cartera vencida por antigüedad, conciliación de pagos,
pedidos con riesgo de retraso, rotación por proveedor, margen por categoría,
devoluciones por motivo, clientes por recuperar y calidad de facturación. Cada
capacidad exige definición de fuente de verdad, permiso por rol y prueba con
una base de cliente representativa.

Las acciones que **modifican** datos (crear tarea CRM, actualizar pedido,
marcar cotización/cuenta de cobro pendiente de pago, ajustar stock, enviar
mensaje o emitir documento) requieren otro contrato: vista previa con datos
exactos, confirmación humana explícita, comprobación de permiso al ejecutar,
clave de idempotencia, auditoría y, cuando aplique, reversión. No deben quedar
expuestas al visitante anónimo ni ejecutarse solo porque el modelo lo sugiera.

## Orden de salida a producción

1. Rotar la clave Anthropic expuesta; fijar límites de gasto externos y dejar
   el umbral local en cero hasta la prueba controlada.
2. Probar cada consulta nueva y la reconciliación de ventas en `cyber_t002`;
   ejecutar suite completa con la BD de pruebas disponible.
3. Implementar roles/credenciales de infraestructura por cliente y comprobar
   explícitamente que A no puede conectarse ni leer B.
4. Resolver la configuración de la instancia principal; probar fallo del PC,
   tres sondeos/180 s, correo de aviso y regreso automático al PC.
5. Desplegar primero en un canario y luego por lotes desde el maestro. No
   habilitar `ai_public` antes de completar F6–F9.

## Anexo 2026-09-24: primera capa operativa

Se implementó localmente una capa separada para ajustar stock por producto y
crear, editar o desactivar contactos mediante propuestas confirmadas. El
maestro incorpora `ai_actions` (apagado por defecto, incluso en Ultra) y ve
las últimas decisiones de la base del cliente seleccionado. La propuesta y la
ejecución están ligadas a la BD y al usuario activos, con caducidad, permisos
revisados al confirmar, comparación de datos bajo bloqueo e idempotencia. Ver
`IA_ACCIONES_OPERATIVAS.md` para el mapa exacto y las funciones siguientes.

Esto **no** cierra los P0 de infraestructura ni constituye una validación con
PostgreSQL real: la migración 0015 y los cuatro flujos necesitan prueba en la
base demo y canario antes de activar el interruptor de un cliente.
