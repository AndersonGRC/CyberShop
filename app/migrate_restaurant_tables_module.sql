-- =============================================================
-- Restaurant Tables module
-- Ejecutar una vez por entorno antes de operar el modulo.
-- El switch visible para activar/desactivar queda en cliente_config.
-- =============================================================

BEGIN;

-- -------------------------------------------------------------
-- Tenancy / feature flags
-- -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS saas_tenants (
    id          SERIAL PRIMARY KEY,
    slug        VARCHAR(80)  NOT NULL UNIQUE,
    nombre      VARCHAR(180) NOT NULL,
    estado      VARCHAR(30)  NOT NULL DEFAULT 'activo',
    is_default  BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_modules (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(80)  NOT NULL UNIQUE,
    nombre      VARCHAR(140) NOT NULL,
    descripcion TEXT,
    categoria   VARCHAR(60)  NOT NULL DEFAULT 'general',
    is_core     BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_tenant_modules (
    tenant_id   INTEGER   NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    module_id   INTEGER   NOT NULL REFERENCES saas_modules(id) ON DELETE CASCADE,
    is_active   BOOLEAN   NOT NULL DEFAULT FALSE,
    settings    JSONB     NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, module_id)
);

INSERT INTO saas_tenants (slug, nombre, estado, is_default)
SELECT 'default', 'Tenant Principal', 'activo', TRUE
WHERE NOT EXISTS (SELECT 1 FROM saas_tenants WHERE slug = 'default');

UPDATE saas_tenants
SET is_default = CASE WHEN slug = 'default' THEN TRUE ELSE FALSE END
WHERE NOT EXISTS (
    SELECT 1
    FROM saas_tenants
    WHERE is_default = TRUE
);

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'orders',
    'Pedidos',
    'Gestion de pedidos web y seguimiento comercial.',
    'ventas',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'orders');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'pos',
    'Punto de Venta',
    'Ventas rapidas, historial POS y facturacion mostrador.',
    'ventas',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'pos');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'quotes',
    'Cotizaciones',
    'Creacion de cotizaciones PDF y seguimiento comercial.',
    'ventas',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'quotes');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'billing',
    'Cuentas de Cobro',
    'Documentos de cobro para contratistas y servicios.',
    'ventas',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'billing');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'coupons',
    'Cupones',
    'Promociones y descuentos por codigo.',
    'ventas',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'coupons');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'inventory',
    'Inventario',
    'Catalogo, stock, generos y resenas de productos.',
    'catalogo',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'inventory');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'wishlist',
    'Wishlist',
    'Favoritos de clientes y estadisticas de lista de deseos.',
    'catalogo',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'wishlist');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'content',
    'Contenido Web',
    'Publicaciones, slides y servicios del sitio.',
    'contenido',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'content');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'users',
    'Usuarios',
    'Gestion y creacion de usuarios administrativos.',
    'administracion',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'users');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'payroll',
    'Nomina',
    'Empleados, periodos, novedades y liquidaciones.',
    'administracion',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'payroll');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'crm',
    'CRM',
    'Contactos, tareas y actividades comerciales.',
    'clientes',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'crm');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'accounting',
    'Contabilidad',
    'Movimientos, plantillas y cierres contables.',
    'finanzas',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'accounting');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'support',
    'Soporte',
    'Tickets de clientes y configuracion del canal de soporte.',
    'clientes',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'support');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'video',
    'Videollamadas',
    'Salas de videollamadas e invitaciones con Jitsi.',
    'clientes',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'video');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'restaurant_tables',
    'Mesas Restaurante',
    'Plano visual de mesas, cuenta abierta y consumos por mesa.',
    'operacion',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'restaurant_tables');

INSERT INTO saas_modules (code, nombre, descripcion, categoria, is_core)
SELECT
    'facturacion_electronica',
    'Facturacion DIAN',
    'Facturacion electronica integrada con el microservicio DIAN.',
    'finanzas',
    FALSE
WHERE NOT EXISTS (SELECT 1 FROM saas_modules WHERE code = 'facturacion_electronica');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'restaurant_tables_habilitado', 'true', 'boolean', 'modulos', 'Módulo de mesas de restaurante', 150
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'restaurant_tables_habilitado');

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES saas_tenants(id);

ALTER TABLE productos
    ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES saas_tenants(id);

UPDATE usuarios
SET tenant_id = (
    SELECT id FROM saas_tenants WHERE is_default = TRUE ORDER BY id LIMIT 1
)
WHERE tenant_id IS NULL;

UPDATE productos
SET tenant_id = (
    SELECT id FROM saas_tenants WHERE is_default = TRUE ORDER BY id LIMIT 1
)
WHERE tenant_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_usuarios_tenant_id
    ON usuarios (tenant_id);

CREATE INDEX IF NOT EXISTS idx_productos_tenant_id
    ON productos (tenant_id);

INSERT INTO saas_tenant_modules (tenant_id, module_id, is_active)
SELECT t.id, m.id, FALSE
FROM saas_tenants t
CROSS JOIN saas_modules m
WHERE m.code IN (
    'orders',
    'pos',
    'quotes',
    'billing',
    'coupons',
    'inventory',
    'wishlist',
    'content',
    'users',
    'payroll',
    'crm',
    'accounting',
    'support',
    'video',
    'restaurant_tables',
    'facturacion_electronica'
)
  AND NOT EXISTS (
      SELECT 1
      FROM saas_tenant_modules tm
      WHERE tm.tenant_id = t.id
        AND tm.module_id = m.id
  );

UPDATE saas_tenant_modules tm
SET is_active = TRUE,
    updated_at = NOW()
FROM saas_tenants t
JOIN saas_modules m
  ON m.code IN (
      'orders',
      'pos',
      'quotes',
      'billing',
      'coupons',
      'inventory',
      'wishlist',
      'content',
      'users',
      'payroll',
      'crm',
      'accounting',
      'support',
      'video',
      'restaurant_tables'
  )
WHERE tm.tenant_id = t.id
  AND tm.module_id = m.id
  AND t.is_default = TRUE
  AND tm.created_at = tm.updated_at;

-- -------------------------------------------------------------
-- Restaurant Tables module
-- -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS restaurant_tables (
    id          SERIAL PRIMARY KEY,
    tenant_id   INTEGER      NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    codigo      VARCHAR(30)  NOT NULL,
    nombre      VARCHAR(120) NOT NULL,
    area        VARCHAR(100) NOT NULL DEFAULT 'Salon principal',
    capacidad   INTEGER      NOT NULL DEFAULT 4,
    forma       VARCHAR(20)  NOT NULL DEFAULT 'square',
    estado      VARCHAR(30)  NOT NULL DEFAULT 'disponible',
    pos_x       NUMERIC(5,2) NOT NULL DEFAULT 8,
    pos_y       NUMERIC(5,2) NOT NULL DEFAULT 10,
    ancho       NUMERIC(5,2) NOT NULL DEFAULT 16,
    alto        NUMERIC(5,2) NOT NULL DEFAULT 16,
    rotacion    SMALLINT     NOT NULL DEFAULT 0,
    meta        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    creado_por  INTEGER REFERENCES usuarios(id),
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_restaurant_tables_codigo UNIQUE (tenant_id, codigo),
    CONSTRAINT chk_restaurant_tables_forma CHECK (forma IN ('round', 'square', 'rectangle')),
    CONSTRAINT chk_restaurant_tables_estado CHECK (estado IN ('disponible', 'ocupada', 'reservada', 'cuenta_solicitada'))
);

CREATE TABLE IF NOT EXISTS restaurant_table_orders (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER      NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    table_id        INTEGER      NOT NULL REFERENCES restaurant_tables(id) ON DELETE CASCADE,
    estado          VARCHAR(20)  NOT NULL DEFAULT 'abierta',
    cliente_nombre  VARCHAR(150),
    comensales      INTEGER      NOT NULL DEFAULT 1,
    notas           TEXT,
    abierta_por     INTEGER REFERENCES usuarios(id),
    cerrada_por     INTEGER REFERENCES usuarios(id),
    total_acumulado NUMERIC(12,2) NOT NULL DEFAULT 0,
    pos_sale_id     INTEGER,
    payment_method  VARCHAR(30)  NOT NULL DEFAULT 'EFECTIVO',
    accounting_status VARCHAR(30) NOT NULL DEFAULT 'pendiente',
    accounting_income_movement_id INTEGER,
    accounting_reversal_movement_id INTEGER,
    accounting_synced_at TIMESTAMP,
    cancel_reason   TEXT,
    cancelled_at    TIMESTAMP,
    cancelled_by    INTEGER REFERENCES usuarios(id),
    opened_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMP   NOT NULL DEFAULT NOW(),
    closed_at       TIMESTAMP,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_restaurant_table_orders_estado CHECK (estado IN ('abierta', 'cerrada', 'cancelada'))
);

ALTER TABLE restaurant_table_orders
    ADD COLUMN IF NOT EXISTS payment_method VARCHAR(30) NOT NULL DEFAULT 'EFECTIVO';

ALTER TABLE restaurant_table_orders
    ADD COLUMN IF NOT EXISTS accounting_status VARCHAR(30) NOT NULL DEFAULT 'pendiente';

ALTER TABLE restaurant_table_orders
    ADD COLUMN IF NOT EXISTS accounting_income_movement_id INTEGER;

ALTER TABLE restaurant_table_orders
    ADD COLUMN IF NOT EXISTS accounting_reversal_movement_id INTEGER;

ALTER TABLE restaurant_table_orders
    ADD COLUMN IF NOT EXISTS accounting_synced_at TIMESTAMP;

ALTER TABLE restaurant_table_orders
    ADD COLUMN IF NOT EXISTS cancel_reason TEXT;

ALTER TABLE restaurant_table_orders
    ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP;

ALTER TABLE restaurant_table_orders
    ADD COLUMN IF NOT EXISTS cancelled_by INTEGER REFERENCES usuarios(id);

CREATE TABLE IF NOT EXISTS restaurant_table_consumptions (
    id             SERIAL PRIMARY KEY,
    tenant_id      INTEGER       NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    order_id       INTEGER       NOT NULL REFERENCES restaurant_table_orders(id) ON DELETE CASCADE,
    table_id       INTEGER       NOT NULL REFERENCES restaurant_tables(id) ON DELETE CASCADE,
    producto_id    INTEGER REFERENCES productos(id) ON DELETE SET NULL,
    descripcion    VARCHAR(220)  NOT NULL,
    cantidad       INTEGER       NOT NULL DEFAULT 1,
    precio_unitario NUMERIC(12,2) NOT NULL DEFAULT 0,
    subtotal       NUMERIC(12,2) NOT NULL DEFAULT 0,
    estado         VARCHAR(20)   NOT NULL DEFAULT 'pendiente',
    notas          TEXT,
    creado_por     INTEGER REFERENCES usuarios(id),
    ordered_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    served_at      TIMESTAMP,
    updated_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_restaurant_table_consumptions_estado CHECK (estado IN ('pendiente', 'preparando', 'servido'))
);

CREATE INDEX IF NOT EXISTS idx_restaurant_tables_tenant_area
    ON restaurant_tables (tenant_id, area, nombre);

CREATE INDEX IF NOT EXISTS idx_restaurant_orders_tenant_table
    ON restaurant_table_orders (tenant_id, table_id, estado);

CREATE UNIQUE INDEX IF NOT EXISTS uq_restaurant_open_order
    ON restaurant_table_orders (tenant_id, table_id)
    WHERE estado = 'abierta';

CREATE INDEX IF NOT EXISTS idx_restaurant_consumptions_order
    ON restaurant_table_consumptions (order_id, estado, ordered_at);

CREATE INDEX IF NOT EXISTS idx_restaurant_consumptions_tenant_table
    ON restaurant_table_consumptions (tenant_id, table_id, estado);

COMMIT;
