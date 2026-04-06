 table_name     |      column_name       |          data_type          | is_nullable |                 column_default

--------------------+------------------------+-----------------------------+-------------+------------------------------------------------

 cotizaciones       | id                     | integer                     | NO          | nextval('cotizaciones_id_seq'::regclass)

 cotizaciones       | fecha                  | timestamp without time zone | YES         | CURRENT_TIMESTAMP

 cotizaciones       | cliente_nombre         | text                        | NO          |

 cotizaciones       | cliente_documento      | text                        | YES         |

 cotizaciones       | logo_url               | text                        | YES         |

 cotizaciones       | total                  | numeric                     | YES         | 0

 cotizaciones       | pdf_path               | text                        | YES         |

 detalle_cotizacion | id                     | integer                     | NO          | nextval('detalle_cotizacion_id_seq'::regclass)

 detalle_cotizacion | cotizacion_id          | integer                     | YES         |

 detalle_cotizacion | descripcion            | text                        | NO          |

 detalle_cotizacion | cantidad               | integer                     | NO          |

 detalle_cotizacion | precio_unitario        | numeric                     | NO          |

 detalle_cotizacion | subtotal               | numeric                     | NO          |

 detalle_cotizacion | imagen_url             | text                        | YES         |

 detalle_pedidos    | id                     | integer                     | NO          | nextval('detalle_pedidos_id_seq'::regclass)

 detalle_pedidos    | pedido_id              | integer                     | YES         |

 detalle_pedidos    | producto_nombre        | character varying           | YES         |

 detalle_pedidos    | cantidad               | integer                     | YES         |

 detalle_pedidos    | precio_unitario        | numeric                     | YES         |

 detalle_pedidos    | subtotal               | numeric                     | YES         |

 generos            | id                     | integer                     | NO          | nextval('generos_id_seq'::regclass)

 generos            | nombre                 | character varying           | NO          |

 inventario_log     | id                     | integer                     | NO          | nextval('inventario_log_id_seq'::regclass)

 inventario_log     | producto_id            | integer                     | YES         |

 inventario_log     | tipo                   | character varying           | YES         |

 inventario_log     | cantidad               | integer                     | YES         |

 inventario_log     | stock_anterior         | integer                     | YES         |

 inventario_log     | stock_nuevo            | integer                     | YES         |

 inventario_log     | motivo                 | text                        | YES         |

 inventario_log     | usuario_id             | integer                     | YES         |

 inventario_log     | fecha                  | timestamp without time zone | YES         | CURRENT_TIMESTAMP

 pedidos            | id                     | integer                     | NO          | nextval('pedidos_id_seq'::regclass)

 pedidos            | referencia_pedido      | character varying           | NO          |

 pedidos            | cliente_nombre         | character varying           | YES         |

 pedidos            | cliente_email          | character varying           | YES         |

 pedidos            | cliente_tipo_documento | character varying           | YES         |

 pedidos            | cliente_documento      | character varying           | YES         |

 pedidos            | cliente_telefono       | character varying           | YES         |

 pedidos            | direccion_envio        | text                        | YES         |

 pedidos            | ciudad                 | character varying           | YES         |

 pedidos            | estado_pago            | character varying           | YES         | 'PENDIENTE'::character varying

 pedidos            | estado_envio           | character varying           | YES         | 'POR_DESPACHAR'::character varying

 pedidos            | monto_total            | numeric                     | YES         |

 pedidos            | id_transaccion_payu    | character varying           | YES         |

 pedidos            | metodo_pago            | character varying           | YES         |

 pedidos            | fecha_creacion         | timestamp without time zone | YES         | CURRENT_TIMESTAMP

 pedidos            | fecha_actualizacion    | timestamp without time zone | YES         | CURRENT_TIMESTAMP

 productos          | id                     | integer                     | NO          | nextval('productos_id_seq'::regclass)

 productos          | imagen                 | character varying           | NO          |

 productos          | nombre                 | character varying           | NO          |

 productos          | precio                 | numeric                     | NO          |

 productos          | referencia             | character varying           | NO          |

 productos          | genero_id              | integer                     | NO          |

 productos          | descripcion            | text                        | YES         |

 productos          | stock                  | integer                     | YES         | 0

 roles              | id                     | integer                     | NO          | nextval('roles_id_seq'::regclass)

 roles              | nombre                 | character varying           | NO          |

 usuarios           | id                     | integer                     | NO          | nextval('usuarios_id_seq'::regclass)

 usuarios           | nombre                 | character varying           | NO          |

 usuarios           | email                  | character varying           | NO          |

 usuarios           | contrase±a             | character varying           | NO          |

 usuarios           | rol_id                 | integer                     | NO          |

 usuarios           | fecha_nacimiento       | date                        | YES         |

 usuarios           | telefono               | character varying           | YES         |

 usuarios           | direccion              | character varying           | YES         |

 usuarios           | fotografia             | character varying           | YES         |

 usuarios           | estado                 | character varying           | YES         | 'habilitado'::character varying

 usuarios           | fecha_registro         | timestamp without time zone | YES         | CURRENT_TIMESTAMP

 usuarios           | ultima_conexion        | timestamp without time zone | YES         |

 usuarios           | fecha_modificacion     | timestamp without time zone | YES         | CURRENT_TIMESTAMP

-- =============================================================
-- MIGRACIÓN: Google Calendar (ejecutar manualmente en psql)
-- =============================================================

-- Tokens OAuth por usuario
CREATE TABLE IF NOT EXISTS google_oauth_tokens (
    id            SERIAL PRIMARY KEY,
    usuario_id    INTEGER REFERENCES usuarios(id) ON DELETE CASCADE UNIQUE,
    access_token  TEXT,
    refresh_token TEXT NOT NULL,
    token_expiry  TIMESTAMP,
    scope         TEXT,
    updated_at    TIMESTAMP DEFAULT NOW()
);

-- Tracking de webhooks bidireccionales
CREATE TABLE IF NOT EXISTS google_calendar_watches (
    id          SERIAL PRIMARY KEY,
    usuario_id  INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    channel_id  TEXT NOT NULL,
    resource_id TEXT,
    expiry      TIMESTAMP,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- IDs de evento en Google y lista de invitados
ALTER TABLE crm_tareas      ADD COLUMN IF NOT EXISTS google_event_id       TEXT;
ALTER TABLE crm_tareas      ADD COLUMN IF NOT EXISTS invitados_emails      TEXT;
ALTER TABLE crm_tareas      ADD COLUMN IF NOT EXISTS recordatorio_diario   BOOLEAN DEFAULT FALSE;

-- =============================================================
-- MIGRACIÓN: Login con Google OAuth 2.0
-- =============================================================

ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS google_sub TEXT UNIQUE;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS foto_google TEXT;
ALTER TABLE usuarios ALTER COLUMN fecha_nacimiento DROP NOT NULL;

-- =============================================================
-- MIGRACIÓN: Panel de Configuración del Cliente
-- =============================================================

CREATE TABLE IF NOT EXISTS cliente_config (
    clave       VARCHAR PRIMARY KEY,
    valor       TEXT,
    tipo        VARCHAR DEFAULT 'text',
    grupo       VARCHAR DEFAULT 'general',
    descripcion TEXT,
    orden       INTEGER DEFAULT 0
);

-- =============================================================
-- MIGRACIÓN: Nuevos roles del sistema
-- =============================================================

-- Renombrar el rol existente 1 a Super Admin
UPDATE roles SET nombre = 'Super Admin' WHERE id = 1;

-- Renombrar el rol existente 2 (Staff) a Propietario
UPDATE roles SET nombre = 'Propietario' WHERE id = 2;

-- El rol 3 (Cliente) se mantiene igual

-- Agregar roles nuevos si no existen
INSERT INTO roles (id, nombre) VALUES (4, 'Empleado')
    ON CONFLICT (id) DO UPDATE SET nombre = EXCLUDED.nombre;

INSERT INTO roles (id, nombre) VALUES (5, 'Contador')
    ON CONFLICT (id) DO UPDATE SET nombre = EXCLUDED.nombre;

-- =============================================================
-- MIGRACIÓN: Estado de cotizaciones y vinculación con contabilidad
-- =============================================================

ALTER TABLE cotizaciones ADD COLUMN IF NOT EXISTS estado VARCHAR(20) DEFAULT 'pendiente';
-- estado: 'pendiente' | 'aprobada' | 'rechazada'

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden) VALUES
('empresa_nombre',        'CyberShop',                          'text',  'empresa',  'Nombre de la empresa',              1),
('empresa_email',         'cybershop.digitalsales@gmail.com',   'email', 'empresa',  'Email de contacto',                 2),
('empresa_telefono',      '3015963776',                         'tel',   'empresa',  'Teléfono de contacto',              3),
('empresa_direccion',     '',                                   'text',  'empresa',  'Dirección física',                  4),
('color_primario',        '#122C94',                            'color', 'colores',  'Color principal',                   1),
('color_primario_oscuro', '#091C5A',                            'color', 'colores',  'Color primario oscuro',             2),
('color_secundario',      '#0e1b33',                            'color', 'colores',  'Color secundario (navbar/footer)',  3),
('color_acento',          '#e60023',                            'color', 'colores',  'Color de acento',                   4),
('color_hover_menu',      '#fb8500',                            'color', 'colores',  'Color hover menú admin',            5)
ON CONFLICT (clave) DO NOTHING;
ALTER TABLE crm_actividades ADD COLUMN IF NOT EXISTS google_event_id   TEXT;
ALTER TABLE crm_actividades ADD COLUMN IF NOT EXISTS invitados_emails   TEXT;
-- =============================================================
-- MIGRACIÓN: Calificaciones y comentarios de productos
-- =============================================================

CREATE TABLE IF NOT EXISTS producto_comentarios (
    id             SERIAL PRIMARY KEY,
    producto_id    INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    usuario_id     INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    autor_nombre   VARCHAR(100) NOT NULL,
    calificacion   SMALLINT NOT NULL CHECK (calificacion BETWEEN 1 AND 5),
    comentario     TEXT NOT NULL,
    aprobado       BOOLEAN DEFAULT FALSE,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pc_producto_aprobado
    ON producto_comentarios (producto_id, aprobado);

-- =============================================================
-- ÍNDICES DE RENDIMIENTO (consultas frecuentes)
-- =============================================================
CREATE INDEX IF NOT EXISTS idx_usuarios_email
    ON usuarios (email);

CREATE INDEX IF NOT EXISTS idx_config_secciones_clave
    ON config_secciones (clave);

CREATE INDEX IF NOT EXISTS idx_cliente_config_clave
    ON cliente_config (clave);

CREATE INDEX IF NOT EXISTS idx_pc_usuario
    ON producto_comentarios (usuario_id);

CREATE INDEX IF NOT EXISTS idx_detalle_cotizacion_cot_id
    ON detalle_cotizacion (cotizacion_id);

CREATE INDEX IF NOT EXISTS idx_detalle_pedidos_pedido_id
    ON detalle_pedidos (pedido_id);

-- =============================================================
-- MIGRACIÓN: Facturación Electrónica DIAN
-- =============================================================

ALTER TABLE pedidos    ADD COLUMN IF NOT EXISTS factura_dian_id UUID;
ALTER TABLE ventas_pos ADD COLUMN IF NOT EXISTS factura_dian_id UUID;

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'facturacion_electronica', 'false', 'boolean', 'modulos', 'Módulo de Facturación Electrónica DIAN', 10
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'facturacion_electronica');

-- =============================================================
-- MIGRACIÓN: Notas de Crédito POS
-- =============================================================

CREATE TABLE IF NOT EXISTS notas_credito_pos (
    id              SERIAL PRIMARY KEY,
    numero_nota     VARCHAR(30) NOT NULL UNIQUE,
    venta_id        INTEGER NOT NULL REFERENCES ventas_pos(id),
    motivo          TEXT NOT NULL,
    total           NUMERIC NOT NULL,
    usuario_id      INTEGER REFERENCES usuarios(id),
    fecha           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_nc_pos_venta_id ON notas_credito_pos(venta_id);

ALTER TABLE ventas_pos ADD COLUMN IF NOT EXISTS estado VARCHAR(20) DEFAULT 'activa';
ALTER TABLE ventas_pos ADD COLUMN IF NOT EXISTS nota_credito_id INTEGER;

-- =============================================================
-- MIGRACIÓN: Módulo de Videollamadas
-- =============================================================

CREATE TABLE IF NOT EXISTS salas_video (
    id                SERIAL PRIMARY KEY,
    codigo_sala       VARCHAR(64)  NOT NULL UNIQUE,
    nombre            VARCHAR(200) NOT NULL,
    descripcion       TEXT,
    creado_por        INTEGER,
    estado            VARCHAR(20)  NOT NULL DEFAULT 'programada',
    fecha_inicio      TIMESTAMP,
    fecha_fin         TIMESTAMP,
    duracion_real     INTEGER,
    max_participantes INTEGER      DEFAULT 10,
    password_sala     VARCHAR(100),
    ticket_id         INTEGER,
    contacto_crm_id   INTEGER,
    created_at        TIMESTAMP    DEFAULT NOW(),
    updated_at        TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sala_video_participantes (
    id            SERIAL PRIMARY KEY,
    sala_id       INTEGER      NOT NULL REFERENCES salas_video(id) ON DELETE CASCADE,
    usuario_id    INTEGER,
    email         VARCHAR(200),
    nombre        VARCHAR(200),
    token_acceso  VARCHAR(128) NOT NULL UNIQUE,
    rol_sala      VARCHAR(20)  DEFAULT 'participante',
    invitado      BOOLEAN      DEFAULT FALSE,
    email_enviado BOOLEAN      DEFAULT FALSE,
    se_unio       BOOLEAN      DEFAULT FALSE,
    fecha_union   TIMESTAMP,
    created_at    TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_salas_video_codigo     ON salas_video (codigo_sala);
CREATE INDEX IF NOT EXISTS idx_salas_video_estado      ON salas_video (estado);
CREATE INDEX IF NOT EXISTS idx_salas_video_creado_por  ON salas_video (creado_por);
CREATE INDEX IF NOT EXISTS idx_sala_part_token         ON sala_video_participantes (token_acceso);
CREATE INDEX IF NOT EXISTS idx_sala_part_sala          ON sala_video_participantes (sala_id);

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'video_habilitado', 'true', 'boolean', 'modulos', 'Módulo de videollamadas', 15
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'video_habilitado');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'video_jitsi_domain', 'meet.jit.si', 'text', 'video', 'Dominio del servidor Jitsi', 1
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'video_jitsi_domain');

INSERT INTO cliente_config (clave, valor, tipo, grupo, descripcion, orden)
SELECT 'video_max_participantes', '10', 'number', 'video', 'Máximo de participantes por sala', 2
WHERE NOT EXISTS (SELECT 1 FROM cliente_config WHERE clave = 'video_max_participantes');
