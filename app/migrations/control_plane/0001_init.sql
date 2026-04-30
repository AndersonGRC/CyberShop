-- ============================================================
-- Control plane — Schema inicial (Fase 1)
-- DB: saas_control_plane
--
-- Tablas incluidas en Fase 1:
--   tenants, tenant_databases, usuarios_globales, refresh_tokens
--
-- Tablas que llegan en Fases posteriores:
--   licencias, feature_flags_globales, sync_health, event_log
-- ============================================================

-- Extensiones
CREATE EXTENSION IF NOT EXISTS citext;      -- emails case-insensitive
CREATE EXTENSION IF NOT EXISTS pgcrypto;    -- gen_random_uuid(), crypt()

-- ────────────────────────────────────────────────────────────
-- Tenants
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id          SERIAL PRIMARY KEY,
    slug        TEXT        UNIQUE NOT NULL,
    nombre      TEXT        NOT NULL,
    estado      TEXT        NOT NULL DEFAULT 'activo'
                CHECK (estado IN ('activo', 'suspendido', 'cancelado')),
    plan        TEXT        NOT NULL DEFAULT 'standard',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE tenants IS 'Un registro por cliente de CyberShop.';

-- ────────────────────────────────────────────────────────────
-- Tenant databases  (1 DB Postgres por tenant)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenant_databases (
    tenant_id        INT         PRIMARY KEY REFERENCES tenants(id),
    db_host          TEXT        NOT NULL DEFAULT 'localhost',
    db_port          INT         NOT NULL DEFAULT 5432,
    db_name          TEXT        UNIQUE NOT NULL,
    db_user          TEXT        NOT NULL,
    db_password_enc  TEXT        NOT NULL,   -- AES-GCM cifrado con KMS_KEY
    schema_version   TEXT        NOT NULL DEFAULT '0001',
    last_migrated_at TIMESTAMPTZ NULL
);

COMMENT ON COLUMN tenant_databases.db_password_enc
    IS 'Contraseña de BD cifrada con AES-256-GCM (services/crypto_utils.py::aes_gcm_encrypt).';

-- ────────────────────────────────────────────────────────────
-- Usuarios globales  (mirror del campo email + rol de la tabla
-- usuarios de cada tenant, para autenticación API centralizada)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS usuarios_globales (
    id            SERIAL      PRIMARY KEY,
    email         CITEXT      UNIQUE NOT NULL,
    contraseña    TEXT        NOT NULL,      -- werkzeug pbkdf2:sha256 (mismo formato que usuarios.contraseña)
    tenant_id     INT         NOT NULL REFERENCES tenants(id),
    rol_id        INT         NOT NULL,
    estado        TEXT        NOT NULL DEFAULT 'habilitado'
                  CHECK (estado IN ('habilitado', 'suspendido')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_usuarios_globales_tenant
    ON usuarios_globales(tenant_id);

COMMENT ON TABLE usuarios_globales IS
    'Usuarios para autenticación de la API REST. Sincronizados desde usuarios de cada tenant.
     Las rutas HTML legacy siguen autenticando contra la tabla usuarios de la DB del tenant.';

-- ────────────────────────────────────────────────────────────
-- Refresh tokens
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash    TEXT        PRIMARY KEY,   -- SHA-256 del token raw
    user_id       INT         NOT NULL REFERENCES usuarios_globales(id),
    device_id     TEXT        NOT NULL,      -- UUID generado por el cliente
    device_name   TEXT,
    issued_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMPTZ NOT NULL,
    revoked_at    TIMESTAMPTZ NULL,
    last_used_at  TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_active
    ON refresh_tokens(user_id)
    WHERE revoked_at IS NULL;

COMMENT ON TABLE refresh_tokens IS
    'Tokens de refresco opacos. Se almacena solo el hash SHA-256; el valor raw nunca persiste.';
