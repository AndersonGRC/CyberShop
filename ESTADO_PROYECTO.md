# CyberShop — Estado Completo del Proyecto

> **Última actualización:** 2026-04-30  
> **Para retomar en otro equipo:** leer este archivo de principio a fin antes de escribir una sola línea.  
> **Repositorio:** https://github.com/AndersonGRC/CyberShop.git  
> **Working directory local:** `C:\Cybershop\CyberShop\` (raíz del repo) / `C:\Cybershop\CyberShop\app\` (código Flask)  
> **Modelo IA usado:** Claude Opus 4.7 en Claude Code CLI  
> **Email propietario:** cybershop.digitalsales@gmail.com

---

## 1. ¿Qué es CyberShop?

Plataforma de gestión empresarial (POS, restaurante, inventario, contabilidad, facturación electrónica DIAN, nómina, CRM, cupones, pedidos web) construida en **Flask 3.1.2 + PostgreSQL**. Actualmente es una app web server-side rendering con Jinja2 + jQuery, 19 blueprints, 7 roles de usuario.

**Objetivo final:** convertirla en una **app de escritorio Windows (y eventualmente macOS) offline-first multi-tenant** usando PyWebView + PyInstaller, que funcione 100 % sin internet en los módulos operativos críticos y se sincronice automáticamente al recuperar conexión.

---

## 2. Decisiones arquitectónicas definitivas (validadas con el usuario)

| Decisión | Elección |
|---|---|
| Empaque desktop | `pywebview==5.4` + `pyinstaller==6.10` |
| BD local desktop | SQLite + SQLCipher AES-256-GCM (`apsw==3.45` + `pysqlcipher3==1.2`) |
| KDF contraseña → clave SQLCipher | `argon2-cffi==23.1` (Argon2id, mem=64 MB, t=3, p=1) |
| Keystore SO | `keyring==24.3` (DPAPI Win / Keychain mac) |
| HTTP sync cliente | `httpx[http2]==0.27` |
| Auth | JWT RS256 `pyjwt[crypto]==2.9` — access 15 min + refresh opaco 30 días |
| Migraciones | `alembic==1.13` multi-DB |
| Rate limit | `flask-limiter==3.8` con Redis backend |
| Cola async VPS | `rq==1.16` + Redis 7 |
| Reverse proxy VPS | Caddy 2.x |
| BD VPS | PostgreSQL 16 + extensión `pgcrypto` |
| Pool VPS | pgbouncer 1.22 modo `transaction` (Fase 5+) |
| IDs | Migración SERIAL → UUID v7 (dual-key transitorio, Fase 2) |
| Multi-tenant | 1 instancia Postgres, **1 database por cliente** (`cyber_t001`, `cyber_t002`, ...) |
| Sincronización | Outbox pattern + LWW (Last-Write-Wins) por `(version, updated_at)` |
| Plataforma desktop | **Windows primero**; macOS como posibilidad futura (sin trabajar hasta Fase 4+) |
| Orden de fases | Estricto 1 → 2 → 3 → 4 → 5 → 6 |
| Producción durante desarrollo | App web HTML siempre operativa; API habilitada con `CYBERSHOP_API_ENABLED=1` |
| pgbouncer | NO en Fase 1 — se agrega en Fase 5 cuando haya >2 tenants |
| KMS | Clave estática `KMS_KEY` en `.env` (Fases 1–5); KMS real en Fase 6 |
| Dominio API | `app.cybershopcol.com` → DNS A → `38.134.148.47` |
| Ventana migración prod | Madrugada 02:00–04:00 hora Colombia (UTC-5), aviso 72 h antes |
| macOS | Posibilidad futura — no se trabaja hasta después de Fase 4 Windows |

### Módulos offline (operativos sin internet)
POS, restaurante, pedidos web (gestión), inventario, catálogo, contabilidad, dinero, billing, cupones, nómina, factura electrónica (estado `pendiente_emision`).

### Solo online (requieren VPS)
Sitio público, PayU webhook, Gmail, Google Calendar, salas de video, soporte chat.

---

## 3. Infraestructura

### VPS de producción
| Dato | Valor |
|---|---|
| IP | `38.134.148.47` |
| SSH | `ssh -p 2222 root@38.134.148.47` |
| Contraseña root | **No almacenada en este archivo** — solicitarla al usuario |
| Dominio app | `app.cybershopcol.com` |
| Dominio principal | `cybershopcol.com` |
| Stack | Caddy 2.x → Gunicorn (workers=4) → Flask → PostgreSQL 16 |
| DB control plane | `saas_control_plane` |
| DB tenant 1 (prod) | `cyber_t001` (migrada desde `cybershop`) |
| Usuario DB | `cybershop_app` |
| Path app en VPS | `/opt/cybershop/` |
| Venv en VPS | `/opt/cybershop/venv/` |
| Logs en VPS | `/opt/cybershop/logs/` |
| Claves JWT en VPS | `/opt/cybershop/app/keys/jwt_private.pem` (chmod 600) |
| Servicio systemd | `cybershop.service` |

### Estado del VPS (al 2026-04-30)
**Los scripts de setup NO se han ejecutado aún.** Se ejecutarán desde casa en este orden:

```bash
# PASO 0 — Desde Windows (Git Bash), subir el código
bash app/tools/vps/00_subir_codigo.sh          # rsync excluyendo venv/, .pem, .cybershop.conf

# PASOS 1–8 — Dentro del VPS (ssh -p 2222 root@38.134.148.47)
bash /opt/cybershop/app/tools/vps/01_diagnostico.sh          # inventario: qué hay instalado
bash /opt/cybershop/app/tools/vps/02_instalar_dependencias.sh # Postgres 16, Redis, Caddy, Python
bash /opt/cybershop/app/tools/vps/03_setup_postgres.sh        # crea saas_control_plane + cyber_t001
bash /opt/cybershop/app/tools/vps/04_deploy_app.sh            # venv + deps + claves JWT + permisos
# ── Editar variables en 05_configurar_env.sh ANTES de ejecutarlo ──
bash /opt/cybershop/app/tools/vps/05_configurar_env.sh        # escribe .cybershop.conf en VPS
bash /opt/cybershop/app/tools/vps/06_gunicorn_service.sh      # systemd service
bash /opt/cybershop/app/tools/vps/07_caddy.sh                 # Caddyfile + TLS Let's Encrypt
bash /opt/cybershop/app/tools/vps/08_firewall.sh              # UFW + fail2ban
```

> **IMPORTANTE en `05_configurar_env.sh`:** completar las variables al inicio del archivo antes de ejecutarlo. El output de `03_setup_postgres.sh` entrega el `DB_PASSWORD` generado automáticamente.

### DNS pendiente
- Crear registro **A**: `app.cybershopcol.com` → `38.134.148.47` en el panel DNS de `cybershopcol.com`
- Esperar propagación (~5 min) antes de ejecutar `07_caddy.sh`
- Verificar: `dig app.cybershopcol.com +short` debe retornar `38.134.148.47`

### Entorno local de desarrollo
| Dato | Valor |
|---|---|
| Python | venv en `C:\Cybershop\venv\` |
| DB local | `cybershop` (PostgreSQL local — la prod actual) |
| Control plane local | `saas_control_plane` — **AÚN NO CREADA** (Semana 2) |
| Claves JWT | `app/keys/jwt_private.pem` + `jwt_public.pem` (generadas, NO en git) |
| KMS_KEY | Generada en `.cybershop.conf` local (NO en git) |
| Puerto Flask dev | `5001` |

---

## 4. Arquitectura completa — Diagrama lógico final (al completar Fase 4)

```
+============================  CLIENTE (Win/Mac)  ===============================+
|  PyWebView Shell (ventana nativa WebView2/WKWebView)                           |
|         |  http://127.0.0.1:5001                                               |
|         v                                                                      |
|  Flask local (mismo código actual, blueprints intactos)                        |
|         |--> services/db_layer.py  (switch Postgres ↔ SQLite)                  |
|         |--> services/sync/worker.py  (thread: pull+push, online detection)    |
|         v                                                                      |
|  SQLite + SQLCipher (cybershop.db, AES-256-GCM)                                |
|     Clave = Argon2id(password_usuario, salt=device_id)                         |
|     Tablas operativas replicadas (~25 tablas)                                  |
|     sync_outbox, sync_cursors, sync_conflicts, audit_log, node_metadata        |
|                                                                                |
|  Keystore SO (DPAPI/Keychain) → refresh_token, db_passphrase_hint              |
+================================================================================+
                          |  HTTPS 1.3 + JWT Bearer
                          v
+================================  VPS (38.134.148.47)  ==========================+
|  Caddy 2.x (TLS auto, HTTP/2) — app.cybershopcol.com                           |
|         v                                                                      |
|  Gunicorn (workers=4) — Flask 3.1.2                                            |
|     /api/v1/auth/*         (JWT login/refresh/logout/me)                       |
|     /api/v1/health         (readiness check)                                   |
|     /api/sync/{pull,push,snapshot}  (Fase 3)                                   |
|     /super/*               (panel superadmin, Fase 5)                          |
|     + 19 blueprints HTML existentes (intactos)                                 |
|         v                                                                      |
|  PostgreSQL 16                                                                 |
|     saas_control_plane     (tenants, usuarios_globales, refresh_tokens,        |
|                             tenant_databases, licencias*, feature_flags*,      |
|                             sync_health*, event_log*)  * = Fase 5              |
|     cyber_t001             (DB completa del cliente 1)                         |
|     cyber_t002             (DB completa del cliente 2, Fase 5+)                |
|  Redis 7 (Flask-Limiter + RQ workers)                                          |
|  Workers RQ: dian_dispatcher, email_dispatcher, backup_nightly (Fase 5)        |
+================================================================================+
```

---

## 5. Plan de 6 fases (~25 semanas)

| Fase | Contenido | Semanas | Estado |
|---|---|---|---|
| **1** | API REST v1 + JWT RS256 + control plane base + VPS setup | 4 | 🟡 Semana 1 ✅ |
| **2** | SERIAL → UUID v7 (dual-key) + columnas universales + triggers | 5 | ⬜ Pendiente |
| **3** | Sync worker + `/api/sync/*` + UI conflictos + barra de estado | 6 | ⬜ Pendiente |
| **4** | PyWebView + PyInstaller + SQLCipher + Argon2id + auto-update | 4 | ⬜ Pendiente |
| **5** | Panel superadmin + onboarding wizard + pgbouncer + RQ workers | 3 | ⬜ Pendiente |
| **6** | Cert pinning + anti-tamper + piloto real + Prometheus/Grafana | 3 | ⬜ Pendiente |

---

## 6. Fase 1 — API REST + JWT + Control Plane (4 semanas)

### 6.1 Semana 1 — COMPLETADA ✅

#### Commits entregados
| Hash | Rama | Descripción |
|---|---|---|
| `af9ae6f` | master | `docs`: checkpoint ESTADO_PROYECTO.md |
| `21a8abb` | master | `chore(vps)`: 9 scripts de setup VPS |
| `4225dea` | master | `feat(api)`: API REST v1 + JWT RS256 + base multi-tenant |

#### Archivos creados
**Servicios:**
- `app/services/auth/__init__.py`
- `app/services/auth/jwt_handler.py` — JWT RS256/HS256 auto-detect, `create_access_token()`, `decode_access_token()`, `generate_refresh_token()`, `hash_token()`
- `app/services/auth/decorators.py` — `@jwt_required` (puebla `g.jwt_payload`, `g.current_user_id`), `@jwt_role_required([ids])`
- `app/services/db_layer.py` — `get_control_plane_conn()`, `control_plane_cursor()`, `get_tenant_conn(db_name)`, `tenant_cursor(db_name)`
- `app/services/tenant_resolver.py` — `resolve_current_tenant()` (puebla `g.current_tenant` desde JWT o session Flask)
- `app/services/crypto_utils.py` — `sha256_hex()`, `aes_gcm_encrypt()`, `aes_gcm_decrypt()`

**Routes API:**
- `app/routes/api_auth.py` — blueprint `api_auth_bp` prefix `/api/v1/auth`
  - `POST /api/v1/auth/login` — retorna `access_token`, `refresh_token`, datos user+tenant
  - `POST /api/v1/auth/refresh` — rota refresh token, emite nuevo access
  - `POST /api/v1/auth/logout` — revoca refresh token
  - `GET  /api/v1/auth/me` — datos del usuario autenticado
- `app/routes/api_health.py` — `GET /api/v1/health` (público, sin auth)

**Migraciones:**
- `app/migrations/control_plane/0001_init.sql` — 4 tablas: `tenants`, `tenant_databases`, `usuarios_globales`, `refresh_tokens`

**Tools:**
- `app/tools/gen_jwt_keys.py` — genera par RSA 2048 en `app/keys/`
- `app/tools/migrate_prod_to_tenant.py` — migra DB `cybershop` → `cyber_t001` + puebla control plane
- `app/tools/seed_test_user.py` — crea usuario en `usuarios_globales`
- `app/tools/vps/00_subir_codigo.sh` — rsync local → VPS
- `app/tools/vps/01_diagnostico.sh` — inventario VPS
- `app/tools/vps/02_instalar_dependencias.sh` — Postgres 16 + Redis + Caddy + Python
- `app/tools/vps/03_setup_postgres.sh` — crea DBs + usuario + permisos
- `app/tools/vps/04_deploy_app.sh` — venv + deps + JWT keys + permisos
- `app/tools/vps/05_configurar_env.sh` — escribe `.cybershop.conf` en VPS
- `app/tools/vps/06_gunicorn_service.sh` — `cybershop.service` systemd
- `app/tools/vps/07_caddy.sh` — Caddyfile + TLS Let's Encrypt
- `app/tools/vps/08_firewall.sh` — UFW + fail2ban

**Otros:**
- `app/keys/.gitkeep` — directorio `keys/` versionado pero `.pem` en `.gitignore`
- `app/.cybershop.conf.example` — plantilla completa con todas las vars nuevas

#### Archivos modificados
| Archivo | Cambio |
|---|---|
| `app/app.py` | `before_request(resolve_current_tenant)` + registro condicional blueprints API + CSRF exempt |
| `app/database.py` | `get_db_cursor()` delega a `db_layer.get_tenant_conn(g.current_tenant['db_name'])` — firma idéntica |
| `app/routes/__init__.py` | `register_blueprints()` registra API blueprints si `CYBERSHOP_API_ENABLED=1` |
| `requirements.txt` | + `PyJWT[crypto]==2.9.0`, `alembic==1.13.2`, `Flask-Limiter==3.8.0`, `redis==5.0.8`, `pytest==8.3.3`, `pytest-flask==1.3.0` |

#### Smoke test JWT (ejecutado localmente — pasó ✅)
```
Token RS256: eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
Claims: sub=1, tenant_id=1, rol_id=2, modules=['pos','inventario'], db_name=cyber_t001
Refresh token: raw 64 chars + hash SHA-256
```

---

### 6.2 Semana 2 — Pendiente: Control plane local + primer login real

- [ ] Crear `saas_control_plane` local: `createdb saas_control_plane`
- [ ] Aplicar schema: `psql -d saas_control_plane -f app/migrations/control_plane/0001_init.sql`
- [ ] Seed test user: `python app/tools/seed_test_user.py --email admin@test.com --password Test1234!`
- [ ] Dry-run migración: `python app/tools/migrate_prod_to_tenant.py --dry-run`
- [ ] Verificar refactor `database.py` con app corriendo: `python app/app.py`
- [ ] Smoke test login: `curl -X POST http://localhost:5001/api/v1/auth/login -H "Content-Type: application/json" -d '{"email":"admin@test.com","password":"Test1234!"}'`
- [ ] Smoke test `GET /me` con Bearer token retornado
- [ ] Smoke test `POST /refresh` y `POST /logout`
- [ ] Confirmar que `/login` HTML legacy sigue operativo
- [ ] Smoke test `GET /api/v1/health`

---

### 6.3 Semana 3 — Pendiente: Migración VPS

- [ ] Configurar DNS `app.cybershopcol.com` → `38.134.148.47` (24 h antes)
- [ ] Avisar al cliente la ventana de 30 min (72 h antes)
- [ ] Ejecutar scripts VPS 00–08 en orden (ver sección 3)
- [ ] Aplicar `0001_init.sql` al control plane del VPS
- [ ] Ejecutar `migrate_prod_to_tenant.py` en VPS (migra `cybershop` → `cyber_t001`)
- [ ] Desplegar con `CYBERSHOP_API_ENABLED=0` → verificar HTML → activar `=1`
- [ ] Smoke test externo: `curl https://app.cybershopcol.com/api/v1/health`

---

### 6.4 Semana 4 — Pendiente: Tests + hardening

- [ ] Escribir `app/tests/api/test_auth_login.py`
- [ ] Escribir `app/tests/api/test_jwt_decorator.py`
- [ ] Escribir `app/tests/api/test_refresh.py`
- [ ] Escribir `app/tests/integration/test_coexistence.py`
- [ ] Configurar Flask-Limiter: 10 RPM `/auth/login`, 60 RPM resto `/api/*`
- [ ] Verificar TLS A+ en ssllabs.com
- [ ] Documentar rotación de claves JWT
- [ ] Sign-off del usuario → arrancar Fase 2

### 6.5 Criterios de aceptación de Fase 1

1. `POST /api/v1/auth/login` → 200 + access_token + refresh_token + datos tenant
2. Password incorrecta → 401 `INVALID_CREDENTIALS`
3. Bearer manipulado → 401 `INVALID_TOKEN`
4. Token expirado → 401 `TOKEN_EXPIRED`
5. Refresh → nuevo access + nuevo refresh (viejo revocado)
6. Logout → siguiente refresh devuelve 401
7. 11 logins fallidos en 60 s → 429 rate-limit
8. HTML legacy intacto: `/login`, `/admin`, POS, mesas, todos los blueprints
9. Sesión HTML activa + cliente API JWT simultáneos sin interferencia
10. `GET /api/v1/health` → 200 `{status:"ok", db:"ok", redis:"ok", version:"1.0.0"}`
11. DB `cyber_t001` sirve el tráfico: conteo filas `usuarios`, `productos`, `pedidos`, `ventas_pos` idéntico
12. TLS A+ en ssllabs.com sobre `app.cybershopcol.com`

### 6.6 Schema de `saas_control_plane` (Fase 1 — 4 tablas)

```sql
-- Extensiones
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- tenants: un registro por cliente
CREATE TABLE tenants (
  id         SERIAL PRIMARY KEY,
  slug       TEXT UNIQUE NOT NULL,
  nombre     TEXT NOT NULL,
  estado     TEXT NOT NULL DEFAULT 'activo' CHECK (estado IN ('activo','suspendido','cancelado')),
  plan       TEXT NOT NULL DEFAULT 'standard',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- tenant_databases: 1 DB Postgres por tenant
CREATE TABLE tenant_databases (
  tenant_id        INT PRIMARY KEY REFERENCES tenants(id),
  db_host          TEXT NOT NULL DEFAULT 'localhost',
  db_port          INT  NOT NULL DEFAULT 5432,
  db_name          TEXT NOT NULL UNIQUE,
  db_user          TEXT NOT NULL,
  db_password_enc  TEXT NOT NULL,  -- AES-256-GCM con KMS_KEY
  schema_version   TEXT NOT NULL DEFAULT '0001',
  last_migrated_at TIMESTAMPTZ NULL
);

-- usuarios_globales: mirror para autenticación API
CREATE TABLE usuarios_globales (
  id            SERIAL PRIMARY KEY,
  email         CITEXT UNIQUE NOT NULL,
  contraseña    TEXT NOT NULL,  -- werkzeug pbkdf2:sha256
  tenant_id     INT NOT NULL REFERENCES tenants(id),
  rol_id        INT NOT NULL,
  estado        TEXT NOT NULL DEFAULT 'habilitado' CHECK (estado IN ('habilitado','suspendido')),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_login_at TIMESTAMPTZ NULL
);
CREATE INDEX idx_usuarios_globales_tenant ON usuarios_globales(tenant_id);

-- refresh_tokens: token raw nunca persiste, solo SHA-256
CREATE TABLE refresh_tokens (
  token_hash   TEXT PRIMARY KEY,
  user_id      INT NOT NULL REFERENCES usuarios_globales(id),
  device_id    TEXT NOT NULL,
  device_name  TEXT,
  issued_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at   TIMESTAMPTZ NOT NULL,
  revoked_at   TIMESTAMPTZ NULL,
  last_used_at TIMESTAMPTZ NULL
);
CREATE INDEX idx_refresh_tokens_user_active ON refresh_tokens(user_id) WHERE revoked_at IS NULL;
```

**Tablas que llegan en Fase 5** (NO crear aún): `licencias`, `feature_flags_globales`, `sync_health`, `event_log`.

---

## 7. Fase 2 — SERIAL → UUID v7 + Columnas Universales (5 semanas)

### 7.1 Objetivo
Preparar todas las tablas replicables para sincronización. Sin UUID v7 y columnas de control, el sync worker de Fase 3 no puede operar.

### 7.2 Tablas replicadas (~25) — operativas en desktop

```
usuarios, roles, productos, generos, inventario_log,
pedidos, detalle_pedidos,
ventas_pos, detalle_venta_pos, notas_credito_pos,
restaurant_tables, restaurant_table_orders, restaurant_table_consumptions,
cupones, cupones_uso,
cliente_config, saas_modules, saas_tenant_modules,
factura_electronica_documentos,
accounting_movement, accounting_account, accounting_period,
billing_account_payable, billing_account_receivable,
nomina_empleados, nomina_periodos, nomina_liquidaciones, nomina_novedades
```

**NO se replican** (online-only): `crm_*`, `quotes`, `salas_video`, `producto_comentarios`, `google_*`, `share_*`, `soporte_*`, `wishlist_*`, `reportes_generados`.

### 7.3 Columnas universales (aplicar a TODA tabla replicada)

```sql
-- Migration: 0001_universal_control_columns
ALTER TABLE <tabla>
  ADD COLUMN id_uuid        UUID        NOT NULL DEFAULT gen_uuid_v7(),
  ADD COLUMN tenant_id      INT         NOT NULL,
  ADD COLUMN created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN deleted_at     TIMESTAMPTZ NULL,
  ADD COLUMN version        INT         NOT NULL DEFAULT 1,
  ADD COLUMN origin_node_id UUID        NULL,
  ADD COLUMN synced_at      TIMESTAMPTZ NULL;

CREATE UNIQUE INDEX idx_<tabla>_uuid    ON <tabla>(id_uuid);
CREATE INDEX        idx_<tabla>_updated ON <tabla>(updated_at);
CREATE INDEX        idx_<tabla>_tenant  ON <tabla>(tenant_id);

CREATE TRIGGER trg_<tabla>_touch BEFORE UPDATE ON <tabla>
  FOR EACH ROW EXECUTE FUNCTION touch_row();
```

```sql
-- Función touch_row (crear una sola vez)
CREATE OR REPLACE FUNCTION touch_row() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := NOW();
  NEW.version    := COALESCE(OLD.version, 0) + 1;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

-- Función gen_uuid_v7 (requiere pgcrypto)
CREATE OR REPLACE FUNCTION gen_uuid_v7() RETURNS UUID AS $$
DECLARE
  unix_ms  BIGINT := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT;
  hex      TEXT;
BEGIN
  hex := lpad(to_hex(unix_ms), 12, '0')
      || lpad(to_hex((random() * 4294967295)::BIGINT), 8, '0')
      || lpad(to_hex((random() * 4294967295)::BIGINT), 8, '0');
  hex := substring(hex, 1, 8) || '-' || substring(hex, 9, 4) || '-7'
      || substring(hex, 14, 3) || '-' || lpad(to_hex(8 + (random() * 3)::INT), 1, '0')
      || substring(hex, 18, 3) || '-' || substring(hex, 21, 12);
  RETURN hex::UUID;
END $$ LANGUAGE plpgsql;
```

### 7.4 Migración SERIAL → UUID v7 (dual-key, no destructiva)

1. Migración `0001_universal_control_columns.py` añade `id_uuid` con default `gen_uuid_v7()`.
2. Backfill: `UPDATE <tabla> SET id_uuid = gen_uuid_v7() WHERE id_uuid IS NULL;`
3. FKs paralelas: `pedido_uuid` en `detalle_pedidos`, etc.
4. Refactorizar `services/restaurant_tables_service.py`, POS (`routes/admin.py`), `routes/payments.py` para escribir `id_uuid`.
5. **Transporte sync usa exclusivamente UUIDs**; SERIAL solo para JOINs internos.
6. En SQLite local (Fase 4): PK es directamente `id_uuid TEXT PRIMARY KEY`.

### 7.5 Archivos Alembic a crear

- `migrations/alembic.ini`
- `migrations/env.py` — multi-DB: acepta `-x tenant_db=cyber_t001` o `-x target=control_plane`
- `migrations/versions/0001_universal_control_columns.py`
- `migrations/versions/0002_uuid_v7_function.py`
- `migrations/versions/0003_touch_row_trigger.py`
- `migrations/tenant/versions/0001_baseline.py` — solo marca baseline, no aplica DDL

---

## 8. Fase 3 — Sync Worker + Endpoints VPS (6 semanas)

### 8.1 Nuevos endpoints en VPS

```
POST /api/sync/pull
  Body: { cursors: { "productos": "ts", ... }, limit: 200 }
  Resp: { entities: { "productos": [rows], ... }, next_cursors: {...}, has_more: bool }

POST /api/sync/push
  Body: { events: [{ event_uuid, entity, entity_uuid, operation,
                     base_version, payload, client_updated_at }] }
  Resp: { results: [{ event_uuid, status, server_version, server_payload? }] }

GET  /api/sync/snapshot/<tenant_slug>?since=<ts>
  → tarball gzipped DDL + COPY de tablas replicadas (bootstrap inicial)
```

### 8.2 Tablas SQLite exclusivas del cliente (crear en `migrations/sqlite/schema_v1.sql`)

```sql
CREATE TABLE sync_outbox (
  event_uuid      TEXT PRIMARY KEY,
  entity          TEXT NOT NULL,
  entity_uuid     TEXT NOT NULL,
  operation       TEXT NOT NULL CHECK (operation IN ('insert','update','delete')),
  payload         BLOB NOT NULL,      -- JSON gzipped
  base_version    INT  NOT NULL,
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  attempts        INT  NOT NULL DEFAULT 0,
  last_attempt_at TEXT NULL,
  last_error      TEXT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','sending','sent','failed','conflict'))
);
CREATE INDEX idx_outbox_status ON sync_outbox(status, created_at);

CREATE TABLE sync_cursors (
  entity         TEXT PRIMARY KEY,
  last_synced_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
  last_event_uuid TEXT NULL,
  full_sync_done INT  NOT NULL DEFAULT 0
);

CREATE TABLE sync_conflicts (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  entity         TEXT NOT NULL,
  entity_uuid    TEXT NOT NULL,
  local_payload  BLOB NOT NULL,
  remote_payload BLOB NOT NULL,
  detected_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  resolved_at    TEXT NULL,
  resolution     TEXT NULL CHECK (resolution IN ('local','remote','merged'))
);

CREATE TABLE audit_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  user_uuid    TEXT NULL,
  action       TEXT NOT NULL,
  entity       TEXT NULL,
  entity_uuid  TEXT NULL,
  ip           TEXT NULL,
  details_json TEXT NULL
);

CREATE TABLE node_metadata (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

### 8.3 Orden topológico de sincronización

```
roles → usuarios → generos → productos → cupones →
cliente_config → saas_modules → saas_tenant_modules →
accounting_account → accounting_period → accounting_movement →
nomina_empleados → nomina_periodos → nomina_liquidaciones → nomina_novedades →
billing_account_payable → billing_account_receivable →
restaurant_tables → restaurant_table_orders → restaurant_table_consumptions →
pedidos → detalle_pedidos →
ventas_pos → detalle_venta_pos → notas_credito_pos →
inventario_log → cupones_uso → factura_electronica_documentos
```

### 8.4 Política de conflictos por tabla

| Tabla | Política |
|---|---|
| `productos`, `generos`, `cupones`, `cliente_config`, `saas_modules`, `saas_tenant_modules`, `roles` | **server-wins** |
| `usuarios` (excepto `ultima_conexion`) | server-wins |
| `ventas_pos`, `detalle_venta_pos`, `notas_credito_pos`, `pedidos`, `detalle_pedidos`, `restaurant_table_orders`, `restaurant_table_consumptions`, `inventario_log`, `cupones_uso`, `billing_*`, `nomina_*` | **LWW por (version, updated_at)** con detección de colisión |
| `restaurant_tables` (estado de mesa) | LWW estricto + alerta |
| `accounting_movement`, `factura_electronica_documentos` | **append-only** — nunca update destructivo |
| `audit_log` (local) | NO se sincroniza |

### 8.5 Triggers de sincronización (4 fuentes)

1. Evento `online` del SO expuesto por PyWebView
2. Tick periódico cada 30 s
3. Push manual desde la barra de estado
4. Commit local en tabla replicada → encola en `sync_outbox` via `services/db_layer.py::commit_with_outbox()`

### 8.6 Archivos a crear en Fase 3

- `services/sync/__init__.py`
- `services/sync/worker.py` — clase `SyncWorker(threading.Thread)`
- `services/sync/topology.py` — orden topológico de entidades
- `services/sync/conflict_policy.py` — políticas por tabla
- `services/sync/outbox.py` — encolado y lectura de eventos
- `services/sync/cursors.py` — manejo de cursores de sincronización
- `services/sync/http_client.py` — wrapper httpx con retry/backoff
- `services/sync/network.py` — detección online/offline
- `routes/api_sync.py` — `/api/sync/{pull,push,snapshot}`
- `routes/api_local.py` — `/api/local/sync/status` (solo desktop)
- `routes/sync_conflicts.py` — `/admin/sync/conflictos`
- `templates/_sync_status_bar.html` — barra 12px con 4 estados
- `templates/sync_conflicts.html` — UI lado a lado para resolver colisiones
- `static/js/sync_status.js` — polling cada 5 s a `/api/local/sync/status`
- `static/css/sync.css`
- `migrations/sqlite/schema_v1.sql` — DDL completo SQLite + tablas de control

### 8.7 Modificar `templates/plantillaapp.html`

```html
{% include '_sync_status_bar.html' %}   ← insertar ANTES de <header id="app-sidebar">
```

### 8.8 Operaciones que requieren red obligatoriamente

| Operación | Comportamiento offline |
|---|---|
| Factura electrónica DIAN | Estado local `pendiente_emision`, `cufe=NULL`. VPS dispara microservicio cuando llega sync. Alerta si >24 h pendiente. |
| Email (Gmail API) | Encolar en `email_dispatcher` del VPS vía sync push |
| Google Calendar | Encolar en VPS vía sync push |
| PayU webhook | Solo en VPS — desactivado en desktop |

---

## 9. Fase 4 — Empaque Desktop (4 semanas)

### 9.1 Stack técnico desktop

| Componente | Versión |
|---|---|
| Shell | `pywebview==5.4` |
| Build | `pyinstaller==6.10` |
| BD local | `apsw==3.45` + `pysqlcipher3==1.2` (SQLCipher 4, AES-256-GCM) |
| KDF | `argon2-cffi==23.1` (Argon2id, mem=64 MB, t=3, p=1) |
| Keystore | `keyring==24.3` (DPAPI Win / Keychain mac) |

**Clave SQLCipher** = `Argon2id(password_usuario, salt=device_id, mem=64 MB, t=3, p=1)`  
**Password nunca se persiste.** En cada arranque el usuario ingresa su contraseña → se deriva la clave → abre SQLCipher.

### 9.2 Flujos de autenticación desktop

**Primer login (online obligatorio):**
1. VPS valida credenciales → devuelve JWT + refresh_token
2. Desktop guarda `refresh_token` en keyring (DPAPI/Keychain)
3. Deriva clave SQLCipher con Argon2id(password, salt=device_id)
4. Descarga bootstrap snapshot del VPS
5. Abre SQLCipher con la clave derivada

**Logins offline:**
1. `routes/auth.py::login()` detecta `CYBERSHOP_MODE=desktop`
2. Verifica bcrypt contra `usuarios.contraseña` en SQLite local
3. Sesión Flask normal (sin JWT — JWT solo para VPS)

**JWT solo se usa para comunicación desktop ↔ VPS**, nunca entre browser local y Flask local.

### 9.3 Archivos a crear en Fase 4

- `desktop/main.py` — entrypoint PyWebView (Flask en thread + ventana nativa)
- `desktop/installer/inno_setup.iss` — instalador Windows con WebView2 runtime
- `desktop/installer/build_macos.sh` — empaque DMG + notarización Apple (futuro)
- `services/db_layer_sqlite.py` — adaptador SQLite+SQLCipher
- `services/db_layer_pg.py` — adaptador Postgres (refactor del actual)
- `services/auth/sqlcipher_kdf.py` — derivación Argon2id
- `services/auth/keyring_store.py` — abstracción keyring SO
- `config_desktop.py` — configuración modo desktop
- `config_vps.py` — configuración modo VPS
- `migrations/sqlite/seed.sql` — datos iniciales SQLite
- `tools/build_template_db.py` — genera SQLite seed para bootstrap
- `.cybershop.desktop.conf.example`

### 9.4 Modificaciones en Fase 4

| Archivo | Cambio |
|---|---|
| `app.py` | Detectar `CYBERSHOP_MODE` (desktop/vps). En desktop: `before_request` abre SQLCipher. |
| `services/db_layer.py` | Añadir rama SQLite: si `CYBERSHOP_MODE=desktop`, usar `db_layer_sqlite.py`. |
| `routes/auth.py` | En `login()` modo desktop: `autenticar_usuario_local()` contra SQLite. |
| `routes/admin.py` | POS offline: si `factura_electronica` activo y offline → `pendiente_emision`. |
| `routes/factura_electronica.py` | Offline: no llamar microservicio, encolar y retornar "pendiente". |
| `routes/payments.py` | PayU webhook desactivado en desktop. |
| `routes/contabilidad.py`, `routes/billing.py`, `routes/nomina.py`, `routes/cupones.py` | `commit_with_outbox()` al modificar tablas replicadas. |

### 9.5 Seguridad del binario

| Capa | Control |
|---|---|
| BD local | SQLCipher AES-256-GCM. Clave = Argon2id(password, salt=device_id). Password no persiste. |
| Tokens | `refresh_token` opaco en DPAPI/Keychain; `access_token` solo en memoria. |
| Transporte | TLS 1.3 obligatorio + cert pinning (raíz Let's Encrypt + secundario rotatorio). |
| Anti-tamper | SHA256 del .exe verificado contra VPS al primer login del día. Si difiere → modo solo-lectura. |
| Firma binario | Authenticode (Win) + notarización Apple (mac). Evita SmartScreen y Gatekeeper. |
| Auto-update | Servidor estático con manifest JSON firmado (Ed25519). Cliente verifica firma antes de aplicar. |
| Backup local | Copia diaria cifrada a `%APPDATA%/CyberShop/backups/`, retención 7 días. |

---

## 10. Fase 5 — Panel Superadmin + Onboarding (3 semanas)

### 10.1 Tablas adicionales en `saas_control_plane` (Fase 5)

```sql
CREATE TABLE licencias (
  tenant_id     INT REFERENCES tenants(id),
  modulo_code   TEXT,
  vigente_hasta DATE,
  PRIMARY KEY (tenant_id, modulo_code)
);

CREATE TABLE feature_flags_globales (
  flag_key    TEXT PRIMARY KEY,
  default_value JSONB,
  descripcion TEXT
);

CREATE TABLE sync_health (
  device_id     UUID PRIMARY KEY,
  tenant_id     INT NOT NULL REFERENCES tenants(id),
  user_id       INT NOT NULL,
  last_seen_at  TIMESTAMPTZ NOT NULL,
  last_push_at  TIMESTAMPTZ NULL,
  pending_events INT NOT NULL DEFAULT 0,
  app_version   TEXT,
  os            TEXT
);

CREATE TABLE event_log (
  event_uuid  TEXT PRIMARY KEY,
  tenant_id   INT NOT NULL,
  device_id   UUID NOT NULL,
  entity      TEXT NOT NULL,
  entity_uuid TEXT NOT NULL,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  result      TEXT NOT NULL
);
CREATE INDEX idx_event_log_tenant_time ON event_log(tenant_id, applied_at);
```

### 10.2 Rutas superadmin (`routes/superadmin.py`)

| Ruta | Función |
|---|---|
| `GET /super` | Dashboard: total tenants, activos hoy, sync_health rojo >1 h |
| `GET /super/tenants` | Lista con filtros |
| `POST /super/tenants/nuevo` | Wizard de provisión |
| `GET /super/tenants/<slug>` | Detalle: usuarios, módulos, sync_health |
| `POST /super/tenants/<slug>/modulos/<code>` | Toggle módulo |
| `GET /super/feature-flags` | Flags globales |
| `GET /super/migraciones` | `schema_version` por tenant + botón "migrar todos" |
| `GET /super/sync-health` | Tabla en tiempo real (HTMX poll 5 s) |
| `GET /super/audit/<slug>` | Eventos del tenant sin abrir su DB (lee `event_log`) |

### 10.3 Onboarding automatizado (`tools/provision_tenant.py`)

1. Generar slug, validar unicidad
2. `CREATE DATABASE cyber_tNNN OWNER cybershop_app TEMPLATE template_cybershop`
3. Insertar en `tenants`, `tenant_databases` (password AES-GCM con KMS_KEY)
4. Crear usuario propietario inicial en `usuarios_globales` con password temporal
5. Enviar email con link de descarga del `.exe` + credenciales temporales
6. Marcar `schema_version` con última migración del template

### 10.4 Agregar pgbouncer en Fase 5

```
pgbouncer modo transaction, pool_size=20 por DB, max_client_conn=2000
```

```python
# services/db_router.py
def get_conn_for_tenant(tenant_id):
    db_name = control_plane.lookup_db_name(tenant_id)   # cache 60s
    return tenant_pools[db_name].getconn()              # pgbouncer transaction-pool
```

### 10.5 Alembic multi-DB en Fase 5

Un árbol `migrations/versions/` + script `tools/migrate_all.py` que itera sobre `control_plane.tenants` ejecutando `alembic -x tenant_db=cyber_tNNN upgrade head`.

### 10.6 Templates superadmin a crear

- `templates/superadmin/dashboard.html`
- `templates/superadmin/tenants.html`
- `templates/superadmin/tenant_detalle.html`
- `templates/superadmin/migraciones.html`
- `templates/superadmin/sync_health.html`

---

## 11. Fase 6 — Endurecimiento + Piloto (3 semanas)

- Cert pinning (TLS 1.3, raíz Let's Encrypt + secundario rotatorio)
- Anti-tamper: SHA256 del .exe verificado contra VPS al primer login del día
- KMS real (AWS KMS o similar) reemplazando `KMS_KEY` estática
- Prometheus + Grafana en VPS (latencia push, eventos en cola, conflictos/día)
- Piloto con 2 clientes reales + 5 cajas durante 30 días
- Backup VPS: `pg_dump -Fc cyber_tNNN | gpg -e -r ops@cybershop.app | aws s3 cp - s3://...`
- Cron 02:00 + WAL archiving + retención 7d/4w/12m
- Documentación operativa para soporte

---

## 12. Infraestructura completa VPS al finalizar todos las fases

```
cybershop.app {
  reverse_proxy 127.0.0.1:8000
}
```

```
Caddy 2.x
  └─ Gunicorn (workers=4, timeout=120)
       └─ Flask 3.1.2
           ├─ 19 blueprints HTML (Jinja2)
           ├─ /api/v1/auth/*
           ├─ /api/v1/health
           ├─ /api/sync/*
           └─ /super/*
  └─ PostgreSQL 16 + pgbouncer 1.22
       ├─ saas_control_plane
       └─ cyber_t001 … cyber_tN
  └─ Redis 7
       ├─ Flask-Limiter
       └─ RQ workers: dian_dispatcher, email_dispatcher, backup_nightly
```

**Backup:** `scripts/backup_tenant.sh` → `pg_dump -Fc cyber_tNNN | gpg -e | aws s3 cp -`

---

## 13. Variables de entorno completas (`.cybershop.conf`)

Ver plantilla completa en `app/.cybershop.conf.example`. Variables críticas:

| Variable | Descripción |
|---|---|
| `FLASK_SECRET_KEY` | Clave de sesión Flask (32+ chars aleatorios) |
| `DB_NAME` | `cyber_t001` (o `cybershop` en dev antes de migrar) |
| `DB_USER` | `cybershop_app` (VPS) / `postgres` (dev) |
| `DB_PASSWORD` | Contraseña Postgres |
| `CONTROL_PLANE_DB_NAME` | `saas_control_plane` |
| `JWT_PRIVATE_KEY_PATH` | Ruta absoluta a `jwt_private.pem` (chmod 600) |
| `JWT_PUBLIC_KEY_PATH` | Ruta absoluta a `jwt_public.pem` |
| `JWT_ACCESS_TTL_SECONDS` | `900` (15 min) |
| `JWT_REFRESH_TTL_SECONDS` | `2592000` (30 días) |
| `KMS_KEY` | 32 bytes en base64 para AES-256-GCM |
| `CYBERSHOP_API_ENABLED` | `1` para activar blueprints API |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `DEFAULT_TENANT_ID` | `1` |
| `DEFAULT_TENANT_SLUG` | `cyber-t001` |
| `TENANT_SLUG` | Slug del cliente principal |
| `TENANT_NOMBRE` | Nombre legible del cliente principal |
| `PAYU_*` | Credenciales PayU Latam |
| `MAIL_*` | Gmail SMTP |
| `GOOGLE_CLIENT_ID/SECRET` | OAuth 2.0 |
| `SESSION_COOKIE_SECURE` | `true` en producción |
| `CYBERSHOP_MODE` | `desktop` o `vps` (Fase 4+) |

---

## 14. Tecnologías por fase (requirements.txt completo al final)

```
# — YA INSTALADAS (Fase 1) —
PyJWT[crypto]==2.9.0
alembic==1.13.2
Flask-Limiter==3.8.0
redis==5.0.8
pytest==8.3.3
pytest-flask==1.3.0
paramiko==4.0.0       # solo en dev, para administración VPS

# — FASE 4 (descomentar cuando corresponda) —
# pywebview==5.4
# pyinstaller==6.10
# pysqlcipher3==1.2
# apsw==3.45.1
# argon2-cffi==23.1.0
# keyring==24.3.1
# httpx[http2]==0.27.0

# — FASE 5 (descomentar cuando corresponda) —
# rq==1.16
```

---

## 15. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Migración prod → `cyber_t001` corrompe datos | `pg_dump -Fc` + rollback documentado + ventana 30 min |
| `database.py` delegando rompe queries | Ambas rutas apuntan a misma DB en Fase 1. Firma idéntica. |
| `tenant_features.py` cambia comportamiento | `g.current_tenant['id']=1` por defecto; tests de regresión |
| Clave privada JWT comprometida | chmod 600, fuera del repo, rotación documentada |
| Redis caído bloquea logins | Flask-Limiter fail-open si Redis no responde |
| SQLCipher overhead I/O | ~10–15 %, aceptable para ráfagas pequeñas de POS |
| Argon2 en login frío tarda ~400 ms | Aceptable; se muestra spinner |
| FKs circulares en `accounting_movement` | Esa tabla sí se replica; orden topológico garantiza inserción |
| Conflictos LWW en `restaurant_tables` | Frecuencia baja; UI resuelve manualmente |
| Token DPAPI atado a usuario+máquina | Reinstalación de Windows obliga re-login online (deseable) |
| Re-cifrado tras cambio de password | Tx exclusiva + backup automático previo |
| VPS mal dimensionado | Verificar ≥2 GB RAM, ≥2 vCPU antes de continuar |
| DNS no propagado al ejecutar Caddy | `07_caddy.sh` verifica con `dig` antes del challenge |

### Alternativas descartadas

- **Electron + Flask local**: dos runtimes, binario 3× más grande.
- **Tauri**: obliga SPA Rust+JS, descarta Jinja2.
- **PWA pura**: sin filesystem cifrado ni impresora ESC/POS.
- **PostgreSQL portable local**: 100 MB+, requiere servicio Windows.
- **CRDTs (Automerge/Yjs)**: meses de reescritura para tablas relacionales.
- **Schemas en vez de databases**: aislamiento débil, backups acoplados.
- **DB compartida con `tenant_id` filter**: una fuga de query mata la privacidad.
- **JWT solo sin refresh**: re-login cada 15 min destruye UX.
- **pgbouncer desde Fase 1**: complejidad innecesaria con un solo tenant.

---

## 16. Cómo retomar en otro equipo

```bash
# 1. Clonar
git clone https://github.com/AndersonGRC/CyberShop.git
cd CyberShop

# 2. Virtualenv
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# 3. Dependencias
pip install -r requirements.txt

# 4. Configuración
copy app\.cybershop.conf.example app\.cybershop.conf
# Editar .cybershop.conf con credenciales reales (pedir al usuario)

# 5. Claves JWT
python app\tools\gen_jwt_keys.py
# Copiar los paths que imprime al .cybershop.conf

# 6. KMS_KEY
python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
# Pegar en .cybershop.conf → KMS_KEY=...

# 7. Arrancar
cd app && python app.py   # Puerto 5001
```

**Credenciales a pedir al usuario (no están en ningún archivo del repo):**
- Password de Postgres local
- `FLASK_SECRET_KEY` (usar la del equipo anterior o generar nueva)
- Credenciales PayU, Mail, Google OAuth (opcionales para desarrollo)
- Password VPS si se necesita continuar el setup del servidor

---

## 17. Contexto para IA que retome el trabajo

- **Stack**: Flask 3.1.2 + PostgreSQL + Jinja2 + jQuery. Todo en español. Sin ORM — raw SQL con psycopg2.
- **19 blueprints HTML** en `routes/`. **Nunca romper las firmas existentes** de `get_db_cursor()`, `@rol_requerido`, `@module_required`.
- **Roles**: 1=SuperAdmin, 2=Propietario, 3=Cliente, 4=Empleado, 5=Contador, 6=Mesero, 7=Cajero.
- **Módulos**: `pos`, `restaurante`, `inventario`, `contabilidad`, `nomina`, `billing`, `crm`, `cupones`, `factura_electronica`, etc. Controlados por `tenant_features.py` + tabla `saas_tenant_modules`.
- **Blueprint prefix en `url_for()`**: siempre `auth.login`, `admin.dashboard_admin`, etc.
- **CSS**: todo color va en `variables.css`, nunca hex directo en módulos CSS.
- **PDF**: colores desde `config.py::Config.BRAND_COLORS` (xhtml2pdf no soporta CSS variables).
- **Repo**: `https://github.com/AndersonGRC/CyberShop.git` (rama `master`).
- **Plan arquitectónico original completo** (si el archivo local no está disponible): reconstruir desde las secciones de este documento — contiene todo.
- **Fases ya implementadas**: solo Semana 1 de Fase 1. Todo lo demás está planificado pero no codificado.
- **NO incluir** pywebview/pyinstaller/sqlcipher en Fase 1 y 2. Solo en Fase 4.
- **Archivos de credenciales que NUNCA van a git**: `.cybershop.conf`, `app/keys/*.pem`. Están en `.gitignore`.
