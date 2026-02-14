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

### Routes (Flask Blueprints)

Routes are organized in the `routes/` package with four blueprints:

- **routes/__init__.py** — `register_blueprints(app)` registers all blueprints
- **routes/auth.py** (`auth_bp`) — `/registrar-cliente`, `/login`, `/logout`, `/cliente`
- **routes/public.py** (`public_bp`) — `/`, `/productos`, `/servicios`, `/quienes_somos`, `/contactenos`, `/carrito`, `/enviar-mensaje`, 404 handler
- **routes/admin.py** (`admin_bp`) — `/admin`, `/agregar-producto`, `/editar-productos`, `/editar-producto/<id>`, `/eliminar-productos`, `/eliminar-producto/<id>`, `/gestion-usuarios`, `/crear-usuario`, `/editar-usuario/<id>`, `/cambiar-password/<id>`, `/gestion-pedidos`
- **routes/payments.py** (`payments_bp`) — `/metodos-pago`, `/crear-orden`, `/confirmacion-pago`, `/respuesta-pago`, `/procesar-carrito`, `/debug-session`

**Important:** Templates use blueprint-prefixed endpoints in `url_for()` calls (e.g., `url_for('auth.login')`, `url_for('public.productos')`, `url_for('admin.dashboard_admin')`, `url_for('payments.crear_orden')`).

### Frontend Structure

- **templates/** — Jinja2 templates. Two base templates: `plantillaindex.html` (public pages) and `plantillaapp.html` (admin panel)
- **static/js/Shoppingcar.js** — Client-side shopping cart using localStorage. Core cart logic: add/remove items, quantity management, flying animation on add-to-cart
- **static/js/layout.js** — Header behavior, image slider, and Vue.js interactive card component (public pages)
- **static/js/app.js** — Admin sidebar toggle and mobile submenu navigation
- **static/js/galeriaprincipal.js** — Mobile menu toggle and image slider for internal pages
- **static/css/** — One CSS file per page/template

### Database Tables

- **usuarios** — Users with bcrypt-hashed passwords, linked to `roles` via `rol_id`
- **roles** — Three roles: Admin (1), Staff (2), Customer (3)
- **productos** — Product catalog linked to `generos` (categories)
- **pedidos** — Orders with PayU transaction tracking, payment/shipping status
- **detalle_pedidos** — Order line items

### Authentication & Authorization

Session-based auth using Flask sessions. Passwords hashed with werkzeug. Role access controlled by `@rol_requerido(role_id)` decorator in `security.py` — Admin=1, Staff=2, Customer=3.

### Shopping Cart → Payment Flow

1. Items stored client-side in localStorage (`Shoppingcar.js`)
2. Cart sent to backend via POST `/procesar-carrito` → stored in Flask session
3. User selects payment method at `/metodos-pago`
4. Order created via `/crear-orden` → inserts into `pedidos` + `detalle_pedidos`
5. Redirect to PayU gateway
6. PayU callback returns to `/respuesta-pago` which polls PayU API for status (4 retries, 2s delay)

### File Uploads

Product images → `static/media/`, user profile photos → `static/user/`. Managed via Flask-Uploads (`configure_uploads` in app.py).

## Conventions

- All user-facing text is in Spanish
- Route URLs use Spanish names (e.g., `/productos`, `/registrar-cliente`, `/metodos-pago`)
- Templates follow naming: public pages use `plantillaindex.html` as base, admin pages use `plantillaapp.html`
- Frontend uses jQuery 3.3.1, SweetAlert2 for notifications, Font Awesome for icons
- No ORM; raw SQL via `psycopg2` with parameterized queries
- Blueprint endpoint names must be prefixed in `url_for()` (e.g., `auth.login`, `public.index`, `admin.dashboard_admin`)
