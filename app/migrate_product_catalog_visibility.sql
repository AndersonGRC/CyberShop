-- =============================================================
-- MIGRACION: Catalogo compartido entre ecommerce y tienda fisica
-- =============================================================

ALTER TABLE productos
    ADD COLUMN IF NOT EXISTS visible_en_ecommerce BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE productos
SET visible_en_ecommerce = TRUE
WHERE visible_en_ecommerce IS NULL;
