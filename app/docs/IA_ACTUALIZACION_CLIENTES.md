# Publicación de este lote de IA con «Actualizar app»

Estado verificado en el código local el 24/09/2026. Esta guía describe el
comportamiento del botón de `admin.cybershopcol.com`; **no es constancia de
despliegue**. No se pulsó el botón, no se consultó producción y no se hizo
ninguna llamada a Anthropic.

## Respuesta corta

El código del botón está diseñado para llevar el **código web CyberShop** y las
**migraciones de la base de cada cliente** desde «Técnico → Actualizar app»,
una vez publicado el lote, actualizado el maestro y verificado el helper del
VPS. Su funcionamiento real no se puede certificar desde este equipo. No se
puede publicar *todo* el
trabajo local con ese único botón: no instala el código de `CyberShopAdmin`,
el POS de escritorio, dependencias, archivos de entorno, servicios ni cron.

Además, el código web es **compartido**. El primer clic integra los archivos
del servidor para todos los clientes; en cada clic se migra únicamente la BD
seleccionada y se recarga únicamente su instancia. Esto no es un despliegue de
código aislado por cliente. Las nuevas funciones deben seguir apagadas por
defecto y ser compatibles con clientes aún no migrados durante el despliegue.

| Parte de este lote | ¿La lleva el botón por cliente? | Condición real |
| --- | --- | --- |
| `CyberShop/app`: rutas, servicios, plantillas internas, JS/CSS y documentación | Sí, como código **global** del repo web | Tiene que estar en `origin/master`; el *gate* bloquea el botón normal si detecta archivos públicos de su lista. |
| Migraciones de tenant pendientes (IA: `0010`, `0012`–`0015`) | Sí, **una base por clic** | Los archivos tienen que existir ya en el servidor de `CyberShopAdmin`; el migrador registra cada SQL aplicado en la BD elegida. |
| Nuevos módulos/controles y configuración Anthropic del maestro | No | Publicar y reiniciar `CyberShopAdmin` por su procedimiento propio **antes** del primer clic. |
| Clave, modelo y presupuesto Anthropic de un cliente | No | Configurar en Integraciones; el `EnvironmentFile` requiere **reinicio**, no la recarga del botón. El cliente primario aún lee `.cybershop.conf`, no el env guardado por ese panel. Presupuesto por defecto: US$0 (apagado). |
| Activación de `ai_actions` y permisos | No automáticamente | El flag nace apagado. Activar cliente por cliente, después de migrar y probar. Guardar módulos reinicia su instancia. |
| Chat público e índice RAG | No queda operativo solo con actualizar | El motor no tiene endpoint/widget público ni indexación automática conectada. `0012` crea la tabla, no la llena. No activar `ai_public` como si ya estuviera listo. |
| POS de escritorio, instalador, env/venv/unit/cron | No | Pipeline y operación separados; no asumir que «Actualizar app» los cubre. |

## Estado de entrega de este workspace

- `CyberShop` está en la rama local `feat/barcode-popup`, con cambios de IA
  modificados y sin seguimiento. `CyberShopAdmin` está en `master`, también con
  cambios locales sin commit; `0015_ia_acciones_pendientes.sql` no está en Git.
  El botón del servidor **no ve archivos locales**: solo integra
  `origin/master` del repo web. Revisar, versionar, integrar y publicar ambos
  repositorios bajo el proceso de release; esta guía no autoriza un `push`.
- El botón invoca `/usr/local/bin/cybershop-deploy-code.sh` y reglas de sudo
  externas. Su fuente/instalación no está en estos repositorios. Confirmar en
  el VPS que existen, son ejecutables y permiten `changes`/`apply`; también
  comprobar `ExecReload` del servicio principal `cybershop.service` y de la
  plantilla `cybershop@.service`. No inferirlo de pruebas locales: en Windows
  la operación de Git y la recarga son no-op.
- El ejemplo de NGINX del maestro antes permitía solo 60 segundos sin
  respuesta del backend, menos que los dos pasos Git más la migración. El
  archivo versionado `CyberShopAdmin/deploy/nginx.admin.conf` ahora propone
  360 segundos; solo surtirá efecto cuando se instale/recargue en el VPS. Un
  timeout del navegador no prueba que la operación se haya revertido.
  También deben revisarse los timeouts de cualquier proxy/CDN situado delante
  de NGINX; el cambio local no los configura.
- La ruta hace hoy `deploy_code()` → `migrate_db(base elegida)` → sincronización
  de aviso de cobro → `reload_service(instancia elegida)`. Si la migración o
  recarga falla, **el código global ya pudo cambiar** y las migraciones previas
  quedan aplicadas; el botón no hace rollback automático. El *gate* solo
  identifica las rutas públicas enumeradas en `PUBLIC_PATHS`: cambios de
  backend compartido también pueden alterar el sitio público.
- Verificación local: 193 pruebas de IA web sin BD pasaron; en el maestro,
  25 pasaron y 1 quedó omitida, incluidas pruebas nuevas del orden del botón,
  el *gate* público y la presencia de `0015`. No prueban el script root, Git
  remoto, systemd ni la BD del VPS.

## Secuencia controlada para este lote

1. Cerrar hallazgos y pruebas antes de liberar: aislamiento entre clientes,
   permisos de acciones, perfil/fecha del enrutador y caché pública. Registrar
   una versión web conforme a [VERSIONADO.md](VERSIONADO.md). Mantener
   `ai_actions` y `ai_public` apagados; Anthropic en US$0 salvo decisión
   explícita de gasto. No usar datos reales para el primer ensayo.
2. Publicar **primero `CyberShopAdmin`** con `module_service`, integraciones y
   migración `0015`; reiniciar el maestro y comprobar que la migración aparece
   en `migrations/tenant/`. El botón del cliente no actualiza ese repo.
3. Preparar y publicar el release probado de `CyberShop` en `origin/master`.
   Un commit presente solo en una rama local, o un archivo sin commit, no llega
   al VPS mediante el botón. Verificar que el servidor no tiene cambios Git
   locales que impidan el `merge --ff-only`.
4. Comprobar la infraestructura del botón y tener respaldo de la BD canaria.
   En el maestro, elegir **un cliente de prueba/canario**. «Actualizar app»
   normal debería bastar para los archivos IA internos; si el *gate* indica
   rutas públicas, detenerse y revisar el diff antes de considerar «Deploy
   completo». No usar ese segundo botón solo para saltarse el aviso.
5. Tras el clic, comprobar el resultado real: instancia activa, migración
   `0015` registrada en **esa** BD, panel IA accesible, consultas de solo
   lectura correctas y acciones aún apagadas. Si hubo error o timeout del
   navegador, verificar Git, migraciones y servicio antes de reintentar: la
   operación pudo continuar o quedar parcial.
6. Con el canario conforme, repetir por cliente y verificar su propia BD y
   servicio. Solo después habilitar `ai_actions` donde corresponda y hacer
   pruebas de confirmar/cancelar con permiso y registros de prueba. Configurar
   Anthropic por cliente solo si se aprueba el gasto, con reinicio y límites
   externos del proveedor: el umbral local es **estimado**, no tope duro.

No afirmar «se actualizó cada cliente» por el primer clic: ese clic trae el
código compartido, pero las bases y procesos restantes siguen pendientes.
Tampoco afirmar que el botón preserva *toda* la presentación pública: los
datos y overrides del cliente están fuera de Git, pero el backend y algunos
estáticos compartidos pueden modificar su comportamiento.
