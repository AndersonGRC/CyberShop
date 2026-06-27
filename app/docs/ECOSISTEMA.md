# Ecosistema CyberShop — Visión general

> Mapa de TODA la plataforma: qué proyectos existen, dónde viven, cómo se
> conectan y cómo se actualizan. Punto de entrada recomendado para cualquier
> persona nueva en el proyecto.

## 1. Los tres proyectos (3 repos)

| Proyecto | Repo GitHub | Qué es | Quién lo usa |
|---|---|---|---|
| **CyberShop** (web) | `AndersonGRC/CyberShop` | Tienda pública + panel `/admin` por cliente. Flask + PostgreSQL, server-side rendering | El cliente final (tienda) y el dueño del negocio (`/admin`) |
| **CyberShopAdmin** (maestro) | `AndersonGRC/Cybershop_innovation` | Panel SaaS central: crea/administra/suspende/destruye clientes, asigna módulos por plan, configura integraciones (PayU/Google/Mail) por cliente | Solo el operador técnico de CyberShop (PIN + allow-list de IP) |
| **CyberShopDesktop** (POS) | `AndersonGRC/Cybreshop-DesktopAPP` | Punto de venta de escritorio **offline-first** (PyQt6 + SQLite) con módulos POS, inventario, restaurante y contabilidad; sincroniza contra la web | Cajeros/meseros/admin del negocio en el local |

## 2. Topología de producción (un servidor, multi-cliente)

```
                              INTERNET
   cybershopcol.com   admin.cybershopcol.com   <cliente>.cybershopcol.com / dominio propio
          │                    │                         │
   ┌──────▼────────────────────▼─────────────────────────▼──────┐
   │                     NGINX (80/443, SSL)                    │  + allow-list IP en admin
   └──────┬────────────────────┬─────────────────────────┬──────┘
     127.0.0.1:5001       127.0.0.1:5002            127.0.0.1:81xx
   ┌──────▼──────┐      ┌──────▼───────┐          ┌──────▼───────┐
   │  cybershop  │      │cybershop-admin│          │ cybershop@<slug>│  ← 1 instancia por cliente
   │ (app ppal)  │      │  (maestro)    │          │ (código COMPARTIDO /var/www/CyberShop
   └──────┬──────┘      └──────┬───────┘          │  + EnvironmentFile /etc/cybershop/<slug>.env)
          │                    │                   └──────┬───────┘
   ┌──────▼────────────────────▼──────────────────────────▼──────┐
   │ PostgreSQL (localhost): cybershop · cyber_tNNN (1 BD/cliente)│
   │                · saas_control_plane (registro central)       │
   └───────────────────────────────────────────────────────────────┘
```

- **Servidor**: `38.134.148.47` (SSH puerto 2222). Código en `/var/www/CyberShop`
  y `/var/www/CyberShopAdmin`.
- **Control plane** (`saas_control_plane`): `tenants`, `tenant_databases`
  (credenciales cifradas AES-GCM con `KMS_KEY`), `tenant_runtime`
  (puerto/subdominio/dominio por cliente), `sync_api_keys`, `admin_users`.
- **Aislamiento**: cada cliente tiene su **BD propia** (`cyber_tNNN`) y su
  **instancia propia** (puerto distinto). El código es uno solo: actualizar a
  todos = `git pull` + reiniciar instancias.
- **Backups**: cron diario 3:30am (`/usr/local/bin/cybershop-backup.sh`) de
  todas las BDs a `/var/backups/cybershop/` con rotación de 7 días.
- **Seguridad**: ufw deny-by-default, fail2ban, HSTS, panel maestro con PIN +
  allow-list de IP, SSL Let's Encrypt con renovación automática.

## 3. Cómo se conectan entre sí

- **Web ↔ Escritorio**: API `/api/v1/sync/*` (14 endpoints) con header
  `X-Sync-Key`. El escritorio hace pull incremental (productos/usuarios/
  categorías) + snapshots (restaurante/contabilidad) y push de su `outbox`
  (ventas, operaciones de mesa, contabilidad) de forma idempotente.
  → Detalle: [INTEGRACION_WEB_DESKTOP.md](INTEGRACION_WEB_DESKTOP.md)
- **Maestro → Clientes**: el maestro crea la BD del cliente (schema real +
  seed de roles/admin/colores), aprovisiona instancia (puerto + systemd) y
  dominio (vhost nginx), y administra su configuración escribiendo en las
  MISMAS tablas que el app lee (`cliente_config`, `config_secciones`) y en el
  `EnvironmentFile` de su instancia (integraciones PayU/Google/Mail).
  → Detalle: repo del maestro, `docs/PLAN_MASTER.md` y `DEPLOY.md`.
- **Onboarding de un cliente al POS**: el maestro emite `client_code` →
  el cliente lo pega en `cybershopcol.com/descargar` → recibe un ZIP con el
  instalador + `bootstrap.json` preconfigurado.
- **Venta automática (app → maestro)**: API interna `POST /internal/api/v1/
  tenants/{create|<id>/suspend|<id>/reactivate}` en el maestro (solo
  `127.0.0.1`, header `X-Internal-Key` = `INTERNAL_API_KEY` compartida). El app
  la llama cuando un pago de plan se aprueba. → Detalle: [VENTA_AUTOMATICA.md](VENTA_AUTOMATICA.md).

## 3b. Venta automática de planes (SaaS self-service)

Un pago de plan mensual crea la tienda y notifica, sin intervención:

```
/software → checkout PayU → pedido + fila en plan_compras (PENDIENTE_PAGO)
  webhook PayU APROBADO → procesar_compra_plan (idempotente):
     plan mensual → token → email "Activa tu tienda"  | plan anual → email "te contactamos"
     siempre → email de aviso al operador
  /activar-tienda/<token> → cliente elige negocio+subdominio → hilo:
     API interna del maestro → create_tenant + apply_plan (BD+seed+instancia+dominio+SSL)
     → email de bienvenida (URL, /admin, credenciales, client_code del POS)
  cron diario notificar_renovaciones.py (8am):
     recordatorios -5d/día0/+3d · AUTO_SUSPENDER_DIAS (0=solo notificar)
  /renovar/<token> → PayU → extiende proximo_pago (+ reactiva si estaba suspendida)
```

- Solo crean tienda los planes **mensuales** (`software-cybershop`→módulos
  `estandar`, `ultra`→`ultra`); los anuales se manejan manualmente.
- Tabla `plan_compras` (app, BD del tenant principal) = ledger de estados y
  fechas de cobro. Idempotente: el hook solo actúa sobre `PENDIENTE_PAGO` y
  es no-op para compras de productos.
- **Requisito de infra**: wildcard DNS `*.cybershopcol.com → 38.134.148.47`
  (Cloudflare, DNS-only) para que los subdominios de clientes nuevos resuelvan
  y certbot emita su SSL.

## 4. Flujos de actualización (DEV → GitHub → PROD)

Regla de oro: **desarrollar y probar en local primero**, luego `git push`, y
en el servidor `git pull` (+ restart). Nunca editar directo en producción.

| Qué cambias | Cómo se actualiza producción |
|---|---|
| App web (CyberShop) | `cd /var/www/CyberShop && git pull` → `systemctl restart cybershop` (y `cybershop@*` si hay instancias de clientes) |
| Maestro | `cd /var/www/CyberShopAdmin && sudo -u www-data git pull` → `systemctl restart cybershop-admin` |
| Esquema de BD de clientes | Migración **aditiva** en `CyberShopAdmin/migrations/tenant/` → `tools/migrate_tenants.py` (idempotente, no toca datos) |
| Escritorio | `build_installer.bat` → subir `CyberShopSetup_base.exe` a `static/installers/` del servidor (NO viaja por git) + bump de `version.json` para el auto-update |

### 4.1. Tres capas: qué se actualiza a todos y qué es por cliente

El código es **compartido**: un cambio llega a TODOS al hacer `git pull` + restart. Lo que diverge por cliente NO vive en el código compartido, sino en estas capas:

| Capa | Qué es | Regla de actualización |
|---|---|---|
| **Lógica** | Python (rutas/servicios) + esquema BD + **panel `/admin`** | **Siempre global**: el fix/mejora llega a TODOS. El `/admin` es producto global (misma paleta CyberShop uniforme; solo conserva el **logo** de cada cliente). |
| **Interfaz pública** | Plantillas + `static/` del **sitio público** | Base compartida **+ overrides por instancia** (ver 4.2). Aislados por cliente, nunca se propagan. |
| **Datos** | `cliente_config`, `public_site_*`, módulos (`tenant_features`) | Por cliente, en su BD. Las actualizaciones de código **no** los tocan. |

**Principio rector**: todo arreglo del sistema (lógica + `/admin`) llega siempre a todos, **sin tocar la BD ni el sitio público** del cliente. Las features en desarrollo viajan a todos pero **se apagan por cliente** con un flag (módulo/sección) **default OFF**.

### 4.2. Overrides de interfaz por instancia (theme a medida del sitio público)

Para personalizar el **sitio público** de UN cliente sin afectar a otros y sin que el próximo `git pull` lo arrastre:

- Carpeta **fuera del repo**: `/var/www/cybershop-overrides/<slug>/{templates,static}` (la crea el provisioning del maestro; `git pull` nunca la toca).
- La app del cliente la engancha vía `INSTANCE_OVERRIDES_DIR` (env de su instancia): un `ChoiceLoader` de Jinja y una vista `static` propia hacen que **sus** plantillas/estáticos **pisen** a los compartidos **solo para él**. Si no hay archivo override, cae a lo compartido (así los fixes globales siguen llegando). Ver `app.py` y `config.py`.
- **Regla de oro**: las personalizaciones a medida JAMÁS se editan dentro de `/var/www/CyberShop`; van en la carpeta de overrides del cliente. Tras colocarlas, `systemctl restart cybershop@<slug>` (o botón "Actualizar a última versión" en el maestro).

**Contrato de datos del sitio público** (para que los themes a medida sobrevivan a las actualizaciones): las plantillas son **solo presentación** y consumen un modelo estable que provee el backend compartido — variables de contexto como `brand_config`, `config_global`, `active_modules`, y el contenido `public_site_*` (publicaciones, novedades, servicios, productos). Un arreglo de **lógica/datos** llega a todos (incluidos los de theme propio) porque vive en el backend, no en la plantilla. Cambios a ese contrato deben ser **retrocompatibles**.

## 5. Documentación por proyecto

| Documento | Contenido |
|---|---|
| `CyberShop/app/CLAUDE.md` | Arquitectura de la web: blueprints, servicios, BD, theming, convenciones |
| `CyberShop/app/docs/MAPA_ARCHIVOS.md` | Para qué sirve cada archivo (web + herramientas) |
| `CyberShop/app/docs/INTEGRACION_WEB_DESKTOP.md` | API de sync, auth X-Sync-Key, outbox, onboarding del POS |
| `CyberShopDesktop/README.md` | El POS: módulos F1–F10, esquema SQLite, RBAC, build del instalador |
| `CyberShopAdmin/README.md` + `DEPLOY.md` | El maestro: qué hace y cómo se monta el entorno multi-cliente completo (nginx, systemd templado, sudoers, actualizaciones) |
| `CyberShopAdmin/docs/PLAN_MASTER.md` | Diseño/decisiones del maestro multi-cliente |
