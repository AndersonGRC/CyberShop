# -*- coding: utf-8 -*-
"""Tests de C1: costo/COGS estampado en la venta."""
import uuid


def test_venta_estampa_costo_unitario(as_cajero, modulo_caja_on, limpiar_caja, cursor):
    ref = 'PYT-' + uuid.uuid4().hex[:8]
    with cursor() as cur:
        cur.execute("SELECT id FROM generos LIMIT 1")
        g = cur.fetchone()
        gid = g['id'] if g else None
        if gid is None:
            cur.execute("INSERT INTO generos (nombre) VALUES ('PYTEST-GEN') RETURNING id")
            gid = cur.fetchone()['id']
        cur.execute("""INSERT INTO productos (imagen,nombre,precio,referencia,genero_id,descripcion,stock,costo)
                       VALUES ('','PYTEST-COSTO',1000,%s,%s,'x',10,600) RETURNING id""", (ref, gid))
        pid = cur.fetchone()['id']

    vid = None
    try:
        as_cajero.post('/admin/pos/caja/abrir', json={'base': '0'})
        r = as_cajero.post('/admin/pos/procesar', json={
            'items': [{'producto_id': pid, 'descripcion': 'PYTEST-COSTO', 'cantidad': 2, 'precio_unitario': 1000}]})
        d = r.get_json()
        assert d and d.get('success'), f"venta fallo: {d}"
        vid = d['venta_id']
        with cursor() as cur:
            cur.execute("SELECT costo_unitario FROM detalle_venta_pos WHERE venta_id=%s", (vid,))
            row = cur.fetchone()
        assert row and float(row['costo_unitario']) == 600, f"costo no estampado: {row}"
    finally:
        # Limpieza en orden FK-safe (detalle, inventario_log, contabilidad, venta, producto)
        with cursor() as cur:
            if vid:
                cur.execute("DELETE FROM contabilidad_movimientos WHERE referencia_tipo='venta_pos' AND referencia_id=%s", (vid,))
                cur.execute("DELETE FROM detalle_venta_pos WHERE venta_id=%s", (vid,))
                cur.execute("DELETE FROM ventas_pos WHERE id=%s", (vid,))
            cur.execute("DELETE FROM inventario_log WHERE producto_id=%s", (pid,))
            cur.execute("DELETE FROM producto_imagenes WHERE producto_id=%s", (pid,))
            cur.execute("DELETE FROM productos WHERE id=%s", (pid,))
