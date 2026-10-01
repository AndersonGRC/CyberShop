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

## Prueba gratis de 15 días (1.6.0.0)

```
/prueba-gratis  (asistente de 4 pasos, static/js/prueba_gratis.js; sin JS funciona igual)
   1. Tu negocio      → nombre + tipo (tienda, restaurante, servicios, otro)
   2. Dirección web   → subdominio sugerido + verificación en vivo
                        GET /prueba-gratis/slug?s=  (plan_compras + maestro /tenants/slug-disponible)
   3. Diseña tu página→ color de marca (muestras o libre, contraste ≥ 3) + frase, con vista previa
   4. Tus datos       → nombre, correo, WhatsApp OBLIGATORIO (10 dígitos, acepta +57)
   POST → plan_compras TRIAL_PENDIENTE (+ color_marca, tipo_negocio, lema)
        → contacto lead en el CRM de CyberShop (origen prueba_gratis, etiqueta prueba-gratis)
        → correo de confirmación (si no confirmó y reintenta: se reenvía, no se bloquea)
/prueba-gratis/confirmar/<token> → activar_tienda_async (MISMA creación de siempre)
/activar-tienda/<token>          → se actualiza sola (GET …/estado cada 3 s) con 4 etapas
```

Después de una creación exitosa (`_worker`), sin tocar create_tenant/seed/provision:

- **Tienda neutra** (todas las autoservicio): `marca_service.valores_tienda_nueva` →
  logo `static/img/tu-logo-aqui.svg`, correo/WhatsApp/teléfono del cliente (no los de
  CyberShop), su paleta (`paleta_desde`) y textos guía para editar en Mi Negocio.
- **Modo prueba** (solo pruebas): maestro `POST /internal/api/v1/tenants/<id>/modo-prueba`
  → `trial_mode_service.aplicar` deja VACÍAS en `<slug>.env` las llaves de PayU, Google,
  Meta, DIAN y BILLING_* y reinicia la instancia. Correo e IA siguen activos (decisión del
  dueño). Al pagar la renovación se quita (`activo=false`): solo se borran las llaves que
  siguen vacías.
- **CRM**: actividad «Prueba gratis activada» + tarea «Llamar a … su prueba vence el …»
  (día 12, prioridad alta). Pantalla **CRM → Pruebas gratis** (`routes/crm_pruebas.py`):
  días que quedan, WhatsApp, correo, link de pago, filtros.
- El teléfono también sale en el aviso al operador y en la ficha del maestro.

Relleno de pruebas anteriores al CRM: `python tools/backfill_crm_pruebas.py` (vista
previa) y `--aplicar` (solo crea los contactos que faltan).
