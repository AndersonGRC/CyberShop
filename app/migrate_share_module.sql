-- migrate_share_module.sql
-- Tablas del módulo "Compartir Archivos" (share):
--   share_carpetas  → árbol de carpetas (raíz con token y clave opcional, hijas heredan token vía parent_id)
--   share_archivos  → archivos asociados a una carpeta
--   share_accesos   → registro de view/download/upload contra la carpeta raíz

CREATE TABLE IF NOT EXISTS share_carpetas (
    id                   SERIAL PRIMARY KEY,
    parent_id            INTEGER REFERENCES share_carpetas(id) ON DELETE CASCADE,
    nombre               VARCHAR(200) NOT NULL,
    descripcion          TEXT,
    token                VARCHAR(64) UNIQUE,
    clave_hash           VARCHAR(255),
    permitir_subida      BOOLEAN DEFAULT FALSE,
    fecha_vence          TIMESTAMP,
    creado_por           INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    fecha_creacion       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_share_carpetas_parent ON share_carpetas(parent_id);
CREATE INDEX IF NOT EXISTS idx_share_carpetas_token  ON share_carpetas(token);

CREATE TABLE IF NOT EXISTS share_archivos (
    id                  SERIAL PRIMARY KEY,
    carpeta_id          INTEGER NOT NULL REFERENCES share_carpetas(id) ON DELETE CASCADE,
    nombre_original     VARCHAR(255) NOT NULL,
    nombre_almacenado   VARCHAR(255) NOT NULL,
    tamano_bytes        BIGINT,
    mime_type           VARCHAR(120),
    subido_por_admin    INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    subido_por_cliente  VARCHAR(120),
    fecha_subida        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_share_archivos_carpeta ON share_archivos(carpeta_id);

CREATE TABLE IF NOT EXISTS share_accesos (
    id              SERIAL PRIMARY KEY,
    carpeta_raiz_id INTEGER REFERENCES share_carpetas(id) ON DELETE CASCADE,
    archivo_id      INTEGER REFERENCES share_archivos(id) ON DELETE SET NULL,
    accion          VARCHAR(20),
    ip              VARCHAR(45),
    user_agent      TEXT,
    fecha           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_share_accesos_raiz ON share_accesos(carpeta_raiz_id);
