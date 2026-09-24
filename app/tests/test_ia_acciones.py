"""Acciones de IA: los tests no abren una BD ni llaman a Ollama/Anthropic."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from services import ia_acciones as acciones


def test_solo_orden_operativa_entra_al_planificador():
    assert acciones.parece_operativa('Cuadra inventario del producto 42')
    assert acciones.parece_operativa('Crea contacto cliente Ana')
    assert acciones.parece_operativa('Elimina el contacto 15')
    assert not acciones.parece_operativa('¿Cómo crear un contacto?')
    assert not acciones.parece_operativa('¿Cuánto stock tengo?')
    assert not acciones.parece_operativa('Sí, hazlo')


def test_modelo_no_puede_cambiar_verbo_ni_dominio():
    acciones._validar_intencion('Crea contacto Ana', 'crear_contacto')
    acciones._validar_intencion('Fijar stock del producto 42', 'ajustar_inventario')
    for frase, tipo in (
        ('Elimina contacto Ana', 'editar_contacto'),
        ('Crea contacto Ana', 'ajustar_inventario'),
        ('Elimina producto 42', 'eliminar_contacto'),
        ('Crea o elimina contacto Ana', 'crear_contacto'),
    ):
        with pytest.raises(acciones.AccionError, match='no coincide'):
            acciones._validar_intencion(frase, tipo)


def test_flag_maestro_apagado_ni_invoca_modelo(monkeypatch):
    class Cursor:
        def execute(self, _sql, _params=None):
            pass

        def fetchall(self):
            return []

    @contextmanager
    def cursor(**_kwargs):
        yield Cursor()

    monkeypatch.setattr(acciones, '_identidad', lambda: (7, 2, 'cyber_t007'))
    monkeypatch.setattr(acciones, 'get_db_cursor', cursor)
    monkeypatch.setattr(acciones, '_interpretar',
                        lambda _texto: pytest.fail('no debe invocar el modelo'))
    with pytest.raises(acciones.AccionError, match='no está habilitado'):
        acciones.preparar('Crear contacto Ana')
    with pytest.raises(acciones.AccionError, match='no coincide'):
        acciones.preparar('Eliminar producto 42')


def test_permiso_y_flags_se_revalidan_sin_cache(monkeypatch):
    class Cursor:
        def execute(self, _sql, params):
            self.clave = params[0]

        def fetchall(self):
            return [{'valor': 'false' if self.clave == 'crm_habilitado' else 'true'}]

    cur = Cursor()
    with pytest.raises(acciones.AccionError, match='módulo'):
        acciones._autorizar(cur, 'crear_contacto', 4)
    cur.fetchall = lambda: [{'valor': 'true'}]
    monkeypatch.setattr(acciones, 'resolver_para_cursor', lambda _cur: lambda *_a: False)
    with pytest.raises(acciones.AccionError, match='permiso'):
        acciones._autorizar(cur, 'crear_contacto', 4)
    monkeypatch.setattr(acciones, 'resolver_para_cursor',
                        lambda _cur: (_ for _ in ()).throw(RuntimeError('sin matriz')))
    with pytest.raises(acciones.AccionError, match='verificar los permisos'):
        acciones._autorizar(cur, 'crear_contacto', 4)


def test_exceso_de_borradores_no_gasta_modelo(monkeypatch):
    class Cursor:
        def execute(self, _sql, _params=None):
            pass

        def fetchall(self):
            return [{'valor': 'true'}]

        def fetchone(self):
            return {'n': 20}

    @contextmanager
    def cursor(**_kwargs):
        yield Cursor()

    monkeypatch.setattr(acciones, '_identidad', lambda: (7, 2, 'cyber_t007'))
    monkeypatch.setattr(acciones, 'get_db_cursor', cursor)
    monkeypatch.setattr(acciones, 'resolver_para_cursor', lambda _cur: lambda *_a: True)
    monkeypatch.setattr(acciones, '_interpretar',
                        lambda _texto: pytest.fail('no debe invocar el modelo'))
    with pytest.raises(acciones.AccionError, match='demasiadas propuestas'):
        acciones.preparar('Crear contacto Ana')


def test_campos_contacto_lista_blanca_y_datos_obligatorios():
    with pytest.raises(acciones.AccionError, match='no permitidos'):
        acciones._campos_contacto({'nombre': 'Ana', 'tipo': 'lead',
                                   'usuario_id': 1}, creacion=True)
    with pytest.raises(acciones.AccionError, match='nombre y tipo'):
        acciones._campos_contacto({'nombre': 'Ana'}, creacion=True)
    with pytest.raises(acciones.AccionError, match='correo'):
        acciones._campos_contacto({'nombre': 'Ana', 'tipo': 'lead',
                                   'email': 'incorrecto'}, creacion=True)


def test_inventario_muestra_estado_y_detecta_cambio_antes_de_escribir():
    class Cursor:
        def __init__(self, stock):
            self.stock = stock
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append((sql, params))

        def fetchall(self):
            return [{'id': 42, 'nombre': 'Camiseta', 'referencia': 'CAM-42',
                     'stock': self.stock}]

    cur = Cursor(5)
    payload, resumen, detalles = acciones._preparar_datos(cur, {
        'tipo': 'ajustar_inventario', 'producto_id': 42, 'stock_nuevo': 8,
        'motivo': 'conteo físico',
    })
    assert payload['stock_anterior'] == 5
    assert 'de 5 a 8' in resumen
    assert 'Diferencia: +3' in detalles
    cur.stock = 6
    with pytest.raises(acciones.AccionError, match='cambió'):
        acciones._ejecutar(cur, {'tipo': 'ajustar_inventario', 'payload': payload}, 7)
    assert not any('UPDATE productos' in sql for sql, _params in cur.sql)
    cur.stock = 5
    resultado = acciones._ejecutar(cur, {'tipo': 'ajustar_inventario', 'payload': payload}, 7)
    assert resultado['stock_nuevo'] == 8
    assert any('UPDATE productos' in sql for sql, _params in cur.sql)
    assert any('INSERT INTO inventario_log' in sql for sql, _params in cur.sql)


def test_contacto_edicion_rechaza_snapshot_obsoleto():
    original = {'id': 3, **{k: None for k in acciones.CONTACTO_CAMPOS}, 'activo': True}
    original.update(nombre='Ana', tipo='lead', email='ana@example.com')

    class Cursor:
        def __init__(self):
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append((sql, params))

        def fetchall(self):
            return [{**original, 'email': 'nuevo@example.com'}]

    cur = Cursor()
    with pytest.raises(acciones.AccionError, match='cambió'):
        acciones._ejecutar(cur, {'tipo': 'editar_contacto', 'payload': {
            'tipo': 'editar_contacto', 'contacto_id': 3, 'snapshot': original,
            'cambios': {'telefono': '3001234567'},
        }}, 7)
    assert not any('UPDATE crm_contactos' in sql for sql, _params in cur.sql)


def test_crear_contacto_serializa_duplicados_antes_de_insertar():
    class Cursor:
        def __init__(self):
            self.sql = []

        def execute(self, sql, params=None):
            self.sql.append(sql)

        def fetchone(self):
            if 'INSERT INTO crm_contactos' in self.sql[-1]:
                return {'id': 12}
            return None

    cur = Cursor()
    resultado = acciones._ejecutar(cur, {'tipo': 'crear_contacto', 'payload': {
        'tipo': 'crear_contacto', 'campos': {'nombre': 'Ana', 'tipo': 'lead',
                                           'email': 'ana@example.com'},
    }}, 7)
    assert resultado['contacto_id'] == 12
    assert cur.sql[0] == 'LOCK TABLE crm_contactos IN SHARE ROW EXCLUSIVE MODE'
    assert 'SELECT id FROM crm_contactos' in cur.sql[1]
    assert 'INSERT INTO crm_contactos' in cur.sql[2]


def test_confirmacion_reutilizada_no_escribe_y_exige_mismo_tenant(monkeypatch):
    pid = str(uuid4())
    seen = []

    class Cursor:
        def execute(self, sql, params=None):
            seen.append((sql, params))

        def fetchone(self):
            if seen[-1][1][2] != 'cyber_t007':
                return None
            return {'id': pid, 'tipo': 'crear_contacto', 'estado': 'ejecutada',
                    'payload': None, 'resultado': {'mensaje': 'Ya creado.'},
                    'vence_en': datetime.now(timezone.utc)}

    @contextmanager
    def cursor(**_kwargs):
        yield Cursor()

    monkeypatch.setattr(acciones, 'get_db_cursor', cursor)
    monkeypatch.setattr(acciones, '_identidad', lambda: (7, 2, 'cyber_t007'))
    monkeypatch.setattr(acciones, '_ejecutar',
                        lambda *_a: pytest.fail('no debe ejecutarse dos veces'))
    assert acciones.confirmar(pid)['ya_ejecutada'] is True
    assert seen[-1][1] == (pid, 7, 'cyber_t007')
    monkeypatch.setattr(acciones, '_identidad', lambda: (7, 2, 'cyber_t008'))
    with pytest.raises(acciones.AccionError) as exc:
        acciones.confirmar(pid)
    assert exc.value.status == 404


def test_confirmacion_vencida_cancela_y_no_ejecuta(monkeypatch):
    pid = str(uuid4())
    statements = []

    class Cursor:
        def execute(self, sql, params=None):
            statements.append(sql)

        def fetchone(self):
            return {'id': pid, 'tipo': 'crear_contacto', 'estado': 'pendiente',
                    'payload': {'tipo': 'crear_contacto'}, 'resultado': None,
                    'vence_en': datetime.now(timezone.utc) - timedelta(seconds=1)}

    @contextmanager
    def cursor(**_kwargs):
        yield Cursor()

    monkeypatch.setattr(acciones, 'get_db_cursor', cursor)
    monkeypatch.setattr(acciones, '_identidad', lambda: (7, 2, 'cyber_t007'))
    monkeypatch.setattr(acciones, '_ejecutar',
                        lambda *_a: pytest.fail('no debe ejecutar una propuesta vencida'))
    assert acciones.confirmar(pid)['ok'] is False
    assert any("estado = 'cancelada'" in sql for sql in statements)


def test_chat_operativo_solo_prepara_y_endpoint_confirma(monkeypatch):
    from flask import Flask
    from routes import ia as rutas

    app = Flask(__name__)
    monkeypatch.setattr(rutas, '_guard', lambda: None)
    propuesta = {'id': str(uuid4()), 'tipo': 'crear_contacto', 'resumen': 'Crear Ana'}
    llamadas = []
    monkeypatch.setattr(acciones, 'preparar',
                        lambda pregunta: llamadas.append(('preparar', pregunta)) or propuesta)
    monkeypatch.setattr(rutas.ai, 'responder_chat',
                        lambda *_a, **_k: pytest.fail('un comando no es consulta de lectura'))
    with app.test_request_context('/admin/ia/chat', method='POST',
                                  json={'pregunta': 'Crear contacto Ana'}):
        respuesta = rutas.chat.__wrapped__()
        assert respuesta.json['propuesta_accion'] == propuesta
    assert llamadas == [('preparar', 'Crear contacto Ana')]

    monkeypatch.setattr(acciones, 'confirmar',
                        lambda pid: llamadas.append(('confirmar', pid)) or
                        {'ok': True, 'mensaje': 'Creado'})
    with app.test_request_context('/admin/ia/acciones/confirmar', method='POST',
                                  json={'propuesta_id': propuesta['id']}):
        respuesta, status = rutas.confirmar_accion.__wrapped__()
        assert status == 200 and respuesta.json['mensaje'] == 'Creado'
    assert llamadas[-1] == ('confirmar', propuesta['id'])
