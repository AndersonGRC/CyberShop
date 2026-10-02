# Backlog consolidado de CyberShop

Única lista de trabajo pendiente (actualizada el 2-oct-2026). Reemplaza los planes
sueltos que ya se borraron: `OPCIONES_DE_MEJORA.md`, `HANDOFF_CONTINUACION.md`,
`ESTADO_PROYECTO.md`, `plan_mejora_crm.md`, `crm_v2_avance.md`, `IA_ESTADO.md` y los
planes de limpieza de abril. Cada punto indica de dónde salió y cómo verificarlo.

La seguridad de credenciales e infraestructura tiene su propio plan:
[PLAN_SEGURIDAD_CREDENCIALES.md](PLAN_SEGURIDAD_CREDENCIALES.md).

`[prod?]` = verificar primero en producción; desde el código local no se puede saber.

## Alta (dinero, datos o algo que ve el cliente)

| # | Pendiente | Origen | Cómo verificar / hacer |
|---|---|---|---|
| A1 | 12 tablas sin secuencia en `id` (`notas_credito_pos`, `tickets_soporte`, `contabilidad_cierres`…): anular venta POS, crear ticket y cierre contable fallarían `[prod?]` | memoria `plan_ia_conectada` | `\d tabla` en prod; migración aditiva `CREATE SEQUENCE … OWNED BY` + `SET DEFAULT nextval` + `setval(max(id))` |
| A2 | Ventas anuladas siguen sumando en `/contabilidad/ventas` | memoria `plan_ia_conectada` | Decisión del dueño: excluir o mostrar aparte |
| A3 | reCAPTCHA sin `RECAPTCHA_SECRET_KEY`: `/enviar-mensaje` aborta → contacto y leads del CRM rotos `[prod?]` | memoria `recaptcha_faltante_plataforma` | Configurar la llave en el `.cybershop.conf` compartido o degradar a honeypot sin captcha |
| A4 | Prod usa `TENANT_SCHEMA_FILE=schema/tenant_schema.sql` (69 tablas, 5-jun; la línea con `migrate_backup_db.sql` queda anulada). `create_tenant` corre `migrate_db` después, así que los clientes nuevos sí reciben 0001–0017. Falta: regenerar el dump, quitar la línea duplicada del `.cybershop.conf` y corregir `migrations/tenant/README.md` y `DEPLOY.md` | auditoría oct-2026 (verificado en prod 2-oct) | Riesgo bajo; hacerlo con la próxima migración |
| A5 | Borrado lógico de datos financieros (DAT-01): no hay `deleted_at` | `OPCIONES_DE_MEJORA` | Diseñar soft-delete para ventas, movimientos y facturas |
| A6 | POS de escritorio sin cifrado local (DESK-01): BD local y llave de sync en claro | `OPCIONES_DE_MEJORA` | DPAPI/keyring en Windows |
| A7 | Facturación electrónica en producción DIAN: software y resolución reales | memoria `facturacion_electronica_dian_prod` | Trámite con la DIAN + cambio de ambiente |
| A8 | Parámetros de nómina 2027 (SMMLV, auxilio, UVT) en cuanto salgan los decretos | `docs/modulo_nomina.md` | Actualizar `PARAMETROS_OFICIALES_NOMINA` y recopiar a `CyberShopDesktop/nomina_calc.py` |

## Media

| # | Pendiente | Origen |
|---|---|---|
| M1 | `/api/v1/sync/outbox` no valida que el módulo esté en el plan del cliente (`api_sync.py:264`) | memoria `provisioning_tenant_model` |
| M2 | BIL-01: avisos de cobro calculan el día en UTC (`toISOString` en `plantillaapp.html:161`); falta `last_sync_at` | `OPCIONES_DE_MEJORA` |
| M3 | DB-01: 36 archivos aún crean/alteran tablas en tiempo de petición (`_ensure_*`); llevarlas a migraciones | `OPCIONES_DE_MEJORA` |
| M4 | SYNC-01: versión por registro en la sincronización (hoy solo registro de ops aplicadas) | `OPCIONES_DE_MEJORA` |
| M5 | QA-01: integración continua (no existe `.github/`) | `OPCIONES_DE_MEJORA` |
| M6 | Publicar el escritorio 1.0.3.0 (motor de nómina nuevo); `installers/version.json` sigue en 1.0.0.4 `[prod?]` | memorias `nomina_2026_motor`, `feature_etiquetas_codigo_barras` |
| M7 | Nómina F2 (calendario de obligaciones, calculadora de turno, soporte PILA, CSV PILA/banco, dashboard sin colores fijos) y F3 (asiento contable al aprobar) | memoria `nomina_2026_motor` |
| M8 | IA: el `perfil` del plan nunca se fija (`ai_service.py` usa siempre 'normal'; `perfil_desde_texto` sin uso) | `IA_ARCHIVOS_Y_DEPENDENCIAS.md` |
| M9 | Etapas del CRM y criterio PAGADO/APROBADO definidos en varios sitios: las cifras pueden no cuadrar | `IA_ARCHIVOS_Y_DEPENDENCIAS.md` |
| M10 | `cliente_config.clave` sin restricción única | memoria `gotcha_cliente_config_sin_unique` |
| M11 | Maestro Etapa 2: centralizar módulos en el control plane, sacar `/admin/sync-keys` y `saas_modules_admin` del app del cliente, ruteo por dominio | `CyberShopAdmin/docs/PLAN_MASTER.md` |
| M12 | Prueba gratis: cron de `tools/purgar_backups_pruebas.py --aplicar` y correr `backfill_crm_pruebas --aplicar` | memoria `prueba_gratis_15_dias` |

## Baja

| # | Pendiente | Origen |
|---|---|---|
| B1 | CRM: botones WhatsApp/teléfono/correo en la lista, plantillas de WhatsApp, ranking por vendedor, posponer tareas, tickets en la línea de tiempo del contacto, meta mensual y scoring | `plan_mejora_crm.md`, `crm_v2_avance.md` |
| B2 | JS de IA de productos duplicado en `GestionProductos.html` y `editar_producto.html` | `IA_ARCHIVOS_Y_DEPENDENCIAS.md` |
| B3 | ARC-01: partir `routes/admin.py` (3.885 líneas) y `CyberShopDesktop/main.py` (9.231) | `OPCIONES_DE_MEJORA` |
| B4 | OBS-01: métricas (ya hay `request_id` en logs) | `OPCIONES_DE_MEJORA` |
| B5 | DIAN: logo real, botones aprobar/anular en `facturas.html`, `modo_aprobacion` en el formulario | memoria `facturacion_electronica_dian_prod` |
| B6 | SearXNG: instalar en el VPS (`tools/vps/09_searxng.sh`) `[prod?]` | memoria `busqueda_web_searxng` |
| B7 | Mover `routes/factura_electronica.py` (no es blueprint) a `services/` | `plan_limpieza_codigo_muerto.md` |
| B8 | Rama `FacturacionDIAN wip/dian-local-20260826` parece superada: borrar con OK del dueño | auditoría oct-2026 |
