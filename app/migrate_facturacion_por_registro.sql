-- =============================================================
-- MIGRACION: Facturacion electronica por venta o pedido
-- =============================================================

ALTER TABLE pedidos
    ADD COLUMN IF NOT EXISTS facturar_electronicamente BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE ventas_pos
    ADD COLUMN IF NOT EXISTS facturar_electronicamente BOOLEAN NOT NULL DEFAULT FALSE;
