# Documentación de CyberShop (web)

Punto de entrada. Si un documento no está aquí, probablemente es histórico.

## Empezar
- [ECOSISTEMA.md](ECOSISTEMA.md): cómo encajan web, maestro (admin.cybershopcol.com), escritorio y FacturacionDIAN.
- [MAPA_ARCHIVOS.md](MAPA_ARCHIVOS.md): para qué sirve cada archivo de `app/`.
- [../tools/README.md](../tools/README.md): herramientas de línea de comandos (vigentes y de un solo uso).
- [../CLAUDE.md](../CLAUDE.md): reglas de trabajo del proyecto.

## Desplegar
- **Runbook único:** [flujo_desarrollo_y_despliegue.md](flujo_desarrollo_y_despliegue.md).
  - Web: commit → push → maestro → cliente → «⬆ Actualizar app» (o «🌐 Deploy completo» si cambia el sitio público).
  - Maestro: `git pull` en `/var/www/CyberShopAdmin` + `systemctl restart cybershop-admin` (ver `CyberShopAdmin/DEPLOY.md`).
- [VERSIONADO.md](VERSIONADO.md): todo despliegue sube la versión.
- Casos especiales de IA: [IA_ACTUALIZACION_CLIENTES.md](IA_ACTUALIZACION_CLIENTES.md) y `CyberShopAdmin/docs/RUNBOOK_ACTUALIZACION_TODOS_CLIENTES_IA.md`.

## Módulos
- [modulo_nomina.md](modulo_nomina.md): nómina 2026 (motor, reglas por fecha, contratistas).
- [VENTA_AUTOMATICA.md](VENTA_AUTOMATICA.md): compra de planes, prueba gratis y motor de cobro.
- [INTEGRACION_WEB_DESKTOP.md](INTEGRACION_WEB_DESKTOP.md): API de sincronización con el POS de escritorio.
- IA: [IA_MAPA.md](IA_MAPA.md), [IA_MOTORES.md](IA_MOTORES.md), [IA_ACCIONES_OPERATIVAS.md](IA_ACCIONES_OPERATIVAS.md),
  [IA_CONTRATOS_PROMPTS.md](IA_CONTRATOS_PROMPTS.md), [IA_ARCHIVOS_Y_DEPENDENCIAS.md](IA_ARCHIVOS_Y_DEPENDENCIAS.md),
  [AUDITORIA_IA_MULTITENANT_2026-09.md](AUDITORIA_IA_MULTITENANT_2026-09.md).

## Pendientes
- [pendientes/BACKLOG.md](pendientes/BACKLOG.md): única lista de trabajo pendiente, por importancia.
- [pendientes/PLAN_SEGURIDAD_CREDENCIALES.md](pendientes/PLAN_SEGURIDAD_CREDENCIALES.md): plan aparte, para ejecutar con tiempo.

## Copias que deben mantenerse iguales entre repositorios
Al cambiar uno, cambiar también el otro en el mismo trabajo.

| Aquí (web) | Copia | Cómo |
|---|---|---|
| `nomina_engine.py` | `CyberShopDesktop/nomina_calc.py` | Copia literal (solo cambia el docstring de cabecera) |
| `tenant_features.MODULE_DEFINITIONS` | `CyberShopAdmin/module_service.MODULES` | Mismo código, categoría, clave y valor por defecto |
| `public_site_service` (campos de marca, landing y colores) | `CyberShopAdmin/tenant_site_fields.SITE_FIELDS` | Mismas claves; todo campo nuevo va en los dos |
| `PUBLIC_SECTION_FIELDS` / `PUBLIC_SYSTEM_FIELDS` | `CyberShopAdmin/client_config_service.py`, `seed_service.py` | Copia a mano |
| `services/crypto_utils.py` | `CyberShopAdmin/crypto.py` | Misma lógica AES-GCM |
| `tools/crear_sync_key.py` | `CyberShopAdmin/api_key_service.py` | Mismo prefijo, alfabeto y hash |
| `services/db_layer.py` | `CyberShopAdmin/db.py` | Copia por diseño |
| `security.py` (roles) | `CyberShopDesktop/main.py` (`ROLE_MODULES`) | Espejo a mano |

## Migraciones de base de datos
- **Clientes:** `CyberShopAdmin/migrations/tenant/NNNN_*.sql` (aditivas e idempotentes), aplicadas por «Actualizar app».
- **Control plane:** `app/migrations/control_plane/`.
- `app/migrations/legacy/`: SQL históricos del web, ya aplicados; no se ejecutan solos.
- `app/migrate_backup_db.sql` sigue en la raíz porque el maestro lo usa como `TENANT_SCHEMA_FILE` (ver BACKLOG A4).
