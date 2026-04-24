# Archivo de scripts obsoletos

Scripts movidos aquí por la limpieza del 2026-04-24.
No se ejecutan ni se importan desde el código activo.
Se conservan como historia por si se necesita consultar
cómo fue alguna migración antigua.

| Archivo | Rol original |
|---|---|
| `init_cuentas_cobro_db.py` | Inicializaba un esquema `app/schema_cuentas_cobro.sql` que ya no existe |
| `init_nomina_db.py` | Inicializaba `app/schema_nomina.sql` + seed — archivos ya no existen |
| `get_schema.py` | Utilidad ad-hoc para imprimir columnas de `productos` (debug) |
| `add_more_colors.py` | Migración one-shot de datos: insertó 4 colores en `cliente_config` |
| `migrate_contabilidad.py` | Migración one-shot: creó tablas `contabilidad_movimientos` y `contabilidad_cierres` |

Si en algún momento queda claro que nadie las va a consultar,
se pueden eliminar con `git rm`.
