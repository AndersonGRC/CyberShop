# Plan de mejora del módulo CRM — CyberShop

Fecha: 2026-04-24
Autor: inspector de código
Objetivo: que el CRM deje de ser un simple directorio de contactos y se convierta
en la herramienta comercial central del negocio.

---

## 1. Diagnóstico del estado actual

### Lo que existe hoy
- **Contactos** con 4 tipos (cliente / proveedor / lead / socio) y 18 campos (nombre, empresa, email, teléfono, whatsapp, foto, origen…).
- **Actividades** (`crm_actividades`): registro de llamadas/emails/reuniones por contacto.
- **Tareas** (`crm_tareas`): con prioridad, fecha límite, asignado_a, recordatorio diario.
- **Dashboard** con conteos por tipo + tareas vencidas/hoy.
- **Sync con Google Calendar** para actividades y tareas (si el usuario tiene Google conectado).
- **Cron** `cron_recordatorios.py` que envía email diario de tareas pendientes.

### Datos actuales (evidencia del problema)
| Fuente comercial | Filas en BD |
|---|---|
| Cotizaciones generadas | **52** |
| Cuentas de cobro | **14** |
| Usuarios rol cliente | 10 |
| Emails únicos que compraron | 6 |
| **Contactos en CRM** | **4** |
| **Actividades registradas** | **0** |

El CRM vive aislado. Hay 52 cotizaciones pero 0 actividades. El negocio genera relaciones comerciales reales que nunca entran al CRM.

### Los 8 problemas estructurales

| # | Problema | Impacto |
|---|---|---|
| 1 | **No hay pipeline/oportunidades** (prospect → calificado → propuesta → ganado/perdido) | El corazón de un CRM no existe |
| 2 | **CRM desconectado de pedidos / cotizaciones / cuentas de cobro** | No se ve el historial comercial de un contacto |
| 3 | **Form público `/enviar-mensaje` no crea lead en CRM** | Cada prospecto web se pierde en un email |
| 4 | **Sin búsqueda** (solo filtro por tipo) | Con 200 contactos se vuelve inusable |
| 5 | **Sin tags / segmentación** | No se puede enviar campañas a "clientes de Bogotá" |
| 6 | **Sin timeline unificado** por contacto | Hay que abrir 4 módulos para ver qué pasó con Juan |
| 7 | **Sin importar/exportar CSV** | Imposible migrar una base externa o respaldar |
| 8 | **Sin métricas comerciales** (tasa de cierre, tiempo promedio, ranking de vendedores) | Ningún insight para decidir |

---

## 2. Visión: qué queremos que sea el CRM

Un único lugar donde cualquier persona del equipo pueda responder sin abrir 3 módulos:

- "¿Quién es este cliente y cuánto ha comprado?"
- "¿Qué cotizaciones aprobadas tenemos este mes y cuánto sumarán?"
- "¿Qué leads nuevos llegaron ayer desde la web?"
- "¿A quién le debo llamar hoy?"
- "¿Qué oportunidades están trabadas hace más de 15 días?"

---

## 3. Plan por fases

Orden pensado para entregar valor desde la primera semana.

### Fase 1 — Conexión con el mundo real (alta prioridad, 2–3 días)
Cerrar la brecha entre CRM y el resto del sistema.

#### 1.1 Captura automática desde `/enviar-mensaje`
Archivo: `app/routes/public.py:349` (`enviar_mensaje`).
- Al enviar el formulario público, además de mandar el email, **crear/actualizar contacto** `tipo='lead'` en `crm_contactos` (matching por email).
- Guardar el mensaje como primera **actividad** tipo `'formulario_web'`.
- Agregar `origen='web'` automáticamente.

Impacto: cada prospecto web queda trazado. Esfuerzo: bajo.

#### 1.2 Enlace auto CRM ↔ usuarios que compran
Archivo: `app/routes/payments.py` (al confirmar pedido aprobado).
- Si `pedidos.cliente_email` existe y no hay contacto CRM con ese email → crear contacto `tipo='cliente'` con los datos del pedido.
- Si existe → actualizar teléfono/dirección si están vacíos.

Impacto: el CRM refleja automáticamente quiénes son los compradores reales.

#### 1.3 Vincular cotizaciones y cuentas de cobro con contactos
BD:
- `cotizaciones` → agregar columna `crm_contacto_id INTEGER NULL` con FK a `crm_contactos(id)`.
- `cuentas_cobro` → agregar columna `crm_contacto_id INTEGER NULL` con FK a `crm_contactos(id)`.
- Migración SQL: poblar FK existente por matching de email/documento cuando sea único.

Esfuerzo: bajo (migración + 2 líneas en forms de cotizar/cuenta_cobro para permitir elegir contacto existente).

#### 1.4 Timeline unificado en la vista de contacto
Archivo: `app/routes/crm.py:242` (`crm_contacto_ver`) + `templates/crm_contacto_ver.html`.
- En la ficha del contacto, listar en orden cronológico:
  - Actividades (ya está)
  - Tareas (nuevo)
  - Cotizaciones asociadas (nuevo — consulta a `cotizaciones WHERE crm_contacto_id=`)
  - Cuentas de cobro asociadas (nuevo)
  - Pedidos (matching por email — `pedidos WHERE cliente_email = contacto.email`)
- Cada entrada del timeline con su link directo (ya lo tenemos en el módulo de contabilidad — reutilizar).

Impacto: un solo scroll responde "¿qué pasó con este cliente?".

---

### Fase 2 — Pipeline de ventas (alta prioridad, 3–4 días)
Agregar la pieza que falta: **oportunidades**.

#### 2.1 Nueva tabla `crm_oportunidades`
```sql
CREATE TABLE crm_oportunidades (
    id               SERIAL PRIMARY KEY,
    contacto_id      INTEGER REFERENCES crm_contactos(id) ON DELETE CASCADE,
    titulo           VARCHAR(200) NOT NULL,
    descripcion      TEXT,
    monto_estimado   NUMERIC(14,2),
    probabilidad     INTEGER DEFAULT 50,        -- 0-100%
    etapa            VARCHAR(30) DEFAULT 'prospecto',
                     -- prospecto | calificado | propuesta | negociacion | ganada | perdida
    fuente           VARCHAR(60),               -- cotizacion, inbound_web, llamada_fria…
    cotizacion_id    INTEGER REFERENCES cotizaciones(id) ON DELETE SET NULL,
    asignado_a       INTEGER REFERENCES usuarios(id),
    fecha_cierre_est DATE,
    fecha_cierre_real DATE,
    motivo_perdida   VARCHAR(120),
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_oport_etapa    ON crm_oportunidades(etapa);
CREATE INDEX idx_oport_contacto ON crm_oportunidades(contacto_id);
```

#### 2.2 Vista tablero Kanban
Ruta nueva: `/admin/crm/pipeline`.
- Columnas = etapas. Tarjetas = oportunidades, drag & drop para cambiar etapa.
- Cada tarjeta muestra: nombre contacto, monto, probabilidad, días en la etapa.
- Filtro por `asignado_a` (vendedor).

#### 2.3 Cotización ↔ oportunidad
- Al **generar una cotización** desde `/admin/cotizar`, si el cliente ya tiene un contacto CRM, crear automáticamente una oportunidad en etapa `'propuesta'`.
- Al **aprobar cotización** (`quotes.aprobar_cotizacion`), mover la oportunidad a `'ganada'`.
- Al **rechazar cotización**, mover a `'perdida'` con motivo.

Impacto: las 52 cotizaciones existentes se vuelven un embudo visible y medible.

---

### Fase 3 — Productividad diaria (media prioridad, 2 días)

#### 3.1 Búsqueda global en contactos
`templates/crm_contactos.html` + endpoint.
- Input en la parte superior: busca por `nombre ILIKE || empresa ILIKE || email ILIKE || telefono LIKE`.
- Debounce 300 ms, sin reload (fetch JSON).

#### 3.2 Tags / etiquetas libres
```sql
ALTER TABLE crm_contactos ADD COLUMN tags TEXT[] DEFAULT '{}';
CREATE INDEX idx_crm_tags ON crm_contactos USING GIN (tags);
```
- Input de tags en el form (estilo chips) y filtros en la lista.
- Ejemplos: `vip`, `campaña-navidad`, `corporativo`, `bogota`.

#### 3.3 Registro rápido de llamada
Botón "📞 Registrar llamada" en la ficha del contacto → modal con 2 campos (asunto + duración) → crea actividad tipo `llamada` en 3 clicks.

#### 3.4 Acciones rápidas en la lista
En la lista de contactos, por fila:
- WhatsApp → abre `wa.me/<numero>` con el primer mensaje pre-rellenado desde un template.
- Email → abre `mailto:` o mejor: usa `helpers_gmail.enviar_email_gmail` con template.
- Llamar → `tel:<numero>`.

---

### Fase 4 — Datos de entrada/salida (media prioridad, 1 día)

#### 4.1 Exportar CSV de contactos
Endpoint `/admin/crm/contactos/exportar` → CSV con filtro por tipo y tags aplicados.
Patrón idéntico al `contabilidad.exportar` ya existente (`routes/contabilidad.py:455`).

#### 4.2 Importar CSV
Upload de CSV con mapeo de columnas en UI (tipo, nombre, email, teléfono, tags).
Validación de duplicados por email antes de insertar.

---

### Fase 5 — Comunicación saliente (media-baja, 3 días)

#### 5.1 Email a lista segmentada
- Seleccionar N contactos (por filtro de tags o tipo).
- Template HTML (reusar `helpers_email_templates.py`).
- Envío vía `enviar_email_gmail` con BCC masivo (evitar spam).
- Registrar actividad `email_masivo` en cada contacto.

#### 5.2 WhatsApp templates
Pre-cargar 3-5 mensajes tipo ("Hola {nombre}, te comparto…") — un solo click desde la lista.

---

### Fase 6 — Métricas e insight (baja prioridad, 2 días)

Ampliar `crm_dashboard` con:
- **Embudo visual** con número y monto por etapa.
- **Tasa de conversión** lead → cliente en los últimos 30/90 días.
- **Tiempo promedio de cierre** (desde creación de oportunidad hasta `ganada`).
- **Ranking por vendedor** (asignado_a → oportunidades ganadas / monto total).
- **Oportunidades estancadas** (>15 días sin movimiento) → lista con alerta.

---

## 4. Mejoras transversales (pequeñas pero valiosas)

| Mejora | Archivo / ubicación | Esfuerzo |
|---|---|---|
| Validar email y teléfono al guardar contacto (regex) | `crm.py:crm_contacto_crear` | 15 min |
| Deduplicar en tiempo real al crear: avisar si ya existe email | form JS | 30 min |
| Paginación en lista de contactos (50 por página) | `crm_contactos_lista` | 30 min |
| Ordenar tareas por prioridad + fecha | `crm_tareas_lista` | 15 min |
| Estado "snooze" en tareas (postponer 1 día / semana) | `crm_tareas` schema + UI | 1 h |
| Permitir asignar actividad (no solo tareas) a otro usuario | `crm_actividades` schema | 30 min |
| Mostrar agenda de Google dentro del CRM (ya hay sync, falta vista) | nuevo endpoint | 1 h |
| Exigir "motivo" al marcar oportunidad como perdida | pipeline UI | 15 min |

---

## 5. Propuesta de orden de ejecución

Si solo pudieras hacer una fase esta semana, haz la **Fase 1.1 + 1.2 + 1.4**:
toma 1 día bien hecho y convierte el CRM de "directorio muerto con 4 contactos"
a "vista unificada de los 6+ compradores reales + todos los leads que lleguen
de la web". Es el cambio que más valor entrega por menor esfuerzo.

Si tienes 2 semanas: completar Fases 1 + 2. Con pipeline y conexión a
cotizaciones, el CRM ya es realmente útil para cerrar ventas.

---

## 6. Checklist de implementación

Cuando autorices, iré marcando:

### Fase 1
- [ ] 1.1 Form público `/enviar-mensaje` → crea lead CRM
- [ ] 1.2 Pedido confirmado → crea/actualiza contacto cliente
- [ ] 1.3 FK `crm_contacto_id` en cotizaciones y cuentas_cobro + migración
- [ ] 1.4 Timeline unificado en la ficha del contacto

### Fase 2
- [ ] 2.1 Tabla `crm_oportunidades` + migración
- [ ] 2.2 Vista Kanban `/admin/crm/pipeline`
- [ ] 2.3 Auto-creación de oportunidad desde cotización + sync de estado

### Fase 3
- [ ] 3.1 Búsqueda global
- [ ] 3.2 Tags / etiquetas
- [ ] 3.3 Modal de llamada rápida
- [ ] 3.4 Acciones rápidas en lista (WhatsApp / mail / tel)

### Fase 4
- [ ] 4.1 Export CSV
- [ ] 4.2 Import CSV

### Fase 5
- [ ] 5.1 Email segmentado
- [ ] 5.2 Templates WhatsApp

### Fase 6
- [ ] Dashboard ampliado con embudo, tasa de cierre, ranking, estancadas

---

## 7. Riesgos y consideraciones

- **Migraciones**: agregar columnas a `cotizaciones`, `cuentas_cobro`, y crear `crm_oportunidades`. Hacer scripts `migrate_crm_fase1.sql` y `migrate_crm_fase2.sql` con `IF NOT EXISTS` para ser idempotentes.
- **Performance**: con índices ya propuestos (`idx_oport_etapa`, `idx_crm_tags`) queda cubierto hasta miles de filas.
- **Permisos**: el CRM hoy usa `ADMIN_STAFF`. Oportunidades con monto deberían ser solo Admin/Propietario; actividades y tareas pueden seguir abiertas a Staff.
- **Borrados**: ya hay `ON DELETE CASCADE` en actividades/tareas. Para oportunidades: `ON DELETE CASCADE` desde contacto. Para cotización vinculada: `ON DELETE SET NULL` para no perder la oportunidad si se borra la cotización.
