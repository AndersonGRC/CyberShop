# Venta automática de planes (SaaS self-service)

> Un pago de plan mensual aprobado crea la tienda del cliente y envía sus
> accesos, sin que nadie toque el panel. Incluye recordatorios de cobro y
> reactivación automática al renovar.

## Decisiones de negocio

- **Solo planes mensuales** crean tienda automática:
  `software-cybershop` → módulos `estandar`, `ultra` → módulos `ultra`
  (mapeo en `services/plan_compras_service.py::PLANES_AUTOMATICOS`).
- Planes **anuales** (`web-corporativa`, `web-ecommerce`): solo correos
  (cliente "te contactaremos" + aviso al operador) y manejo manual.
- **Activación post-pago**: el cliente elige nombre del negocio y subdominio
  en una página, no en el checkout.

## Flujo

```
/comprar-plan/<key> (checkout PayU)
   → pedido (PENDIENTE) + plan_compras (PENDIENTE_PAGO)
   → redirección a PayU

webhook /confirmacion-pago (y respaldo en /respuesta-pago) APROBADO
   → venta_automatica_service.procesar_compra_plan(ref)   [idempotente]
        mensual → marcar_pagada_con_token → email activación al comprador
        anual   → marcar_contacto → email "te contactaremos"
        siempre → email de aviso al operador

GET/POST /activar-tienda/<token>
   → cliente: nombre del negocio + subdominio (slugify en vivo)
   → POST: marcar_activando + threading.Thread:
        master_client.crear_tenant_en_maestro(slug, nombre, email, plan)
          → maestro: create_tenant + apply_plan (BD+seed+instancia+dominio+SSL)
        éxito → marcar_activada (fija proximo_pago, emite token_renovacion)
              → email de bienvenida (URL, /admin, credenciales, client_code POS)
        fallo → marcar_error (reintentable reabriendo el link)

cron diario tools/notificar_renovaciones.py (8:00am)
   → recordatorios: 'previo' (≤5d), 'dia0', 'vencido' (≥3d) — sin duplicados
   → AUTO_SUSPENDER_DIAS > 0: suspende vía maestro a los N días vencido
   → aviso al operador con la lista de vencidos

GET/POST /renovar/<token> (PayU)
   → webhook APROBADO → extender_periodo (corre proximo_pago un período)
   → si estaba suspendida_por_pago → master_client.reactivar_tenant (revive sola)
```

## Componentes

| Archivo | Rol |
|---|---|
| `services/plan_compras_service.py` | Tabla `plan_compras` (estados + fechas de cobro), transiciones idempotentes |
| `services/venta_automatica_service.py` | `procesar_compra_plan()` (webhook), `activar_tienda_async()` (hilo), `validar_slug()` |
| `services/master_client.py` | Cliente HTTP de la API interna del maestro (create/suspend/reactivate) |
| `helpers_email_templates.py` | 5 plantillas: activación, bienvenida, plan anual, aviso operador, recordatorio |
| `routes/public.py` | `/activar-tienda/<token>`, `/renovar/<token>` + hook en `comprar_plan` |
| `routes/payments.py` | Hook `procesar_compra_plan` en webhook y respuesta |
| `tools/notificar_renovaciones.py` | Cron diario de cobro (recordatorios + suspensión opcional) |
| `CyberShopAdmin/routes/internal_api.py` | API interna del maestro (X-Internal-Key) |

## Configuración

| Variable (env de ambas apps) | Default | Uso |
|---|---|---|
| `INTERNAL_API_KEY` | — | Secreto compartido app ↔ maestro (token_urlsafe 32). Sin él, la API interna responde 503 |
| `MASTER_INTERNAL_URL` | `http://127.0.0.1:5002` | Base de la API interna del maestro |
| `AUTO_SUSPENDER_DIAS` | `0` | Días de gracia tras vencer antes de suspender. `0` = solo notificar |

- Cron: `/etc/cron.d/cybershop-billing` (8:00am) → `tools/notificar_renovaciones.py`.
- **Infra**: wildcard DNS `*.cybershopcol.com → 38.134.148.47` (Cloudflare,
  DNS-only) para subdominios de clientes nuevos + SSL automático.

## Estados de `plan_compras`

`PENDIENTE_PAGO` → `PAGADO` (token) → `ACTIVANDO` → `ACTIVADA` | `ERROR` (reintentable)
· `CONTACTO` (planes anuales) · fila de renovación: `renovacion_de` apunta al padre.

## Cómo probar sin gastar dinero

Simular el webhook de PayU con firma MD5 válida (mismo formato que valida
`routes/payments.py::confirmacion_pago`):

```
sign = md5(f"{API_KEY}~{MERCHANT_ID}~{ref}~{value}~COP~4")
POST /confirmacion-pago  con merchant_id, reference_sale=ref, value, currency=COP,
                              state_pol=4, sign
```

Luego abrir `/activar-tienda/<token>` (el token queda en `plan_compras`),
activar con un slug de prueba, verificar el tenant en el control plane y
finalmente `destroy_hard` desde el panel. Probado así en DEV y en PROD.
