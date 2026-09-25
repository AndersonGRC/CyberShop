# -*- coding: utf-8 -*-
"""Documentos internos: el índice privado del asistente del panel.

Lo que se cuida, en orden de importancia:

  1. Que un documento interno JAMÁS salga en el chat del sitio público.
  2. Que cada rol lea solo lo que le toca (administración o todo el equipo).
  3. Que archivar lo saque de las respuestas sin borrar nada.
"""
import pytest
from flask import session

from database import get_db_cursor
from services.ia_datos.acceso import CANAL_ESCRITORIO, CANAL_PUBLICO, Contexto

MARCA = 'TEST-DOCINT'
PALABRA = 'zorrillo7731'          # no aparece en ningún otro texto del índice


@pytest.fixture()
def internos(flask_app):
    """El servicio con el índice disponible; al terminar, sin restos de la prueba."""
    from services.ia_rag import indexador
    from services.ia_rag import internos as servicio
    with flask_app.app_context():
        with get_db_cursor() as cur:
            if not indexador.indice_disponible(cur):
                pytest.skip('este cliente no tiene la migración 0012 aplicada')
        yield servicio
        with get_db_cursor() as cur:
            servicio.asegurar_tabla(cur)
            cur.execute('DELETE FROM ia_documentos_internos WHERE titulo LIKE %s', (f'{MARCA}%',))
        indexador.reindexar(['interno'], limpiar=False)


def _doc(servicio, visibilidad='administracion', texto=None, titulo='Apertura'):
    return servicio.guardar(f'{MARCA} {titulo}', texto or f'Procedimiento {PALABRA}: abrir la reja.',
                            visibilidad)


def _titulos(docs):
    return {d['titulo'] for d in docs}


# ── 1. Nunca público ───────────────────────────────────────────
def test_un_documento_interno_nunca_sale_en_la_busqueda_publica(internos):
    from services.ia_rag.buscar import buscar
    _doc(internos, 'equipo')
    assert buscar(PALABRA, solo_publico=True) == []
    assert buscar(PALABRA, solo_publico=False), 'el panel sí debe encontrarlo'


def test_el_chat_del_sitio_no_lo_menciona(internos, chat_encendido, monkeypatch):
    from services.chat_publico import motor
    _doc(internos, 'equipo')
    monkeypatch.setattr(motor, '_registrar', lambda *a, **k: None)
    plan = motor.preparar(f'¿Qué es {PALABRA}?')
    assert PALABRA not in plan['texto_base']
    assert 'reja' not in plan['texto_base']


def test_el_visitante_no_puede_ejecutar_la_capacidad(internos):
    import services.ai_tools as tools
    _doc(internos, 'equipo')
    datos = tools.ejecutar('documentos_internos', {'texto': PALABRA}, Contexto(canal=CANAL_PUBLICO))
    assert datos.get('denegado')


def test_el_escritorio_tampoco(internos):
    import services.ai_tools as tools
    datos = tools.ejecutar('documentos_internos', {'texto': PALABRA},
                           Contexto(canal=CANAL_ESCRITORIO))
    assert datos.get('denegado')


# ── 2. Cada rol lee lo suyo ────────────────────────────────────
def test_administracion_solo_la_leen_dueno_y_superadmin(internos):
    _doc(internos, 'administracion')
    assert internos.buscar_para_rol(PALABRA, 2)
    assert internos.buscar_para_rol(PALABRA, 1)
    assert internos.buscar_para_rol(PALABRA, 4) == []     # empleado
    assert internos.buscar_para_rol(PALABRA, None) == []  # sin rol, nada


def test_equipo_la_lee_todo_el_que_usa_el_asistente(internos):
    _doc(internos, 'equipo')
    assert internos.buscar_para_rol(PALABRA, 4)
    assert internos.buscar_para_rol(PALABRA, 2)


def test_la_capacidad_filtra_por_el_rol_de_la_sesion(internos, flask_app):
    import services.ai_tools as tools
    _doc(internos, 'administracion', titulo='Solo admin')
    _doc(internos, 'equipo', titulo='Para todos')
    with flask_app.test_request_context('/'):
        session['rol_id'], session['usuario_id'] = 4, 1
        datos = tools.ejecutar('documentos_internos', {'texto': PALABRA}, tools.contexto_actual())
    assert _titulos(datos['documentos']) == {f'{MARCA} Para todos'}


def test_cambiar_la_visibilidad_no_deja_restos_en_el_indice(internos):
    doc_id = _doc(internos, 'administracion')
    internos.guardar(f'{MARCA} Apertura', f'Procedimiento {PALABRA}: abrir la reja.', 'equipo',
                     doc_id=doc_id)
    assert internos.buscar_para_rol(PALABRA, 4), 'ahora es de todo el equipo'
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT fuente FROM ia_documentos WHERE fuente_id LIKE %s",
                    (f'{doc_id}-%',))
        assert {r['fuente'] for r in cur.fetchall()} == {'interno_equipo'}


# ── 3. Archivar no borra ───────────────────────────────────────
def test_archivado_no_se_consulta_y_se_puede_restaurar(internos):
    doc_id = _doc(internos, 'equipo')
    assert internos.cambiar_estado(doc_id, False)
    assert internos.buscar_para_rol(PALABRA, 2) == []
    assert internos.obtener(doc_id) is not None, 'archivar nunca borra la fila'
    assert internos.cambiar_estado(doc_id, True)
    assert internos.buscar_para_rol(PALABRA, 2)


def test_reconstruir_todo_el_indice_conserva_los_internos_y_no_los_publica(internos):
    from services.ia_rag import indexador
    from services.ia_rag.buscar import buscar
    _doc(internos, 'equipo')
    indexador.reindexar()
    assert internos.buscar_para_rol(PALABRA, 4)
    assert buscar(PALABRA, solo_publico=True) == []


# ── Documentos largos y validaciones ───────────────────────────
def test_un_documento_largo_se_encuentra_por_su_ultima_parte(internos):
    relleno = 'Texto de relleno sobre turnos y horarios del personal. ' * 30
    texto = f'{relleno}\n\n{relleno}\n\nAl final: la clave {PALABRA} del depósito.'
    _doc(internos, 'equipo', texto=texto)
    docs = internos.buscar_para_rol(PALABRA, 2)
    assert docs and PALABRA in docs[0]['texto']


def test_partir_respeta_el_maximo_y_no_deja_partes_vacias():
    from services.ia_rag.indexador import partir
    texto = ('Frase de prueba número uno. ' * 120) + '\n\n' + 'Párrafo corto.'
    partes = partir(texto, maximo=500)
    assert len(partes) > 1
    assert all(0 < len(p) <= 500 for p in partes)
    assert partes[-1].endswith('Párrafo corto.')


@pytest.mark.parametrize('titulo, texto, visibilidad', [
    ('', 'contenido', 'equipo'),
    ('Título', '   ', 'equipo'),
    ('Título', 'contenido', 'todos'),
    ('x' * 201, 'contenido', 'equipo'),
    ('Título', 'x' * 20001, 'equipo'),
])
def test_guardar_valida_lo_que_recibe(internos, titulo, texto, visibilidad):
    with pytest.raises(ValueError):
        internos.guardar(titulo, texto, visibilidad)


def test_sin_indice_busca_directo_en_los_documentos(internos, monkeypatch):
    """Cliente sin la migración 0012: responde igual, con la misma regla de roles."""
    from services.ia_rag import indexador
    _doc(internos, 'administracion')
    monkeypatch.setattr(indexador, 'indice_disponible', lambda cur=None: False)
    assert internos.buscar_para_rol(PALABRA, 2)
    assert internos.buscar_para_rol(PALABRA, 4) == []


# ── La tabla es la misma en los dos repos ──────────────────────
def test_la_tabla_del_codigo_es_la_de_la_migracion_del_maestro():
    """El código crea la tabla si la migración 0016 aún no llegó al cliente:
    las dos definiciones deben ser idénticas. Se salta si el maestro no está al
    lado (en el servidor cada repo vive por su cuenta)."""
    import os
    import re
    from services.ia_rag import internos as servicio
    app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidatos = [os.path.join(app, *rel, 'CyberShopAdmin', 'migrations', 'tenant',
                               '0016_ia_documentos_internos.sql')
                  for rel in (('..', '..'), ('..',))]
    ruta = next((os.path.normpath(r) for r in candidatos if os.path.exists(os.path.normpath(r))), None)
    if ruta is None:
        pytest.skip('el repo del maestro no está al lado')
    with open(ruta, encoding='utf-8') as f:
        sql = re.sub(r'--[^\n]*', '', f.read())

    def normal(texto):
        return re.sub(r'\s+', ' ', texto).strip().rstrip(';').strip()
    assert normal(servicio._DDL) == normal(sql)


# ── Pantalla del dueño ─────────────────────────────────────────
def test_el_dueno_ve_la_pantalla(internos, as_propietario):
    r = as_propietario.get('/admin/ia/documentos')
    assert r.status_code == 200
    assert 'Documentos internos' in r.get_data(as_text=True)


def test_el_empleado_no_administra_documentos(internos, client):
    with client.session_transaction() as s:
        s['usuario_id'], s['rol_id'], s['username'] = 1, 4, 'PytestUser'
    r = client.get('/admin/ia/documentos')
    assert r.status_code in (302, 403)


def test_guardar_y_archivar_desde_la_pantalla(internos, as_propietario):
    r = as_propietario.post('/admin/ia/documentos/guardar', data={
        'titulo': f'{MARCA} Desde pantalla', 'texto': f'Cómo cerrar el {PALABRA}.',
        'visibilidad': 'equipo'})
    assert r.status_code == 302
    doc = next(d for d in internos.listar() if d['titulo'] == f'{MARCA} Desde pantalla')
    r = as_propietario.post(f"/admin/ia/documentos/{doc['id']}/estado", data={'activo': '0'})
    assert r.status_code == 302
    assert internos.obtener(doc['id'])['activo'] is False


def test_un_error_no_pierde_lo_escrito(internos, as_propietario):
    r = as_propietario.post('/admin/ia/documentos/guardar', data={
        'titulo': f'{MARCA} Sin contenido', 'texto': '', 'visibilidad': 'equipo'})
    assert r.status_code == 400
    assert f'{MARCA} Sin contenido' in r.get_data(as_text=True)
