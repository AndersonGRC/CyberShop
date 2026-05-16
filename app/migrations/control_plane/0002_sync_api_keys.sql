-- ============================================================
-- Control plane — Migración 0002
-- Tabla: sync_api_keys
--
-- Asocia API keys (X-Sync-Key) con tenants para que el endpoint
-- /api/v1/sync/* resuelva la BD destino desde la key, en vez de
-- usar la SYNC_API_KEY global de env (legacy single-tenant).
--
-- Cada cliente recibe:
--   - api_key: token largo (cyb_live_...) que va en X-Sync-Key
--   - client_code: token corto memorable (CYB-A3F2K9P1) que el
--                  cliente teclea en /descargar para bajar su
--                  instalador personalizado.
-- ============================================================

CREATE TABLE IF NOT EXISTS sync_api_keys (
    id           BIGSERIAL   PRIMARY KEY,
    tenant_id    INT         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash     TEXT        NOT NULL UNIQUE,   -- SHA-256(api_key)
    key_prefix   TEXT        NOT NULL,          -- primeros 12 chars del api_key, en claro, para UI
    client_code  TEXT        NOT NULL UNIQUE,   -- código corto que el cliente pega en /descargar
    label        TEXT,                          -- "POS Tienda Centro"
    active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_sync_api_keys_client_code
    ON sync_api_keys(client_code) WHERE active;

CREATE INDEX IF NOT EXISTS idx_sync_api_keys_tenant
    ON sync_api_keys(tenant_id);

COMMENT ON TABLE sync_api_keys IS
    'API keys para autenticar el desktop POS contra /api/v1/sync/*. Cada key resuelve a un tenant.';

COMMENT ON COLUMN sync_api_keys.key_hash IS
    'SHA-256 hex del api_key. El raw nunca se persiste; se entrega al cliente una sola vez al crear la key.';

COMMENT ON COLUMN sync_api_keys.client_code IS
    'Código corto y memorable (8-12 chars) que el cliente teclea en el portal público /descargar para obtener su instalador. Distinto del api_key real para evitar exponer el secreto en URLs públicas.';
