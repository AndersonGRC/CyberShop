# -*- coding: utf-8 -*-
"""«¿Te sirvió?» 👍 / 👎 en el chat del sitio (services/chat_publico/calificaciones.py).

Cada respuesta trae un `calificar` firmado con la BD de la tienda: no se puede
calificar algo que no se recibió, ni dos veces la misma respuesta. Solo un 👎
guarda la pregunta y la respuesta (lo que hay que corregir).
"""
import pytest

from database import get_db_cursor

MARCA = 'TEST-CALIF'


@pytest.fixture()
def limpio(flask_app):
    yield
    with flask_app.app_context():
        with get_db_cursor() as cur:
            cur.execute("SELECT to_regclass('public.ia_calificaciones')")
            if cur.fetchone()[0] is not None:
                cur.execute('DELETE FROM ia_calificaciones WHERE consulta_id >= 900000000')
                cur.execute('DELETE FROM ia_calificaciones WHERE pregunta LIKE %s', (f'{MARCA}%',))
            cur.execute("SELECT to_regclass('public.ia_conocimiento_log')")
            if cur.fetchone()[0] is not None:
                cur.execute('DELETE FROM ia_conocimiento_log WHERE titulo LIKE %s', (f'{MARCA}%',))


def _fila(consulta_id):
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT * FROM ia_calificaciones WHERE consulta_id = %s', (consulta_id,))
        return cur.fetchall()


def test_un_voto_por_respuesta_y_solo_el_malo_guarda_el_texto(flask_app, limpio):
    from services.chat_publico import calificaciones as c
    with flask_app.test_request_context():
        bueno = c.token(900000001, f'{MARCA} ¿abren?', 'Sí, de 8 a 6.', 'rag')
        malo = c.token(900000002, f'{MARCA} ¿hacen envíos?', 'No sé.', 'sin_respuesta')
        assert c.registrar(bueno, True) and c.registrar(malo, False)
        assert c.registrar(malo, True)                    # el segundo voto no cambia nada
        assert _fila(900000001)[0]['pregunta'] is None     # 👍: sin texto
        votos = _fila(900000002)
    assert len(votos) == 1 and votos[0]['util'] is False
    assert votos[0]['pregunta'] == f'{MARCA} ¿hacen envíos?' and votos[0]['respuesta'] == 'No sé.'


def test_un_token_falso_o_de_otra_tienda_no_vale(flask_app, limpio):
    from itsdangerous import URLSafeTimedSerializer
    from services.chat_publico import calificaciones as c
    with flask_app.test_request_context():
        assert c.registrar('inventado', False) is False
        ajeno = URLSafeTimedSerializer(flask_app.secret_key, salt='chat-calificar:otra_tienda') \
            .dumps({'c': 900000003, 'p': 'x', 'r': 'y', 'v': 'rag'})
        assert c.registrar(ajeno, False) is False
        assert c.registrar(c.token(900000004, 'a', 'b', 'rag'), 'si') is False
    with flask_app.app_context():
        assert _fila(900000003) == []


def test_la_ruta_solo_acepta_el_token_firmado(client, flask_app, chat_encendido, ip_unica, limpio):
    from services.chat_publico import calificaciones as c
    with flask_app.test_request_context():
        firmado = c.token(900000005, f'{MARCA} ¿parqueadero?', 'No.', 'rag')
    r = client.post('/chat/calificar', json={'token': 'malo', 'util': False},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 200 and r.get_json() == {'ok': False}
    r = client.post('/chat/calificar', json={'token': firmado, 'util': 'no'},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 400
    r = client.post('/chat/calificar', json={'token': firmado, 'util': False},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.get_json() == {'ok': True}
    with flask_app.app_context():
        assert len(_fila(900000005)) == 1


def test_con_el_chat_apagado_no_existe(client, chat_apagado, ip_unica):
    r = client.post('/chat/calificar', json={'token': 'x', 'util': True},
                    environ_base={'REMOTE_ADDR': ip_unica()})
    assert r.status_code == 404


def test_cada_respuesta_del_chat_trae_su_calificar(flask_app, chat_encendido, monkeypatch, limpio):
    from services.chat_publico import motor
    monkeypatch.setattr(motor, '_registrar', lambda *a, **k: 900000006)
    with flask_app.test_request_context():
        salida = motor.responder(f'{MARCA} ¿qué productos manejan?', redactar=False)
        assert salida.get('calificar')
        from services.chat_publico.calificaciones import registrar
        assert registrar(salida['calificar'], False)
        assert _fila(900000006)[0]['pregunta'] == f'{MARCA} ¿qué productos manejan?'


def test_la_base_de_conocimiento_muestra_las_que_no_sirvieron(as_propietario, flask_app, limpio):
    from services.chat_publico import calificaciones as c
    with flask_app.test_request_context():
        c.registrar(c.token(900000007, f'{MARCA} ¿tienen garantía?', 'No tengo ese dato.', 'rag'), False)
        c.registrar(c.token(900000008, f'{MARCA} ¿abren hoy?', 'Sí.', 'rag'), True)
    def seccion():
        html = as_propietario.get('/admin/chat-publico/conocimiento').data.decode('utf-8')
        return html.split('id="kbx-calif"')[1].split('id="kbx-faq"')[0]
    html = seccion()
    assert '¿Les sirvió la respuesta?' in html
    assert f'{MARCA} ¿tienen garantía?' in html and 'No tengo ese dato.' in html
    assert f'{MARCA} ¿abren hoy?' not in html                       # la buena no se lista
    as_propietario.post('/admin/chat-publico/conocimiento/descartar',
                        data={'pregunta': f'{MARCA} ¿tienen garantía?'})
    assert f'{MARCA} ¿tienen garantía?' not in seccion()             # atendida


def test_el_widget_pinta_los_botones():
    import os
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'static', 'js', 'chat_publico.js')
    with open(ruta, encoding='utf-8') as f:
        js = f.read()
    assert "agregarCalificar(datos.calificar)" in js and "'/chat/calificar'" in js
    assert 'X-CSRFToken' in js.split('function votar')[1][:800]


def test_la_tabla_del_codigo_es_la_de_la_migracion_del_maestro():
    import os
    import re
    from services.chat_publico import calificaciones
    app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidatos = [os.path.join(app, *rel, 'CyberShopAdmin', 'migrations', 'tenant',
                               '0029_ia_calificaciones.sql') for rel in (('..', '..'), ('..',))]
    ruta = next((os.path.normpath(r) for r in candidatos if os.path.exists(os.path.normpath(r))), None)
    if ruta is None:
        pytest.skip('el repo del maestro no está al lado')
    with open(ruta, encoding='utf-8') as f:
        sql = re.sub(r'--[^\n]*', '', f.read())

    def normal(texto):
        return re.sub(r'\s+', ' ', texto).strip().rstrip(';').strip()
    assert normal(calificaciones._DDL) == normal(sql)
