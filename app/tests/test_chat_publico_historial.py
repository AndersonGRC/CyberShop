# -*- coding: utf-8 -*-
"""services/chat_publico/historial.py::preguntas_sin_responder() (F9).

Lee ia_consultas (la misma tabla que llena motor.py::_registrar() en cada
respuesta del chat público) filtrando por canal público, y purga a los 90
días — purga propia, independiente de la de services/ai_service.py, porque
ai_public puede estar activo sin ai_assistant."""
import pytest

from database import get_db_cursor
from services.chat_publico.historial import preguntas_sin_responder
from services.ia_datos.acceso import CANAL_PUBLICO

_DDL = """
CREATE TABLE IF NOT EXISTS ia_consultas (
    id BIGSERIAL PRIMARY KEY,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    usuario_id INTEGER,
    rol_id INTEGER,
    canal VARCHAR(20) NOT NULL DEFAULT 'web',
    herramientas TEXT[] NOT NULL DEFAULT '{}',
    ok BOOLEAN NOT NULL DEFAULT TRUE,
    error VARCHAR(300),
    ms INTEGER,
    sensible VARCHAR(40),
    objetivo VARCHAR(120),
    pregunta_sin_herramienta VARCHAR(200),
    intencion VARCHAR(40),
    via VARCHAR(20),
    motor VARCHAR(4),
    documentos BIGINT[]
);
"""


@pytest.fixture()
def limpiar_consultas_test():
    yield
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM ia_consultas WHERE pregunta_sin_herramienta LIKE 'TEST-%%'")


def _insertar(cur, pregunta, canal=CANAL_PUBLICO, dias_atras=0):
    cur.execute(_DDL)
    cur.execute(
        """INSERT INTO ia_consultas (canal, herramientas, ok, ms, pregunta_sin_herramienta,
                                     via, creado_en)
           VALUES (%s, '{}', TRUE, 5, %s, 'sin_respuesta', NOW() - make_interval(days => %s))""",
        (canal, pregunta, dias_atras))


def test_solo_trae_preguntas_del_canal_publico(limpiar_consultas_test):
    with get_db_cursor() as cur:
        _insertar(cur, 'TEST-publica', canal=CANAL_PUBLICO)
        _insertar(cur, 'TEST-del-panel', canal='web')
    resultado = [p['pregunta'] for p in preguntas_sin_responder()]
    assert 'TEST-publica' in resultado
    assert 'TEST-del-panel' not in resultado


def test_respeta_el_limite(limpiar_consultas_test):
    with get_db_cursor() as cur:
        for i in range(5):
            _insertar(cur, f'TEST-limite-{i}')
    resultado = preguntas_sin_responder(limite=3)
    assert len(resultado) <= 3


def test_purga_preguntas_de_mas_de_90_dias(limpiar_consultas_test):
    with get_db_cursor() as cur:
        _insertar(cur, 'TEST-vieja', dias_atras=100)
    antes = [p['pregunta'] for p in preguntas_sin_responder()]
    assert 'TEST-vieja' not in antes, 'una pregunta de hace 100 dias no deberia seguir apareciendo'
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute("SELECT pregunta_sin_herramienta FROM ia_consultas "
                    "WHERE canal = %s AND ms = 5 AND creado_en < NOW() - INTERVAL '90 days' "
                    "ORDER BY id DESC LIMIT 1", (CANAL_PUBLICO,))
        fila = cur.fetchone()
    assert fila is not None and fila['pregunta_sin_herramienta'] is None, \
        'la purga deberia haber puesto pregunta_sin_herramienta en NULL'


def test_no_revienta_si_la_tabla_no_existe_aun(limpiar_consultas_test, monkeypatch):
    """to_regclass devuelve NULL si la tabla no existe en un tenant nuevo."""
    import services.chat_publico.historial as historial_mod

    class _CursorFalso:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return {'t': None}

    monkeypatch.setattr(historial_mod, 'get_db_cursor', lambda dict_cursor=True: _CursorFalso())
    assert preguntas_sin_responder() == []
