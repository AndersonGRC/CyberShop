# Plan de limpieza de código muerto — CyberShop

Fecha: 2026-04-24
Autor: inspector de código
Alcance revisado en esta pasada: scripts raíz, blueprints Flask, templates Jinja.
No se ha borrado nada — este documento es solo el plan.

> Importante: antes de eliminar cualquier archivo, hacer commit limpio
> del estado actual y probar en dev con `python app.py`. Marcar cada
> ítem como "confirmado en prod" antes de borrar (varios archivos
> referenciados podrían usarse por cron externo o procesos no visibles
> en el repo).

---

## 1. Nivel ALTO de confianza — candidatos a eliminar

Archivos con referencias rotas, duplicados u obsoletos.

### 1.1 Scripts raíz rotos / obsoletos

| Archivo | Motivo | Evidencia |
|---|---|---|
| `/init_cuentas_cobro_db.py` | Referencia a `app/schema_cuentas_cobro.sql` que NO existe en el repo | `ls app/schema_*.sql` devuelve vacío |
| `/init_nomina_db.py` | Referencia a `app/schema_nomina.sql` y `app/seed_nomina_2025.sql` que NO existen | mismo listado |
| `/get_schema.py` | Utilidad ad-hoc de inspección (imprime columnas de `productos`) — no se importa desde ningún lado | `grep -rn get_schema` solo lo encuentra a sí mismo |
| `/app/add_more_colors.py` | Migración one-shot de datos (ya aplicada en `cliente_config`) | Sin referencias en código; inserta colores que ya están en BD |
| `/app/migrate_contabilidad.py` | Migración one-shot (ya aplicada) | Solo referenciado por un comentario en `routes/contabilidad.py` |

Acción: mover a `/app/migrations_aplicadas/` (o carpeta `archivo/`) en lugar de eliminar directamente, para preservar historia de cambios de esquema.

### 1.2 Logs en el repo

| Archivo | Motivo |
|---|---|
| `/payu_integration.log` | Log de runtime, no debería estar versionado |
| `/app/payu_integration.log` (≈112 KB) | Igual |
| `/app/error.log` | Igual |

Acción: añadir a `.gitignore` y truncar (o mover a `/var/log/cybershop/`).

### 1.3 Duplicado de logo

`static/img/Logo.png` y `static/img/Logo.PNG` coexisten (mismo nombre distinto case).
Verificar cuál se referencia en templates y borrar el otro.

---

## 2. Nivel MEDIO — requiere confirmación

### 2.1 Migraciones SQL sueltas

En `app/` conviven:
- `database.sql` (schema base)
- `migrate_public_site_settings.sql`
- `migrate_public_site_structured.sql`
- `migrate_facturacion_por_registro.sql`
- `migrate_pdf_fields.sql`
- `migrate_product_catalog_visibility.sql`
- `migrate_restaurant_roles.sql`
- `migrate_restaurant_tables_module.sql`

Acción propuesta: crear `app/migrations/aplicadas/` y mover los `migrate_*.sql` que ya estén consolidados en `database.sql`. Los nuevos (`migrate_public_site_*`) todavía no han sido aplicados a juzgar por el `git status` (aparecen como `??`), así que quedan fuera.

### 2.2 Archivos "basura" del entorno

- `/.codex`, `/app/.codex` — archivos vacíos (0 bytes) de herramientas externas. Deberían estar en `.gitignore`.
- `/.codex` aparece como `??` en `git status`.

### 2.3 Blueprint `factura_electronica`

`routes/factura_electronica.py` NO registra Blueprint, solo expone funciones que se importan en `payments.py` y `admin.py`. Está correcto como está, pero conviene renombrarlo a `services/factura_electronica.py` para reflejar que es un servicio y no un blueprint. (Cambio de ubicación, no eliminación).

---

## 3. Pendiente de analizar en las siguientes pasadas

No se alcanzó a inspeccionar en esta sesión:

1. **Templates huérfanos** — script generado en `/tmp/templates_all.txt` y `/tmp/templates_referenced.txt`. Falta hacer el diff final. Observaciones preliminares:
   - `plantillaindexError.html` solo lo usa `404.html` (OK).
   - `crm_dashboard.html` y `crm_contacto_ver.html` se renderean desde `crm.py` líneas 138 y 295 (en uso).
   - `config_secciones.html` se renderea desde `admin.config_secciones` (en uso).
   - `tenant_modules.html` desde `restaurant_tables.py` (en uso).

2. **Funciones muertas en helpers** — revisar cada función de `helpers.py`, `helpers_google.py`, `helpers_gmail.py`, `helpers_email_templates.py` cruzándolas con `grep` de sus nombres.

3. **Variables y constantes no usadas** — ejecutar `vulture` o `pyflakes` para listar imports y variables no usadas (requiere instalar la herramienta).

4. **Static CSS/JS sin referencia** — cruzar los 58 archivos en `static/css/` y `static/js/` contra `{{ url_for('static', filename=...) }}` y `<script src=...>` / `<link href=...>` en templates.

5. **Archivos en `static/uploads/` y `static/media/media/`** — algunos son imágenes de productos que podrían ya no existir en la tabla `productos`. Requiere SQL para comparar.

6. **Base de datos** — identificar:
   - Tablas declaradas en `database.sql` sin uso en código (buscar nombre de tabla en `grep -rn "FROM <tabla>"` y `INSERT INTO <tabla>`).
   - Columnas nunca leídas ni escritas.
   - Recomiendo generar un listado con:
     ```sql
     SELECT table_name FROM information_schema.tables WHERE table_schema='public';
     SELECT table_name, column_name FROM information_schema.columns WHERE table_schema='public';
     ```
     y cruzarlo con `grep` sobre el código.

### 3.1 Resultado análisis BD (pasada 2026-04-24)

BD `cybershop` en Postgres tiene **56 tablas** en schema `public`.
Cruzado con `grep` sobre `app/*.py`, `app/*.sql`, `app/*.html`, las siguientes tablas tienen **cero referencias en el código** y son candidatas a revisión:

| Tabla | Observación |
|---|---|
| `nomina_arl_niveles` | Creadas por alguna migración vieja del módulo de nómina |
| `nomina_asientos_contables` | Sospecha: el asiento contable de nómina se genera de otra forma |
| `nomina_asientos_detalle` | Idem |
| `nomina_parafiscales` | Probablemente configuración que el engine nuevo ignora |
| `nomina_prestaciones` | Idem |
| `nomina_retencion_tabla` | Idem |
| `nomina_seguridad_social` | Idem |
| `reportes_generados` | Solo aparece su `CREATE TABLE` en `database.sql`, nada lee/escribe |

Acción recomendada (NO ejecutada en esta pasada):
1. Verificar en producción que las tablas están vacías o tienen datos obsoletos:
   ```sql
   SELECT COUNT(*) FROM nomina_arl_niveles;
   SELECT COUNT(*) FROM reportes_generados;
   -- etc.
   ```
2. Si están vacías o solo tienen semillas de hace >6 meses sin uso, hacer dump de seguridad y luego `DROP TABLE`.
3. NO borrar hasta tener backup (`pg_dump -Fc cybershop > backup_pre_limpieza.dump`).

Tablas con pocas referencias (3-5) como `nomina_contratistas_pila`, `cupones_uso`, `google_calendar_watches`, `detalle_cuenta_cobro` deben revisarse manualmente — pueden ser módulos recientes todavía no totalmente integrados.

---

## 4. Procedimiento recomendado (cuando autorices borrar)

1. Crear rama `chore/limpieza-codigo-muerto`.
2. Para cada ítem de la sección 1 (ALTO):
   - mover a `archivo/` en lugar de `rm`.
   - commit separado por categoría ("archive: scripts rotos", "archive: migraciones aplicadas", …).
3. Ejecutar `python app.py` y navegar un smoke-test mínimo:
   - `/`, `/productos`, `/login`, `/admin`, `/admin/crm`, `/admin/nomina`, `/admin/contabilidad`, `/carrito`.
4. Si todo pasa, abrir PR — NO borrar de `archivo/` hasta que la rama lleve al menos una semana en producción.
5. Repetir con la sección 2 (MEDIO) tras confirmación explícita tuya de cada ítem.
6. Pasadas siguientes: secciones 3.1–3.6.

---

## 5. Resumen ejecutivo

| Categoría | Archivos candidatos | Riesgo |
|---|---|---|
| Scripts raíz rotos | 5 | Bajo |
| Logs versionados | 3 | Bajo |
| Duplicado logo | 1 | Bajo |
| Migraciones aplicadas | ~6 | Medio (mantener como historia) |
| Archivos `.codex` | 2 | Bajo |
| Reubicación factura_electronica | 1 | Medio (import paths) |
| Templates huérfanos | pendiente | — |
| Helpers no usados | pendiente | — |
| Static sin referencia | pendiente | — |
| BD: tablas/columnas sin uso | pendiente | Alto (requiere análisis más cuidadoso) |

Total estimado en la pasada 1: ~11 archivos con alta confianza, 9 con confirmación previa.
