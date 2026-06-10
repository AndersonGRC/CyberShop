# Integración Web ↔ POS de Escritorio

Cómo se conectan la web Flask (`CyberShop/app`) y el POS de escritorio offline
(`CyberShopDesktop`): onboarding, autenticación de sync, endpoints y flujo de
datos. Único documento que describe la cadena de punta a punta.

- **Última actualización:** 2026-05-19
- **Relacionados:** [MAPA_ARCHIVOS.md](MAPA_ARCHIVOS.md) · [onboarding_nuevo_cliente_pos_desktop.md](onboarding_nuevo_cliente_pos_desktop.md) · [../CLAUDE.md](../CLAUDE.md) · [../../../CyberShopDesktop/README.md](../../../CyberShopDesktop/README.md)

---

## 1. Cadena de onboarding

```
Admin (servidor)                Cliente final                 Servidor
  │ crear_sync_key.py              │ /descargar (pega          │ /api/v1/sync/*
  │ → client_code (CYB-XXXX)       │   client_code)            │
  │ → api_key (cyb_live_…,         │ ↓ ZIP: CyberShopSetup.exe │
  │   se ve una sola vez)          │   + bootstrap.json        │
  ▼                                ▼ instalador asistido       ▼
sync_api_keys                %APPDATA%\CyberShopNative\    DB del tenant
(solo el SHA-256)               .cybershop.conf            (cyber_tNNN)
```

1. **Admin**: `python tools/crear_sync_key.py --tenant-slug <slug> --label <etiqueta>`
   → imprime `client_code` y `api_key`. En DB solo queda `sync_api_keys.key_hash`
   (SHA-256). La `api_key` **no se vuelve a mostrar**.
2. **Admin** entrega solo el `client_code` al cliente.
3. **Cliente** abre `https://<server>/descargar`, pega el código → baja un ZIP
   con `CyberShopSetup.exe` + `bootstrap.json` (armado por
   `services/installer_packager.py`).
4. El instalador (`installer.iss`) lee `bootstrap.json` y escribe
   `.cybershop.conf` en `%APPDATA%\CyberShopNative\` (SERVER_URL, SYNC_API_KEY,
   TENANT_*). El escritorio copia esos valores a `sync_config.json`.

Detalle paso a paso del alta del tenant: [onboarding_nuevo_cliente_pos_desktop.md](onboarding_nuevo_cliente_pos_desktop.md).

## 2. Autenticación de sync (`X-Sync-Key`)

Toda llamada a `/api/v1/sync/*` lleva el header `X-Sync-Key: <api_key>`. El
decorador `require_sync_key` en `routes/api_sync.py` resuelve el tenant así:

1. **Multi-tenant**: `_lookup_key_in_db()` busca el SHA-256 de la key en
   `sync_api_keys` (JOIN con `tenant_databases`/`tenants`). Si hay match →
   `g.sync_tenant_id`, `g.sync_db_name`, `g.sync_tenant_slug` y `last_used_at`.
2. **Fallback legacy**: si no hay match, `_legacy_env_key_matches()` compara la
   key contra `SYNC_API_KEY` de entorno. Si coincide → tenant por defecto
   (`DEFAULT_TENANT_ID` / `DB_NAME`).
3. Si ninguno → **HTTP 401** `invalid_key`.

> **Por qué un cambio de key da 401:** si una key que funcionaba por la vía
> legacy deja de estar en `SYNC_API_KEY` del `.cybershop.conf` del servidor, y
> nunca se insertó en `sync_api_keys`, ambas vías fallan → 401 → el escritorio
> cae al login local. Solución: o re-poner `SYNC_API_KEY` en el servidor y
> reiniciar el servicio (restaura la vía legacy), o emitir una key nueva con
> `crear_sync_key.py` y ponerla en `sync_config.json`.

## 3. Endpoints `/api/v1/sync/*`

14 endpoints (`routes/api_sync.py`), todos bajo `require_sync_key`:

| Endpoint | Método | Quién/cuándo lo llama |
|---|---|---|
| `/health` | GET | SyncPage / verificación de conectividad |
| `/auth` | POST | `LoginView` (login remoto: email+password) |
| `/products` | GET | Pull incremental (`?since=<cursor>`) |
| `/users` | GET | Pull de usuarios |
| `/generos` | GET | Pull de categorías |
| `/sales_web` | GET | Pull de ventas web (caché solo lectura) |
| `/inventory_log` | GET | Pull de inventario web (caché solo lectura) |
| `/outbox` | POST | Push de cambios locales |
| `/branding` | GET | ~500 ms tras login (colores/logo del tenant) |
| `/config` | GET | Info pública del tenant (slug, nombre, plan) |
| `/version` | GET | ~1500 ms tras login (auto-update) |
| `/stats` | GET | Métricas agregadas (reservado para dashboard) |
| `/restaurant/snapshot` | GET | Estado completo del módulo de mesas (tables + open_orders + consumptions + products) — snapshot, no incremental |
| `/contabilidad/snapshot` | GET | Movimientos (≤1000) + plantillas + cierres + categorías — snapshot, no incremental |

## 4. Mismo usuario y contraseña (web ↔ escritorio)

Requisito clave: un usuario de la web entra al escritorio con **las mismas
credenciales**.

1. `LoginView._login` → `_try_remote_login()` → `SyncClient.remote_login()` →
   **`POST /api/v1/sync/auth`** con `{email, password}`.
2. El servidor (`auth_login` en `api_sync.py`) busca en `usuarios` del tenant
   (`tenant_cursor(db_name=g.sync_db_name)`) y valida con
   `werkzeug.security.check_password_hash`. Devuelve `{user:{remote_id, email,
   nombre, rol_id, rol_nombre, estado}}`. 401 = credenciales malas; 403 =
   `estado != 'habilitado'`.
3. Con éxito, `LocalStore.cache_remote_login(remote_user, password)` crea/
   actualiza el usuario local y **guarda el hash PBKDF2 (600k iter.) de la
   contraseña recién verificada**.

Resultado: tras un primer login **con internet**, ese usuario también entra
**sin internet** (validación local contra `users.password_hash`). El hash
werkzeug del servidor nunca viaja; el escritorio genera su propio hash PBKDF2.
`pull_users` crea perfiles con `must_change_password=1` (placeholder) hasta que
el usuario hace su primer login online o cambia la contraseña.

## 5. Flujo de datos (pull / push)

- **Pull (servidor → escritorio)**, incremental por cursor (uno por entidad en
  `sync_config.json`): `products` → `upsert_product_from_remote()` (match por
  SKU), `users` → `upsert_user_from_remote()` (match por email), `generos` →
  por `remote_id`; `sales_web`/`inventory_log` → cachés de solo lectura.
- **Push (escritorio → servidor)**: `LocalStore.pending_outbox()` →
  `POST /api/v1/sync/outbox` `{items:[{entity,entity_id,action,payload}]}`
  (sale, inventory_movement, product, user, category, order, **restaurant_op**,
  **contabilidad_op**). Éxito → `mark_outbox_synced()`; fallo → reintento en el
  próximo ciclo.
- **Operaciones offline-first** (`restaurant_op` / `contabilidad_op`): el
  payload lleva `op` (p.ej. `open_table`, `add_consumption`, `close_table`,
  `create_movimiento`, `create_cierre`) y un `client_op_uuid`; el servidor las
  aplica con `_apply_restaurant_op`/`_apply_contabilidad_op` de forma
  **idempotente** (ledger `sync_applied_ops`). `close_table` crea el movimiento
  contable `venta_restaurante`; cierres y generar-plantillas se calculan
  **server-side** (el espejo local puede estar incompleto). El resultado baja
  en el siguiente pull de snapshot (`mark_*_pushed()` → el pull adopta la
  verdad del servidor sin duplicar).
- **Conflictos**: LWW (last-write-wins) por SKU/email usando `updated_at`.
- **Branding** (`/branding`): `apply_remote_branding()` mapea
  `cliente_config.colores.*` → `branding.json` (`secundario→sidebar_inicio`,
  `botones→sidebar_fin`). `branding_local_override:true` evita que el servidor
  pise la marca local.
- **Auto-update** (`/version`): compara contra `APP_VERSION`; ofrece descargar
  el `.exe` desde `static/installers/` o saltar la versión.

## 6. Configuración del escritorio (`%APPDATA%\CyberShopNative\`)

| Archivo | Lo escribe | Contiene |
|---|---|---|
| `.cybershop.conf` | Instalador (`installer.iss`) | SERVER_URL, SYNC_API_KEY, TENANT_*, AUTO_UPDATE_CHECK |
| `sync_config.json` | `sync_config.py` | base_url, api_key, enabled, interval_sec, cursores, last_sync_* |
| `branding.json` | `branding.py` / F8 / sync | empresa + colores |
| `cybershop_offline.db` | `local_store.py` | SQLite (ver README del escritorio) |

> Para un caso real de regresión (key revocada → 401 → login local) y su fix,
> ver §2 de este documento.
