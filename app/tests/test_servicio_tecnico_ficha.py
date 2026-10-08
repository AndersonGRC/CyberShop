# -*- coding: utf-8 -*-
"""Servicio Técnico: la ficha técnica del equipo en PDF (formato del taller).

Generar la ficha (roja si presenta inconvenientes, azul si está en buen
estado), volver a leerla igual, el código consecutivo, los textos que proponen
las reglas y la IA (sin datos de personas), importar fichas en PDF
(reconocidas sin IA), reimportarlas, deshacer y las pantallas.

Contra la base de pruebas. Todo lo creado lleva la marca PYTEST-STF-<uuid> y se
borra al final; el interruptor del módulo vuelve a quedar como estaba."""
import io
import json
import uuid
from datetime import date, timedelta

import pytest
from werkzeug.datastructures import FileStorage

from tests.conftest import _login
from tests.test_servicio_tecnico import modulo  # noqa: F401  (fixture)

MARCA = 'PYTEST-STF-' + uuid.uuid4().hex[:6]


@pytest.fixture()
def limpiar(cursor):
    lotes = []
    yield lotes
    with cursor() as cur:
        # ILIKE: la importación deja el nombre de la empresa en mayúsculas.
        cur.execute("SELECT id FROM crm_contactos WHERE nombre ILIKE %s OR empresa ILIKE %s", (MARCA + '%', MARCA + '%'))
        contactos = [r['id'] for r in cur.fetchall()]
        cur.execute("""SELECT id FROM st_equipos WHERE crm_contacto_id = ANY(%s) OR importacion_id = ANY(%s)
                       OR ficha_codigo LIKE %s""", (contactos, lotes, MARCA + '%'))
        equipos = [r['id'] for r in cur.fetchall()]
        cur.execute("SELECT id FROM st_ordenes WHERE equipo_id = ANY(%s)", (equipos,))
        ordenes = [r['id'] for r in cur.fetchall()]
        cur.execute("DELETE FROM st_documentos WHERE equipo_id = ANY(%s) OR importacion_id = ANY(%s)", (equipos, lotes))
        cur.execute("DELETE FROM st_mantenimientos WHERE equipo_id = ANY(%s)", (equipos,))
        cur.execute("DELETE FROM st_seguimientos WHERE equipo_id = ANY(%s) OR orden_id = ANY(%s)", (equipos, ordenes))
        cur.execute("DELETE FROM st_fotos WHERE equipo_id = ANY(%s)", (equipos,))
        cur.execute("DELETE FROM st_eventos WHERE equipo_id = ANY(%s) OR orden_id = ANY(%s)", (equipos, ordenes))
        cur.execute("DELETE FROM st_ordenes WHERE id = ANY(%s)", (ordenes,))
        cur.execute("DELETE FROM st_equipos WHERE id = ANY(%s)", (equipos,))
        cur.execute("DELETE FROM st_importaciones WHERE id = ANY(%s)", (lotes,))
        cur.execute("DELETE FROM crm_actividades WHERE contacto_id = ANY(%s)", (contactos,))
        cur.execute("DELETE FROM crm_contactos WHERE id = ANY(%s)", (contactos,))


@pytest.fixture()
def dueno(client):
    _login(client, 2)
    return client


@pytest.fixture()
def sin_ia(monkeypatch):
    from services import servicio_tecnico_ia as st_ia
    monkeypatch.setattr(st_ia, 'estado', lambda: (False, 'La IA está apagada.'))


def _jpeg(color=(30, 60, 140)):
    from PIL import Image
    salida = io.BytesIO()
    Image.new('RGB', (320, 240), color).save(salida, 'JPEG')
    return salida.getvalue()


class _Archivo:
    def __init__(self, datos, nombre):
        self.datos, self.filename = datos, nombre

    def read(self, n=-1):
        return self.datos


def _equipo(flask_app, ram='8 GB DDR4', libres='1', empresa=MARCA + ' EMPRESA'):
    from services import servicio_tecnico_service as st
    with flask_app.test_request_context('/'):
        equipo_id = st.registrar_equipo({
            'cliente': {'nombre': empresa},
            'equipo': {'tipo': 'portatil', 'marca': 'HP', 'modelo': 'HP Laptop 15-gw0',
                       'procesador': 'AMD Ryzen 3 3250U with Radeon Graphics, 2.6 GHz', 'ram': ram,
                       'almacenamiento': 'SSD 256 GB', 'sistema_operativo': 'Windows 11 Home',
                       'extras': {'ram_ranuras_total': '2', 'ram_ranuras_libres': libres, 'tipo_disco': 'SSD NVMe'}}},
            None)
        st.guardar_fotos(equipo_id, [_Archivo(_jpeg(), 'frente.jpg')], 'ficha', usuario_id=None)
    return equipo_id


def _guardar_ficha(flask_app, equipo_id, estado='inconveniente', **extra):
    from services import servicio_tecnico_ficha as ficha
    with flask_app.test_request_context('/'):
        datos = ficha.armar(equipo_id)
        form = {'estado': estado, 'version': '1', 'asignado_a': MARCA + ' FULANO', 'empresa': MARCA + ' EMPRESA',
                'descripcion': 'Este equipo de cómputo es un portátil HP Laptop 15-gw0 con 8 GB de RAM.',
                'vida_util': 'La vida útil estimada es de 4 a 6 años. Recomendaciones:',
                'recomendaciones': 'Conectarlo a un regulador de voltaje o UPS.\nAmpliar la memoria RAM.',
                'problema': 'Memoria RAM insuficiente: 8 GB instalados.' if estado == 'inconveniente' else '',
                'requerimientos': 'Ampliación de memoria RAM a 16 GB (mínimo recomendado).'}
        for i, f in enumerate(datos['filas']):
            form[f'etiqueta_{i}'] = f['etiqueta']
            if f['etiqueta'] == 'Nombre de Usuario':
                form[f'fila_{i}'] = 'OFICINA\\fulano'
            if f['etiqueta'] == 'Memoria RAM' and estado == 'inconveniente':
                form[f'fila_{i}'] = '8,00 GB DDR4 - 1 de 2 ranuras en uso. SE SUGIERE AMPLIAR A 16 GB.'
                form[f'destacar_{i}'] = '1'
        form.update(extra)
        return ficha.guardar(equipo_id, form)


# ── Reglas, códigos y fechas ────────────────────────────────────
def test_codigo_consecutivo_sigue_la_serie():
    from services import servicio_tecnico_ficha as ficha
    assert ficha.siguiente_codigo(['CYBER-F00-CS-012', 'CYBER-F00-CS-005', 'CYBER-F00-CS-014']) == 'CYBER-F00-CS-015'
    assert ficha.siguiente_codigo(['CYBER-F00-CS-012', 'OTRO-9'], 'CYBER-F00-CS-') == 'CYBER-F00-CS-013'
    assert ficha.siguiente_codigo([], 'ABC-') == 'ABC-001'
    assert ficha.siguiente_codigo([]) == 'FT-001'


def test_fechas_de_la_ficha():
    from services import servicio_tecnico_ficha as ficha
    assert ficha.leer_fecha('5-ago-26') == date(2026, 8, 5)
    assert ficha.leer_fecha('28-07-2026') == date(2026, 7, 28)
    assert ficha.leer_fecha('2027-08-05') == date(2027, 8, 5)
    assert ficha.fecha_corta(date(2026, 8, 5)) == '5-ago-26'


def test_borrador_con_reglas_rojo_y_azul():
    from services import servicio_tecnico_ficha as ficha
    base = {'tipo': 'portatil', 'marca': 'HP', 'modelo': 'HP Laptop 15-gw0', 'sistema_operativo': 'Windows 11 Home',
            'procesador': 'AMD Ryzen 3 3250U with Radeon Graphics, 2.6 GHz', 'almacenamiento': 'SSD 256 GB'}
    rojo = ficha.borrador({**base, 'ram': '8 GB DDR4', 'extras': {'ram_ranuras_libres': '1'}})
    assert rojo['estado'] == 'inconveniente' and 'Memoria RAM' in rojo['destacar']
    assert rojo['problema'].startswith('Memoria RAM insuficiente') and 'ranura libre' in rojo['requerimientos']
    assert 'gama básica' in rojo['descripcion'] and 'HP Laptop 15-gw0' in rojo['descripcion']
    assert any('Ampliar la memoria RAM' in r for r in rojo['recomendaciones'])
    azul = ficha.borrador({**base, 'procesador': 'AMD Ryzen 7 5825U', 'ram': '16 GB DDR4', 'extras': {}})
    assert azul['estado'] == 'bueno' and azul['problema'] == 'N/A - El equipo no presenta fallas.'
    assert azul['destacar'] == [] and '5 a 7 años' in azul['vida_util']


# ── Generar la ficha y volver a leerla ──────────────────────────
def test_ficha_roja_se_genera_y_se_lee_igual(flask_app, modulo, cursor, limpiar):
    from pypdf import PdfReader

    from services import servicio_tecnico_ficha as ficha
    equipo_id = _equipo(flask_app)
    _guardar_ficha(flask_app, equipo_id)
    with flask_app.test_request_context('/'):
        codigo = ficha.asignar_codigo(equipo_id)
        assert ficha.asignar_codigo(equipo_id) == codigo               # se asigna una sola vez
        datos = ficha.armar(equipo_id)
        contenido = ficha.pdf(datos)
    assert contenido.startswith(b'%PDF') and len(PdfReader(io.BytesIO(contenido)).pages) == 1
    leida = ficha.leer_pdf(contenido)
    assert leida and leida['codigo'] == codigo and leida['estado'] == 'inconveniente'
    assert leida['asignado_a'] == (MARCA + ' FULANO').upper() and leida['empresa'] == (MARCA + ' EMPRESA').upper()
    filas = dict(leida['filas'])
    assert filas['Memoria RAM'].startswith('8,00 GB DDR4') and filas['Nombre de Usuario'] == 'OFICINA\\fulano'
    assert filas['Procesador'].startswith('AMD Ryzen 3 3250U') and filas['Fabricante del Sistema'] == 'HP'
    assert leida['destacar'] == ['Memoria RAM']
    assert leida['recomendaciones'] == ['Conectarlo a un regulador de voltaje o UPS.', 'Ampliar la memoria RAM.']
    assert leida['problema'] == 'Memoria RAM insuficiente: 8 GB instalados.' and leida['fotos'] == 1
    assert ficha.nombre_pdf(datos) == f"{(MARCA + ' FULANO')} - HP Laptop 15-gw0 - Ult Mtto {date.today().isoformat()}.pdf"


def test_ficha_azul_no_resalta_nada(flask_app, modulo, cursor, limpiar):
    from services import servicio_tecnico_ficha as ficha
    equipo_id = _equipo(flask_app, ram='16 GB DDR4', libres='0')
    _guardar_ficha(flask_app, equipo_id, estado='bueno')
    with flask_app.test_request_context('/'):
        leida = ficha.leer_pdf(ficha.pdf(ficha.armar(equipo_id)))
    assert leida['estado'] == 'bueno' and leida['destacar'] == [] and leida['problema'] == 'N/A'
    assert dict(leida['filas'])['Memoria RAM'].startswith('16 GB DDR4')    # sin dato propio: sale del equipo


# ── IA: solo datos técnicos, nada inventado ─────────────────────
def test_ia_redacta_sin_datos_de_personas_ni_cifras_inventadas(flask_app, modulo, cursor, limpiar, monkeypatch):
    from services import servicio_tecnico_ficha as ficha
    from services import servicio_tecnico_ia as st_ia
    equipo_id = _equipo(flask_app)
    _guardar_ficha(flask_app, equipo_id)
    enviado = []

    class _IA:
        MSG_MOTOR_PREPARANDO = 'preparando'

        @staticmethod
        def estado_ia():
            return True, None

        @staticmethod
        def _chat(system, user, **kw):
            enviado.append(user)
            return json.dumps({
                'estado': 'inconveniente',
                'descripcion': 'Portátil HP con 32 GB de RAM.',                       # 32 GB no está en el equipo
                'vida_util': 'Vida útil de 4 a 6 años. Recomendaciones:',
                'recomendaciones': ['Ampliar la memoria a 16 GB.', 'Conectarlo a una UPS.'],
                'problema': 'Memoria RAM insuficiente: 8 GB.',
                'requerimientos': 'Agregar un módulo de 8 GB para llegar a 16 GB.',
                'destacar': ['Memoria RAM', 'Inventada']}), None
    monkeypatch.setattr(st_ia, '_ia', lambda: _IA)
    with flask_app.test_request_context('/'):
        datos = ficha.armar(equipo_id)
        res = st_ia.redactar_ficha(datos['equipo'], [(f['etiqueta'], f['valor']) for f in datos['filas']],
                                   ficha.borrador(datos['equipo']))
    texto = '\n'.join(enviado)
    for dato in (MARCA, 'FULANO', 'EMPRESA', 'OFICINA\\fulano'):
        assert dato not in texto, dato
    p = res['propuesta']
    assert res['ia'] and p['descripcion'] != 'Portátil HP con 32 GB de RAM.'       # inventado → el de las reglas
    assert p['requerimientos'] == 'Agregar un módulo de 8 GB para llegar a 16 GB.'   # 16 GB es la meta: se acepta
    assert p['recomendaciones'] == ['Ampliar la memoria a 16 GB.', 'Conectarlo a una UPS.']
    assert p['destacar'] == ['Memoria RAM'] and 'descripcion' in res['aviso']


# ── Importar fichas en PDF ──────────────────────────────────────
def test_importar_ficha_pdf_reimportar_y_deshacer(flask_app, modulo, cursor, limpiar, sin_ia):
    from services import servicio_tecnico_ficha as ficha
    from services import servicio_tecnico_importar as imp
    origen = _equipo(flask_app, empresa=MARCA + ' ORIGEN')
    codigo = 'STF' + uuid.uuid4().hex[:6].upper() + '-001'
    _guardar_ficha(flask_app, origen, asignado_a=MARCA + ' MENGANA', empresa=MARCA + ' TECNO')
    with cursor() as cur:
        cur.execute('UPDATE st_equipos SET ficha_codigo = %s WHERE id = %s', (codigo, origen))
    with flask_app.test_request_context('/'):
        documento = ficha.pdf(ficha.armar(origen))
    with cursor() as cur:                       # el equipo de origen se retira: la ficha llega como «nueva»
        cur.execute('UPDATE st_equipos SET activo = FALSE WHERE id = %s', (origen,))
    with flask_app.test_request_context('/'):
        lote_id, errores = imp.crear_lote([FileStorage(stream=io.BytesIO(documento), filename='ficha.pdf')], 1)
        limpiar.append(lote_id)
        lote = imp.obtener_lote(lote_id)
        assert lote['estado'] == 'revision' and lote['archivos'][0]['partes'][0]['tipo'] == 'ficha'
        assert lote['archivos'][0]['partes'][0]['ia'] == 'no_aplica'          # se lee completa sin IA
        v = imp.revisar(lote)['filas'][0]
        assert v['estado'] == 'ok' and v['fila']['cliente'] == {'empresa': (MARCA + ' TECNO').upper()}
        assert any('Ficha técnica reconocida' in m[1] for m in v['mensajes'])
        res = imp.importar(lote_id, 1)
    assert res['resumen']['equipos_creados'] == 1 and len(res['fichas']) == 1 and len(res['fotos']) == 1
    nuevo = res['equipos_creados'][0]
    with cursor() as cur:
        cur.execute('SELECT * FROM st_equipos WHERE id = %s', (nuevo,))
        e = cur.fetchone()
    assert e['ficha_codigo'] == codigo and e['ficha']['estado'] == 'inconveniente'
    assert e['ficha']['asignado_a'] == (MARCA + ' MENGANA').upper() and e['ficha']['destacar'] == ['Memoria RAM']
    assert e['tipo'] == 'portatil' and e['ram'] == '8 GB DDR4' and e['mant_proximo'] is None

    # Otra vez el mismo PDF: el código de la ficha dice que es el mismo equipo.
    with flask_app.test_request_context('/'):
        lote2, _ = imp.crear_lote([FileStorage(stream=io.BytesIO(documento), filename='ficha.pdf')], 1)
        limpiar.append(lote2)
        v = imp.revisar(imp.obtener_lote(lote2))['filas'][0]
        assert v['existente'] and v['existente']['id'] == nuevo
        assert not any('ya lo tiene otro equipo' in m[1] for m in v['mensajes'])
        imp.descartar(lote2)

    # Deshacer: el equipo se retira y su código queda libre para otro equipo.
    with flask_app.test_request_context('/'):
        imp.deshacer(lote_id, 1)
    with cursor() as cur:
        cur.execute('SELECT activo FROM st_equipos WHERE id = %s', (nuevo,))
        assert cur.fetchone()['activo'] is False
        cur.execute('SELECT COUNT(*) AS n FROM st_fotos WHERE equipo_id = %s AND activo', (nuevo,))
        assert cur.fetchone()['n'] == 0
        cur.execute('UPDATE st_equipos SET ficha_codigo = %s WHERE id = %s', (codigo, origen))   # no choca: retirados


# ── Pantallas ───────────────────────────────────────────────────
def test_pantalla_de_la_ficha_guardar_y_generar(flask_app, modulo, dueno, cursor, limpiar, sin_ia):
    equipo_id = _equipo(flask_app)
    base = f'/admin/servicio-tecnico/equipo/{equipo_id}'
    html = dueno.get(base + '/ficha').get_data(as_text=True)
    assert '¿Cómo está el equipo?' in html and 'Presenta inconvenientes' in html and 'name="etiqueta_0"' in html
    assert 'Ficha técnica' in dueno.get(base).get_data(as_text=True)
    form = {'estado': 'inconveniente', 'version': '2', 'asignado_a': MARCA + ' Ana', 'problema': 'Falla de RAM',
            'etiqueta_0': 'Sistema Operativo', 'fila_0': 'Windows 11 Pro', 'etiqueta_1': 'Inventada', 'fila_1': 'x'}
    r = dueno.post(base + '/ficha', data=form)
    assert r.status_code == 302
    with cursor() as cur:
        cur.execute('SELECT ficha, ficha_codigo FROM st_equipos WHERE id = %s', (equipo_id,))
        fila = cur.fetchone()
    assert fila['ficha']['estado'] == 'inconveniente' and fila['ficha']['version'] == 2
    assert fila['ficha']['filas'] == {'Sistema Operativo': 'Windows 11 Pro'} and fila['ficha_codigo'] is None
    r = dueno.post(base + '/ficha.pdf', data={**form, 'guardar': '1', 'copia': '1'})
    assert r.status_code == 200 and r.mimetype == 'application/pdf' and r.data.startswith(b'%PDF')
    assert r.headers['Content-Disposition'].startswith('inline') and 'Ult Mtto' in r.headers['Content-Disposition']
    with cursor() as cur:
        cur.execute('SELECT ficha_codigo FROM st_equipos WHERE id = %s', (equipo_id,))
        assert cur.fetchone()['ficha_codigo']                                    # código asignado al generar
        cur.execute("SELECT COUNT(*) AS n FROM st_documentos WHERE equipo_id = %s AND mime = 'application/pdf'",
                    (equipo_id,))
        assert cur.fetchone()['n'] == 1                                         # copia en Documentos
    r = dueno.post(base + '/ficha/proponer')
    d = r.get_json()
    assert r.status_code == 200 and d['ok'] and not d['ia'] and d['propuesta']['estado'] in ('bueno', 'inconveniente')
    assert dueno.get('/admin/servicio-tecnico/equipos').status_code == 200


def test_modulo_apagado_sin_ficha(modulo, dueno):
    modulo(False)
    assert dueno.get('/admin/servicio-tecnico/equipo/1/ficha').status_code == 302
