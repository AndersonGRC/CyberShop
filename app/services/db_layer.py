"""
Capa de abstracción de base de datos para CyberShop.

Conexiones disponibles:
  get_control_plane_conn()  → saas_control_plane (tenants, usuarios_globales, etc.)
  get_tenant_conn(db_name)  → DB del tenant (cyber_t001, cyber_t002, ...)
  control_plane_cursor()    → context manager para control plane
  tenant_cursor(db_name)    → context manager para tenant (mismo contrato que get_db_cursor)

POOLING (B1): las conexiones se sirven desde un ThreadedConnectionPool por
db_name (uno por proceso/worker, creado perezosamente). Es TRANSPARENTE: las
funciones devuelven un proxy cuyo .close() DEVUELVE la conexión al pool en vez
de cerrarla, de modo que todo el código existente (que hace conn.close()) sigue
funcionando sin cambios. Salvaguardas:
  - DB_POOL_ENABLED=0  → desactiva el pool (conexión directa), kill-switch sin deploy.
  - Si el pool se agota o falla → fallback a conexión directa (nunca 500 por el pool).
  - Al devolver: si la conexión quedó en transacción abierta se hace rollback;
    si está rota se descarta del pool.
"""

import os
import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extensions as _ext
from psycopg2 import pool as _pgpool
from psycopg2.extras import DictCursor
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.cybershop.conf')

_POOL_ENABLED = os.getenv('DB_POOL_ENABLED', '1').strip().lower() not in ('0', 'false', 'no', 'off', '')
_POOL_MIN = int(os.getenv('DB_POOL_MIN', '1'))
_POOL_MAX = int(os.getenv('DB_POOL_MAX', '10'))

_pools = {}                 # key -> ThreadedConnectionPool (por proceso)
_pools_lock = threading.Lock()


def _dsn_tenant(db_name):
    return dict(
        dbname   = db_name,
        user     = os.getenv('DB_USER', 'postgres'),
        password = os.getenv('DB_PASSWORD', ''),
        host     = os.getenv('DB_HOST', 'localhost'),
        port     = os.getenv('DB_PORT', '5432'),
    )


def _dsn_control_plane():
    return dict(
        dbname   = os.getenv('CONTROL_PLANE_DB_NAME', 'saas_control_plane'),
        user     = os.getenv('CONTROL_PLANE_DB_USER',  os.getenv('DB_USER', 'postgres')),
        password = os.getenv('CONTROL_PLANE_DB_PASSWORD', os.getenv('DB_PASSWORD', '')),
        host     = os.getenv('CONTROL_PLANE_DB_HOST',  os.getenv('DB_HOST', 'localhost')),
        port     = os.getenv('CONTROL_PLANE_DB_PORT',  os.getenv('DB_PORT', '5432')),
    )


def _get_pool(key, dsn):
    p = _pools.get(key)
    if p is not None:
        return p
    with _pools_lock:
        p = _pools.get(key)
        if p is None:
            p = _pgpool.ThreadedConnectionPool(_POOL_MIN, _POOL_MAX, **dsn)
            _pools[key] = p
        return p


class _PooledConnection:
    """Proxy de conexión: delega todo a la conexión real, pero su .close()
    devuelve la conexión al pool (o la cierra de verdad si no es del pool)."""

    __slots__ = ('_real', '_pool', '_released')

    def __init__(self, real, pool):
        object.__setattr__(self, '_real', real)
        object.__setattr__(self, '_pool', pool)     # None = conexión directa (sin pool)
        object.__setattr__(self, '_released', False)

    def close(self):
        if object.__getattribute__(self, '_released'):
            return
        object.__setattr__(self, '_released', True)
        real = object.__getattribute__(self, '_real')
        pool = object.__getattribute__(self, '_pool')
        if pool is None:
            try:
                real.close()
            except Exception:
                pass
            return
        try:
            if real.closed:
                pool.putconn(real, close=True)
                return
            # Limpiar transacción colgante antes de devolver al pool
            try:
                if real.info.transaction_status != _ext.TRANSACTION_STATUS_IDLE:
                    real.rollback()
            except Exception:
                pool.putconn(real, close=True)
                return
            pool.putconn(real)
        except Exception:
            try:
                real.close()
            except Exception:
                pass

    # Delegación explícita de los métodos usados por el código
    def cursor(self, *args, **kwargs):
        return object.__getattribute__(self, '_real').cursor(*args, **kwargs)

    def commit(self):
        return object.__getattribute__(self, '_real').commit()

    def rollback(self):
        return object.__getattribute__(self, '_real').rollback()

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, '_real'), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, '_real'), name, value)

    # `with conn:` de psycopg2: commit/rollback pero SIN cerrar (misma semántica)
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        real = object.__getattribute__(self, '_real')
        if exc_type is None:
            real.commit()
        else:
            real.rollback()
        return False


def _serve(key, dsn):
    """Devuelve una conexión (proxy). Usa pool si está habilitado; si el pool
    falla o se agota, cae a conexión directa para no romper el request."""
    if _POOL_ENABLED:
        try:
            pool = _get_pool(key, dsn)
            real = pool.getconn()
            return _PooledConnection(real, pool)
        except Exception:
            pass  # fallback directo
    return _PooledConnection(psycopg2.connect(**dsn), None)


# ──────────────────────────────────────────────
# Control plane
# ──────────────────────────────────────────────

def get_control_plane_conn():
    """Conexión a saas_control_plane (desde el pool, transparente)."""
    return _serve('cp:saas_control_plane', _dsn_control_plane())


@contextmanager
def control_plane_cursor(dict_cursor=True):
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
    """Conexión a la DB de un tenant (desde el pool, transparente).

    Si db_name es None, usa DB_NAME del entorno (comportamiento legacy).
    """
    effective = db_name or os.getenv('DB_NAME', 'cybershop')
    return _serve('tenant:' + effective, _dsn_tenant(effective))


@contextmanager
def tenant_cursor(db_name=None, dict_cursor=False):
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


def pool_stats():
    """Diagnóstico: nº de pools vivos en este proceso (para /health o debug)."""
    return {'pools': list(_pools.keys()), 'enabled': _POOL_ENABLED,
            'min': _POOL_MIN, 'max': _POOL_MAX}
