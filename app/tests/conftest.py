# -*- coding: utf-8 -*-
"""
Configuración de pytest para CyberShop.

Los tests corren contra la BD del tenant demo (cyber_t002) con el test-client
de Flask y CSRF desactivado. Cada test que crea datos los limpia (marcadores
'TEST-' + fixtures de teardown). NO tocar tenants reales.

Ejecutar en el servidor con el venv de prod:
    DB_NAME=cyber_t002 env/bin/python -m pytest tests/ -q
"""
import os
import sys

# DB del tenant demo ANTES de importar la app (load_dotenv no sobrescribe env ya seteado)
os.environ.setdefault('DB_NAME', 'cyber_t002')
os.environ.setdefault('WTF_CSRF_ENABLED', 'false')

# La app se importa con cwd = /var/www/CyberShop/app (config.py resuelve rutas relativas)
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

import pytest

# Barrera dura: NUNCA correr la suite (que borra datos) contra un tenant real.
# Solo se permite la BD demo/pruebas.
_ALLOWED_TEST_DBS = {'cyber_t002', 'cybershop_test'}


def pytest_configure(config):
    db = os.environ.get('DB_NAME', '')
    if db not in _ALLOWED_TEST_DBS:
        raise pytest.UsageError(
            f"ABORTADO: DB_NAME='{db}' no es una BD de pruebas. "
            f"La suite borra datos; solo se permite {_ALLOWED_TEST_DBS}. "
            f"Ejecuta con DB_NAME=cyber_t002.")


@pytest.fixture(scope='session')
def flask_app():
    from app import app as flask_app
    flask_app.config['WTF_CSRF_ENABLED'] = False
    flask_app.config['TESTING'] = True
    return flask_app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture()
def cursor(flask_app):
    """Cursor dict sobre la BD demo (autocommit del context manager)."""
    from database import get_db_cursor

    class _C:
        def __call__(self, dict_cursor=True):
            return get_db_cursor(dict_cursor=dict_cursor)
    return _C()


def _login(client, rol_id, usuario_id=1, nombre='PytestUser'):
    with client.session_transaction() as s:
        s['usuario_id'] = usuario_id
        s['rol_id'] = rol_id
        s['username'] = nombre


@pytest.fixture()
def as_cajero(client):
    _login(client, 7)  # ROL_CAJERO
    return client


@pytest.fixture()
def as_propietario(client):
    _login(client, 2)  # ROL_PROPIETARIO
    return client


@pytest.fixture()
def modulo_caja_on(flask_app):
    """Asegura el módulo caja activo + tablas creadas; limage sesiones de test al final."""
    from database import get_db_cursor
    import tenant_features as tf
    with get_db_cursor() as cur:
        cur.execute("UPDATE cliente_config SET valor='true' WHERE clave='caja_habilitado'")
        if cur.rowcount == 0:
            cur.execute("""INSERT INTO cliente_config (clave,valor,tipo,grupo,descripcion,orden)
                           VALUES ('caja_habilitado','true','boolean','modulos','Caja',0)""")
    tf._clear_cache()
    yield
    tf._clear_cache()


@pytest.fixture()
def limpiar_caja(flask_app):
    """Teardown: borra cualquier sesión/movimiento de caja y ventas TEST- creadas."""
    yield
    from database import get_db_cursor
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM contabilidad_movimientos WHERE referencia_tipo IN ('caja_movimiento','caja_cierre')")
        cur.execute("DELETE FROM contabilidad_movimientos WHERE referencia_tipo='venta_pos' AND referencia_id IN (SELECT id FROM ventas_pos WHERE numero_venta LIKE 'TEST-%%' OR numero_venta LIKE 'POS-%%' AND cliente_nombre='PYTEST')")
        cur.execute("DELETE FROM caja_movimientos WHERE caja_sesion_id IN (SELECT id FROM caja_sesiones)")
        cur.execute("DELETE FROM detalle_venta_pos WHERE venta_id IN (SELECT id FROM ventas_pos WHERE numero_venta LIKE 'TEST-%%')")
        cur.execute("DELETE FROM ventas_pos WHERE numero_venta LIKE 'TEST-%%'")
        cur.execute("DELETE FROM caja_sesiones")
