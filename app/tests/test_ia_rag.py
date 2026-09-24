# -*- coding: utf-8 -*-
"""Índice de textos del asistente (RAG).

Corre contra la BD de pruebas (`cybershop_test`/`cyber_t002`, ver conftest).
Lo que se cuida aquí, en orden de importancia:

  1. Que un documento NO público jamás salga en el canal público.
  2. Que las preguntas de siempre encuentren su respuesta.
  3. Que reindexar no duplique ni deje basura de lo borrado.
"""

import pytest

from database import get_db_cursor
from services.ia_rag import indexador
# El paquete reexporta la FUNCIÓN buscar, así que el módulo se importa explícito.
from services.ia_rag.buscar import buscar, contexto_para_modelo, expandir

MARCA = 'TEST-RAG'


@pytest.fixture()
def indice(flask_app):
    """Índice reconstruido, y limpio de restos de pruebas al terminar."""
    with flask_app.app_context():
        with get_db_cursor() as cur:
            if not indexador.indice_disponible(cur):
                pytest.skip('este cliente no tiene la migración 0012 aplicada')
        indexador.reindexar()
        yield
        with get_db_cursor() as cur:
            cur.execute("DELETE FROM ia_documentos WHERE titulo LIKE %s", (f'{MARCA}%',))


# ── Lo primero: el candado del canal público ───────────────────
def test_un_documento_interno_nunca_sale_en_el_canal_publico(flask_app, indice):
    with flask_app.app_context():
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO ia_documentos (fuente, fuente_id, titulo, texto, canal_publico, tsv)
                VALUES ('pagina', 'test-interno', %s, %s, FALSE,
                        to_tsvector('spanish', %s))
                ON CONFLICT (fuente, fuente_id) DO UPDATE
                    SET titulo = EXCLUDED.titulo, texto = EXCLUDED.texto,
                        canal_publico = FALSE, tsv = EXCLUDED.tsv
            """, (f'{MARCA} margenes internos', 'La clave del wifi es zanahoria4321',
                  f'{MARCA} margenes internos La clave del wifi es zanahoria4321'))

        publico = buscar('zanahoria4321', solo_publico=True)
        interno = buscar('zanahoria4321', solo_publico=False)

    assert publico == [], 'un documento interno se filtró al canal público'
    assert any('zanahoria4321' in (d['texto'] or '') for d in interno), \
        'el documento interno debería verse desde el panel'


def test_el_canal_publico_tampoco_lo_trae_por_parecido_ni_por_contiene(flask_app, indice):
    """Las tres pasadas del buscador deben respetar el filtro, no solo la primera."""
    with flask_app.app_context():
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO ia_documentos (fuente, fuente_id, titulo, texto, canal_publico, tsv)
                VALUES ('pagina', 'test-interno2', %s, 'secreto', FALSE, NULL)
                ON CONFLICT (fuente, fuente_id) DO UPDATE
                    SET titulo = EXCLUDED.titulo, canal_publico = FALSE, tsv = NULL
            """, (f'{MARCA} zanahoria4321',))
        # tsv NULL fuerza a caer hasta las pasadas de parecido/contiene
        assert buscar('zanahoria4321', solo_publico=True) == []


# ── Reindexar ──────────────────────────────────────────────────
def test_reindexar_es_idempotente(flask_app, indice):
    with flask_app.app_context():
        primero = indexador.reindexar()
        segundo = indexador.reindexar()
    assert 'error' not in primero and primero == segundo


def test_reindexar_borra_lo_que_ya_no_existe(flask_app, indice):
    with flask_app.app_context():
        with get_db_cursor() as cur:
            cur.execute("""
                INSERT INTO ia_documentos (fuente, fuente_id, titulo, texto, canal_publico)
                VALUES ('producto', '999999', %s, 'fantasma', TRUE)
                ON CONFLICT (fuente, fuente_id) DO NOTHING
            """, (f'{MARCA} producto borrado',))
        indexador.reindexar()
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT COUNT(*) AS n FROM ia_documentos WHERE fuente_id = '999999'")
            assert cur.fetchone()['n'] == 0


def test_el_estado_reporta_lo_que_hay(flask_app, indice):
    with flask_app.app_context():
        est = indexador.estado()
    assert est['disponible'] is True
    assert est['documentos'] >= 1
    assert est['publicos'] <= est['documentos']


# ── Preguntas reales de un visitante ───────────────────────────
# (titulo esperado o None si NO debe encontrar nada). Las que deben fallar son
# tan importantes como las otras: un buscador que siempre responde algo miente.
PREGUNTAS = [
    ('¿hacen domicilios?', 'domicilio'),
    ('¿cuánto se demora el envío?', 'env'),
    ('¿puedo pagar con Nequi?', 'pago'),
    ('¿los productos tienen garantía?', 'garant'),
    ('¿a qué hora abren?', 'horario'),
    ('¿puedo devolver un producto?', 'devolver'),
    ('domisilios', 'domicilio'),                      # con error de escritura
    ('¿cuál es el clima en Marte?', None),
    ('hola', None),
    ('aaaaaaa', None),
]


@pytest.mark.parametrize('pregunta,esperado', PREGUNTAS)
def test_las_preguntas_de_un_visitante_encuentran_su_respuesta(flask_app, indice,
                                                               pregunta, esperado):
    with flask_app.app_context():
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT COUNT(*) AS n FROM ia_documentos WHERE fuente = 'faq'")
            if not cur.fetchone()['n']:
                pytest.skip('esta base no tiene preguntas frecuentes cargadas')
        res = buscar(pregunta, solo_publico=True, limite=3)

    if esperado is None:
        assert res == [], f'«{pregunta}» no debería encontrar nada y trajo {res[:1]}'
    else:
        assert res, f'«{pregunta}» no encontró nada'
        encontrado = ' '.join(f"{d['titulo']} {d['texto']}".lower() for d in res)
        assert esperado in encontrado, f'«{pregunta}» trajo {[d["titulo"] for d in res]}'


# ── Piezas sueltas ─────────────────────────────────────────────
def test_los_sinonimos_solo_se_aplican_a_lo_conocido():
    assert expandir('¿a qué hora abren?') != '¿a qué hora abren?'
    assert 'horario' in expandir('¿a qué hora abren?')
    assert expandir('pregunta cualquiera') == 'pregunta cualquiera'


def test_el_texto_plano_quita_html_y_recorta():
    sucio = '<p>Hola <b>mundo</b></p>\n\n<script>malo()</script>&amp; final'
    limpio = indexador.texto_plano(sucio)
    assert '<' not in limpio and '&amp;' not in limpio
    assert 'Hola mundo' in limpio and '& final' in limpio
    assert len(indexador.texto_plano('x' * 9000)) <= 4000


def test_el_contexto_para_el_modelo_se_recorta():
    docs = [{'titulo': f'Doc {i}', 'texto': 'x' * 500} for i in range(10)]
    ctx = contexto_para_modelo(docs, max_caracteres=600)
    assert len(ctx) <= 620          # 600 + los saltos de línea
    assert ctx.startswith('[1] Doc 0')


def test_una_consulta_muy_corta_no_busca(flask_app, indice):
    with flask_app.app_context():
        assert buscar('a') == []
        assert buscar('') == []
        assert buscar(None) == []
