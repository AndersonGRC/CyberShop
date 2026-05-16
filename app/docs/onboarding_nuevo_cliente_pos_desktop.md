# Onboarding de un nuevo cliente — POS Desktop

Guía paso a paso para dar de alta a un cliente nuevo en CyberShop POS Desktop
(la app de escritorio offline en [CyberShopDesktop/](../../../CyberShopDesktop/)).

> Resumen del modelo: una sola plantilla `CyberShopSetup_base.exe` (firmada,
> idéntica para todos) + un `bootstrap.json` corto por cliente. La marca
> (colores/logo/datos) se sincroniza desde el servidor al primer arranque.
> No se compila un instalador por cliente.

---

## 0. Arquitectura en 30 segundos

```
┌──────────────┐  client_code  ┌────────────────┐  X-Sync-Key  ┌──────────┐
│  Admin (vos) │ ─────────────►│  Cliente final │ ───────────► │ Servidor │
└──────────────┘               └────────────────┘              └──────────┘
        │                            │                              │
        │ crear_sync_key.py          │ /descargar (portal)          │ /api/v1/sync/*
        │ → genera client_code       │ ↓ ZIP con bootstrap.json     │ → branding,
        │ → genera api_key (única    │   + CyberShopSetup.exe       │   productos,
        │   vez, no se vuelve a      │ → instalador asistido        │   outbox,
        │   ver)                     │ → escribe                    │   versión
        │                            │   %APPDATA%\CyberShopNative\ │
        │                            │   .cybershop.conf            │
        ▼                            ▼                              ▼
   Tenant + DB              POS Desktop offline               Postgres por
   (cyber_tNNN)             (SQLite local + sync)             tenant
```

Documentos relacionados:
- [CyberShopDesktop/README.md](../../../CyberShopDesktop/README.md) — manual de la app
- [services/installer_packager.py](../services/installer_packager.py) — empaquetado del ZIP
- [tools/crear_sync_key.py](../tools/crear_sync_key.py) — generación de credenciales
- [routes/api_sync.py](../routes/api_sync.py) — endpoints `/api/v1/sync/*`
- [routes/public.py:462](../routes/public.py#L462) — portal `/descargar`

---

## 1. Pre‑requisitos del lado servidor (una sola vez)

Antes del primer cliente, verificar que estos artefactos existen:

| Artefacto | Cómo se genera | Notas |
|---|---|---|
| Control plane DB (`saas_control_plane`) con tablas `tenants`, `tenant_databases`, `sync_api_keys`, `usuarios_globales`, `refresh_tokens` | `tools/vps/03_setup_postgres.sh` | Idempotente |
| `static/installers/CyberShopSetup_base.exe` | `CyberShopDesktop\build_installer.bat` | Compilar en Windows con Inno Setup 6 |
| `static/installers/version.json` | A mano, ya commiteado | Bumpear `latest` en cada release |
| `.cybershop.conf` del servidor con `KMS_KEY`, credenciales Postgres, `SERVER_URL` | `tools/vps/05_configurar_env.sh` | |

Si falta el `.exe` base, `/descargar` lanza `InstallerNotBuiltError`.

---

## 2. Alta del tenant (admin → servidor)

### 2.1. Crear la base de datos del cliente

Cada cliente vive en una DB Postgres separada (`cyber_tNNN`). El esquema sale del
backup en [migrate_backup_db.sql](../migrate_backup_db.sql) (o de un `pg_dump`
de un tenant plantilla).

```bash
# En el servidor:
sudo -u postgres createdb cyber_t007
sudo -u postgres psql cyber_t007 < migrate_backup_db.sql
```

### 2.2. Registrar el tenant en el control plane

Insertar en `tenants` y `tenant_databases`. Con el script automático:

```bash
TENANT_SLUG=panaderia-roma TENANT_NOMBRE="Panadería Roma" \
  python tools/migrate_prod_to_tenant.py
```

O manualmente (psql sobre `saas_control_plane`):

```sql
INSERT INTO tenants (slug, nombre, estado)
VALUES ('panaderia-roma', 'Panadería Roma', 'activo')
RETURNING id;

INSERT INTO tenant_databases (tenant_id, db_name, db_host, db_port, db_user, db_password_enc)
VALUES (<id>, 'cyber_t007', 'localhost', 5432, 'cyber_t007_user', '<aes_gcm_encrypted>');
```

> La password se cifra con `services.crypto_utils.aes_gcm_encrypt()` usando
> `KMS_KEY` del `.cybershop.conf` del servidor. Nunca en claro.

### 2.3. Generar la API key + client_code

```bash
cd CyberShop/app
python tools/crear_sync_key.py \
  --tenant-slug panaderia-roma \
  --label "POS Tienda Centro"
```

Salida típica:

```
────────────────────────────────────────────────────────
  Tenant:      panaderia-roma (Panadería Roma)
  Key ID:      42
  Etiqueta:    POS Tienda Centro
  Client code: CYB-A3F2K9P1
  API key:     cyb_live_a3f2k9p1xyz... (NO se vuelve a mostrar)
────────────────────────────────────────────────────────
```

**Lo único que se entrega al cliente es el `client_code`** (`CYB-A3F2K9P1`).
La `api_key` viaja embebida en el `bootstrap.json` que arma `/descargar`,
nunca por canal humano.

> En la DB solo queda el SHA‑256 de la key (`sync_api_keys.key_hash`). Si se
> pierde, se revoca y se emite una nueva — no hay forma de recuperarla.

### 2.4. Configurar la marca del cliente

Login admin → **Configuración del cliente** (`/admin/configuracion-cliente`) →
completar los 5 grupos de `cliente_config`:

| Grupo | Claves | Dónde se ve en el POS Desktop |
|---|---|---|
| `empresa` | nombre, email, telefono, direccion, website, whatsapp, copyright | Header, recibos, footer |
| `colores` | primario, primario_oscuro, secundario, acento, hover_menu, transicion, botones, acento_secundario | Sidebar, botones, badges |
| `redes` | facebook, twitter, youtube, linkedin, instagram | (solo sitio web, no POS) |
| `contacto` | empresa_maps_embed, contacto_email_destino | (solo sitio web) |
| Logo | `static/img/Logo.png` | Header del POS Desktop |

El POS Desktop pulla esto vía `/api/v1/sync/branding` y mapea las claves así
([api_sync.py:47](../routes/api_sync.py#L47)):

| `cliente_config.colores.*` | `branding.json.colores.*` |
|---|---|
| `primario`, `primario_oscuro`, `acento`, `acento_secundario` | (mismo nombre) |
| `secundario` | `sidebar_inicio` |
| `botones` | `sidebar_fin` |

---

## 3. Entrega al cliente

### 3.1. Instrucciones que mando al cliente (plantilla email)

```
Hola <cliente>,

Tu CyberShop POS Desktop está listo. Para instalarlo:

1. Abrí en cualquier navegador: https://cybershopcol.com/descargar
2. Pegá este código de cliente: CYB-A3F2K9P1
3. Bajás un ZIP. Extraelo en una carpeta (Escritorio sirve).
4. Ejecutá CyberShopSetup.exe (el bootstrap.json al lado, no lo borres).
5. El asistente pre-llena los datos solo. Aceptá Siguiente / Siguiente.
6. Al terminar la instalación, abrí "CyberShop POS" desde el menú inicio.

Login inicial:
   Usuario:    admin@cybershop.local
   Contraseña: admin123
   (cambiala desde F6 → Usuarios al primer ingreso)

Atajos: F1 Dashboard · F2 Productos · F3 POS · F4 Inventario
        F5 Ventas · F6 Usuarios · F7 Sincronización · F8 Configuración

Soporte: <tu email>
```

### 3.2. Qué pasa internamente cuando ejecuta el instalador

1. Inno Setup detecta `bootstrap.json` adyacente y pre-llena el wizard
   ([installer.iss:96](../../../CyberShopDesktop/installer.iss#L96)).
2. El cliente confirma URL del servidor + API key + slug.
3. El asistente escribe `%APPDATA%\CyberShopNative\.cybershop.conf` con
   todas las claves de `DEFAULTS` en
   [cybershop_conf.py:33](../../../CyberShopDesktop/cybershop_conf.py#L33).
4. PyInstaller deposita `CyberShopOffline.exe` en `Program Files\CyberShop POS\`.
5. Al primer arranque la app crea SQLite local + jala branding/productos del
   servidor.

---

## 4. Verificación post‑instalación

Pedirle al cliente que confirme estos puntos. Si alguno falla, atender en orden:

| Check | Cómo verifica el cliente | Qué hago si falla |
|---|---|---|
| Login funciona | Abre app, logea admin@cybershop.local / admin123 | Borrar `%APPDATA%\CyberShopNative\cybershop_offline.db` y reabrir |
| Colores y logo correctos | Sidebar y header con la marca del cliente | Verificar `cliente_config` en `/admin/configuracion-cliente` y forzar sync (F7 → "Sincronizar ahora") |
| Productos bajaron | F2 Productos lista catálogo | F7 muestra el estado de sync; revisar logs en `%APPDATA%\CyberShopNative\` |
| POS escanea (F3) | Pasa una pistola USB sobre un código → suma al carrito | El campo verde tiene que tener foco; ver troubleshooting en README |
| Venta llega al servidor | Hacer venta de prueba; luego desde `/contabilidad/movimientos` ver el registro | El outbox está en `pos_outbox` (SQLite local); F7 muestra ítems pendientes |
| Auto‑update funciona | Al login muestra "no hay actualizaciones" si `version.json.latest == APP_VERSION` | Revisar `static/installers/version.json` y `APP_VERSION` en `main.py` |

---

## 5. Operaciones recurrentes

### 5.1. Revocar acceso a una instalación (cliente perdió equipo, despido, etc.)

```sql
-- En saas_control_plane:
UPDATE sync_api_keys SET active = FALSE WHERE id = <key_id>;
```

A partir de ese momento todos los `/api/v1/sync/*` de esa instalación
devuelven 401. Emitir nueva key con `crear_sync_key.py` si reinstala.

### 5.2. Liberar una nueva versión del POS Desktop

1. Bumpear `APP_VERSION` en
   [CyberShopDesktop/main.py](../../../CyberShopDesktop/main.py).
2. `cd CyberShopDesktop && build_installer.bat` (regenera `.exe` y lo copia
   a `static/installers/CyberShopSetup_base.exe`).
3. Editar [version.json](../static/installers/version.json):
   ```json
   {
     "latest":         "1.1.0",
     "min_required":   "1.0.0",
     "download_url":   "/static/installers/CyberShopSetup_base.exe",
     "checksum_sha256":"<sha256 del .exe>",
     "release_notes":  "..."
   }
   ```
4. Commit del `version.json` (no del `.exe` — pesa).
5. Subir el `.exe` a producción aparte (rsync/scp/CI).

Los clientes existentes ven el diálogo de actualización en su próximo login.

### 5.3. Cliente quiere overridear el branding localmente

Por ejemplo, una sucursal con tema propio. En `%APPDATA%\CyberShopNative\sync_config.json`:

```json
{ "branding_local_override": true }
```

Con eso, los colores/logo del servidor dejan de pisar lo que hay en
`branding.json`. Editan desde F8 o copian `branding.json` entre máquinas
(Exportar/Importar).

### 5.4. Deshabilitar auto‑update en una máquina

En `%APPDATA%\CyberShopNative\.cybershop.conf`:

```
AUTO_UPDATE_CHECK=false
```

---

## 6. Checklist condensado (copy‑paste)

```
[ ] DB del tenant creada y poblada con esquema base
[ ] Tenant insertado en saas_control_plane.tenants + tenant_databases
[ ] python tools/crear_sync_key.py --tenant-slug <slug> --label <label>
    → guardar client_code en CRM, descartar la api_key (ya está en DB hasheada)
[ ] /admin/configuracion-cliente → grupos empresa, colores, contacto
[ ] Subir Logo.png a static/img/
[ ] Verificar que static/installers/CyberShopSetup_base.exe existe
[ ] Enviar al cliente: URL /descargar + client_code + credenciales iniciales
[ ] Acompañar primer login: branding ✓, productos ✓, venta de prueba ✓
[ ] Cambiar password de admin@cybershop.local
```

---

## 7. Troubleshooting rápido

| Síntoma | Causa probable | Fix |
|---|---|---|
| `/descargar` dice "El instalador no está disponible" | Falta `CyberShopSetup_base.exe` en `static/installers/` | Correr `build_installer.bat` y copiar el .exe |
| Wizard pide URL/key a mano (no se pre‑llenó) | `bootstrap.json` no está al lado de `CyberShopSetup.exe` | Recordar al cliente que extraiga TODO el ZIP, no solo el .exe |
| App abre pero F7 muestra "401 Unauthorized" | API key revocada, expirada o tenant `inactivo` | `SELECT active FROM sync_api_keys` y `SELECT estado FROM tenants` |
| Colores no se aplican tras cambiar `cliente_config` | Sync de branding aún no corrió | F7 → "Sincronizar ahora", o cerrar/abrir la app |
| Productos no aparecen | Catálogo vacío en el tenant, o sync sin éxito | Cargar productos en `/admin/editar-productos` y forzar pull |
| Ventas no llegan al servidor | Outbox bloqueado por error | Ver `pos_outbox` en SQLite local; F7 muestra contador de pendientes |
| `branding.json` se pisa cada arranque | El override local no está activado | Activar `branding_local_override: true` en `sync_config.json` |
