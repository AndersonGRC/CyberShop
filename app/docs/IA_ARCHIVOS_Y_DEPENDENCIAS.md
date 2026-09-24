# Inventario de archivos de IA y dependencias

Auditoría del código local: 24/09/2026. Abarca `CyberShop/app`,
`CyberShopAdmin` y `CyberShopDesktop`. «Conectado» significa que existe una
ruta o un llamador en este código, **no** que esté desplegado ni habilitado en
producción. No se consultaron bases de clientes, cron del servidor ni servicios
de pago. Las pruebas con dobles tampoco certifican el aislamiento SQL entre
clientes; véase [la auditoría multicliente](AUDITORIA_IA_MULTITENANT_2026-09.md).
Para publicar este lote, véase [el procedimiento por cliente](IA_ACTUALIZACION_CLIENTES.md).

## Qué significa cada carpeta

```text
Pregunta del panel ──> routes/ia.py ──> ai_service.py
                                          ├─> ia/ (registro y decisión)
                                          ├─> ia_datos/ (consultas SQL fijas)
                                          ├─> ia_motores.py ──> ia_nube.py (solo emergencia)
                                          └─> ia_acciones.py (escritura con confirmación)

Escritorio ──> api_sync.py ──> ai_service.py

Visitante ──> [ruta/widget pendientes] ──> chat_publico/motor.py
                                            ├─> ia_datos/publico.py
                                            └─> ia_rag/ (textos publicados)

admin.cybershopcol.com ──> módulos, integraciones, migraciones y auditoría
```

`ia/` **no es otro modelo de IA**: define capacidades y palabras clave.
`ia_datos/` tampoco es una base de datos distinta: contiene consultas que
utilizan la conexión del cliente actual. `ia_rag/` indexa textos de ese mismo
cliente para el chat público previsto. El modelo local o Anthropic solo
selecciona/redacta en los flujos que lo requieren; las consultas tienen SQL
predefinido. Las operaciones de escritura están separadas en `ia_acciones.py`.

El registro de 46 capacidades se llena al importar `services.ia_datos`; importar
solo `services.ia` no lo puebla. El mapa de funciones y frases se genera con
`tools/ia_mapa.py` en [IA_MAPA.md](IA_MAPA.md); no se edita a mano.

## Inventario de `services/ia/` y `services/ia_datos/`

Todos los archivos de esta tabla están conectados por importaciones del
asistente, del catálogo o de sus consultas. «Conectado» no garantiza que cada
frase se haya probado contra una base real.

| Archivo | Responsabilidad |
| --- | --- |
| `ia/__init__.py` | Expone el contrato del registro; no carga por sí solo las capacidades. |
| `ia/registro.py` | Define capacidades, canales, metadatos y registro único. |
| `ia/intenciones.py` | Frases disparadoras y metadatos de las 46 capacidades. |
| `ia/enrutador.py` | Reconoce preguntas inequívocas y parámetros sin llamar al modelo. |
| `ia_datos/__init__.py` | Importa dominios, registra las 46 consultas, valida parámetros y ejecuta. |
| `ia_datos/acceso.py` | Contexto de canal, módulos y permisos por rol. |
| `ia_datos/base.py` | Utilidades comunes de fechas, esquema, rangos y SQL. También lo usan `cartera_service.py` e `ia_rag/`. |
| `ia_datos/ventas.py` | Ventas, productos, clientes, pedidos y tendencias. |
| `ia_datos/analitica.py` | Comparativos, ticket, anulaciones e inventario por categoría. |
| `ia_datos/inventario.py` | Existencias, reorden, catálogo y valor. |
| `ia_datos/operacion.py` | Pedidos, soporte, inventario, facturación, cupones y calidad. |
| `ia_datos/comercial.py` | CRM, cartera, historial y reseñas. |
| `ia_datos/finanzas.py` | Resultados y márgenes. |
| `ia_datos/caja.py` | Caja y medios de pago. |
| `ia_datos/restaurante.py` | Mesas y desempeño del restaurante. |
| `ia_datos/nomina.py` | Resúmenes de nómina y empleados según permiso. |
| `ia_datos/publico.py` | Cinco consultas de catálogo, servicios y negocio para el canal público previsto. |
| `ia_datos/alertas.py` | Alertas por regla; también se usa directamente desde panel y correo. |

No se encontraron sentencias de escritura de negocio en `ia_datos/`. Su
facultad es consultar. La fachada `services/ai_tools.py` reexporta símbolos
de ese paquete y tiene consumidores reales; **no debe borrarse** como supuesto
duplicado.

## Otros archivos del sistema IA

| Estado en el código | Archivos | Para qué sirven |
| --- | --- | --- |
| Conectado al panel | `routes/ia.py`, `services/ai_service.py`, `services/ai_tools.py`, `templates/admin/ia_panel.html` | Rutas, planificación, consultas, generación de contenido y pantalla del Asistente IA. |
| Frontera de cliente conectada | `database.py`, `services/db_layer.py`, `services/tenant_resolver.py`, `tenant_features.py` | Selección de la base efectiva del request y módulos permitidos para ese cliente. La independencia física de bases debe completarse con roles SQL separados. |
| Conectado al panel, apagado por cliente por defecto | `services/ia_acciones.py`, `CyberShopAdmin/migrations/tenant/0015_ia_acciones_pendientes.sql` | Proponer, confirmar, cancelar y auditar cambios de inventario/contactos. Requiere módulo, permiso y confirmación explícita; ver [contrato](IA_ACCIONES_OPERATIVAS.md). |
| Condicional al tipo de solicitud y configuración | `services/ia_motores.py`, `services/ia_nube.py` | Selección de motor local y respaldo Anthropic. El respaldo viene con presupuesto local cero por defecto. |
| Conectado bajo `CYBERSHOP_API_ENABLED=1` | `routes/api_sync.py` | Proxy autenticado `/ai/estado`, `/ai/chat` y `/ai/accion` para el escritorio. Aquí `/ai/accion` **genera texto**; no ejecuta el CRUD conversacional del panel. |
| Conectado a rutas/plantillas | `services/ia_resumen_correo.py`, `static/js/ia_contenido.js`, `static/js/ia_espera.js`, `static/css/ia_gemini.css` | Resumen por correo, asistentes de contenido, espera y estilo de pantalla. `ia_contenido.js` lo usan publicaciones, servicios y slides. |
| Entrada manual; programación externa no verificada | `cron_resumen_ia.py` | Envía resumen diario al ejecutarse. No se encontró instalador de cron por cliente en los repositorios; no afirmar que corre automáticamente. |
| Preparado, sin ruta/widget público | `services/chat_publico/__init__.py`, `services/chat_publico/motor.py` | Respuesta informativa al visitante. `ai_public` como flag no crea por sí solo un endpoint. |
| Preparado, sin indexación automática detectada | `services/ia_rag/__init__.py`, `services/ia_rag/buscar.py`, `services/ia_rag/indexador.py`, `CyberShopAdmin/migrations/tenant/0012_ia_documentos.sql` | Índice y búsqueda de textos. `buscar` solo tiene consumidor en el motor público; `reindexar`/`reindexar_uno` solo aparecen como llamadas en pruebas. |
| Administración conectada | `CyberShopAdmin/config.py`, `tenant_service.py`, `module_service.py`, `integrations_service.py`, `routes/tenant_routes.py`, `templates/tenant_detail.html` | Alta/instancia y migraciones, habilitación por cliente, configuración del PC/Anthropic e historial de acciones desde `admin.cybershopcol.com`. |
| Escritorio conectado a la API condicional | `CyberShopDesktop/sync_client.py`, `main.py`, `local_store.py` | Chat online, sugerencia de texto CRM y persistencia local del historial. No es otro motor ni ejecuta acciones CRUD de IA; la sugerencia CRM solo llena notas editables. |

Las migraciones `CyberShopAdmin/migrations/tenant/0010_ia_consultas.sql`,
`0013_ia_consultas_traza.sql` y `0014_ia_uso_nube.sql` son esquema necesario,
no scripts de ejecución del chat. Los servicios crean algunas tablas también
en tiempo de petición; esa duplicación se debe revisar antes de retirarla.

Los archivos `tools/ia_mapa.py`, `ia_foto_herramientas.py`,
`ia_comparar_fotos.py`, `ia_medir_modelos.py`, `ia_medir_tokens.py` e
`ia_reconciliar_ventas.py` son utilidades manuales/de diagnóstico, no rutas
del usuario. `ia_mapa.py` sí participa en una prueba de consistencia. El
script de fotos aún menciona 37 herramientas y contiene rutas locales fijas;
debe actualizarse antes de volver a usarlo. Los `tests/test_ia_*.py` y
`tests/test_chat_publico_*.py` verifican contratos, pero no equivalen a una
prueba de despliegue. `nomina_inteligente.py`, aunque tenga ese nombre, calcula
nómina de forma determinista y no pertenece a esta IA conversacional.

## Duplicación, código candidato y riesgos hallados

| Prioridad | Hallazgo comprobado en código | Tratamiento propuesto |
| --- | --- | --- |
| Alta | `ai_service.py` consulta `plan.get('perfil', 'normal')` en los dos caminos de respuesta, pero `_plan_chat_pasos()` no incluye `perfil` en ningún plan. `ia_motores.perfil_desde_texto()` no tiene llamador de producción detectado. La selección profunda documentada no se activa por esa vía. | Conectar la decisión de perfil una sola vez, con pruebas para chat normal/stream y sin alterar permisos. |
| Alta antes de publicar | `chat_publico/motor.py::_clave_cache()` pierde la identidad del cliente si falla su obtención y usa solo la huella del texto como clave. No hay ruta pública hoy. | Fallar cerrado o desactivar caché ante identidad incierta; probar dos clientes antes de conectar el endpoint. |
| Media | La IA de productos está repetida en `templates/GestionProductos.html` y `templates/editar_producto.html` (aprox. 160 líneas por plantilla). | Extraer módulo JS común, conservando los selectores/estados de ambas pantallas, y probar en navegador. |
| Media | Etapas CRM definidas en `ia_datos/comercial.py` y dos veces en `routes/crm.py`; el predicado común de pedido pagado acepta `PAGADO` y `APROBADO`, mientras algunas consultas filtran solo `APROBADO`. | Acordar semántica de negocio y fijar una fuente de verdad con tests de cifras; no sustituir cadenas a ciegas. |
| Media | `ia_rag/indexador.py::reindexar_uno(fuente, fuente_id)` ignora `fuente_id` y reindexa un grupo entero. No tiene llamador de producción detectado. | Implementar actualización por documento o renombrar según contrato antes de conectar guardados. |
| Media | El enrutador interpreta «anteayer» como «ayer». | Agregar período exacto o dejar la pregunta al planificador; nunca devolver cifras de otro día. |
| Baja | Comprobaciones de salud del modelo y normalizadores de texto se repiten en varios servicios, con diferencias de credenciales/semántica. | Comparar contratos antes de unificar; la similitud no autoriza eliminar uno. |
| Baja | `ia_datos.__init__.TOOLS` solo aparece como reexportación en el análisis estático; no se halló consumidor interno. | Marcar como candidato, revisar importadores externos y conservar compatibilidad antes de retirarlo. |

La política de `ia_datos/acceso.py` comprueba el canal explícitamente solo
para el público. Conviene especificar y probar qué herramientas de canal
«Público» puede ver el panel cuando `ai_public` esté encendido. El aislamiento
completo de clientes sigue condicionado por los pendientes P0 de la auditoría
multicliente: bases independientes no bastan si comparten un rol PostgreSQL con
acceso entre ellas.

## Verificación de esta auditoría

- Pasaron 193 pruebas del registro, enrutamiento, panel, motores, respaldo,
  analítica, acciones y enrutamiento público que no requieren la base local.
- En `CyberShopAdmin`, pasaron 6 pruebas de control de acciones e integraciones;
  1 quedó omitida.
- `tests/test_chat_publico_acceso.py` no se pudo validar aquí: sus 26 casos
  terminan durante la preparación de la base con `UnicodeDecodeError` de
  `psycopg2.connect`. No son 26 fallos de aserción. También falta un canario
  con bases reales para el índice RAG, el aislamiento y las cifras.
- `git diff --check` no reportó errores de formato. No se movieron módulos,
  eliminaron archivos ni cambiaron SQL o rutas en esta organización.

## Orden seguro de reorganización

1. Mantener estas carpetas y la fachada `ai_tools.py` mientras haya importadores.
   No se encontró un archivo Python de IA completo demostrablemente prescindible.
2. Cerrar los fallos de perfil, fecha, caché y política de canal con pruebas.
3. Unificar JS de productos y constantes/criterios de negocio con pruebas de
   regresión, conservando adaptadores para importaciones anteriores.
4. Solo entonces dividir módulos mixtos (`operacion.py`, `ventas.py`,
   `comercial.py`), migrar imports y considerar retirar símbolos sin lectores.
5. Para validar «funciona en producción»: comprobar despliegue, flags,
   migraciones, cron de cada instancia y pruebas canario con dos bases de
   clientes; el inventario estático no puede reemplazar esa comprobación.
