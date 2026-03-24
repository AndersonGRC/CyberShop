-- migrate_pdf_fields.sql — Añade campos extendidos a cotizaciones y detalle_cotizacion.
--
-- Ejecutar UNA SOLA VEZ al desplegar la versión con cotizaciones extendidas:
--   psql -U usuario -d basededatos -f migrate_pdf_fields.sql
--
-- MIGRACIÓN A OTRO CLIENTE: no requiere cambios, las columnas son neutrales.

ALTER TABLE cotizaciones
    ADD COLUMN IF NOT EXISTS cliente_direccion    TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS cliente_ciudad       TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS cliente_telefono     TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS cliente_representante TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS cliente_cargo        TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS cliente_localidad    TEXT DEFAULT '';

ALTER TABLE detalle_cotizacion
    ADD COLUMN IF NOT EXISTS descuento_porc NUMERIC DEFAULT 0,
    ADD COLUMN IF NOT EXISTS iva_porc       NUMERIC DEFAULT 0;
