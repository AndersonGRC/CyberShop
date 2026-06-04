# Mapa de archivos — Proyecto CyberShop

Referencia "para qué sirve cada archivo", por módulo y archivos clave.
Granularidad: cada `.py` de `routes/`, `services/`, `tools/` y la raíz; las
carpetas grandes (`templates/`, `static/`) se describen por convención.

- **Última actualización:** 2026-05-19
- **Apps:** Web Flask SaaS multi-tenant (`CyberShop/app`) + POS escritorio offline (`CyberShopDesktop`)
- **Docs relacionados:** [CLAUDE.md](../CLAUDE.md) · [INTEGRACION_WEB_DESKTOP.md](INTEGRACION_WEB_DESKTOP.md) · [onboarding_nuevo_cliente_pos_desktop.md](onboarding_nuevo_cliente_pos_desktop.md) · [../../ESTADO_PROYECTO.md](../../ESTADO_PROYECTO.md)

---

## 1. App web — raíz (`CyberShop/app/`)

| Archivo | Para qué sirve |
|---|---|
| `app.py` | App factory Flask: carga config, extensiones (Mail, Uploads, CORS, CSRF), `before_request` de tenant, registra blueprints, exenta CSRF del webhook PayU y de la API |
| `config.py` | Clase `Config` centralizada (PayU, Mail, Google OAuth, reCAPTCHA, uploads, `BRAND_COLORS`); carga `.cybershop.conf` con `load_dotenv` |
| `database.py` | `get_db_connection()` y `get_db_cursor()` (commit/rollback automático); resuelve la DB del tenant actual |
| `security.py` | 7 roles + grupos de permisos; decorador `@rol_requerido()`, `autenticar_usuario()`, rate limiting por IP |
| `helpers.py` | Menús de navegación (público/admin), `formatear_moneda()`, `generar_reference_code()`, datos comunes de plantilla |
| `helpers_gmail.py` | Envío de correo vía Gmail API (OAuth) con fallback a Flask-Mail SMTP |
| `helpers_email_templates.py` | Generadores de plantillas de email (confirmaciones, reset, notificaciones) |
| `helpers_google.py` | Utilidades OAuth 2.0 de Google (tokens, flujo Calendar) |
| `tenant_features.py` | Flags de módulos opcionales por tenant: `is_module_active()`, `get_active_module_codes()`, `get_current_tenant_id()` |
| `nomina_engine.py` | Motor puro de cálculo de nómina (ley laboral colombiana); sin Flask/DB |
| `nomina_inteligente.py` | Calculadora de nómina de alto nivel; envuelve el engine con `PARAMETROS_OFICIALES_NOMINA` (SMMLV, topes) |
| `cron_recordatorios.py` | Script cron diario: envía recordatorios de tareas CRM pendientes |

> Otros `.sql` y logs de la raíz: ver §6.

## 2. Blueprints (`CyberShop/app/routes/`)

19 blueprints registrados en `routes/__init__.py` (16 siempre + 3 API con
`CYBERSHOP_API_ENABLED=1`). `factura_electronica.py` **no es blueprint**.

| Archivo (`bp`) | Prefijo | Responsabilidad |
|---|---|---|
| `auth.py` (`auth`) | `/` | Registro cliente, login/logout, dashboard cliente, OAuth Google staff |
| `public.py` (`public`) | `/` | Home, catálogo, servicios, contacto, carrito, portal `/descargar`, `/software` (landing + planes), `/comprar-plan/<key>` (checkout PayU), `/robots.txt`, `/sitemap.xml`, 404 |
| `admin.py` (`admin`) | `/admin` | Dashboard admin, CRUD productos/usuarios, pedidos, POS, inventario, branding, config módulos, `/admin/software-planes` (gestor de planes) |
| `payments.py` (`payments`) | `/` | Flujo PayU: métodos, crear-orden, confirmación (webhook), respuesta-pago |
| `quotes.py` (`quotes`) | `/admin/cotizar` | Cotizaciones en PDF (xhtml2pdf) |
| `restaurant_tables.py` (`restaurant_tables`) | `/admin/salon` | Mesas, ocupación, pedidos por mesa |
| `nomina.py` (`nomina`) | `/admin/nomina` | Nómina: planilla, períodos, novedades |
| `billing.py` (`billing`) | `/admin/cuenta_cobro` | Cuentas de cobro en PDF |
| `crm.py` (`crm`) | `/admin/crm` | Contactos, oportunidades, actividades, tareas, email masivo, import/export |
| `google_calendar.py` (`google`) | `/admin/google` | OAuth + sync bidireccional Google Calendar |
| `soporte.py` (`soporte`) | `/admin/soporte` | Tickets de soporte cliente↔vendedor |
| `contabilidad.py` (`contabilidad`) | `/admin/contabilidad` | Ingresos/egresos, retenciones, cierres |
| `video.py` (`video`) | `/admin/video` | Salas de videollamada (Jitsi) |
| `cupones.py` (`cupones`) | `/` | CRUD cupones + validación AJAX en carrito |
| `wishlist.py` (`wishlist`) | `/admin/deseos` | Listas de deseos |
| `share.py` (`share`) | `/` | Compartir archivos: carpetas + link público `/c/<token>` |
| `api_auth.py` (`api_auth`) † | `/api/v1/auth` | JWT: login/refresh/logout/me |
| `api_health.py` (`api_health`) † | `/api/v1` | `/health` público |
| `api_sync.py` (`api_sync`) † | `/api/v1/sync` | API POS escritorio (14 endpoints, incl. `restaurant/snapshot` y `contabilidad/snapshot` + outbox `restaurant_op`/`contabilidad_op` — ver INTEGRACION_WEB_DESKTOP.md) |
| `factura_electronica.py` (módulo) | — | **No blueprint**: funciones `emitir_factura_electronica`, `facturacion_habilitada`, `emitir_factura_pos` (puente DIAN); las usa `admin.py` |

† Solo con `CYBERSHOP_API_ENABLED=1`.

## 3. Servicios (`CyberShop/app/services/`)

| Archivo | Para qué sirve |
|---|---|
| `db_layer.py` | `control_plane_cursor()` (SaaS) y `get_tenant_conn()`/`tenant_cursor(db_name)` (por tenant) |
| `tenant_resolver.py` | `resolve_current_tenant()` en `before_request` → `g.current_tenant` (JWT/sesión/env) |
| `crypto_utils.py` | `sha256_hex()`, `aes_gcm_encrypt/decrypt()` (cifra passwords de DB con `KMS_KEY`) |
| `public_site_service.py` | Lee/escribe config del sitio público; compat con `cliente_config`/`config_secciones`; grupo de colores `descarga` y `set_public_section()` (toggle tienda online) |
| `software_planes_service.py` | Planes de la landing `/software` (tabla `software_planes`): auto-crea + siembra defaults, CRUD, fallback robusto |
| `crm_service.py` | Upsert de contactos compartido (formularios, cotizaciones, billing, pagos) |
| `installer_packager.py` | Empaqueta el ZIP del POS (base `.exe` + `bootstrap.json`); tokens de descarga |
| `restaurant_tables_service.py` | API interna de estado de mesas/cocina (desacoplada del blueprint) |
| `auth/jwt_handler.py` | Crea/decodifica/revoca JWT (RS256 prod con keypair, HS256 dev) |
| `auth/decorators.py` | `@jwt_required()`, `@jwt_role_required([...])` → `g.jwt_payload`, `g.current_user_id` |

## 4. Herramientas (`CyberShop/app/tools/`)

| Archivo | Para qué sirve |
|---|---|
| `gen_jwt_keys.py` | Genera el keypair RSA para JWT RS256 → `keys/jwt_private.pem` + `jwt_public.pem` |
| `seed_test_user.py` | Crea usuario de prueba en `saas_control_plane.usuarios_globales` |
| `migrate_prod_to_tenant.py` | Migración única monolito → multi-tenant (crea `cyber_t001`, registra tenant, copia usuarios). Soporta `--dry-run` |
| `crear_sync_key.py` | Genera API key de sync del POS: imprime `client_code` (CYB-XXXX) y `api_key` (cyb_live_…, una sola vez); guarda solo el hash en `sync_api_keys` |

### Scripts de despliegue VPS (`tools/vps/`)

| Script | Para qué sirve |
|---|---|
| `00_subir_codigo.sh` | Clona/actualiza el repo en `/opt/cybershop`; crea `keys/` y `sql_logs/` |
| `01_diagnostico.sh` | Diagnóstico del VPS (Python, PostgreSQL, Redis, Caddy, disco/RAM/CPU) |
| `02_instalar_dependencias.sh` | Instala PostgreSQL 16, Redis, Caddy, Python 3.11+, build tools, ufw |
| `03_setup_postgres.sh` | Crea `saas_control_plane`, usuario `cybershop_app`, `cyber_t001` |
| `04_deploy_app.sh` | Usuario de sistema, estructura de directorios, venv, dependencias Python |
| `05_configurar_env.sh` | Genera `/opt/cybershop/app/.cybershop.conf` con valores de producción |
| `06_gunicorn_service.sh` | Crea `cybershop.service` (systemd, Gunicorn en `127.0.0.1:8000`) |
| `07_caddy.sh` | Caddy 2 como reverse proxy + TLS automático → Gunicorn |
| `08_firewall.sh` | UFW: permite SSH (2222), HTTP (80), HTTPS (443); bloquea PostgreSQL/Redis externos |

## 5. Migraciones

| Archivo | Ámbito | Crea |
|---|---|---|
| `migrations/control_plane/0001_init.sql` | Control plane | `tenants`, `tenant_databases`, `usuarios_globales`, `refresh_tokens` |
| `migrations/control_plane/0002_sync_api_keys.sql` | Control plane | `sync_api_keys` (hash de key, client_code, label, active) |

## 6. SQL de raíz (`CyberShop/app/*.sql`)

Se aplican sobre la DB de un tenant (no el control plane):

| Archivo | Para qué sirve |
|---|---|
| `migrate_backup_db.sql` | Esquema de backups/auditoría (también plantilla de tenant nuevo) |
| `migrate_crm_mejoras.sql` | Mejoras CRM: log de actividades, prioridades, campos de Google Calendar |
| `migrate_public_site_settings.sql` | Tablas de config del sitio público (`public_site_settings/blocks`) |
| `migrate_public_site_structured.sql` | Esquema extendido del sitio público (`public_site_items`, visibilidad, SEO) |
| `migrate_share_module.sql` | Módulo compartir: carpetas, archivos, tokens, password opcional |

## 7. Frontend (convención, no archivo por archivo)

- **`templates/`** (~100+ `.html`): SSR Jinja2. Dos bases — `plantillaindex.html`
  (público) y `plantillaapp.html` (panel admin). Agrupados por dominio:
  productos (`GestionProductos.html`, `editar_producto*.html`), pedidos/POS
  (`gestion_pedidos.html`, `facturacion_pos.html`), cotizaciones/billing,
  CRM (`crm_*.html`), contabilidad (`contabilidad_*.html`), nómina (`nomina_*`),
  sitio público (`index.html`, `config_secciones.html`), auth, soporte/video/
  wishlist/cupones, utilidades (`404.html`, `descargar.html`), `pdf_quote.html`.
- **`static/css/`**: un CSS por página; todos importan `variables.css`
  (único lugar de colores de marca). Subcarpetas `css/crm/`, `css/nomina/`,
  `css/video/`. Detalle del mapa CSS en [CLAUDE.md](../CLAUDE.md).
- **`static/js/`**: `Shoppingcar.js` (carrito localStorage), `layout.js`
  (header/slider/Vue público), `app.js` (sidebar admin),
  `galeriaprincipal.js` (menú/slider interno) + scripts por módulo.
- **`static/`** (datos): `media/` (imágenes de productos), `user/` (fotos
  perfil), `crm/fotos/`, `cotizaciones/pdf/`, `cuentas_cobro/pdf/`,
  `installers/` (base `.exe` del POS), `img/`.

## 8. App de escritorio (`CyberShopDesktop/`)

| Archivo | Para qué sirve |
|---|---|
| `main.py` | App PyQt6: `DesktopShell`, `LoginView`, `ScannerEngine`, vistas F1–F8 |
| `local_store.py` | Capa SQLite (10 tablas, CRUD, PBKDF2, outbox, cachés remotas) |
| `sync_client.py` | Cliente HTTP `/api/v1/sync/*` (solo `urllib`) |
| `sync_config.py` | Estado de sync (`sync_config.json`) |
| `cybershop_conf.py` | Lee/escribe `.cybershop.conf` (lo crea el instalador) |
| `branding.py` | Marca: `branding.json`, validación hex, render QSS |
| `run.bat` / `build_exe.bat` / `build_installer.bat` | Lanzador dev / EXE / instalador |
| `installer.iss` | Script Inno Setup 6 (asistente + `.cybershop.conf`) |
| `CyberShopOffline.spec` | Spec PyInstaller activo (`CyberShopDesktop.spec` = legacy, no usar) |
| `requirements.txt` | `PyQt6>=6.5` |
| `assets/cybershop.ico` / `.png` | Icono / fallback |

Detalle ampliado en [../../../CyberShopDesktop/README.md](../../../CyberShopDesktop/README.md).
