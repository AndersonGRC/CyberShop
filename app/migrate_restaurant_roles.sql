-- =============================================================
-- Migración: Roles operativos del módulo Restaurante
-- =============================================================
-- Mesero (6): toma pedidos en mesas, no puede cobrar ni cancelar
-- Cajero (7): puede cobrar mesas, anular consumos y cerrar cuentas
-- =============================================================

INSERT INTO roles (id, nombre) VALUES (6, 'Mesero')
    ON CONFLICT (id) DO UPDATE SET nombre = EXCLUDED.nombre;

INSERT INTO roles (id, nombre) VALUES (7, 'Cajero')
    ON CONFLICT (id) DO UPDATE SET nombre = EXCLUDED.nombre;

-- Reajustar el secuencial para evitar colisiones de PK al crear futuros roles
SELECT setval('roles_id_seq', GREATEST((SELECT MAX(id) FROM roles), 7));
