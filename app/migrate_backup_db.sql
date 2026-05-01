-- ============================================================
-- Migracion: Backups de base de datos para super admin
-- ============================================================
-- Crea tablas para almacenar metadatos de backups y la clave
-- de acceso protegida (bcrypt) gestionada por el super admin.
-- Sistema independiente del modulo de compartir (no toca share_*).
-- ============================================================

CREATE TABLE IF NOT EXISTS backups_db (
    id                SERIAL PRIMARY KEY,
    nombre_archivo    VARCHAR(255) NOT NULL,
    nombre_descarga   VARCHAR(255) NOT NULL,
    tipo              VARCHAR(20) NOT NULL CHECK (tipo IN ('full', 'schema')),
    comprimido        BOOLEAN NOT NULL DEFAULT FALSE,
    tamano_bytes      BIGINT,
    creado_por        INTEGER REFERENCES usuarios(id),
    fecha_creacion    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_backups_db_fecha
    ON backups_db(fecha_creacion DESC);

CREATE TABLE IF NOT EXISTS backup_config (
    id                  INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    clave_hash          VARCHAR(255),
    actualizado_por     INTEGER REFERENCES usuarios(id),
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO backup_config (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;
