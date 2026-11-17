# -*- coding: utf-8 -*-
"""Subir un PDF, Word o texto como documento interno (services/ia_rag/importar.py).

El texto queda en el formulario para revisarlo: nada se guarda solo. Al
guardar, la bitácora anota que vino de un archivo.
"""
import io
import zipfile

import pytest

from database import get_db_cursor
from services.ia_rag.importar import MAX_BYTES, texto_de_archivo

MARCA = 'TEST-IMP'


def _docx(*parrafos):
    cuerpo = ''.join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in parrafos)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.'
           'openxmlformats.org/wordprocessingml/2006/main"><w:body>' + cuerpo + '</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', xml)
    return buf.getvalue()


def _pdf(*lineas):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 720
    for linea in lineas:
        c.drawString(72, y, linea)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


# ── Leer el archivo ───────────────────────────────────────────
def test_lee_un_word_por_parrafos():
    titulo, texto = texto_de_archivo('Manual_de_apertura.docx',
                                     _docx('Abrir la reja a las 7.', 'Encender la caja.'))
    assert titulo == 'Manual de apertura'
    assert texto == 'Abrir la reja a las 7.\n\nEncender la caja.'


def test_lee_un_pdf_con_texto():
    titulo, texto = texto_de_archivo('politica-devoluciones.pdf',
                                     _pdf('Politica de devoluciones', 'Hasta 30 dias con factura.'))
    assert titulo == 'politica devoluciones'
    assert 'Hasta 30 dias con factura.' in texto


def test_lee_texto_plano_en_utf8_o_latin1():
    assert texto_de_archivo('notas.txt', 'Café y pan'.encode('utf-8'))[1] == 'Café y pan'
    assert texto_de_archivo('notas.txt', 'Café y pan'.encode('latin-1'))[1] == 'Café y pan'


@pytest.mark.parametrize('nombre, datos, error', [
    ('manual.doc', b'xx', 'PDF, un Word'),
    ('manual.docx', b'', 'vacío'),
    ('manual.docx', b'no es un zip', 'no es un Word'),
], ids=['doc-viejo', 'vacio', 'no-es-zip'])
def test_explica_por_que_no_se_puede(nombre, datos, error):
    with pytest.raises(ValueError, match=error):
        texto_de_archivo(nombre, datos)


def test_un_archivo_de_mas_de_10_mb_se_rechaza():
    with pytest.raises(ValueError, match='10 MB'):
        texto_de_archivo('grande.txt', b'x' * (MAX_BYTES + 1))


def test_un_pdf_escaneado_se_avisa():
    with pytest.raises(ValueError, match='escaneado'):
        texto_de_archivo('foto.pdf', _pdf())


def test_un_word_sin_documento_se_rechaza():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('otra/cosa.xml', '<a/>')
    with pytest.raises(ValueError, match='no es un Word'):
        texto_de_archivo('raro.docx', buf.getvalue())


# ── Pantalla ──────────────────────────────────────────────────
@pytest.fixture()
def limpio(flask_app):
    yield
    with flask_app.app_context():
        from services.ia_rag import internos
        with get_db_cursor() as cur:
            internos.asegurar_tabla(cur)
            cur.execute('DELETE FROM ia_documentos_internos WHERE titulo LIKE %s', (f'{MARCA}%',))
            cur.execute("SELECT to_regclass('public.ia_conocimiento_log')")
            if cur.fetchone()[0] is not None:
                cur.execute('DELETE FROM ia_conocimiento_log WHERE titulo LIKE %s', (f'{MARCA}%',))


def _contar(titulo_like):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT to_regclass('public.ia_documentos_internos') AS t")
        if cur.fetchone()['t'] is None:
            return 0
        cur.execute('SELECT COUNT(*) AS n FROM ia_documentos_internos WHERE titulo LIKE %s',
                    (titulo_like,))
        return cur.fetchone()['n']


def test_subir_deja_el_texto_para_revisar_sin_guardar(as_propietario, limpio):
    r = as_propietario.post('/admin/ia/documentos/importar', content_type='multipart/form-data',
                            data={'archivo': (io.BytesIO(_docx('Cerrar la caja a las 8.')),
                                              f'{MARCA}_cierre.docx')})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'Cerrar la caja a las 8.' in html
    assert 'value="TEST IMP cierre"' in html                        # título sugerido del nombre
    assert 'name="origen" value="archivo"' in html
    assert _contar(f'{MARCA}%') == 0                                 # nada se guardó solo


def test_al_guardar_queda_que_vino_de_un_archivo(as_propietario, limpio):
    r = as_propietario.post('/admin/ia/documentos/guardar', data={
        'titulo': f'{MARCA} cierre', 'texto': 'Cerrar la caja a las 8.',
        'visibilidad': 'equipo', 'origen': 'archivo'})
    assert r.status_code == 302
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("""SELECT accion, origen FROM ia_conocimiento_log
                       WHERE tipo = 'documento' AND titulo = %s""", (f'{MARCA} cierre',))
        assert [(f['accion'], f['origen']) for f in cur.fetchall()] == [('crear', 'archivo')]


def test_un_archivo_que_no_sirve_avisa(as_propietario, limpio):
    r = as_propietario.post('/admin/ia/documentos/importar', content_type='multipart/form-data',
                            data={'archivo': (io.BytesIO(b'xx'), 'viejo.doc')}, follow_redirects=True)
    assert 'Sube un PDF, un Word' in r.get_data(as_text=True)


def test_un_texto_largo_se_recorta_con_aviso(as_propietario, limpio):
    from services.ia_rag.internos import MAX_TEXTO
    largo = ('Párrafo de prueba del manual. ' * 40 + '\n\n') * (MAX_TEXTO // 1200 + 3)
    r = as_propietario.post('/admin/ia/documentos/importar', content_type='multipart/form-data',
                            data={'archivo': (io.BytesIO(largo.encode('utf-8')), f'{MARCA}.txt')})
    html = r.get_data(as_text=True)
    assert 'se cargaron los primeros' in html
