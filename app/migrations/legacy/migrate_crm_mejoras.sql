-- ─────────────────────────────────────────────────────────────────────
--  migrate_crm_mejoras.sql
--  Fase 1+2+3: conexión con el mundo real, pipeline y segmentación.
--  Idempotente: se puede correr múltiples veces sin romper nada.
-- ─────────────────────────────────────────────────────────────────────

-- ── F1.3 — FK a contacto CRM en documentos comerciales ────────────────
ALTER TABLE cotizaciones
    ADD COLUMN IF NOT EXISTS crm_contacto_id INTEGER
    REFERENCES crm_contactos(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_cotizaciones_crm_contacto
    ON cotizaciones(crm_contacto_id);

ALTER TABLE cuentas_cobro
    ADD COLUMN IF NOT EXISTS crm_contacto_id INTEGER
    REFERENCES crm_contactos(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_cuentas_cobro_crm_contacto
    ON cuentas_cobro(crm_contacto_id);

-- ── F2.1 — Tabla de oportunidades (pipeline) ──────────────────────────
CREATE TABLE IF NOT EXISTS crm_oportunidades (
    id                SERIAL PRIMARY KEY,
    contacto_id       INTEGER NOT NULL REFERENCES crm_contactos(id) ON DELETE CASCADE,
    titulo            VARCHAR(200) NOT NULL,
    descripcion       TEXT,
    monto_estimado    NUMERIC(14,2) DEFAULT 0,
    probabilidad      INTEGER DEFAULT 50 CHECK (probabilidad BETWEEN 0 AND 100),
    etapa             VARCHAR(30) NOT NULL DEFAULT 'prospecto'
                      CHECK (etapa IN ('prospecto','calificado','propuesta',
                                       'negociacion','ganada','perdida')),
    fuente            VARCHAR(60),
    cotizacion_id     INTEGER REFERENCES cotizaciones(id) ON DELETE SET NULL,
    asignado_a        INTEGER REFERENCES usuarios(id)    ON DELETE SET NULL,
    fecha_cierre_est  DATE,
    fecha_cierre_real DATE,
    motivo_perdida    VARCHAR(160),
    notas             TEXT,
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_oport_etapa     ON crm_oportunidades(etapa);
CREATE INDEX IF NOT EXISTS idx_oport_contacto  ON crm_oportunidades(contacto_id);
CREATE INDEX IF NOT EXISTS idx_oport_asignado  ON crm_oportunidades(asignado_a);
CREATE INDEX IF NOT EXISTS idx_oport_cotizacion ON crm_oportunidades(cotizacion_id);

-- ── F3.2 — Tags libres por contacto ───────────────────────────────────
ALTER TABLE crm_contactos
    ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_crm_contactos_tags
    ON crm_contactos USING GIN (tags);

-- ── Mejoras transversales ─────────────────────────────────────────────
ALTER TABLE crm_actividades
    ADD COLUMN IF NOT EXISTS asignado_a INTEGER REFERENCES usuarios(id) ON DELETE SET NULL;

ALTER TABLE crm_tareas
    ADD COLUMN IF NOT EXISTS snooze_hasta DATE NULL;

-- ── F1.3 backfill — vincular cotizaciones y cuentas_cobro por email ───
-- Solo asocia cuando la coincidencia es única para no mezclar historiales.
UPDATE cotizaciones c
   SET crm_contacto_id = sub.contacto_id
  FROM (
      SELECT cot.id AS cot_id, cc.id AS contacto_id
        FROM cotizaciones cot
        JOIN crm_contactos cc
          ON lower(cot.cliente_nombre) = lower(cc.nombre)
       WHERE cot.crm_contacto_id IS NULL
         AND cot.cliente_nombre IS NOT NULL
       GROUP BY cot.id, cc.id
      HAVING COUNT(*) = 1
  ) sub
 WHERE c.id = sub.cot_id;

UPDATE cuentas_cobro c
   SET crm_contacto_id = sub.contacto_id
  FROM (
      SELECT cc.id AS cc_id, cn.id AS contacto_id
        FROM cuentas_cobro cc
        JOIN crm_contactos cn
          ON lower(cc.cliente_nombre) = lower(cn.nombre)
       WHERE cc.crm_contacto_id IS NULL
         AND cc.cliente_nombre IS NOT NULL
       GROUP BY cc.id, cn.id
      HAVING COUNT(*) = 1
  ) sub
 WHERE c.id = sub.cc_id;
