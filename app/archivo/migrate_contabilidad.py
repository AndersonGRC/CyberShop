"""
migrate_contabilidad.py — Crea las tablas del módulo de Contabilidad.

Ejecutar UNA SOLA VEZ al desplegar este módulo en un cliente nuevo:
    python migrate_contabilidad.py

Tablas creadas:
  - contabilidad_movimientos : registro de ingresos y egresos
  - contabilidad_cierres     : resúmenes de cierre de período

MIGRACIÓN A OTRO CLIENTE: ajustar solo la ruta de .cybershop.conf si
el archivo de configuración tiene un nombre diferente.
"""
import os, sys
sys.path.insert(0, '/var/www/CyberShop/app')
os.chdir('/var/www/CyberShop/app')
from dotenv import load_dotenv
load_dotenv('.cybershop.conf')
from database import get_db_cursor

sql = """
CREATE TABLE IF NOT EXISTS contabilidad_movimientos (
    id              SERIAL PRIMARY KEY,
    tipo            VARCHAR(10) NOT NULL CHECK (tipo IN ('ingreso','egreso')),
    categoria       VARCHAR(60) NOT NULL DEFAULT 'otro',
    descripcion     TEXT NOT NULL,
    monto           NUMERIC(14,2) NOT NULL CHECK (monto >= 0),
    fecha           DATE NOT NULL DEFAULT CURRENT_DATE,
    referencia_tipo VARCHAR(30),
    referencia_id   INTEGER,
    notas           TEXT,
    usuario_id      INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    auto_generado   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contabilidad_cierres (
    id               SERIAL PRIMARY KEY,
    nombre           VARCHAR(120) NOT NULL,
    fecha_inicio     DATE NOT NULL,
    fecha_fin        DATE NOT NULL,
    total_ingresos   NUMERIC(14,2) DEFAULT 0,
    total_egresos    NUMERIC(14,2) DEFAULT 0,
    saldo            NUMERIC(14,2) DEFAULT 0,
    notas            TEXT,
    usuario_id       INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_contab_fecha ON contabilidad_movimientos(fecha);
CREATE INDEX IF NOT EXISTS idx_contab_tipo  ON contabilidad_movimientos(tipo);
"""

with get_db_cursor() as cur:
    cur.execute(sql)
print("OK: tablas contabilidad creadas")
