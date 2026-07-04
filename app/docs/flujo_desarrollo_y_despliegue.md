# Flujo de desarrollo y despliegue de CyberShop

> **Léelo antes de tocar código.** Define cómo se desarrolla una mejora en el master de
> CyberShop y cómo se **replica a cada cliente** sin afectar lo suyo. Este flujo es
> obligatorio para próximos desarrollos.

---

## 1. Modelo (cómo está montado)

- **Un solo código COMPARTIDO** — repo `AndersonGRC/CyberShop` en `/var/www/CyberShop`. Todas
  las instancias corren el mismo código; se diferencian por su `.env` y su base de datos.
- **Una instancia por cliente** — `cybershop@<slug>.service` (puerto propio); el cliente primario
  corre como `cybershop.service`. Cada cliente carga el código nuevo **al reiniciar su instancia**.
- **Panel de administración** — repo `AndersonGRC/Cybershop_innovation` en `/var/www/CyberShopAdmin`
  (`admin.cybershopcol.com`). Desde aquí se crean clientes y se les **llevan las actualizaciones**.
- **Dos caras del app:**
  - **ANTES del login** = sitio público / storefront. Base: `templates/plantillaindex.html`.
  - **DESPUÉS del login** = software interno (POS, admin, inventario, ventas, CRM, nómina,
    contabilidad…). Base: `templates/plantillaapp.html`.

### Qué es de cada cliente (NUNCA lo toca un despliegue)
| Cosa | Dónde vive | Fuera del repo |
|---|---|---|
| Base de datos | PostgreSQL `cyber_t<id>` (una por cliente) | ✅ |
| Integraciones / secretos / puerto | `/etc/cybershop/<slug>.env` | ✅ |
| Overrides de tema del cliente | `/var/www/cybershop-overrides/<slug>/` | ✅ |
| Marca (colores, logo, textos, secciones) | filas en la BD del cliente (`cliente_config`, `public_site_settings`) | ✅ |
| Logos subidos | `app/static/media/public_site/` — **en `.gitignore`** | ✅ (no entra a git) |

---

## 2. Regla de oro

Las actualizaciones deben **COMPLEMENTAR, no AFECTAR** a cada cliente:

1. **Nunca tocar datos del cliente.** Su marca y su configuración viven en su BD/overrides, fuera
   del repo → un `git pull` jamás los cambia.
2. **Migraciones de BD SIEMPRE aditivas e idempotentes** — `CREATE TABLE IF NOT EXISTS`,
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`. **Jamás** `DROP`/`ALTER`
   destructivo. Van en `CyberShopAdmin/migrations/tenant/*.sql`.
3. **No soltar cambios del sitio público sin querer** — hay un *gate* (ver §4).
4. **Nunca committear medios de clientes** (`app/static/media/public_site/` ya está ignorado).

---

## 3. Cómo subir una mejora (paso a paso)

1. **Desarrolla en el master** (código compartido). Prueba en local/dev.
2. **Commit + push a `origin/master`.**
   - **Disciplina de ramas:** lo del sitio público a medio hacer va en **ramas**; a `master` solo
     lo que esté **listo para todos**. Así el botón normal casi nunca se bloquea.
3. **¿Cambiaste estructura de BD?** Agrega una migración **aditiva** en
   `CyberShopAdmin/migrations/tenant/NNN_descripcion.sql`.
4. **Lleva la actualización a cada cliente** — panel `admin.cybershopcol.com` → tenant → pestaña
   **Técnico**:
   - **⬆ Actualizar app (después del login)** — el uso normal. Trae el código (con *gate*), migra
     su BD (aditivo) y reinicia su instancia. **Se BLOQUEA** si el push tocó archivos del sitio
     público (te dice cuáles) y no aplica nada.
   - **🌐 Deploy completo (incluye público)** — úsalo **solo** cuando quieras publicar también los
     cambios del sitio público.

> El código es global: al pulsar el botón para un cliente, se hace `git pull` (sirve a todos) y se
> reinicia **esa** instancia. Repite por cada cliente que quieras actualizar.

---

## 4. El *gate* de "cambios públicos" (no traer cosas públicas)

Como el app interno **depende del backend compartido**, no se puede hacer un checkout "solo interno"
sin desfases. En su lugar, el deploy **detecta** si traería archivos del **sitio público** y
**bloquea salvo "Deploy completo"**:

- La lista está en **`CyberShopAdmin/provisioning_service.py` → `PUBLIC_PATHS`**
  (`plantillaindex.html`, `index/productos/carrito/software/login/…`, `share/publico_*`, CSS público
  `index.css`, `Productos.css`, `carrito.css`, `error404.css`, `respuesta _pago.css`, `Shoppingcar.js`).
- **Si agregas una página o CSS del sitio público, añádela a `PUBLIC_PATHS`.**
- **NO** metas ahí backend/servicios/`variables.css`/`layout.css`/`layout.js`: eso debe **fluir
  siempre** (por ejemplo, parches de seguridad).
- Estado de git siempre limpio: el deploy hace `git merge --ff-only` completo **o nada** (nunca un
  checkout parcial que ensucie el árbol).

---

## 5. Clasificación de archivos (referencia rápida)

- **ANTES del login (público):** `plantillaindex.html`, `plantillaindexError.html`, `index.html`,
  `productos.html`, `producto_detalle.html`, `servicios.html`, `carrito.html`, `metodos_pago.html`,
  `respuesta_pago.html`, `redireccion_payu.html`, `software.html`, `descargar.html`,
  `comprar_plan.html`, `activar_tienda.html`, `renovar_plan.html`, `login.html`,
  `registrarcliente.html`, `lista_deseos.html`, `404.html`, `share/publico_*.html` + CSS/JS público.
- **DESPUÉS del login (interno):** `plantillaapp.html`, `Menuapp.css`, `app.js`, `dashboard_admin`,
  `gestion_*`, `GestionProductos`, `facturacion_pos`, `historial_pos`, `crm_*`, `nomina_*`,
  `contabilidad_*`, `restaurant_*`, `video_*`, `configuracion_cliente`, `sitio_publico_admin`, etc.
- **COMPARTIDO (fluye siempre):** `app.py`, `config.py`, `database.py`, `helpers.py`, `security.py`,
  `tenant_features.py`, `services/*` (incl. `db_layer.py`, `tenant_resolver.py`,
  `public_site_service.py`, `crypto_utils.py`), `static/css/variables.css`, `layout.css`, `layout.js`.

---

## 6. Infraestructura del despliegue (cómo funciona por dentro)

- El panel corre como **www-data** (sin permiso de git). El `git pull` lo hace un **script root**
  `/usr/local/bin/cybershop-deploy-code.sh` con subcomandos `changes` (lista lo que cambiaría) y
  `apply` (`git merge --ff-only`), habilitado por `/etc/sudoers.d/cybershop-deploy` (www-data,
  **solo esos dos subcomandos**, `NOPASSWD`).
- `provisioning_service.deploy_code(include_public=False)` orquesta: `changes` → clasifica vs
  `PUBLIC_PATHS` → bloquea o `apply`. Devuelve `(status, msg)` con `status ∈
  {updated, uptodate, blocked, error}`.
- **`--ff-only` nunca pisa cambios locales**: si el árbol del servidor está sucio (p. ej. un hot-fix
  por SSH sin commitear), el deploy **falla avisando** en vez de romper. Por eso, **todo hot-fix por
  SSH debe commitearse y pushearse** a `master`.

---

## 7. Checklist para un desarrollo nuevo

- [ ] Cambios en `master`, probados. WIP público en rama aparte.
- [ ] ¿Estructura de BD nueva? → migración **aditiva** en `migrations/tenant/`.
- [ ] ¿Página/CSS público nuevo? → agregar a `PUBLIC_PATHS`.
- [ ] `git push origin master`.
- [ ] Por cliente: **Actualizar app** (o **Deploy completo** si el cambio público es intencional).
- [ ] Verificar que la marca/datos del cliente quedaron intactos.
- [ ] Nunca `git add` de `app/static/media/**` (medios de clientes).

