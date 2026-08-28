-- ─────────────────────────────────────────────────────────────────────
--  migrate_crm_v2.sql
--  CRM v2: línea de negocio en oportunidades + vínculo tickets↔CRM.
--  100% aditivo e idempotente (IF NOT EXISTS). El código además se
--  auto-sana en runtime vía _ensure_crm_v2_schema() en routes/crm.py.
-- ─────────────────────────────────────────────────────────────────────

-- Línea de negocio de la oportunidad (POS / Software / Hardware / Servicio…)
ALTER TABLE crm_oportunidades
    ADD COLUMN IF NOT EXISTS linea_negocio VARCHAR(40);
CREATE INDEX IF NOT EXISTS idx_oport_linea ON crm_oportunidades(linea_negocio);

-- Vínculo de tickets de soporte con el contacto CRM
ALTER TABLE tickets_soporte
    ADD COLUMN IF NOT EXISTS crm_contacto_id INTEGER
    REFERENCES crm_contactos(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_tickets_crm_contacto
    ON tickets_soporte(crm_contacto_id);

-- Backfill: asocia ticket → contacto por el email del usuario dueño del ticket,
-- solo cuando la coincidencia es única (no mezcla historiales).
UPDATE tickets_soporte t
   SET crm_contacto_id = sub.contacto_id
  FROM (
      SELECT ts.id AS ticket_id, cc.id AS contacto_id
        FROM tickets_soporte ts
        JOIN usuarios u       ON ts.usuario_id = u.id
        JOIN crm_contactos cc ON lower(cc.email) = lower(u.email)
       WHERE ts.crm_contacto_id IS NULL
         AND u.email IS NOT NULL
       GROUP BY ts.id, cc.id
      HAVING COUNT(*) = 1
  ) sub
 WHERE t.id = sub.ticket_id;
