# Herramientas de línea de comandos (`app/tools`)

Se corren desde `app/` con el Python del entorno: `python tools/<script>.py`.
Ninguna se ejecuta sola salvo las marcadas como **cron**.

## Vigentes

| Script | Para qué | Cuándo |
|---|---|---|
| `notificar_renovaciones.py` | Recordatorios de pago y suspensión del motor de cobro | **cron** diario (`/etc/cron.d/cybershop-billing`, ver `docs/VENTA_AUTOMATICA.md`) |
| `crear_sync_key.py` | Crea la API key de un POS de escritorio | Alta de un equipo (también desde el maestro → Accesos) |
| `gen_jwt_keys.py` | Genera el par de llaves JWT del API | Instalación (`vps/04_deploy_app.sh`) |
| `ia_mapa.py` | Mapa de herramientas de la IA (lo usa una prueba y la documentación) | Al cambiar herramientas de IA |
| `ia_reconciliar_ventas.py` | Diagnóstico de solo lectura: ventas de la IA vs contabilidad | Antes de cambiar la fuente de datos de la IA |
| `optimizar_media.py` | Recomprime imágenes de `static/` (`--dry-run` primero) | Cuando haya imágenes pesadas |
| `backfill_crm_pruebas.py` | Crea en el CRM los contactos de pruebas gratis anteriores (`--aplicar` escribe) | Pendiente de correr una vez en producción (BACKLOG M12) |
| `backfill_plan_compras.py` | Incorpora al motor de cobro a un cliente creado a mano (`--dry-run` primero) | Lo indica el maestro → Cobros → «Fuera del motor» |
| `vps/00-09*.sh` | Instalación del servidor desde cero | Servidor nuevo |

`cron_recordatorios.py` (8:00) y `cron_resumen_ia.py` (7:00) están en la raíz de `app/`; su
línea de cron está en su docstring. Ojo: esas líneas usan `/var/www/CyberShop/app/env`, mientras
que los scripts de `vps/` instalan en `/opt/cybershop/app/venv`; usar la ruta del entorno real.

## De un solo uso (históricas, no correr sin revisar)

| Script | Qué hizo |
|---|---|
| `migrate_prod_to_tenant.py` | Migración única de la BD de producción al modelo multi-cliente |
| `sembrar_blog.py` | Sembró el plan editorial del blog |
| `seed_test_user.py` | Usuario de prueba para desarrollo local |
| `ia_foto_herramientas.py`, `ia_comparar_fotos.py` | Foto antes/después del refactor F0.1 de la IA |
| `ia_medir_modelos.py`, `ia_medir_tokens.py` | Mediciones de modelos y tokens (rutas `C:/Cybershop` fijas) |
