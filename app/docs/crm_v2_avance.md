# CRM v2 - Avance de implementación

Fecha de corte: 2026-08-27

## Hecho

- Se creó la base moderna del CRM en `templates/crm_base.html`.
- Se agregó el sistema visual nuevo en `static/css/crm/crm_ui.css`.
- Se actualizó el pipeline comercial en `templates/crm_pipeline.html`.
- Se añadió la migración aditiva `migrate_crm_v2.sql`.
- Se incorporó soporte para `linea_negocio` en oportunidades.
- Se vinculó soporte con CRM mediante `tickets_soporte.crm_contacto_id`.
- Se agregó narración IA para el panel "Tu día" en `services/ai_service.py`.
- Se extendió `routes/crm.py` con:
  - auto-saneado del esquema v2,
  - guard de módulo por tenant para `MODULE_CRM`,
  - etiquetas comerciales del pipeline,
  - filtro por línea de negocio,
  - cálculo de días sin movimiento,
  - endpoint `POST /admin/crm/tu-dia`,
  - búsqueda global del CRM.
- Se reemplazó el dashboard por una versión nueva basada en `crm_base.html`.
- Se agregó `templates/crm_buscar.html` para resultados de búsqueda.

## Pendiente

- Validación de sintaxis Python y render Jinja.
- Ajuste fino de métricas del dashboard si la meta comercial mensual se vuelve configurable.
- Revisión funcional del drag & drop y filtros del pipeline.
- Integración completa del timeline de tickets en la ficha del contacto.
- Automatizaciones adicionales para cierre de ciclo, follow-ups y scoring.

## Criterio de seguridad

Todo lo aplicado es aditivo o de presentación. No se eliminaron rutas existentes ni claves
internas del pipeline. El sistema sigue tolerando ausencia de columnas nuevas.
Además, si el módulo CRM se desactiva en `tenant_features.py` o en la configuración del tenant,
el blueprint `/admin/crm` queda inaccesible para ese cliente.
