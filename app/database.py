"""
database.py — Conexion a la base de datos PostgreSQL de CyberShop.

Provee ``get_db_connection()`` para obtener una conexion directa
y ``get_db_cursor()`` como context manager que abre conexion + cursor
y cierra ambos automaticamente al salir del bloque ``with``.
"""

import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import DictCursor
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.cybershop.conf')


def _current_db_name():
    """Retorna el db_name del tenant activo o el default de env vars.

    Durante un request Flask usa g.current_tenant si está disponible.
    Fuera de request context (scripts, tests) usa DB_NAME del entorno.
    """
    try:
        from flask import g
        if hasattr(g, 'current_tenant') and g.current_tenant.get('db_name'):
            return g.current_tenant['db_name']
    except RuntimeError:
        pass  # Fuera de request context
    return os.getenv('DB_NAME', 'cybershop')


def get_db_connection():
    """Crea y retorna una conexion psycopg2 a la base de datos del tenant activo.

    En requests Flask usa g.current_tenant para resolver la DB correcta.
    Fuera de contexto Flask usa DB_NAME del entorno (.cybershop.conf).

    Raises:
        psycopg2.OperationalError: Si no puede conectarse al servidor.
    """
    from services.db_layer import get_tenant_conn
    return get_tenant_conn(_current_db_name())


@contextmanager
def get_db_cursor(dict_cursor=False):
    """Context manager que provee un cursor con commit/rollback automatico.

    Abre una conexion al tenant activo, crea un cursor y al salir del
    bloque ``with`` ejecuta ``commit`` si no hubo errores o ``rollback``
    si ocurrio una excepcion. Siempre cierra cursor y conexion.

    Args:
        dict_cursor: Si es ``True``, usa ``DictCursor`` para obtener
            filas como diccionarios en lugar de tuplas.

    Yields:
        psycopg2 cursor listo para ejecutar consultas.

    Ejemplo::

        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM usuarios WHERE id = %s', (user_id,))
            usuario = cur.fetchone()
    """
    conn = get_db_connection()
    cursor_factory = DictCursor if dict_cursor else None
    cur = conn.cursor(cursor_factory=cursor_factory)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
