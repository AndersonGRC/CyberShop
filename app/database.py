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


def get_db_connection():
    """Crea y retorna una conexion psycopg2 a la base de datos.

    Lee las credenciales desde variables de entorno (.cybershop.conf).

    Raises:
        psycopg2.OperationalError: Si no puede conectarse al servidor.
    """
    conn = psycopg2.connect(
        dbname=os.getenv('DB_NAME', 'cybershop'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', ''),
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
    )
    return conn


@contextmanager
def get_db_cursor(dict_cursor=False):
    """Context manager que provee un cursor con commit/rollback automatico.

    Abre una conexion, crea un cursor y al salir del bloque ``with``
    ejecuta ``commit`` si no hubo errores o ``rollback`` si ocurrio
    una excepcion. Siempre cierra cursor y conexion.

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
