# -*- coding: utf-8 -*-
"""Servicio Técnico: carpetas por empresa.

Al importar fichas en Excel o PDF, cada equipo va a la carpeta de la empresa a
la que pertenece, o a «Particulares» si es de una persona (los computadores
normales). Reglas para empresa / persona, la IA local para lo dudoso (nunca la
nube, y solo vale una empresa que esté en el documento), corregir en la
revisión, importar, deshacer, mover un equipo y las pantallas.

Contra la base de pruebas. Lo creado lleva marcas al azar y se borra al final."""
import random
import string
import uuid

import pytest

from tests.test_servicio_tecnico import modulo  # noqa: F401  (fixture)
from tests.test_servicio_tecnico_importar import _archivo, _xlsx, dueno, sin_ia  # noqa: F401  (fixtures)

MARCA = 'PYTEST-EMP-' + uuid.uuid4().hex[:6].upper()
LETRAS = ''.join(random.choice(string.ascii_uppercase) for _ in range(7))      # sin números: nombres «limpios»
EMPRESA_A = f'{MARCA} ACME S.A.S.'
EMPRESA_B = f'{MARCA} GLOBAL LTDA'
PERSONA = f'JUAN CARLOS {LETRAS}'


@pytest.fixture()
def limpiar(cursor):
    lotes = []
    yield lotes
    with cursor() as cur:
        cur.execute("SELECT id FROM crm_contactos WHERE nombre ILIKE %s OR nombre ILIKE %s OR empresa ILIKE %s",
                    (MARCA + '%', f'%{LETRAS}%', MARCA + '%'))
        contactos = [r['id'] for r in cur.fetchall()]
        cur.execute("""SELECT id FROM st_equipos WHERE crm_contacto_id = ANY(%s) OR importacion_id = ANY(%s)
                       OR serial ILIKE %s""", (contactos, lotes, MARCA + '%'))
        equipos = [r['id'] for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT empresa_id FROM st_equipos WHERE id = ANY(%s) AND empresa_id IS NOT NULL", (equipos,))
        empresas = [r['empresa_id'] for r in cur.fetchall()]
        for tabla in ('st_documentos', 'st_mantenimientos', 'st_seguimientos', 'st_fotos', 'st_eventos'):
            cur.execute(f'DELETE FROM {tabla} WHERE equipo_id = ANY(%s)', (equipos,))
        cur.execute('DELETE FROM st_documentos WHERE importacion_id = ANY(%s)', (lotes,))
        cur.execute('DELETE FROM st_equipos WHERE id = ANY(%s)', (equipos,))
        cur.execute("""DELETE FROM st_empresas x WHERE (x.id = ANY(%s) OR x.nombre ILIKE %s OR x.nombre ILIKE %s)
                       AND NOT EXISTS (SELECT 1 FROM st_equipos e WHERE e.empresa_id = x.id)""",
                    (empresas, MARCA + '%', f'%{LETRAS}%'))
        cur.execute('DELETE FROM st_importaciones WHERE id = ANY(%s)', (lotes,))
        cur.execute('DELETE FROM crm_actividades WHERE contacto_id = ANY(%s)', (contactos,))
        cur.execute('DELETE FROM crm_contactos WHERE id = ANY(%s)', (contactos,))


# ── Reglas: empresa o persona ───────────────────────────────────
@pytest.mark.parametrize('nombre, esperado', [
    ('TECNOSERVICIOS', 'empresa'), ('Tecnoservicios S.A.S.', 'empresa'), ('TECNOSERVICIOS S. A. S. NIT 900.123.456-7', 'empresa'),
    ('Constructora Bolívar', 'empresa'), ('Clínica San José', 'empresa'), ('Inversiones ABC Ltda', 'empresa'),
    ('Carlos Ramírez e Hijos', 'empresa'), ('E.S.E. Hospital del Sur', 'empresa'),
    ('PEDRO NUÑEZ', 'persona'), ('ANA PEÑA', 'persona'), ('Luis Gómez', 'persona'),
    ('MARIA FERNANDA LOPEZ GOMEZ', 'persona'), ('Juan', 'persona'), ('Gonzalez', 'persona'),
    ('N/A', 'generico'), ('Particular', 'generico'), ('Consumidor final', 'generico'), ('CyberShop', 'generico'),
    ('ALFA BETA', 'dudoso'), ('YEISON MOSQUERA', 'dudoso'), ('ACME', 'dudoso'),
])
def test_reglas_empresa_o_persona(nombre, esperado):
    from services import servicio_tecnico_empresas as emp
    assert emp.clasificar(nombre, 'CyberShop')[0] == esperado


def test_la_clave_no_repite_carpetas():
    from services import servicio_tecnico_empresas as emp
    assert emp.clave('TECNOSERVICIOS S.A.S.') == emp.clave('Tecnoservicios SAS') == emp.clave('tecnoservicios') == 'tecnoservicios'
    assert emp.clave('Inversiones Ríos & Cía Ltda.') == 'inversiones rios'
    assert emp.nombre_visible('  ACME  S.A.S.  NIT 900.1 ') == 'ACME S.A.S.'
    assert emp.titular_de_ficha('FICHA\nEQUIPO ASIGNADO A ANA PEREZ - TECNOSERVICIOS\nX') == ('ANA PEREZ', 'TECNOSERVICIOS')
    assert emp.titular_de_ficha('EQUIPO ASIGNADO A ANA PEREZ') == ('ANA PEREZ', None)
    assert emp.titular_de_ficha('sin barra') == (None, None)


# ── IA: solo la local y solo lo que está en el documento ────────
class _IAFalsa:
    MSG_MOTOR_PREPARANDO = 'preparando'
    MSG_SOLO_LOCAL = 'solo local'

    def __init__(self, respuesta):
        self.respuesta, self.llamadas = respuesta, []

    def _chat(self, system, user, **kw):
        self.llamadas.append((user, kw))
        return self.respuesta, None

    @staticmethod
    def estado_ia():
        return True, None


def test_ia_identifica_la_empresa_solo_en_local_y_verificada(monkeypatch):
    from services import servicio_tecnico_ia as st_ia
    monkeypatch.setattr(st_ia, 'estado', lambda: (True, None))
    ia = _IAFalsa('{"empresa": "ACME Soluciones S.A.S.", "clasificacion": {"ZETA OMEGA": "empresa", "Otro": "persona"}}')
    monkeypatch.setattr(st_ia, '_ia', lambda: ia)
    r = st_ia.identificar_empresa('INVENTARIO DE EQUIPOS\nACME Soluciones S.A.S.\nSede norte', ['ZETA OMEGA'],
                                  negocio='cybershop', archivo='inventario.xlsx')
    assert r['ia'] and r['empresa'] == 'ACME Soluciones S.A.S.'
    assert r['clasificacion'] == {'zeta omega': 'empresa'}                   # solo los nombres que se preguntaron
    assert ia.llamadas[0][1]['permitir_nube'] is False                       # nunca a la nube
    # Una empresa que no está en el documento (inventada), el propio taller o una persona: no vale.
    for inventada in ('Microsoft Corporation', 'CyberShop', 'Ana Pérez'):
        monkeypatch.setattr(st_ia, '_ia', lambda r=inventada: _IAFalsa('{"empresa": "%s", "clasificacion": {}}' % r))
        r = st_ia.identificar_empresa('Hoja de vida del equipo de Ana Pérez\nCyberShop', [], negocio='cybershop')
        assert r['ia'] and r['empresa'] is None, inventada


def test_ia_local_ocupada_se_reintenta(monkeypatch):
    from services import servicio_tecnico_ia as st_ia

    class _Ocupada(_IAFalsa):
        def _chat(self, system, user, **kw):
            return None, self.MSG_SOLO_LOCAL
    monkeypatch.setattr(st_ia, 'estado', lambda: (True, None))
    monkeypatch.setattr(st_ia, '_ia', lambda: _Ocupada(None))
    r = st_ia.identificar_empresa('ACME', ['ZETA'], negocio='cybershop')
    assert not r['ia'] and r['reintentar']


# ── Importar: cada equipo a su carpeta ──────────────────────────
def _lote_excel(flask_app, filas, limpiar):
    from services import servicio_tecnico_importar as imp
    with flask_app.test_request_context('/'):
        lote_id, _ = imp.crear_lote([_archivo('equipos.xlsx', _xlsx(filas))], usuario_id=1)
    limpiar.append(lote_id)
    return lote_id


def test_importar_excel_reparte_por_empresa_y_deshacer(flask_app, modulo, cursor, limpiar, sin_ia):
    from services import servicio_tecnico_empresas as emp
    from services import servicio_tecnico_importar as imp
    from services import servicio_tecnico_service as st
    lote_id = _lote_excel(flask_app, [
        ['Cliente', 'Empresa', 'Tipo de equipo', 'Marca', 'Modelo', 'Serial'],
        [f'ANA MARIA {LETRAS}', EMPRESA_A, 'Portátil', 'HP', '240 G8', MARCA + '-A1'],
        [f'LUIS FERNANDO {LETRAS}', EMPRESA_A.lower(), 'Portátil', 'Lenovo', 'V15', MARCA + '-A2'],
        [f'PEDRO PABLO {LETRAS}', EMPRESA_B, 'Computador', 'Dell', 'Optiplex', MARCA + '-B1'],
        [PERSONA, '', 'Celular', 'Samsung', 'A54', MARCA + '-P1'],
    ], limpiar)
    with flask_app.test_request_context('/'):
        vista = imp.revisar(imp.obtener_lote(lote_id))
        carpetas = {v['fila']['equipo']['serial']: v['carpeta'] for v in vista['filas']}
        assert carpetas[MARCA + '-A1']['tipo'] == 'empresa' and carpetas[MARCA + '-A1']['nombre'] == EMPRESA_A
        assert emp.clave(carpetas[MARCA + '-A2']['nombre']) == emp.clave(EMPRESA_A)   # misma carpeta
        assert carpetas[MARCA + '-B1']['nombre'] == EMPRESA_B
        assert carpetas[MARCA + '-P1']['tipo'] == 'particular'                        # una persona: Particulares
        r = vista['resumen']
        assert r['carpetas'] == 2 and r['carpetas_nuevas'] == 2 and r['particulares'] == 1
        res = imp.importar(lote_id, usuario_id=1)
    assert res['resumen']['carpetas'] == 2 and res['resumen']['carpetas_creadas'] == 2
    with cursor() as cur:
        cur.execute("""SELECT e.serial, x.nombre FROM st_equipos e LEFT JOIN st_empresas x ON x.id = e.empresa_id
                       WHERE e.importacion_id = %s""", (lote_id,))
        por_serial = {r['serial']: r['nombre'] for r in cur.fetchall()}
    assert por_serial == {MARCA + '-A1': EMPRESA_A, MARCA + '-A2': EMPRESA_A, MARCA + '-B1': EMPRESA_B,
                          MARCA + '-P1': None}
    with flask_app.test_request_context('/'):
        a = next(c for c in emp.listar()['empresas'] if c['nombre'] == EMPRESA_A)
        assert a['equipos'] == 2
        assert {e['serial'] for e in st.listar_equipos(carpeta=a['id'])} == {MARCA + '-A1', MARCA + '-A2'}
        assert MARCA + '-P1' in {e['serial'] for e in st.listar_equipos(carpeta='particulares', q=MARCA)}
        d = imp.deshacer(lote_id, usuario_id=1)
    assert d['carpetas_archivadas'] == 2                                     # nada se borra: quedan archivadas
    with cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM st_empresas WHERE id = ANY(%s) AND NOT activo', (res['empresas_creadas'],))
        assert cur.fetchone()['n'] == 2


def test_nombre_dudoso_lo_decide_la_ia(flask_app, modulo, cursor, limpiar, monkeypatch):
    from services import servicio_tecnico_ia as st_ia
    from services import servicio_tecnico_importar as imp
    monkeypatch.setattr(st_ia, 'estado', lambda: (True, None))
    preguntas = []

    def identificar(encabezado, nombres=(), negocio='', archivo=''):
        preguntas.append(list(nombres))
        return {'ia': True, 'aviso': None, 'reintentar': False, 'empresa': None,
                'clasificacion': {f'zeta {LETRAS.lower()}': 'empresa', f'omega {LETRAS.lower()}': 'persona'}}
    monkeypatch.setattr(st_ia, 'identificar_empresa', identificar)
    lote_id = _lote_excel(flask_app, [
        ['Cliente', 'Tipo de equipo', 'Marca', 'Modelo', 'Serial'],
        [f'ZETA {LETRAS}', 'Portátil', 'HP', '240 G8', MARCA + '-Z1'],
        [f'OMEGA {LETRAS}', 'Portátil', 'HP', '240 G8', MARCA + '-O1'],
    ], limpiar)
    with flask_app.test_request_context('/'):
        assert imp.obtener_lote(lote_id)['estado'] == 'leyendo'               # falta el paso de la empresa
        paso = imp.leer_siguiente(lote_id)
        assert paso['parte'] == 'Empresa' and paso['estado'] == 'hecha'
        assert imp.leer_siguiente(lote_id)['listo'] is True
        assert sorted(preguntas[0]) == sorted([f'ZETA {LETRAS}', f'OMEGA {LETRAS}'])
        vista = imp.revisar(imp.obtener_lote(lote_id))
    carpetas = {v['fila']['equipo']['serial']: v['carpeta'] for v in vista['filas']}
    assert carpetas[MARCA + '-Z1']['tipo'] == 'empresa' and carpetas[MARCA + '-Z1']['fuente'] == 'ia'
    assert carpetas[MARCA + '-O1']['tipo'] == 'particular'


def test_sin_ia_lo_dudoso_de_la_columna_empresa_se_toma_como_empresa(flask_app, modulo, limpiar, sin_ia):
    from services import servicio_tecnico_importar as imp
    lote_id = _lote_excel(flask_app, [
        ['Cliente', 'Empresa', 'Marca', 'Modelo', 'Serial'],
        [PERSONA, f'ZETA {LETRAS}', 'HP', '240 G8', MARCA + '-S1'],
    ], limpiar)
    with flask_app.test_request_context('/'):
        lote = imp.obtener_lote(lote_id)
        assert lote['estado'] == 'revision' and lote['archivos'][0]['empresa']['ia'] == 'sin_ia'
        v = imp.revisar(lote)['filas'][0]
    assert v['carpeta']['tipo'] == 'empresa' and v['carpeta']['fuente'] == 'supuesto'
    assert any('No se pudo confirmar' in m[1] for m in v['mensajes'])        # se avisa: el usuario lo revisa


def test_corregir_la_carpeta_en_la_revision(flask_app, modulo, limpiar, sin_ia):
    from services import servicio_tecnico_importar as imp
    lote_id = _lote_excel(flask_app, [
        ['Cliente', 'Empresa', 'Marca', 'Modelo', 'Serial'],
        [PERSONA, EMPRESA_A, 'HP', '240 G8', MARCA + '-C1'],
    ], limpiar)
    with flask_app.test_request_context('/'):
        imp.editar_fila(lote_id, 1, {'accion': 'corregir', 'carpeta': 'particulares'})
        v = imp.revisar(imp.obtener_lote(lote_id))['filas'][0]
        assert v['carpeta']['tipo'] == 'particular' and v['carpeta']['fuente'] == 'manual'
        imp.editar_fila(lote_id, 1, {'accion': 'corregir', 'carpeta': 'empresa', 'carpeta_nombre': EMPRESA_B})
        v = imp.revisar(imp.obtener_lote(lote_id))['filas'][0]
        assert v['carpeta'] == {**v['carpeta'], 'tipo': 'empresa', 'nombre': EMPRESA_B, 'fuente': 'manual'}
        with pytest.raises(Exception, match='nombre de la empresa'):
            imp.editar_fila(lote_id, 1, {'accion': 'corregir', 'carpeta': 'empresa', 'carpeta_nombre': '  '})
        imp.editar_fila(lote_id, 1, {'accion': 'corregir', 'carpeta': 'auto'})
        assert imp.revisar(imp.obtener_lote(lote_id))['filas'][0]['carpeta']['nombre'] == EMPRESA_A


def test_reimportar_no_mueve_el_equipo_de_su_carpeta(flask_app, modulo, cursor, limpiar, sin_ia):
    from services import servicio_tecnico_importar as imp
    fila = [PERSONA, EMPRESA_A, 'HP', '240 G8', MARCA + '-R1']
    lote1 = _lote_excel(flask_app, [['Cliente', 'Empresa', 'Marca', 'Modelo', 'Serial'], fila], limpiar)
    with flask_app.test_request_context('/'):
        imp.importar(lote1, usuario_id=1)
    lote2 = _lote_excel(flask_app, [['Cliente', 'Empresa', 'Marca', 'Modelo', 'Serial'],
                                    [PERSONA, EMPRESA_B, 'HP', '240 G8', MARCA + '-R1']], limpiar)
    with flask_app.test_request_context('/'):
        v = imp.revisar(imp.obtener_lote(lote2))['filas'][0]
        assert v['existente'] and v['carpeta']['fuente'] == 'existente' and v['carpeta']['nombre'] == EMPRESA_A
        assert any('ya está en la carpeta' in m[1] for m in v['mensajes'])
        imp.importar(lote2, usuario_id=1)
    with cursor() as cur:
        cur.execute("""SELECT x.nombre FROM st_equipos e JOIN st_empresas x ON x.id = e.empresa_id
                       WHERE e.serial = %s AND e.activo""", (MARCA + '-R1',))
        assert cur.fetchone()['nombre'] == EMPRESA_A


def test_ficha_en_excel_dice_su_empresa(flask_app, modulo, limpiar, sin_ia):
    """La ficha del taller hecha en Excel: la barra «EQUIPO ASIGNADO A PERSONA -
    EMPRESA» manda el equipo a la carpeta de la empresa."""
    from services import servicio_tecnico_importar as imp
    lote_id = _lote_excel(flask_app, [
        ['FICHA TECNICA', None, 'CODIGO', 'CYBER-F00-CS-099'],
        [f'EQUIPO ASIGNADO A {PERSONA} - {EMPRESA_A}'],
        ['Fabricante del Sistema', 'HP'],
        ['Modelo', 'HP Laptop 15-gw0'],
        ['Serial', MARCA + '-F1'],
        ['Memoria RAM', '8 GB'],
    ], limpiar)
    with flask_app.test_request_context('/'):
        v = imp.revisar(imp.obtener_lote(lote_id))['filas'][0]
    assert v['carpeta']['tipo'] == 'empresa' and v['carpeta']['nombre'] == EMPRESA_A
    assert any(PERSONA in n for n in v['notas'])                            # la persona queda como «asignado a»


# ── Pantallas ───────────────────────────────────────────────────
def test_carpetas_en_pantalla_mover_y_registrar(flask_app, modulo, dueno, cursor, limpiar, sin_ia):
    from services import servicio_tecnico_importar as imp
    lote_id = _lote_excel(flask_app, [['Cliente', 'Empresa', 'Marca', 'Modelo', 'Serial'],
                                      [PERSONA, EMPRESA_A, 'HP', '240 G8', MARCA + '-V1']], limpiar)
    with flask_app.test_request_context('/'):
        res = imp.importar(lote_id, usuario_id=1)
    equipo_id = res['equipos_creados'][0]
    html = dueno.get('/admin/servicio-tecnico/equipos').get_data(as_text=True)
    assert 'class="st-carpetas"' in html and EMPRESA_A in html and 'Particulares' in html
    with cursor() as cur:
        cur.execute('SELECT empresa_id FROM st_equipos WHERE id = %s', (equipo_id,))
        empresa_id = cur.fetchone()['empresa_id']
    html = dueno.get(f'/admin/servicio-tecnico/equipos?carpeta={empresa_id}').get_data(as_text=True)
    assert f'/equipo/{equipo_id}"' in html and 'aria-current="page"' in html
    html = dueno.get(f'/admin/servicio-tecnico/equipo/{equipo_id}').get_data(as_text=True)
    assert 'Carpeta: ' + EMPRESA_A in html and 'name="carpeta"' in html
    # Mover a una empresa nueva y luego a Particulares (no cambia el cliente).
    r = dueno.post(f'/admin/servicio-tecnico/equipo/{equipo_id}/carpeta', data={'carpeta': 'nueva', 'carpeta_nombre': EMPRESA_B})
    assert r.status_code == 302
    with cursor() as cur:
        cur.execute("""SELECT e.crm_contacto_id, x.nombre FROM st_equipos e LEFT JOIN st_empresas x ON x.id = e.empresa_id
                       WHERE e.id = %s""", (equipo_id,))
        fila = cur.fetchone()
    assert fila['nombre'] == EMPRESA_B
    dueno.post(f'/admin/servicio-tecnico/equipo/{equipo_id}/carpeta', data={'carpeta': 'particulares'})
    with cursor() as cur:
        cur.execute('SELECT empresa_id, crm_contacto_id FROM st_equipos WHERE id = %s', (equipo_id,))
        despues = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS n FROM st_eventos WHERE equipo_id = %s AND detalle LIKE 'Carpeta:%%'", (equipo_id,))
        eventos = cur.fetchone()['n']
    assert despues['empresa_id'] is None and despues['crm_contacto_id'] == fila['crm_contacto_id'] and eventos >= 2
    # Registrar un equipo nuevo escribiendo la empresa: va a esa carpeta (sin repetirla).
    html = dueno.get('/admin/servicio-tecnico/equipos/nuevo').get_data(as_text=True)
    assert 'name="empresa"' in html and 'list="eqn-empresas"' in html
    r = dueno.post('/admin/servicio-tecnico/equipos/nuevo', data={
        'cliente_nombre': PERSONA, 'cliente_whatsapp': '3150000000', 'equipo_tipo': 'portatil',
        'equipo_marca': 'HP', 'equipo_modelo': '240 G8', 'equipo_serial': MARCA + '-N1',
        'empresa': EMPRESA_B.lower()})
    assert r.status_code == 302
    with cursor() as cur:
        cur.execute("""SELECT x.nombre FROM st_equipos e JOIN st_empresas x ON x.id = e.empresa_id
                       WHERE e.serial = %s""", (MARCA + '-N1',))
        assert cur.fetchone()['nombre'] == EMPRESA_B                         # la misma carpeta, no otra


def test_inventario_de_una_empresa_sin_cliente_por_fila(flask_app, modulo, cursor, limpiar, monkeypatch):
    """Inventario de funcionarios: la empresa solo está en el título (la dice la
    IA). Las filas no traen cliente: el cliente es la empresa (uno solo para
    todas) y los equipos van a su carpeta; el funcionario queda en las notas."""
    from services import servicio_tecnico_ia as st_ia
    from services import servicio_tecnico_importar as imp
    monkeypatch.setattr(st_ia, 'estado', lambda: (True, None))
    empresa = f'CONSTRUCTORA {LETRAS}'
    vistos = []

    def identificar(encabezado, nombres=(), negocio='', archivo=''):
        vistos.append(encabezado)
        return {'ia': True, 'aviso': None, 'reintentar': False, 'empresa': empresa, 'clasificacion': {}}
    monkeypatch.setattr(st_ia, 'identificar_empresa', identificar)
    monkeypatch.setattr(st_ia, 'mapear_columnas', lambda columnas, destinos: {'mapeo': {}, 'ia': True,
                                                                              'aviso': None, 'reintentar': False})
    lote_id = _lote_excel(flask_app, [
        [f'INVENTARIO DE EQUIPOS - {empresa}'], [],
        ['Funcionario', 'Tipo de equipo', 'Marca', 'Modelo', 'Serial'],
        [f'LAURA MARIA {LETRAS}', 'Portátil', 'Lenovo', 'ThinkPad E14', MARCA + '-I1'],
        [f'CARLOS ANDRES {LETRAS}', 'Portátil', 'HP', 'ProBook 450', MARCA + '-I2'],
    ], limpiar)
    with flask_app.test_request_context('/'):
        while not imp.leer_siguiente(lote_id).get('listo'):
            pass
        assert empresa in vistos[0]                                          # el título va a la IA (local)
        vista = imp.revisar(imp.obtener_lote(lote_id))
        for v in vista['filas']:
            assert v['estado'] == 'ok' and v['cliente_accion'] == 'nuevo' and v['cliente'].get('empresa') == empresa
            assert v['carpeta']['nombre'] == empresa and v['carpeta']['fuente'] == 'ia'
        assert vista['resumen']['clientes_nuevos'] == 1                       # una sola empresa en el CRM
        res = imp.importar(lote_id, usuario_id=1)
    with cursor() as cur:
        cur.execute("""SELECT c.nombre AS cliente, x.nombre AS carpeta, x.crm_contacto_id = c.id AS enlazada, e.notas
                       FROM st_equipos e JOIN crm_contactos c ON c.id = e.crm_contacto_id
                       JOIN st_empresas x ON x.id = e.empresa_id WHERE e.importacion_id = %s""", (lote_id,))
        filas = cur.fetchall()
    assert len(filas) == 2 and all(f['cliente'] == empresa and f['carpeta'] == empresa and f['enlazada'] for f in filas)
    assert any(LETRAS in (f['notas'] or '') for f in filas)                 # el funcionario no se pierde
    assert len(res['contactos_creados']) == 1
