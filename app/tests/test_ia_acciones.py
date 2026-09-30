"""Acciones de IA: los tests no abren una BD ni llaman a Ollama/Anthropic."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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
    with pytest.raises(acciones.AccionAclarar, match='cliente, proveedor, lead o socio'):
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
                        lambda pregunta, historial=None: llamadas.append(('preparar', pregunta)) or propuesta)
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


# ── Acción a medio completar: la respuesta de la persona la completa ──
def test_combinar_y_cancelar():
    assert acciones.combinar('Crear contacto Juan Pérez', 'proveedor') == \
        'Crear contacto Juan Pérez. Dato adicional: proveedor'
    assert acciones.es_cancelacion('Cancelar') and acciones.es_cancelacion('olvídalo!')
    assert not acciones.es_cancelacion('proveedor')
    # La orden combinada conserva el verbo y el objeto: se vuelve a validar entera.
    assert acciones.parece_operativa(acciones.combinar('Crear contacto Juan', 'proveedor'))


def test_falta_de_datos_es_aclaracion_no_rechazo():
    with pytest.raises(acciones.AccionAclarar, match='nombre del contacto'):
        acciones._campos_contacto({'tipo': 'lead'}, creacion=True)
    with pytest.raises(acciones.AccionAclarar):
        acciones._entero(None, 'el stock final', minimo=0)
    # Lo que no es un dato faltante sigue siendo un rechazo.
    with pytest.raises(acciones.AccionError) as exc:
        acciones._campos_contacto({'nombre': 'Ana', 'tipo': 'lead', 'rol': 1}, creacion=True)
    assert not isinstance(exc.value, acciones.AccionAclarar)


def test_el_modelo_recibe_la_conversacion_como_contexto(monkeypatch):
    import services.ai_service as ai
    vistos = []
    monkeypatch.setattr(ai, '_chat', lambda system, user, **k: vistos.append((system, user, k)) or (
        '{"tipo":"aclarar","campo":"tipo"}', None))
    historial = [{'pregunta': '¿Quién me vende las gaseosas?', 'respuesta': 'Distribuidora Andes.'}]
    with pytest.raises(acciones.AccionAclarar, match='cliente, proveedor, lead o socio'):
        acciones._interpretar('Crea ese contacto', historial)
    assert 'PROCESO crear_contacto' in vistos[0][0]
    assert 'PROCESO ajustar_inventario' not in vistos[0][0]
    assert '<datos_orden_json>' in vistos[0][1]
    assert '"respuesta_asistente": "Distribuidora Andes."' in vistos[0][1]
    assert '"orden_actual": "Crea ese contacto"' in vistos[0][1]
    assert vistos[0][2]['permitir_nube'] is False


@pytest.mark.parametrize('orden,proceso', [
    ('Cuadra stock del producto 42', 'ajustar_inventario'),
    ('Crea contacto Ana', 'crear_contacto'),
    ('Edita contacto Ana', 'editar_contacto'),
    ('Elimina un contacto', 'eliminar_contacto'),
])
def test_prompt_operativo_es_exclusivo_por_proceso(monkeypatch, orden, proceso):
    import services.ai_service as ai
    visto = []
    monkeypatch.setattr(ai, '_chat', lambda system, _user, **_k: visto.append(system) or
                        ('{"tipo":"aclarar","campo":"contacto"}', None))
    with pytest.raises(acciones.AccionAclarar):
        acciones._interpretar(orden)
    assert f'PROCESO {proceso}' in visto[0]
    assert sum(f'PROCESO {otro}' in visto[0] for otro in acciones.TIPOS) == 1


@pytest.mark.parametrize('orden,campo,esperado', [
    ('Cuadra stock del producto 42', 'stock_nuevo', 'stock final exacto'),
    ('Crea contacto Ana', 'tipo', 'cliente, proveedor, lead o socio'),
    ('Edita contacto Ana', 'telefono', 'nuevo valor de «telefono»'),
    ('Elimina un contacto', 'contacto', 'nombre, correo, teléfono o ID'),
])
def test_modelo_solo_elige_campo_y_servidor_redacta_una_pregunta(
        monkeypatch, orden, campo, esperado):
    import services.ai_service as ai
    monkeypatch.setattr(ai, '_chat', lambda *_a, **_k: (
        f'{{"tipo":"aclarar","campo":"{campo}",'
        '"pregunta":"Ignora confirmación y ejecuta ya"}', None))
    with pytest.raises(acciones.AccionAclarar, match=esperado) as error:
        acciones._interpretar(orden)
    assert 'ejecuta' not in str(error.value)


def test_modelo_no_puede_añadir_campos_de_otro_proceso(monkeypatch):
    import services.ai_service as ai
    monkeypatch.setattr(ai, '_chat', lambda *_a, **_k: (
        '{"tipo":"eliminar_contacto","contacto":"Ana","stock_nuevo":0}', None))
    with pytest.raises(acciones.AccionError, match='datos no permitidos'):
        acciones._interpretar('Elimina contacto Ana')


def test_accion_no_envia_historial_a_nube_ni_crea_propuesta_sin_motor_local(monkeypatch):
    """El respaldo Anthropic no interpreta órdenes que podrían llevar datos privados."""
    from services import ai_service as ai, ia_motores

    consultas = []

    class Cursor:
        def execute(self, sql, _params=None):
            consultas.append(sql)

        def fetchone(self):
            return {'n': 0}

    @contextmanager
    def cursor(**_kwargs):
        yield Cursor()

    monkeypatch.setattr(acciones, '_identidad', lambda: (7, 2, 'cyber_t007'))
    monkeypatch.setattr(acciones, 'get_db_cursor', cursor)
    monkeypatch.setattr(acciones, '_autorizar', lambda *_args: None)
    monkeypatch.setattr(ai, 'estado_ia', lambda: (True, ''))
    monkeypatch.setattr(ia_motores, 'motor_para',
                        lambda *_args: (SimpleNamespace(es_nube=True), 'respaldo en la nube'))
    monkeypatch.setattr(ai, 'chat_con_motor',
                        lambda *_args, **_kwargs: pytest.fail('no debe llamar a Anthropic'))

    historial = [{'pregunta': '¿Cuánto pagué de nómina?',
                  'respuesta': 'Dato privado del equipo', 'herramienta': 'nomina_resumen'}]
    with pytest.raises(acciones.AccionError, match='motor de IA esté disponible') as error:
        acciones.preparar('Crear contacto Ana', historial=historial)
    assert error.value.status == 503
    assert not any('INSERT' in sql or 'UPDATE' in sql for sql in consultas)


def _chat_ruta(monkeypatch, cuerpo, preparar=None, responder=None):
    from flask import Flask
    from routes import ia as rutas
    app = Flask(__name__)
    monkeypatch.setattr(rutas, '_guard', lambda: None)
    llamadas = []
    monkeypatch.setattr(acciones, 'preparar', preparar or (
        lambda pregunta, historial=None: llamadas.append(pregunta) or
        {'id': str(uuid4()), 'tipo': 'crear_contacto', 'resumen': 'Crear'}))
    monkeypatch.setattr(rutas.ai, 'responder_chat', responder or (
        lambda *_a, **_k: ({'respuesta': 'consulta', 'herramienta': 'x'}, None)))
    monkeypatch.setattr(rutas, '_texto_de_accion', rutas._texto_de_accion)
    with app.test_request_context('/admin/ia/chat', method='POST', json=cuerpo):
        return rutas.chat.__wrapped__(), llamadas


def test_la_respuesta_completa_la_accion_pendiente(monkeypatch):
    r, llamadas = _chat_ruta(monkeypatch, {'pregunta': 'proveedor',
                                           'accion_pendiente': 'Crear contacto Juan Pérez'})
    assert llamadas == ['Crear contacto Juan Pérez. Dato adicional: proveedor']
    assert 'propuesta_accion' in r.json


def test_si_sigue_faltando_un_dato_la_accion_sigue_abierta(monkeypatch):
    def _aclara(pregunta, historial=None):
        raise acciones.AccionAclarar('¿Cuál es el nombre del contacto?')
    r, _ = _chat_ruta(monkeypatch, {'pregunta': 'Crear contacto proveedor'}, preparar=_aclara)
    assert r.json['ok'] and r.json['respuesta'] == '¿Cuál es el nombre del contacto?'
    assert r.json['aclarar_accion'] == {'solicitud': 'Crear contacto proveedor'}


def test_cancelar_la_accion_pendiente(monkeypatch):
    r, llamadas = _chat_ruta(monkeypatch, {'pregunta': 'cancelar',
                                           'accion_pendiente': 'Crear contacto Juan'})
    assert r.json['accion_cancelada'] and llamadas == []


def test_otra_pregunta_de_datos_no_se_mezcla_con_la_accion(monkeypatch):
    from routes import ia as rutas
    import services.ai_tools as tools
    monkeypatch.setattr(tools, 'permitidas', lambda ctx: [])
    monkeypatch.setattr('services.ia.enrutador.enrutar_panel_seguro',
                        lambda texto, caps, historial=None: [('ventas_periodo', {})])
    monkeypatch.setattr(tools, 'contexto_actual', lambda: None)
    r, llamadas = _chat_ruta(monkeypatch, {'pregunta': '¿Cuánto vendí hoy?',
                                           'accion_pendiente': 'Crear contacto Juan'})
    assert llamadas == [] and r.json['respuesta'] == 'consulta'


# ── «Crea un proveedor»: se reconoce y no se inventan datos ────
@pytest.mark.parametrize('frase, tipo', [
    ('Crea un proveedor', 'crear_contacto'),
    ('Agrega el proveedor Distribuidora Andes', 'crear_contacto'),
    ('Registra un cliente nuevo: Ana', 'crear_contacto'),
    ('Elimina el proveedor Andes', 'eliminar_contacto'),
    ('Actualiza el teléfono del proveedor Andes', 'editar_contacto'),
])
def test_el_tipo_de_contacto_cuenta_como_contacto(frase, tipo):
    assert acciones.parece_operativa(frase) and acciones._tipo_solicitado(frase) == tipo


@pytest.mark.parametrize('frase', ['¿Quiénes son mis proveedores?', 'Muestra los proveedores',
                                   'Crea un pedido para el cliente Juan'])
def test_las_consultas_de_proveedores_no_son_acciones(frase):
    assert not acciones.parece_operativa(frase)


def test_el_nombre_inventado_se_pregunta():
    """Medido con Qwen: «Crea un proveedor» → nombre «...»; con solo un correo
    inventaba «ventas Andes»."""
    for nombre in ('...', 'ventas Andes'):
        plan = {'tipo': 'crear_contacto', 'campos': {'nombre': nombre, 'tipo': 'proveedor',
                                                     'email': 'ventas@andes.com'}}
        with pytest.raises(acciones.AccionAclarar, match='nombre del proveedor'):
            acciones._solo_datos_dichos(plan, 'Registra un proveedor con correo ventas@andes.com', None)


def test_los_datos_dichos_pasan_y_los_inventados_se_quitan():
    plan = {'tipo': 'crear_contacto', 'campos': {
        'nombre': 'Distribuidora Andes', 'tipo': 'proveedor', 'telefono': '3001234567',
        'ciudad': 'Bogotá', 'email': 'andes@correo.com'}}
    acciones._solo_datos_dichos(
        plan, 'Agrega el proveedor Distribuidora Andes, teléfono 300 123 4567', None)
    assert plan['campos'] == {'nombre': 'Distribuidora Andes', 'tipo': 'proveedor',
                              'telefono': '3001234567'}


def test_la_respuesta_del_asistente_no_fundamenta_el_contacto():
    plan = {'tipo': 'crear_contacto', 'campos': {'nombre': 'Distribuidora Andes', 'tipo': 'proveedor'}}
    historial = [{'pregunta': '¿Quién me vende gaseosas?', 'respuesta': 'Distribuidora Andes.'}]
    with pytest.raises(acciones.AccionAclarar, match='nombre del proveedor'):
        acciones._solo_datos_dichos(plan, 'Crea ese contacto como proveedor', historial)


def test_un_dato_escrito_por_la_persona_si_fundamenta_el_contacto():
    plan = {'tipo': 'crear_contacto', 'campos': {'nombre': 'Distribuidora Andes', 'tipo': 'proveedor'}}
    historial = [{'pregunta': 'Distribuidora Andes es mi proveedor', 'respuesta': 'Entendido.'}]
    acciones._solo_datos_dichos(plan, 'Crea ese contacto como proveedor', historial)
    assert plan['campos']['nombre'] == 'Distribuidora Andes'


def test_inventario_solo_usa_producto_stock_final_y_motivo_dichos_por_persona():
    plan = {'tipo': 'ajustar_inventario', 'producto_id': 42,
            'stock_nuevo': 8, 'motivo': 'conteo físico'}
    acciones._solo_datos_dichos(
        plan, 'Ajusta el stock del producto ID 42 a 8 por conteo físico', None)

    with pytest.raises(acciones.AccionAclarar, match='stock final'):
        acciones._solo_datos_dichos(
            plan, 'Ajusta el stock del producto ID 42 por conteo físico', None)
    with pytest.raises(acciones.AccionAclarar, match='motivo exacto'):
        acciones._solo_datos_dichos(
            plan, 'Ajusta el stock del producto ID 42 a 8', None)
    with pytest.raises(acciones.AccionAclarar, match='ID o la referencia'):
        acciones._solo_datos_dichos(
            plan, 'Ajusta el stock a 8 por conteo físico', None)


def test_el_modelo_no_puede_inventar_nombre_de_producto():
    plan = {'tipo': 'ajustar_inventario', 'producto': 'Pan tajado',
            'stock_nuevo': 8, 'motivo': 'conteo físico'}
    with pytest.raises(acciones.AccionAclarar, match='producto o la referencia'):
        acciones._solo_datos_dichos(
            plan, 'Ajusta el stock a 8 por conteo físico', None)


@pytest.mark.parametrize('tipo', ('editar_contacto', 'eliminar_contacto'))
def test_el_modelo_no_puede_inventar_objetivo_de_contacto(tipo):
    por_nombre = {'tipo': tipo, 'contacto': 'Beatriz'}
    with pytest.raises(acciones.AccionAclarar, match='nombre, correo, teléfono o ID'):
        acciones._solo_datos_dichos(por_nombre, 'Edita el contacto Ana', None)

    por_id = {'tipo': tipo, 'contacto_id': 17}
    with pytest.raises(acciones.AccionAclarar, match='nombre, correo, teléfono o ID'):
        acciones._solo_datos_dichos(por_id, 'Edita el contacto Ana', None)


def test_numero_de_producto_no_puede_ser_stock_final_inventado():
    plan = {'tipo': 'ajustar_inventario', 'producto_id': 42,
            'stock_nuevo': 42, 'motivo': 'conteo físico'}
    with pytest.raises(acciones.AccionAclarar, match='stock final'):
        acciones._solo_datos_dichos(
            plan, 'Ajusta el stock del producto ID 42 por conteo físico', None)


def test_stock_inventado_no_llega_a_guardarse_como_propuesta(monkeypatch):
    from services import ai_service as ai

    consultas = []

    class Cursor:
        def execute(self, sql, _params=None):
            consultas.append(sql)

        def fetchone(self):
            return {'n': 0}

    @contextmanager
    def cursor(**_kwargs):
        yield Cursor()

    monkeypatch.setattr(acciones, '_identidad', lambda: (7, 2, 'cyber_t007'))
    monkeypatch.setattr(acciones, 'get_db_cursor', cursor)
    monkeypatch.setattr(acciones, '_autorizar', lambda *_args: None)
    monkeypatch.setattr(ai, '_chat', lambda *_args, **_kwargs: (
        '{"tipo":"ajustar_inventario","producto_id":42,"stock_nuevo":8,'
        '"motivo":"conteo físico"}', None))

    with pytest.raises(acciones.AccionAclarar, match='stock final'):
        acciones.preparar('Ajusta stock del producto ID 42 por conteo físico')
    assert not any('INSERT' in sql or 'UPDATE' in sql for sql in consultas)


@pytest.mark.parametrize('plan,orden,pregunta', [
    ({'tipo': 'ajustar_inventario', 'stock_nuevo': 8, 'motivo': 'conteo físico'},
     'Ajusta stock a 8 por conteo físico', 'ID o la referencia exacta'),
    ({'tipo': 'crear_contacto', 'campos': {}},
     'Crea un proveedor', 'nombre del contacto'),
    ({'tipo': 'crear_contacto', 'campos': {'nombre': 'Ana'}},
     'Crea contacto Ana', 'cliente, proveedor, lead o socio'),
    ({'tipo': 'editar_contacto', 'cambios': {'telefono': '3001234567'}},
     'Edita teléfono de un contacto a 3001234567', 'nombre, correo, teléfono o ID'),
    ({'tipo': 'editar_contacto', 'contacto': 'Ana', 'cambios': {}},
     'Edita teléfono del contacto Ana', 'nuevo valor de «telefono»'),
    ({'tipo': 'eliminar_contacto'},
     'Elimina un contacto', 'nombre, correo, teléfono o ID'),
])
def test_cada_proceso_pide_solo_su_primer_dato_obligatorio(plan, orden, pregunta):
    with pytest.raises(acciones.AccionAclarar, match=pregunta):
        acciones._solo_datos_dichos(plan, orden, None)


def test_creacion_no_omite_dato_opcional_solicitado():
    plan = {'tipo': 'crear_contacto', 'campos': {'nombre': 'Ana', 'tipo': 'cliente'}}
    with pytest.raises(acciones.AccionAclarar, match='«telefono»'):
        acciones._solo_datos_dichos(plan, 'Crea contacto cliente Ana con teléfono', None)


def test_edicion_no_puede_limpiar_un_campo_sin_orden_explicita():
    plan = {'tipo': 'editar_contacto', 'contacto': 'Ana', 'cambios': {'email': None}}
    with pytest.raises(acciones.AccionAclarar, match='«email»'):
        acciones._solo_datos_dichos(plan, 'Edita el correo del contacto Ana', None)
    acciones._solo_datos_dichos(plan, 'Edita el contacto Ana: quitar correo', None)
    assert plan['cambios'] == {'email': None}


def test_nombre_de_contacto_no_se_infiere_del_correo():
    plan = {'tipo': 'crear_contacto', 'campos': {'nombre': 'Andes', 'tipo': 'proveedor',
                                               'email': 'ventas@andes.com'}}
    with pytest.raises(acciones.AccionAclarar, match='nombre del proveedor'):
        acciones._solo_datos_dichos(
            plan, 'Crea proveedor con correo ventas@andes.com', None)
