# -*- coding: utf-8 -*-
"""Tests del POS (bloqueo por caja) y del toggle del módulo Caja."""
import pytest


def _venta(client):
    return client.post('/admin/pos/procesar',
                       json={'items': [{'producto_id': None, 'descripcion': 'Item libre pytest',
                                        'cantidad': 1, 'precio_unitario': 1000}]})


def test_pos_bloquea_sin_caja(as_cajero, modulo_caja_on, limpiar_caja):
    # módulo caja activo y sin caja abierta -> 409
    r = _venta(as_cajero)
    assert r.status_code == 409 and r.get_json().get('caja_cerrada')


def test_pos_muestra_franja_y_menu(as_cajero, modulo_caja_on, limpiar_caja):
    h = as_cajero.get('/admin/pos').data.decode('utf-8')
    assert 'id="pos-caja-strip"' in h
    assert 'Caja / Arqueo' in h


def test_toggle_modulo_off_desbloquea_pos(as_cajero, limpiar_caja, flask_app):
    from database import get_db_cursor
    import tenant_features as tf
    # desactivar módulo caja
    with get_db_cursor() as cur:
        cur.execute("UPDATE cliente_config SET valor='false' WHERE clave='caja_habilitado'")
    tf._clear_cache()
    try:
        h = as_cajero.get('/admin/pos').data.decode('utf-8')
        assert 'id="pos-caja-strip"' not in h
        assert 'Caja / Arqueo' not in h
        r = _venta(as_cajero)
        d = r.get_json()
        assert r.status_code != 409
        assert d and d.get('success')
        vid = d.get('venta_id')
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT caja_sesion_id FROM ventas_pos WHERE id=%s", (vid,))
            assert cur.fetchone()['caja_sesion_id'] is None  # sin turno estampado
        # limpiar la venta
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM contabilidad_movimientos WHERE referencia_tipo='venta_pos' AND referencia_id=%s", (vid,))
            cur.execute("DELETE FROM detalle_venta_pos WHERE venta_id=%s", (vid,))
            cur.execute("DELETE FROM ventas_pos WHERE id=%s", (vid,))
    finally:
        with get_db_cursor() as cur:
            cur.execute("UPDATE cliente_config SET valor='true' WHERE clave='caja_habilitado'")
        tf._clear_cache()


def test_historial_solo_admin_contador(as_cajero, modulo_caja_on):
    r = as_cajero.get('/admin/pos/caja/historial')
    assert r.status_code in (302, 403)  # cajero no puede


def test_historial_ok_para_propietario(as_propietario, modulo_caja_on):
    r = as_propietario.get('/admin/pos/caja/historial')
    assert r.status_code == 200
