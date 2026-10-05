# -*- coding: utf-8 -*-
"""El taller en el asistente IA del panel: las 5 consultas de Servicio Técnico,
su enrutamiento por palabras, permisos por rol/módulo y que nunca expongan la
clave del equipo ni el enlace público.

Contra la base de pruebas; reutiliza los fixtures de test_servicio_tecnico."""
import json

import pytest

from services.ia_datos.acceso import Contexto
from tests.test_servicio_tecnico import MARCA, _crear, dueno, limpiar, modulo  # noqa: F401  (fixtures)

DUENO = Contexto(rol_id=2, usuario_id=1)
CONTADOR = Contexto(rol_id=5, usuario_id=1)


def _ej(code, params=None, ctx=DUENO):
    import services.ia_datos as d
    return d.ejecutar(code, params or {}, ctx)


@pytest.fixture()
def taller(modulo, dueno, limpiar, cursor):
    """Tres órdenes: una lista hace 4 días, una en reparación con promesa vencida y una entregada calificada."""
    from services import servicio_tecnico_seguimiento as seg
    from services import servicio_tecnico_service as st
    lista = _crear(dueno)
    for e in ('diagnostico', 'listo'):
        st.cambiar_estado(lista, e)
    vencida = _crear(dueno, equipo_serial='VEN-' + MARCA, equipo_imei='', equipo_tipo='portatil',
                     equipo_marca='Lenovo', equipo_modelo='IdeaPad 3', fecha_promesa='2026-01-05')
    st.cambiar_estado(vencida, 'reparacion')
    entregada = _crear(dueno, equipo_serial='ENT-' + MARCA, equipo_imei='')
    for e in ('diagnostico', 'listo'):
        st.cambiar_estado(entregada, e)
    st.cambiar_estado(entregada, 'entregado', datos={'valor_final': '150000'})
    seg.registrar_encuesta(st.obtener_orden(entregada), 2, 'Demoraron')
    with cursor() as cur:
        cur.execute("UPDATE st_ordenes SET fecha_listo = NOW() - INTERVAL '4 days' WHERE id = %s", (lista,))
        cur.execute("UPDATE st_seguimientos SET fecha_programada = CURRENT_DATE - 1 WHERE orden_id = %s", (lista,))
    return {'lista': lista, 'vencida': vencida, 'entregada': entregada}


def _sin_secretos(resultado):
    texto = json.dumps(resultado, ensure_ascii=False, default=str)
    assert 'patron-L-1234' not in texto and 'clave_cifrada' not in texto and 'token' not in texto


def test_estado_del_taller(taller):
    r = _ej('taller_estado')
    _sin_secretos(r)
    assert r['equipos_en_taller'] == 2 and r['listos_para_entregar'] == 1
    ordenes = {o['orden']: o for o in r['ordenes']}
    lista = ordenes[f"OS-{taller['lista']:06d}"]
    assert lista['estado'] == 'Listo para entregar' and lista['dias_listo_sin_recoger'] == 4
    assert ordenes[f"OS-{taller['vencida']:06d}"]['promesa_vencida'] is True
    assert f"OS-{taller['vencida']:06d}" in r['promesas_vencidas']


def test_seguimientos_y_calificacion_baja(taller):
    r = _ej('taller_seguimientos')
    _sin_secretos(r)
    que = [s['que_hacer'] for s in r['seguimientos']]
    assert que[0].startswith('Calificación baja') and r['seguimientos'][0]['urgente']
    assert 'Listo sin recoger' in que
    assert 'calificaron mal' in r['nota']


def test_una_orden_por_numero_y_por_cliente(taller):
    num = f"OS-{taller['vencida']:06d}"
    r = _ej('taller_orden', {'texto': num})
    _sin_secretos(r)
    o = r['ordenes'][0]
    assert o['orden'] == num and o['estado'] == 'En reparación' and 'Lenovo IdeaPad 3' in o['equipo']
    assert o['falla_reportada'] == 'No carga y se calienta' and o['ultimos_movimientos']
    assert _ej('taller_orden', {'texto': str(taller['vencida'])})['ordenes'][0]['orden'] == num
    por_cliente = _ej('taller_orden', {'texto': MARCA})
    assert por_cliente['ordenes_encontradas'] == 3
    assert 'No encontré' in _ej('taller_orden', {'texto': 'OS-9999999'})['conclusion']


def test_historial_de_equipos(taller):
    r = _ej('taller_equipo_historial', {'texto': MARCA})
    _sin_secretos(r)
    assert r['equipos_encontrados'] == 3
    por_serial = _ej('taller_equipo_historial', {'texto': 'VEN-' + MARCA})
    assert por_serial['equipos_encontrados'] == 1 and por_serial['equipos'][0]['servicios'][0]['estado'] == 'En reparación'
    por_imei = _ej('taller_equipo_historial', {'texto': '490154203237518'})
    assert any(e['imei'] == '490154203237518' for e in por_imei['equipos'])


def test_desempeno_solo_agregados(taller):
    r = _ej('taller_desempeno', {'periodo': 'mes'})
    assert r['ordenes_recibidas'] >= 3 and r['equipos_entregados'] >= 1
    assert r['satisfaccion']['respuestas'] >= 1 and r['satisfaccion']['calificaciones_bajas'] >= 1
    texto = json.dumps(r, ensure_ascii=False, default=str)
    assert MARCA not in texto                       # sin nombres: puede ir a la nube


def test_permisos_y_nube(taller, modulo):
    import services.ia_datos as d
    assert _ej('taller_estado', ctx=CONTADOR).get('denegado')
    codigos = {h.code for h in d.permitidas(DUENO)}
    assert {'taller_estado', 'taller_seguimientos', 'taller_orden', 'taller_equipo_historial', 'taller_desempeno'} <= codigos
    reg = d.REGISTRO
    assert all(reg[c].extra.get('nube') is False
               for c in ('taller_estado', 'taller_seguimientos', 'taller_orden', 'taller_equipo_historial'))
    assert reg['taller_desempeno'].extra.get('nube', True) is not False
    modulo(False)
    assert not ({h.code for h in d.permitidas(DUENO)} & {'taller_estado', 'taller_orden'})


def test_enrutamiento_por_palabras():
    import services.ia_datos as d
    from services.ia.enrutador import enrutar
    caps = list(d.REGISTRO.values())
    assert enrutar('¿Cómo está el taller?', caps)[0][0] == 'taller_estado'
    assert enrutar('¿Qué equipos están listos para entregar?', caps)[0][0] == 'taller_estado'
    code, params = enrutar('¿Cómo va la orden OS-000012?', caps)[0]
    assert code == 'taller_orden' and params['texto'] == 'OS-000012'
    code, params = enrutar('¿Qué equipos tiene Laura Gómez?', caps)[0]
    assert code == 'taller_equipo_historial' and params['texto'] == 'Laura Gómez'
    assert enrutar('¿Cómo le fue al taller este mes?', caps)[0][0] == 'taller_desempeno'
    # El CRM conserva sus frases
    assert enrutar('¿A quién tengo que llamar hoy?', caps)[0][0] == 'crm_seguimiento'


def test_sin_modulo_responde_claro(flask_app, monkeypatch):
    from services.ia_datos import servicio_tecnico as stc
    monkeypatch.setattr(stc, '_existe', lambda cur, tabla: False)
    with flask_app.app_context():
        assert 'Servicio Técnico' in stc.taller_estado()['conclusion']


def test_chat_del_panel_responde_del_taller_sin_modelo(taller, flask_app, monkeypatch):
    """Pregunta escrita en el chat del panel → enrutador → consulta real del
    taller → respuesta con los datos, sin cargar ningún modelo."""
    import services.ai_service as ai
    import services.ai_tools as tools
    from services import ia_motores
    monkeypatch.setattr(ai, '_contexto_tenant', lambda: 'Taller de prueba')
    monkeypatch.setattr(ai, '_contexto_panel', lambda: 'Taller de prueba')
    monkeypatch.setattr(ai, '_modelo_en_memoria',
                        lambda *_: (_ for _ in ()).throw(AssertionError('no debe esperar Ollama')))
    monkeypatch.setattr(ai, '_chat',
                        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError('no debe llamar modelo')))
    monkeypatch.setattr(ai, '_registrar_consulta', lambda *args: None)
    monkeypatch.setattr(ia_motores, 'motor_para', lambda *_a, **_k: (None, 'sin motor'))
    with flask_app.test_request_context('/'):
        res, err = ai.responder_chat('¿Qué equipos están listos para entregar?',
                                     contexto=tools.Contexto(rol_id=2, usuario_id=1))
    assert err is None
    assert f"OS-{taller['lista']:06d}" in res['respuesta'] and 'patron-L-1234' not in res['respuesta']


def test_sugerencias_del_taller_en_el_panel(modulo, dueno, monkeypatch):
    import tenant_features as tf
    monkeypatch.setattr('services.ai_service.estado_ia', lambda: (True, 'ok'))
    orig = tf.is_module_active
    monkeypatch.setattr(tf, 'is_module_active', lambda code, *a, **k: True if code == 'ai_assistant' else orig(code, *a, **k))
    r = dueno.get('/admin/ia/')
    assert r.status_code == 200 and '¿Cómo está el taller?' in r.get_data(as_text=True)
    modulo(False)
    assert '¿Cómo está el taller?' not in dueno.get('/admin/ia/').get_data(as_text=True)
