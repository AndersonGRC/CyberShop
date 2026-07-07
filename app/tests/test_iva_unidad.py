# -*- coding: utf-8 -*-
"""Tests de C5: IVA + unidad de medida (opcionales, con default seguro)."""
import io
import uuid


def test_normalizadores(flask_app):
    from routes.admin import _norm_impuesto, _norm_unidad
    assert _norm_impuesto('19%') == '19'
    assert _norm_impuesto('IVA 5%') == '5'
    assert _norm_impuesto('') == 'excluido'       # vacío -> default seguro
    assert _norm_impuesto('cualquier cosa') == 'excluido'
    assert _norm_unidad('kg') == 'kilo'
    assert _norm_unidad('') == 'unidad'           # vacío -> default
    assert _norm_unidad('LIBRA') == 'libra'


def test_plantilla_incluye_iva_unidad(as_propietario):
    import pandas as pd
    r = as_propietario.get('/descargar-plantilla-productos')
    df = pd.read_excel(io.BytesIO(r.data))
    assert 'IVA' in df.columns and 'Unidad' in df.columns


def test_carga_masiva_iva_unidad(as_propietario, cursor):
    import pandas as pd
    ref = 'PYT-' + uuid.uuid4().hex[:8]
    with cursor() as cur:
        cur.execute("SELECT nombre FROM generos LIMIT 1")
        g = cur.fetchone()
        genero = g['nombre'] if g else 'General'
        if not g:
            cur.execute("INSERT INTO generos (nombre) VALUES ('General')")
    df = pd.DataFrame([{
        'Nombre del Producto': 'PYTEST-IVA', 'Referencia': ref, 'Género': genero,
        'Descripción': 'x', 'Precio': 1000, 'Costo': 600, 'Stock inicial': 2,
        'Stock mínimo': 1, 'IVA': '19%', 'Unidad': 'kg', 'Visible en E-commerce': 'Sí',
    }])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    buf.seek(0)
    as_propietario.post('/cargue-masivo-productos',
                        data={'archivo_excel': (buf, 'p.xlsx')}, content_type='multipart/form-data')
    try:
        with cursor() as cur:
            cur.execute("SELECT impuesto, unidad_medida FROM productos WHERE referencia=%s", (ref,))
            row = cur.fetchone()
        assert row and row['impuesto'] == '19' and row['unidad_medida'] == 'kilo'
    finally:
        with cursor() as cur:
            cur.execute("DELETE FROM productos WHERE referencia=%s", (ref,))


def test_default_seguro_sin_iva(as_propietario, cursor):
    """Producto cargado SIN columnas IVA/Unidad -> defaults excluido/unidad (no obligatorio)."""
    import pandas as pd
    ref = 'PYT-' + uuid.uuid4().hex[:8]
    with cursor() as cur:
        cur.execute("SELECT nombre FROM generos LIMIT 1")
        genero = cur.fetchone()['nombre']
    df = pd.DataFrame([{  # sin columnas IVA ni Unidad
        'Nombre del Producto': 'PYTEST-SINIVA', 'Referencia': ref, 'Género': genero,
        'Descripción': 'x', 'Precio': 500,
    }])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        df.to_excel(w, index=False)
    buf.seek(0)
    as_propietario.post('/cargue-masivo-productos',
                        data={'archivo_excel': (buf, 'p.xlsx')}, content_type='multipart/form-data')
    try:
        with cursor() as cur:
            cur.execute("SELECT impuesto, unidad_medida FROM productos WHERE referencia=%s", (ref,))
            row = cur.fetchone()
        assert row and row['impuesto'] == 'excluido' and row['unidad_medida'] == 'unidad'
    finally:
        with cursor() as cur:
            cur.execute("DELETE FROM productos WHERE referencia=%s", (ref,))
