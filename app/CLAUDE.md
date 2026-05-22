# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
python app.py  # Starts Flask dev server on http://0.0.0.0:5001
```

There is no formal build system, test suite, or linter configured. Dependencies are managed via pip:

```bash
pip install -r requirements.txt
```

## Architecture

CyberShop is a Flask-based e-commerce platform (Spanish language) with PostgreSQL. It uses server-side rendering with Jinja2 templates, vanilla JS on the frontend, and PayU Latam for payment processing.

### Backend Structure

- **app.py** — Flask app factory: creates app, loads config, initializes extensions (Mail, Uploads, CORS), registers blueprints
- **config.py** — Centralized `Config` class with all settings (PayU, Mail, Uploads, Session) and `verificar_configuracion_payu()`
- **helpers.py** — Shared utility functions: `get_common_data()` (public menu), `get_data_app()` (admin menu), `formatear_moneda()`, `generar_reference_code()`
- **database.py** — `get_db_connection()` for raw connections and `get_db_cursor()` context manager with auto commit/rollback
- **security.py** — `@rol_requerido(role_id)` decorator, `autenticar_usuario()`, `actualizar_ultima_conexion()`, basic rate limiting
- **validators.py** — PSE bank transfer payment validation

### Multi-Tenant SaaS Architecture

CyberShop opera en modelo **control plane + 1 base de datos por cliente**:

- **Control plane** (`saas_control_plane`): metadatos globales — `tenants`, `tenant_databases` (credenciales cifradas con KMS), `usuarios_globales`, `refresh_tokens`, `sync_api_keys`. Acceso vía `services/db_layer.py::control_plane_cursor()`.
- **DB por tenant** (`cyber_t001`, `cyber_t002`, …): todos los datos operativos (usuarios, productos, pedidos, contabilidad, CRM, nómina). Acceso vía `services/db_layer.py::tenant_cursor(db_name=...)` o `get_db_cursor()` (que resuelve el tenant actual).
- **Resolución de tenant por request**: `app.before_request(resolve_current_tenant)` (`services/tenant_resolver.py`) puebla `g.current_tenant` desde (1) JWT Bearer (API), (2) sesión Flask (HTML legacy), o (3) defaults de entorno (`DEFAULT_TENANT_ID`/`DB_NAME`, rutas públicas/pre-login).
- Módulos opcionales por tenant: `tenant_features.py` (`is_module_active()`, `get_active_module_codes()`).

> Mapa completo "para qué sirve cada archivo": [docs/MAPA_ARCHIVOS.md](docs/MAPA_ARCHIVOS.md).
> Integración con el POS de escritorio: [docs/INTEGRACION_WEB_DESKTOP.md](docs/INTEGRACION_WEB_DESKTOP.md).

### Routes (Flask Blueprints)

`routes/__init__.py::register_blueprints(app)` registra **16 blueprints siempre** y **3 de la API REST solo si `CYBERSHOP_API_ENABLED=1`** (19 en total). `routes/factura_electronica.py` **no es un blueprint** — es un módulo de funciones (`emitir_factura_electronica`, `facturacion_habilitada`, `emitir_factura_pos`) que importa `admin.py`.

| Blueprint (archivo) | Prefijo URL | Responsabilidad |
|---|---|---|
| `auth.py` (`auth`) | `/` | Registro cliente, login, logout, dashboard cliente, Google OAuth staff |
| `public.py` (`public`) | `/` | Home, catálogo, servicios, quiénes somos, contacto, carrito, `/descargar` (portal POS), 404 |
| `admin.py` (`admin`) | `/admin` | Dashboard admin, CRUD productos/usuarios, pedidos, POS, inventario, config módulos, branding |
| `payments.py` (`payments`) | `/` | Flujo de pago PayU: métodos, crear-orden, confirmación (webhook), respuesta-pago, procesar-carrito |
| `quotes.py` (`quotes`) | `/admin/cotizar` | Cotizaciones en PDF |
| `restaurant_tables.py` (`restaurant_tables`) | `/admin/salon` | Mesas de restaurante, ocupación, pedidos por mesa |
| `nomina.py` (`nomina`) | `/admin/nomina` | Nómina (planilla, períodos, novedades) — usa `nomina_inteligente.py` |
| `billing.py` (`billing`) | `/admin/cuenta_cobro` | Cuentas de cobro en PDF |
| `crm.py` (`crm`) | `/admin/crm` | Contactos, oportunidades, actividades, tareas, email masivo, import/export |
| `google_calendar.py` (`google`) | `/admin/google` | OAuth Google + sync bidireccional de Calendar (CRM) |
| `soporte.py` (`soporte`) | `/admin/soporte` | Tickets de soporte cliente↔vendedor |
| `contabilidad.py` (`contabilidad`) | `/admin/contabilidad` | Ingresos/egresos, retenciones, cierres de período |
| `video.py` (`video`) | `/admin/video` | Salas de videollamada (Jitsi) |
| `cupones.py` (`cupones`) | `/` | CRUD cupones de descuento + validación AJAX en carrito |
| `wishlist.py` (`wishlist`) | `/admin/deseos` | Listas de deseos de clientes |
| `share.py` (`share`) | `/` | Compartir archivos: carpetas + link público `/c/<token>` |
| `api_auth.py` (`api_auth`) † | `/api/v1/auth` | JWT: `/login`, `/refresh`, `/logout`, `/me` (RS256 prod / HS256 dev) |
| `api_health.py` (`api_health`) † | `/api/v1` | `/health` público (estado DB/servicios) |
| `api_sync.py` (`api_sync`) † | `/api/v1/sync` | API del POS de escritorio (12 endpoints — ver abajo) |

† Solo registrados con `CYBERSHOP_API_ENABLED=1`.

**Important:** Templates use blueprint-prefixed endpoints in `url_for()` calls (e.g., `url_for('auth.login')`, `url_for('public.productos')`, `url_for('admin.dashboard_admin')`, `url_for('payments.crear_orden')`).

### REST API `/api/v1/` (POS de escritorio + integraciones)

- **`api_auth`** — JWT: emite access + refresh, refresca, revoca (blacklist por hash), `/me`. `services/auth/jwt_handler.py` y `services/auth/decorators.py` (`@jwt_required`, `@jwt_role_required`).
- **`api_health`** — chequeo público sin auth.
- **`api_sync`** — sincronización del POS de escritorio. Auth por header `X-Sync-Key`: primero busca el SHA-256 de la key en `sync_api_keys` (multi-tenant); si no, *fallback legacy* contra `SYNC_API_KEY` de entorno → `DEFAULT_TENANT`. 12 endpoints: `health`, `auth` (login contra `usuarios`), `products`, `users`, `generos`, `sales_web`, `inventory_log`, `outbox` (push), `branding`, `config`, `version`, `stats`. Detalle en [docs/INTEGRACION_WEB_DESKTOP.md](docs/INTEGRACION_WEB_DESKTOP.md).

### services/ — capa de servicios

| Módulo | Rol |
|---|---|
| `db_layer.py` | Conexiones: `control_plane_cursor()` (SaaS) y `tenant_cursor(db_name)` (por tenant) |
| `tenant_resolver.py` | `resolve_current_tenant()` en `before_request` → `g.current_tenant` (JWT/sesión/env) |
| `crypto_utils.py` | `sha256_hex()`, `aes_gcm_encrypt/decrypt()` (cifra passwords de DB con `KMS_KEY`) |
| `public_site_service.py` | Config del sitio público (`public_site_settings/blocks/items`) + compat `cliente_config` |
| `crm_service.py` | Upsert de contactos compartido (formularios/cotizaciones/billing) |
| `installer_packager.py` | Empaqueta el ZIP del instalador POS (base .exe + `bootstrap.json`) |
| `restaurant_tables_service.py` | API interna de estado de mesas/cocina |
| `auth/jwt_handler.py` | Creación/validación/revocación de JWT (RS256 prod, HS256 dev) |
| `auth/decorators.py` | `@jwt_required()`, `@jwt_role_required([...])` |

### Frontend Structure

- **templates/** — Jinja2 templates. Two base templates: `plantillaindex.html` (public pages) and `plantillaapp.html` (admin panel)
- **static/js/Shoppingcar.js** — Client-side shopping cart using localStorage. Core cart logic: add/remove items, quantity management, flying animation on add-to-cart
- **static/js/layout.js** — Header behavior, image slider, and Vue.js interactive card component (public pages)
- **static/js/app.js** — Admin sidebar toggle and mobile submenu navigation
- **static/js/galeriaprincipal.js** — Mobile menu toggle and image slider for internal pages
- **static/css/** — One CSS file per page/template

### Database Tables

Las tablas viven en la **DB del tenant** (no en el control plane):

- **usuarios** — Users con password hasheado (werkzeug), linked to `roles` via `rol_id`
- **roles** — **7 roles** (ver abajo)
- **productos** — Product catalog linked to `generos` (categories)
- **pedidos** — Orders with PayU transaction tracking, payment/shipping status
- **detalle_pedidos** — Order line items

(El control plane `saas_control_plane` tiene su propio esquema: `tenants`, `tenant_databases`, `usuarios_globales`, `refresh_tokens`, `sync_api_keys` — ver `migrations/control_plane/`.)

### Authentication & Authorization

Auth basada en sesión Flask (HTML) o JWT (API). Passwords con werkzeug. Control de acceso vía `@rol_requerido(rol_id_o_lista)` en `security.py`. **7 roles** (corrige el modelo viejo de 3):

| ID | Constante | Rol |
|---|---|---|
| 1 | `ROL_SUPER_ADMIN` | Administrador del sitio (desarrollador, control total) |
| 2 | `ROL_PROPIETARIO` | Dueño del negocio / cliente del software |
| 3 | `ROL_CLIENTE` | Cliente final (comprador en la tienda) |
| 4 | `ROL_EMPLEADO` | Empleado del negocio (ventas, productos, CRM) |
| 5 | `ROL_CONTADOR` | Contador (solo contabilidad y facturación) |
| 6 | `ROL_MESERO` | Mesero del restaurante (toma pedidos en mesas) |
| 7 | `ROL_CAJERO` | Cajero del restaurante (cobra y anula) |

`security.py` agrupa estos roles en conjuntos de permisos reutilizables: `ADMIN_FULL`, `ADMIN_STAFF`, `ADMIN_CONTADOR`, `POS_OPERATIONAL`, `POS_DELETE`, `CATALOG_OPERATIONAL`, `RESTAURANT_OPERATIONAL`, `RESTAURANT_CHARGE`, `RESTAURANT_CANCEL`, etc.

### Shopping Cart → Payment Flow

1. Items stored client-side in localStorage (`Shoppingcar.js`)
2. Cart sent to backend via POST `/procesar-carrito` → stored in Flask session
3. User selects payment method at `/metodos-pago`
4. Order created via `/crear-orden` → inserts into `pedidos` + `detalle_pedidos`
5. Redirect to PayU gateway
6. PayU callback returns to `/respuesta-pago` which polls PayU API for status (4 retries, 2s delay)

### File Uploads

Product images → `static/media/`, user profile photos → `static/user/`. Managed via Flask-Uploads (`configure_uploads` in app.py).

## Personalizacion para Nuevos Clientes

### Sistema de Theming (Colores)

Los colores del proyecto estan centralizados para facilitar la personalizacion por cliente:

#### 1. Colores del Sitio Web (CSS)

**Archivo:** `static/css/variables.css`

Todos los colores del sitio se definen como CSS custom properties en `:root`. Para cambiar la identidad visual de un cliente, editar la seccion **"COLORES DE MARCA"**:

```css
--color-primario: #122C94;           /* Azul principal */
--color-primario-oscuro: #091C5A;    /* Azul oscuro */
--color-secundario: #0e1b33;         /* Navbar, footer */
--color-transicion: #2a4d69;         /* Hover de navbar */
--color-botones: #1F3A93;            /* Botones secundarios */
--color-hover-menu: #fb8500;         /* Hover menu admin */
--color-accent: #e60023;             /* Elementos destacados */
--color-acento-secundario: #a6c438;  /* Iconos busqueda, pago */
```

Los colores neutros (grises, fondos) y de estado (exito, peligro, warning) generalmente no necesitan cambio.

#### 2. Colores del PDF de Cotizaciones

**Archivo:** `config.py` → `Config.BRAND_COLORS`

`xhtml2pdf` no soporta CSS variables, asi que los colores del PDF se controlan desde `config.py`. El template `pdf_quote.html` usa Jinja2 (`{{ colores.primario }}`) en vez de CSS variables.

```python
BRAND_COLORS = {
    'primario': '#122C94',       # Enlaces en el PDF
    'primario_oscuro': '#091C5A',
    'secundario': '#0e1b33',
    'texto': '#333333',          # Texto principal
    'texto_claro': '#888888',    # Footer del PDF
    'fondo_claro': '#f9f9f9',    # Fondos de celdas
    'exito': '#28a745',          # Fila de total
    'borde': '#000000',          # Bordes de tablas
}
```

**Importante:** Al cambiar colores de marca, actualizar AMBOS archivos (`variables.css` y `config.py`) para mantener consistencia entre el sitio web y los PDFs.

#### 3. Archivos Clave para Personalizar

| Que cambiar | Archivo | Seccion |
|---|---|---|
| Colores del sitio | `static/css/variables.css` | `:root` - COLORES DE MARCA |
| Colores del PDF | `config.py` | `Config.BRAND_COLORS` |
| Logo del sitio | `static/img/Logo.png` | Reemplazar archivo |
| Logo en PDF | Se sube por formulario o usa `static/img/Logo.png` por defecto |
| Nombre empresa | `templates/plantillaindex.html` y `plantillaapp.html` | Texto en footer/header |
| Email corporativo | `config.py` | `MAIL_USERNAME`, `MAIL_DEFAULT_SENDER` |
| URL de la empresa | `templates/pdf_quote.html` | Enlace en footer del PDF |

### Generacion de PDFs (Cotizaciones)

**Ruta:** `/admin/cotizar` → `/admin/cotizar/generar` (POST)

**Flujo:**
1. Admin llena formulario en `cotizar.html` (cliente, items, logo)
2. `routes/quotes.py::generar_cotizacion()` procesa los datos
3. Se renderiza `templates/pdf_quote.html` con Jinja2 (incluye colores de `Config.BRAND_COLORS`)
4. `xhtml2pdf.pisa.CreatePDF()` convierte HTML a PDF
5. PDF se guarda en `static/cotizaciones/pdf/Cotizacion_{id}.pdf`
6. Se registra en tabla `cotizaciones` de la BD

**Para modificar el formato del PDF:**
- Estructura/contenido: editar `templates/pdf_quote.html`
- Colores: editar `config.py` → `Config.BRAND_COLORS`
- Logica de calculo: editar `routes/quotes.py::generar_cotizacion()`
- Formato de moneda: editar `helpers.py::formatear_moneda()`

## Documentación CSS

### Mapa de archivos CSS

Cada página o módulo tiene su propio CSS. Todos importan `variables.css` como primera línea.

| Archivo CSS | Página / Módulo |
|---|---|
| `variables.css` | Sistema de variables global — **único lugar para cambiar colores** |
| `ProductoDetalle.css` | Página `/producto/<id>`: galería, info, reseñas |
| `Productos.css` | Catálogo `/productos`: tarjetas, popup, carrito lateral |
| `Menuapp.css` | Sidebar y header del panel admin |
| `carrito.css` | Página `/carrito` |
| *(otros)* | Un CSS por template adicional |

### Regla de colores

> **Ningún hex ni `rgba()` directo en archivos CSS de módulo.**
> Todo color va en `variables.css`. Los módulos solo referencian variables.

### variables.css — Grupos de variables

#### COLORES DE MARCA *(los únicos que cambian por cliente)*

```css
--color-primario            Azul principal (botones, encabezados, links admin)
--color-primario-oscuro     Azul oscuro (hover de botones, sidebar)
--color-secundario          Azul muy oscuro (navbar, footer)
--color-transicion          Azul medio (hover navbar, gradientes)
--color-botones             Azul botones secundarios
--color-hover-menu          Naranja (hover menú admin)
--color-accent              Rojo acento (elementos destacados)
--color-acento-secundario   Verde lima (iconos búsqueda, pago)
--color-fondo-destacado     Gradiente secciones oscuras públicas
--color-carrito             Encabezados tabla, título y botón flotante carrito
--color-carrito-hover       Hover de botones carrito
```

#### Página de productos y reseñas

```css
--color-producto-boton      Precio y botón "Ver Detalles" en catálogo
--color-producto-popup      Título popup, tag categoría, iconos en detalle
--color-star-on             Estrella activa/seleccionada en rating  (#f5a623)
--color-star-off            Estrella vacía  (alias de --color-gris-borde)
--color-star-sombra         Sombra para badge de calificación
```

#### Botón carrito / compra

```css
--sombra-exito              Box-shadow normal del botón "Añadir al carrito"
--sombra-exito-hover        Box-shadow hover del botón "Añadir al carrito"
```

#### Tintes de peligro (eliminar ítem)

```css
--color-peligro-tinte       Fondo suave rojo del botón eliminar  (#ffebee)
--color-peligro-tinte-hover Hover del botón eliminar             (#ffcdd2)
```

#### Sombras de marca (derivadas de --color-primario)

```css
--marca-focus-ring          Ring de foco en inputs y controles
--marca-sombra-sutil        Sombra muy suave de marca
--marca-sombra-card         Sombra hover de tarjetas
--marca-sombra-boton        Sombra de botones primarios
--marca-sombra-boton-hover  Sombra hover de botones primarios
--marca-tinte-leve          Fondo tintado de marca (fondos de aviso, tags)
--marca-tinte-medio         Borde tintado de marca (hover de cards)
```

### ProductoDetalle.css — Módulo detalle de producto

**Clases principales:**

| Clase | Descripción |
|---|---|
| `.detalle-wrapper` | Contenedor máximo (1140px centrado) |
| `.detalle-grid` | Grid 2 col. (galería + info) |
| `.detalle-galeria` | Columna izquierda sticky con imagen y miniaturas |
| `.detalle-imagen-principal-wrap` | Contenedor cuadrado con zoom hover |
| `.detalle-miniatura` | Miniatura del carrusel; `.activa` marca la seleccionada |
| `.detalle-nav-btn` | Flechas prev/next del carrusel |
| `.detalle-info` | Columna derecha con toda la info del producto |
| `.detalle-categoria-tag` | Pill de categoría |
| `.detalle-cantidad-ctrl` | Control +/- de cantidad con `focus-within` animado |
| `.btn-detalle-carrito` | Botón principal de compra (verde, con sombra de marca) |
| `.btn-detalle-volver` | Botón outline secundario |
| `.detalle-relacionados` | Sección de productos relacionados |
| `.detalle-rel-card` | Tarjeta de producto relacionado con zoom imagen en hover |

**Módulo de reseñas (clases `.resenas-*` y `.resena-*`):**

| Clase | Descripción |
|---|---|
| `.resenas-seccion` | Contenedor de toda la sección de reseñas (`#resenas`) |
| `.resenas-resumen` | Card con promedio + barras de distribución |
| `.resenas-num-grande` | Número de promedio (3.8rem) |
| `.resenas-estrellas-grandes` | Fila de iconos de estrellas (usa `--color-star-on`) |
| `.resenas-barra-fill` | Barra de progreso animada (`pd-barraCrecer`) con gradiente |
| `.resenas-lista` | Contenedor de tarjetas de reseñas aprobadas |
| `.resena-card` | Tarjeta individual con hover elevado |
| `.resena-avatar` | Círculo con inicial del autor (gradiente de marca) |
| `.resenas-form-wrap` | Card del formulario; cambia sombra con `focus-within` |
| `.star-selector` | Contenedor del selector interactivo de estrellas |
| `.star-btn` | Botón de estrella individual; `.activa` dispara `pd-starPop` |
| `.resenas-form-btn` | Botón enviar reseña (color primario, sombra de marca) |
| `.resenas-aviso` | Aviso de moderación (fondo `--marca-tinte-sutil`) |

**Animaciones definidas en este archivo:**

| Nombre | Efecto |
|---|---|
| `pd-fadeSlideUp` | Aparición suave desde abajo (entrada de secciones) |
| `pd-barraCrecer` | Crecimiento de 0% hacia el ancho real (barras de rating) |
| `pd-starPop` | Rebote de escala al seleccionar una estrella |
| `pd-pulseRing` | Ring de pulso de marca (disponible para uso) |
| `pd-shimmer` | Efecto shimmer de carga (disponible para skeleton loaders) |

### Productos.css — Módulo catálogo y popup

**Clases principales:**

| Clase / ID | Descripción |
|---|---|
| `.producto` | Tarjeta de producto en el catálogo |
| `.añadir-carrito` | Botón verde de la tarjeta (fondo `--color-exito`) |
| `.ver-descripcion` | Botón pill "Ver Detalles" (fondo `--color-producto-boton`) |
| `.popup` | Overlay fijo del modal de detalle rápido |
| `.popup-contenido` | Card del modal (max 860px, animación `scaleUp`) |
| `.popup-layout` | Grid 2 col. dentro del modal |
| `.popup-galeria` | Galería de imágenes del modal |
| `.popup-miniatura` | Miniatura del modal; `.activa` marca la seleccionada |
| `.popup-btn-carrito` | Botón "Añadir al carrito" dentro del modal |
| `.carrito-lateral` | Panel derecho del carrito en la vista de catálogo |
| `#vaciar-carrito` | Botón vaciar carrito (rojo `--color-eliminar`) |
| `#pagar-carrito` | Botón pagar carrito (verde `--color-exito`) |
| `.item-controls` | Controles +/- de cantidad por ítem en el carrito |
| `.item-controls .eliminar-item` | Botón eliminar ítem (fondo `--color-peligro-tinte`) |

### Módulo de reseñas — Backend

**Tabla BD:** `producto_comentarios`

```sql
id, producto_id, usuario_id, autor_nombre,
calificacion (1-5), comentario, aprobado (bool), fecha_creacion
```

**Rutas públicas** (`routes/public.py`):
- `GET  /producto/<id>`            → muestra detalle + reseñas aprobadas + stats
- `POST /producto/<id>/comentar`   → guarda reseña (aprobado=false por defecto)

**Rutas admin** (`routes/admin.py`):
- `GET  /admin/resenas`                       → lista con filtro `?filtro=pendientes|aprobadas|todas`
- `POST /admin/resenas/<id>/aprobar`           → aprueba una reseña
- `POST /admin/resenas/<id>/rechazar`          → elimina una reseña

**Menú admin:** Inventario → Reseñas (`admin.gestion_resenas`)

## Conventions

- All user-facing text is in Spanish
- Route URLs use Spanish names (e.g., `/productos`, `/registrar-cliente`, `/metodos-pago`)
- Templates follow naming: public pages use `plantillaindex.html` as base, admin pages use `plantillaapp.html`
- Frontend uses jQuery 3.3.1, SweetAlert2 for notifications, Font Awesome for icons
- No ORM; raw SQL via `psycopg2` with parameterized queries
- Blueprint endpoint names must be prefixed in `url_for()` (e.g., `auth.login`, `public.index`, `admin.dashboard_admin`)
- CSS colors must use variables from `variables.css` — never hardcode hex values in CSS files
- PDF template colors use Jinja2 variables from `Config.BRAND_COLORS` — not CSS variables
