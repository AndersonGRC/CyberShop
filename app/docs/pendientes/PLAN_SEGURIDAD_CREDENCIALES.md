# Plan pendiente: seguridad de credenciales e infraestructura

**Estado:** pendiente. Ejecutarlo en una sesión dedicada, con tiempo y con acceso al
servidor, porque implica cambiar contraseñas en producción. Detectado en la
auditoría del 2-oct-2026. Este documento no contiene ningún secreto.

## Hallazgos

1. **Contraseñas en texto plano en la configuración de Claude Code**
   - `C:\Cybershop\.claude\settings.json` y `settings.local.json`: la contraseña de root del VPS
     (`VPS_PASSWORD=…`) aparece en ~46 reglas de permisos y la de postgres (`PGPASSWORD=…`) en una.
   - No están en ningún repositorio (`C:\Cybershop` no es repo git), pero quedan en disco y en los
     historiales de sesión.
2. **Scripts con credenciales incrustadas** en `C:\Cybershop\.vps_helper\`:
   `inspect_schema.py`, `migrate_sync_v2.py`, `reset_pos_desktop.py`, `setup_sync.py`,
   `verify_e2e.py`, `verify_landed.py`, `verify_product.py`, `verify_stock.py`.
   `vps_ssh.py` sí lee la contraseña del entorno. Hay ~190 scripts de un solo uso y copias viejas
   de producción en `_prodpull/`.
3. **`C:\Cybershop\CONTEXTO_IA_SERVIDOR.md` §3** muestra como «nombre de variable» una cadena que
   parece la contraseña misma.
4. **`DB_PASSWORD` en el historial de git** (memoria `provisioning_tenant_model`).
5. **Aislamiento entre clientes** (P0 de `AUDITORIA_IA_MULTITENANT_2026-09.md`): las instancias
   `cybershop@.service` corren como `root` y todas usan el rol `postgres` compartido.
6. **Respaldos**: no hay copia fuera del servidor (restic/rclone) ni una restauración probada.
7. **Llave de despliegue** de git con permisos de escritura (debería ser solo lectura).

## Pasos propuestos (en este orden)

1. **Inventario sin mostrar valores**: listar qué servicios usan cada contraseña
   (SSH root, postgres, `DB_PASSWORD` de las instancias y del maestro, llaves de despliegue).
2. **Rotar**:
   - Root del VPS: crear un usuario sudo con llave SSH, deshabilitar el login por contraseña de root.
   - Postgres: nueva contraseña; actualizar `/var/www/CyberShop/app/.cybershop.conf`,
     `/var/www/CyberShopAdmin/.cybershop.conf` y `/etc/cybershop/*.env`; reiniciar instancias de a una.
3. **Limpiar la configuración local**: quitar de `.claude/settings*.json` todas las reglas con
   secretos (reemplazarlas por reglas genéricas que lean variables de entorno).
4. **`.vps_helper`**: mover lo reutilizable a `CyberShopAdmin/tools/ops/` leyendo credenciales solo
   del entorno; archivar el resto fuera de cualquier repo y borrar `_prodpull/`.
5. **Corregir `CONTEXTO_IA_SERVIDOR.md` §3** y moverlo a la documentación versionada sin secretos.
6. **Historial de git**: tras la rotación, el valor viejo deja de servir; decidir si además se
   reescribe el historial (afecta a todos los clones).
7. **Aislamiento**: usuario de sistema propio para `cybershop@.service` y un rol de PostgreSQL por
   cliente con permisos solo sobre su base.
8. **Respaldos**: copia cifrada fuera del servidor (restic/rclone) diaria y una restauración de
   prueba documentada.
9. **Llave de despliegue** de solo lectura.

## Verificación

- Ningún archivo del workspace contiene contraseñas (búsqueda por las cadenas viejas).
- Login SSH solo por llave; las contraseñas viejas ya no sirven.
- Todas las instancias responden tras la rotación (`/admin` 302 y `/` 200 por dominio).
- Una base restaurada desde el respaldo externo arranca y muestra datos.
