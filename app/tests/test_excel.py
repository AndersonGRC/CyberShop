# -*- coding: utf-8 -*-
"""Tests del Excel de productos (plantilla + carga masiva + CSV) con Costo/Stock mínimo."""
import io
import uuid


def test_plantilla_incluye_costo_y_stock(as_propietario):
    import pandas as pd
    r = as_propietario.get('/descargar-plantilla-productos')
    assert r.status_code == 200
    df = pd.read_excel(io.BytesIO(r.data))
    for col in ['Costo', 'Stock inicial']:
        assert col in df.columns, f"falta columna {col} en la plantilla"
    # Stock mínimo es automático (5), ya NO es una columna capturable
    assert 'Stock mínimo' not in df.columns


def test_csv_export_incluye_costo_y_margen(as_propietario):
    r = as_propietario.get('/inventario/exportar')
    assert r.status_code == 200
    txt = r.data.decode('utf-8')
    assert 'Costo' in txt and 'Margen' in txt


def test_carga_masiva_lee_costo_stock(as_propietario, cursor):
    import pandas as pd
    ref = 'PYT-' + uuid.uuid4().hex[:8]
    with cursor() as cur:
        cur.execute("SELECT nombre FROM generos LIMIT 1")
        g = cur.fetchone()
        genero = g['nombre'] if g else 'General'
        if not g:
            cur.execute("INSERT INTO generos (nombre) VALUES ('General')")
    df = pd.DataFrame([{
        'Nombre del Producto': 'PYTEST-MASIVO', 'Referencia': ref, 'Género': genero,
        'Descripción': 'x', 'Precio': 1000, 'Costo': 600,
        'Stock inicial': 7, 'Visible en E-commerce': 'Sí',
    }])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    buf.seek(0)
    r = as_propietario.post('/cargue-masivo-productos',
                            data={'archivo_excel': (buf, 'productos.xlsx')},
                            content_type='multipart/form-data')
    assert r.status_code in (200, 302)
    try:
        with cursor() as cur:
            cur.execute("SELECT costo, stock, stock_minimo FROM productos WHERE referencia=%s", (ref,))
            row = cur.fetchone()
        assert row, "el producto no se creo por carga masiva"
        assert float(row['costo']) == 600
        assert int(row['stock']) == 7
        assert int(row['stock_minimo']) == 5   # automatico
    finally:
        with cursor() as cur:
            cur.execute("DELETE FROM productos WHERE referencia=%s", (ref,))


def test_carga_masiva_ignora_fila_ejemplo(as_propietario, cursor):
    import pandas as pd
    df = pd.DataFrame([{
        'Nombre del Producto': 'Pan (EJEMPLO — borra esta fila)', 'Referencia': 'PYT-EJEMPLO',
        'Género': 'x', 'Descripción': 'x', 'Precio': 1000, 'Costo': 600,
        'Stock inicial': 1, 'Stock mínimo': 1, 'Visible en E-commerce': 'Sí',
    }])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    buf.seek(0)
    as_propietario.post('/cargue-masivo-productos',
                        data={'archivo_excel': (buf, 'p.xlsx')},
                        content_type='multipart/form-data')
    with cursor() as cur:
        cur.execute("SELECT count(*) n FROM productos WHERE referencia='PYT-EJEMPLO'")
        assert cur.fetchone()['n'] == 0, "la fila de EJEMPLO no debe crearse"
