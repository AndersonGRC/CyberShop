# CyberShop — Estado del Proyecto (Checkpoint)

> **Última actualización:** 2026-04-30  
> **Para retomar en otro equipo:** leer este archivo completo antes de continuar.  
> **Plan arquitectónico completo:** `C:\Users\agroa\.claude\plans\continua-con-el-plan-snappy-fog.md` (local)  
> o bien releer la sección de arquitectura en este mismo archivo.

---

## 1. ¿Qué es CyberShop?

Aplicación web Flask 3.1 + PostgreSQL (actualmente en producción). El objetivo es convertirla en una **app de escritorio Windows offline-first multi-tenant** usando PyWebView + PyInstaller. El trabajo se hace en **6 Fases (~25 semanas)**.

---

## 2. Estado actual (Fase 1 — Semana 1 completada)

### Commits entregados

| Hash | Descripción |
|---|---|
| `21a8abb` | `chore(vps)`: scripts de setup VPS para Fase 1 |
| `4225dea` | `feat(api)`: Fase 1 — API REST v1 + JWT RS256 + base multi-tenant |
| `19f31aa` | Código existente pre-Fase 1 (baseline) |

### Archivos nuevos creados en Fase 1

**Servicios:**
- `app/services/auth/__init__.py`
- `app/services/auth/jwt_handler.py` — JWT RS256/HS256, refresh tokens, hashing
- `app/services/auth/decorators.py` — `@jwt_required`, `@jwt_role_required`
- `app/services/db_layer.py` — abstracción Postgres: `get_control_plane_conn()`, `get_tenant_conn()`
- `app/services/tenant_resolver.py` — puebla `g.current_tenant` desde JWT o session Flask
- `app/services/crypto_utils.py` — AES-256-GCM para cifrar contraseñas de BD de tenants

**Routes API:**
- `app/routes/api_auth.py` — `POST /api/v1/auth/login|refresh|logout`, `GET /api/v1/auth/me`
- `app/routes/api_health.py` — `GET /api/v1/health`

**Migraciones:**
- `app/migrations/control_plane/0001_init.sql` — schema de `saas_control_plane` (4 tablas)

**Tools:**
- `app/tools/gen_jwt_keys.py` — genera par RSA para JWT
- `app/tools/migrate_prod_to_tenant.py` — migra DB prod → `cyber_t001` + puebla control plane
- `app/tools/seed_test_user.py` — crea usuario de prueba en `usuarios_globales`
- `app/tools/vps/00_subir_codigo.sh` — rsync local → VPS
- `app/tools/vps/01_diagnostico.sh` — inventario del VPS
- `app/tools/vps/02_instalar_dependencias.sh` — Postgres 16, Redis, Caddy, Python
- `app/tools/vps/03_setup_postgres.sh` — crea `saas_control_plane` + `cyber_t001`
- `app/tools/vps/04_deploy_app.sh` — venv, deps, claves JWT, permisos
- `app/tools/vps/05_configurar_env.sh` — genera `.cybershop.conf` en VPS
- `app/tools/vps/06_gunicorn_service.sh` — servicio systemd Gunicorn
- `app/tools/vps/07_caddy.sh` — Caddy 2 + TLS Let's Encrypt para `app.cybershopcol.com`
- `app/tools/vps/08_firewall.sh` — UFW + fail2ban

**Archivos modificados:**
- `app/app.py` — `before_request` para `resolve_current_tenant()`, CSRF exempt para API
- `app/database.py` — `get_db_cursor()` ahora delega a `db_layer` (firma idéntica)
- `app/routes/__init__.py` — registro condicional de blueprints API con `CYBERSHOP_API_ENABLED=1`
- `requirements.txt` — añadidos: `PyJWT[crypto]`, `alembic`, `Flask-Limiter`, `redis`, `pytest`
- `app/.cybershop.conf.example` — plantilla actualizada con todas las vars nuevas

**Claves JWT generadas localmente (NO commiteadas):**
- `app/keys/jwt_private.pem` — clave privada RSA 2048 (en `.gitignore`)
- `app/keys/jwt_public.pem` — clave pública RSA

---

## 3. Infraestructura

### VPS
- **Host:** `38.134.148.47`
- **SSH:** `ssh -p 2222 root@38.134.148.47`
- **Contraseña:** (solicitarla al usuario — no se almacena aquí)
- **Dominio:** `app.cybershopcol.com` → DNS A record → `38.134.148.47`

### Estado del VPS (al 2026-04-30)
- **Los scripts de setup NO se han ejecutado aún** — el usuario los ejecutará desde su casa.
- Secuencia a seguir:
  1. `bash app/tools/vps/00_subir_codigo.sh` (desde Windows, sube el código al VPS)
  2. En el VPS, ejecutar scripts `01` a `08` en orden
  3. Editar variables en `05_configurar_env.sh` antes de ejecutarlo

### DB local de desarrollo
- **DB_NAME:** `cybershop` (la DB de producción actual, usada en dev)
- **Claves JWT locales:** `app/keys/jwt_private.pem` + `jwt_public.pem` (generadas, NO en git)
- **KMS_KEY:** en `.cybershop.conf` local (generada, NO en git)
- **Control plane local:** `saas_control_plane` — **AÚN NO CREADA** (pendiente Semana 2)

---

## 4. Lo que falta de Fase 1 (Semanas 2–4)

### Semana 2 — Control plane local + primer login real
- [ ] Crear `saas_control_plane` en Postgres local: `createdb saas_control_plane`
- [ ] Aplicar schema: `psql -d saas_control_plane -f app/migrations/control_plane/0001_init.sql`
- [ ] Crear usuario de prueba: `python app/tools/seed_test_user.py --email admin@test.com --password TuPassword`
- [ ] Ejecutar `migrate_prod_to_tenant.py --dry-run` para verificar migración
- [ ] Smoke test: `curl -X POST http://localhost:5001/api/v1/auth/login -H "Content-Type: application/json" -d '{"email":"admin@test.com","password":"TuPassword"}'`

### Semana 3 — Migración VPS
- [ ] Ejecutar scripts VPS 00–08
- [ ] Verificar app web HTML en `https://app.cybershopcol.com`
- [ ] Verificar API en `https://app.cybershopcol.com/api/v1/health`
- [ ] Migrar DB prod a `cyber_t001` (ventana 02:00–04:00 Colombia)

### Semana 4 — Tests + hardening
- [ ] Escribir tests en `app/tests/api/` (login OK, 401, rate-limit, refresh, logout)
- [ ] Configurar `Flask-Limiter` con Redis en VPS
- [ ] Verificar TLS A+ en `ssllabs.com`
- [ ] Documentar rotación de claves JWT

---

## 5. Decisiones arquitectónicas tomadas

| Decisión | Detalle |
|---|---|
| Empaque desktop | PyWebView 5.x + PyInstaller 6.x (Fase 4) |
| IDs | Migración SERIAL → UUID v7 (Fase 2, dual-key) |
| BD local desktop | SQLite + SQLCipher AES-256-GCM (Fase 4) |
| Sync | Outbox pattern, LWW por versión, endpoints `/api/sync/{pull,push}` (Fase 3) |
| Auth | JWT RS256 (access 15 min) + refresh opaco 30 días en DPAPI/Keychain (Fase 4) |
| Multi-tenant | 1 Postgres, 1 database por cliente (`cyber_t001`, `cyber_t002`, ...) |
| Proxy VPS | Caddy 2.x (TLS auto Let's Encrypt) |
| SO desktop | Windows primero; macOS como posibilidad futura |
| Orden de fases | Estricto: 1→2→3→4→5→6 |

---

## 6. Plan completo de 6 fases (resumen)

| Fase | Contenido | Duración | Estado |
|---|---|---|---|
| **1** | API REST + JWT + control plane | 4 semanas | 🟡 En curso (Semana 1 ✅) |
| **2** | Refactor SERIAL → UUID v7 + columnas universales | 5 semanas | ⬜ Pendiente |
| **3** | Sync worker + endpoints `/api/sync/*` + UI conflictos | 6 semanas | ⬜ Pendiente |
| **4** | Empaque PyWebView + PyInstaller + SQLCipher + Argon2id | 4 semanas | ⬜ Pendiente |
| **5** | Panel superadmin + onboarding + licencias + sync_health | 3 semanas | ⬜ Pendiente |
| **6** | Cert pinning + anti-tamper + piloto + métricas | 3 semanas | ⬜ Pendiente |

---

## 7. Cómo retomar en otro equipo

```bash
# 1. Clonar el repo
git clone https://github.com/AndersonGRC/CyberShop.git
cd CyberShop

# 2. Crear y activar virtualenv
python -m venv venv
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Copiar y completar la configuración
cp app/.cybershop.conf.example app/.cybershop.conf
# Editar app/.cybershop.conf con credenciales reales

# 5. Regenerar claves JWT (o copiarlas del equipo anterior)
python app/tools/gen_jwt_keys.py
# Añadir los paths al .cybershop.conf

# 6. Arrancar la app
cd app && python app.py
```

**Variables críticas en `.cybershop.conf`** (pedir al usuario las reales):
- `FLASK_SECRET_KEY`
- `DB_PASSWORD` (Postgres local)
- `KMS_KEY` (AES-256-GCM, 32 bytes base64)
- `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH`
- PayU, Mail, Google OAuth (opcionales para desarrollo)

---

## 8. Arquitectura técnica (referencia rápida)

```
Cliente Windows (Fase 4)
  └─ PyWebView → Flask local → SQLite/SQLCipher
                              └─ SyncWorker → HTTPS → VPS

VPS (app.cybershopcol.com)
  └─ Caddy 2.x (TLS) → Gunicorn → Flask
                                  ├─ /api/v1/auth/*    (JWT)
                                  ├─ /api/v1/health
                                  ├─ /api/sync/*       (Fase 3)
                                  └─ blueprints HTML existentes (intactos)
                       └─ PostgreSQL 16
                           ├─ saas_control_plane  (tenants, usuarios_globales, refresh_tokens)
                           └─ cyber_t001          (DB del cliente, clone de la prod actual)
```

---

## 9. Contexto de IA (para Claude u otro asistente)

- El plan arquitectónico completo está en el archivo `act-a-como-arquitecto-de-expressive-rainbow.md` (en la carpeta de planes de Claude local). Si no está disponible, reconstruirlo desde las secciones de este archivo.
- La sesión de Claude usó **modelo Opus 4.7** en modo consola (`C:\Cybershop` como working directory).
- Las claves JWT y `.cybershop.conf` con credenciales reales **nunca se suben a git** (en `.gitignore`).
- El correo del usuario/propietario del proyecto es `cybershop.digitalsales@gmail.com`.
- Repo GitHub: `https://github.com/AndersonGRC/CyberShop.git`
