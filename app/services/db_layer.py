"""
Capa de abstracción de base de datos para CyberShop.

En Fase 1 solo maneja PostgreSQL. En Fase 4 se extenderá con SQLite/SQLCipher
para la app de escritorio, sin cambiar la firma de las funciones públicas.

Conexiones disponibles:
  get_control_plane_conn()  → saas_control_plane (tenants, usuarios_globales, etc.)
  get_tenant_conn(db_name)  → DB del tenant (cyber_t001, cyber_t002, ...)
  control_plane_cursor()    → context manager para control plane
  tenant_cursor(db_name)    → context manager para tenant (mismo contrato que get_db_cursor)
"""

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.cybershop.conf')

# ──────────────────────────────────────────────
# Control plane
# ──────────────────────────────────────────────

def get_control_plane_conn():
    """Conexión directa a saas_control_plane."""
    return psycopg2.connect(
        dbname   = os.getenv('CONTROL_PLANE_DB_NAME', 'saas_control_plane'),
        user     = os.getenv('CONTROL_PLANE_DB_USER',  os.getenv('DB_USER', 'postgres')),
        password = os.getenv('CONTROL_PLANE_DB_PASSWORD', os.getenv('DB_PASSWORD', '')),
        host     = os.getenv('CONTROL_PLANE_DB_HOST',  os.getenv('DB_HOST', 'localhost')),
        port     = os.getenv('CONTROL_PLANE_DB_PORT',  os.getenv('DB_PORT', '5432')),
    )


@contextmanager
def control_plane_cursor(dict_cursor=True):
    """Context manager para operaciones sobre saas_control_plane."""
    conn = get_control_plane_conn()
    factory = DictCursor if dict_cursor else None
    cur = conn.cursor(cursor_factory=factory)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ──────────────────────────────────────────────
# Tenant DB
# ──────────────────────────────────────────────

def get_tenant_conn(db_name=None):
    """Conexión directa a la DB de un tenant.

    Si db_name es None, usa la variable de entorno DB_NAME (comportamiento legacy).
    """
    effective = db_name or os.getenv('DB_NAME', 'cybershop')
    return psycopg2.connect(
        dbname   = effective,
        user     = os.getenv('DB_USER', 'postgres'),
        password = os.getenv('DB_PASSWORD', ''),
        host     = os.getenv('DB_HOST', 'localhost'),
        port     = os.getenv('DB_PORT', '5432'),
    )


@contextmanager
def tenant_cursor(db_name=None, dict_cursor=False):
    """Context manager para operaciones sobre la DB de un tenant.

    Firma idéntica a get_db_cursor() de database.py para compatibilidad.
    """
    conn = get_tenant_conn(db_name)
    factory = DictCursor if dict_cursor else None
    cur = conn.cursor(cursor_factory=factory)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
