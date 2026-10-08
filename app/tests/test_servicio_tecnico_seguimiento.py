# -*- coding: utf-8 -*-
"""Servicio Técnico F2: seguimientos programados, bandeja «Hoy», correos al
cliente (simulados), encuesta de satisfacción, cotizaciones sin respuesta,
configuración y resumen diario.

Contra la base de pruebas; reutiliza los fixtures de test_servicio_tecnico.
Todo lo creado se borra al final (incluidas las claves st_* de configuración)."""
import sys
from datetime import date, timedelta

import pytest

from tests.conftest import _login
from tests.test_servicio_tecnico import MARCA, _crear, dueno, limpiar, modulo  # noqa: F401  (fixtures)


@pytest.fixture()
def correos(monkeypatch):
    """Correos simulados y sin hilos: todo se ve al instante en la prueba."""
    from services import servicio_tecnico_seguimiento as seg
    enviados = []
    monkeypatch.setattr(seg, '_enviar', lambda d, a, t, h: enviados.append((d, a, t)) or True)

    class _HiloInmediato:
        def __init__(self, target, args=(), daemon=None):
            self._t, self._a = target, args

        def start(self):
            self._t(*self._a)
    monkeypatch.setattr(seg.threading, 'Thread', _HiloInmediato)
    return enviados


@pytest.fixture()
def aislado(cursor):
    """Deja la configuración st_* y los seguimientos como estaban."""
    with cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM st_seguimientos")
        tope = cur.fetchone()['m']
        cur.execute("SELECT clave FROM cliente_config WHERE clave LIKE 'st\\_%%'")
        previas = {r['clave'] for r in cur.fetchall()}
    yield
    with cursor() as cur:
        cur.execute('DELETE FROM st_seguimientos WHERE id > %s', (tope,))
        cur.execute("SELECT clave FROM cliente_config WHERE clave LIKE 'st\\_%%'")
        nuevas = {r['clave'] for r in cur.fetchall()} - previas
        if nuevas:
            cur.execute('DELETE FROM cliente_config WHERE clave = ANY(%s)', (list(nuevas),))


def _segs(cursor, orden_id):
    with cursor() as cur:
        cur.execute('SELECT tipo, estado, fecha_programada, calificacion FROM st_seguimientos WHERE orden_id = %s ORDER BY id',
                    (orden_id,))
        return [dict(r) for r in cur.fetchall()]


def _estado(dueno, orden_id, nuevo, **datos):
    return dueno.post(f'/admin/servicio-tecnico/orden/{orden_id}/estado', data={'estado': nuevo, **datos})


# ── Programación automática ─────────────────────────────────────
def test_seguimientos_nacen_y_se_cierran_con_la_orden(modulo, dueno, cursor, limpiar, aislado, correos):
    oid = _crear(dueno)
    for e in ('diagnostico', 'reparacion', 'listo'):
        _estado(dueno, oid, e)
    s = _segs(cursor, oid)
    assert [(x['tipo'], x['estado']) for x in s] == [('listo_sin_recoger', 'pendiente')]
    assert s[0]['fecha_programada'] == date.today() + timedelta(days=3)

    _estado(dueno, oid, 'entregado', valor_final='90000')
    s = {x['tipo']: x for x in _segs(cursor, oid)}
    assert s['listo_sin_recoger']['estado'] == 'omitido'
    assert s['satisfaccion']['fecha_programada'] == date.today() + timedelta(days=7)
    assert s['garantia_por_vencer']['fecha_programada'] == date.today() + timedelta(days=30 - 5)
    assert s['mantenimiento']['estado'] == 'pendiente'
    assert s['mantenimiento']['fecha_programada'] > date.today() + timedelta(days=170)


def test_garantia_y_cancelar(modulo, dueno, cursor, limpiar, aislado, correos):
    # Vuelve por garantía y queda listo otra vez: nuevo recordatorio de recoger
    oid = _crear(dueno)
    for e in ('diagnostico', 'listo', 'entregado', 'garantia', 'listo'):
        _estado(dueno, oid, e)
    assert [x['estado'] for x in _segs(cursor, oid) if x['tipo'] == 'listo_sin_recoger'] == ['omitido', 'pendiente']
    # Cancelar cierra todo lo pendiente de la orden
    otra = _crear(dueno, equipo_serial='CAN-' + MARCA, equipo_imei='')
    _estado(dueno, otra, 'diagnostico')
    with cursor() as cur:
        cur.execute("""INSERT INTO st_seguimientos (orden_id, tipo, fecha_programada)
                       VALUES (%s, 'mantenimiento', CURRENT_DATE)""", (otra,))
    _estado(dueno, otra, 'cancelado')
    assert [x['estado'] for x in _segs(cursor, otra)] == ['omitido']


# ── Correos al cliente por estado ───────────────────────────────
def test_correos_de_estado_una_sola_vez(modulo, dueno, cursor, limpiar, aislado, correos):
    oid = _crear(dueno)                               # recibido → correo
    assert [c[0] for c in correos] == ['pytest-st@ejemplo.com']
    assert 'Recibimos tu equipo' in correos[0][1] and '/servicio/' in correos[0][2]
    _estado(dueno, oid, 'diagnostico')                # sin correo
    _estado(dueno, oid, 'listo')                      # correo
    assert len(correos) == 2 and 'listo' in correos[1][1].lower()
    from services import servicio_tecnico_seguimiento as seg
    assert seg.correo_estado(oid, 'listo') is False   # no se repite
    # Reenvío a mano desde la orden: sí sale
    dueno.post(f'/admin/servicio-tecnico/orden/{oid}/correo-estado')
    assert len(correos) == 3


def test_correo_apagado_en_configuracion(modulo, dueno, cursor, limpiar, aislado, correos):
    dueno.post('/admin/servicio-tecnico/configuracion', data={'st_dias_listo': '1'})   # todos los checks vacíos
    _crear(dueno)
    assert correos == []


# ── Bandeja «Hoy» y acciones ────────────────────────────────────
def test_bandeja_whatsapp_y_completar(modulo, dueno, cursor, limpiar, aislado, correos):
    oid = _crear(dueno)
    for e in ('diagnostico', 'listo'):
        _estado(dueno, oid, e)
    with cursor() as cur:   # vencido hace 2 días
        cur.execute("UPDATE st_seguimientos SET fecha_programada = CURRENT_DATE - 2 WHERE orden_id = %s", (oid,))
        cur.execute('SELECT id FROM st_seguimientos WHERE orden_id = %s', (oid,))
        seg_id = cur.fetchone()['id']
    html = dueno.get('/admin/servicio-tecnico/hoy').get_data(as_text=True)
    assert 'Listo sin recoger' in html and 'atrasado 2 días' in html
    assert 'https://wa.me/573001234567?text=' in html and 'OS-' in html

    r = dueno.post(f'/admin/servicio-tecnico/seguimiento/{seg_id}/completar', data={'canal': 'whatsapp'},
                   headers={'X-Requested-With': 'XMLHttpRequest'})
    assert r.get_json() == {'ok': True}
    s = _segs(cursor, oid)[0]
    assert s['estado'] == 'hecho'
    from services import servicio_tecnico_service as st
    assert any(e['tipo'] == 'whatsapp' for e in st.eventos(orden_id=oid))
    # Ya hecho: no se vuelve a completar
    r = dueno.post(f'/admin/servicio-tecnico/seguimiento/{seg_id}/completar', data={'estado': 'omitido'},
                   headers={'X-Requested-With': 'XMLHttpRequest'})
    assert r.get_json() == {'ok': False}


def test_correo_desde_bandeja(modulo, dueno, cursor, limpiar, aislado, correos):
    oid = _crear(dueno)
    for e in ('diagnostico', 'listo', 'entregado'):
        _estado(dueno, oid, e)
    with cursor() as cur:
        cur.execute("SELECT id FROM st_seguimientos WHERE orden_id = %s AND tipo = 'satisfaccion'", (oid,))
        seg_id = cur.fetchone()['id']
    antes = len(correos)
    dueno.post(f'/admin/servicio-tecnico/seguimiento/{seg_id}/correo')
    assert len(correos) == antes + 1 and '¿Cómo te ha ido' in correos[-1][1]
    assert next(x for x in _segs(cursor, oid) if x['tipo'] == 'satisfaccion')['estado'] == 'hecho'


def test_cotizacion_sin_respuesta(modulo, dueno, cursor, limpiar, aislado, correos):
    with cursor() as cur:
        cur.execute("""INSERT INTO cotizaciones (cliente_nombre, cliente_telefono, total, fecha, estado)
                       VALUES (%s, '3109998877', 450000, NOW() - INTERVAL '5 days', 'pendiente') RETURNING id""",
                    (MARCA + ' Cotizado',))
        cot = cur.fetchone()['id']
    html = dueno.get('/admin/servicio-tecnico/hoy').get_data(as_text=True)
    assert 'Cotización sin respuesta' in html and '$450.000' in html and 'wa.me/573109998877' in html
    with cursor() as cur:
        cur.execute("UPDATE cotizaciones SET estado = 'aprobada' WHERE id = %s", (cot,))
    from services import servicio_tecnico_seguimiento as seg
    seg.sincronizar_cotizaciones()
    with cursor() as cur:
        cur.execute("SELECT estado FROM st_seguimientos WHERE cotizacion_id = %s", (cot,))
        assert cur.fetchone()['estado'] == 'hecho'


def test_pieza_con_revision_programa_recordatorio(modulo, dueno, cursor, limpiar, aislado, correos):
    from services import servicio_tecnico_service as st
    o = st.obtener_orden(_crear(dueno))
    proxima = date.today() + timedelta(days=700)
    dueno.post(f"/admin/servicio-tecnico/equipo/{o['equipo_id']}/cambio",
               data={'componente': 'Baterías de la UPS', 'proxima_revision': proxima.isoformat()})
    with cursor() as cur:
        cur.execute("SELECT fecha_programada FROM st_seguimientos WHERE equipo_id = %s AND tipo = 'revision_pieza'",
                    (o['equipo_id'],))
        assert cur.fetchone()['fecha_programada'] == proxima


# ── Encuesta ────────────────────────────────────────────────────
def test_encuesta_publica(modulo, dueno, client, cursor, limpiar, aislado, correos):
    from services import servicio_tecnico_service as st
    oid = _crear(dueno)
    token = st.obtener_orden(oid)['token_publico']
    assert 'name="calificacion"' not in client.get(f'/servicio/{token}').get_data(as_text=True)
    assert client.post(f'/servicio/{token}/encuesta', data={'calificacion': '5'}).status_code == 404

    for e in ('diagnostico', 'listo', 'entregado'):
        _estado(dueno, oid, e)
    assert 'name="calificacion"' in client.get(f'/servicio/{token}').get_data(as_text=True)
    client.post(f'/servicio/{token}/encuesta', data={'calificacion': '9'})
    assert all(x['calificacion'] is None for x in _segs(cursor, oid))

    r = client.post(f'/servicio/{token}/encuesta', data={'calificacion': '2', 'comentario': 'Tardaron mucho'})
    assert r.status_code == 302 and 'gracias=1' in r.headers['Location']
    s = {x['tipo']: x for x in _segs(cursor, oid)}
    assert s['satisfaccion']['calificacion'] == 2 and s['satisfaccion']['estado'] == 'hecho'
    assert s['calificacion_baja']['estado'] == 'pendiente'
    assert 'Calificación baja' in dueno.get('/admin/servicio-tecnico/hoy').get_data(as_text=True)
    # Segunda respuesta: no cambia nada
    client.post(f'/servicio/{token}/encuesta', data={'calificacion': '5'})
    assert next(x for x in _segs(cursor, oid) if x['tipo'] == 'satisfaccion')['calificacion'] == 2
    assert '¡Gracias' in client.get(f'/servicio/{token}?gracias=1').get_data(as_text=True)


# ── Configuración, menú, resumen y cron ─────────────────────────
def test_configuracion_y_plantilla(modulo, dueno, cursor, limpiar, aislado, correos):
    dueno.post('/admin/servicio-tecnico/configuracion', data={
        'st_dias_listo': '1', 'st_correo_listo': '1',
        'st_msg_listo': 'Hola {cliente}, {numero} listo. {variable_que_no_existe}fin'})
    from services import servicio_tecnico_mensajes as msj
    cfg = msj.config()
    assert cfg['st_dias_listo'] == 1 and cfg['st_correo_listo'] and not cfg['st_correo_recibido']
    oid = _crear(dueno)
    for e in ('diagnostico', 'listo'):
        _estado(dueno, oid, e)
    assert _segs(cursor, oid)[0]['fecha_programada'] == date.today() + timedelta(days=1)
    assert correos[-1][2].startswith(f'Hola {MARCA}, OS-') and correos[-1][2].endswith('listo. fin')


def test_menu_resumen_y_cron(modulo, dueno, cursor, limpiar, aislado, correos, monkeypatch, capsys):
    oid = _crear(dueno)
    for e in ('diagnostico', 'listo'):
        _estado(dueno, oid, e)
    with cursor() as cur:
        cur.execute("UPDATE st_seguimientos SET fecha_programada = CURRENT_DATE WHERE orden_id = %s", (oid,))
    from services import servicio_tecnico_seguimiento as seg
    seg._CONTEO.clear()
    html = dueno.get('/admin/servicio-tecnico/').get_data(as_text=True)
    assert 'Pendientes (' in html            # contador en el menú (grupo Soporte)

    res = seg.enviar_resumen(prueba=True)
    assert 'Listo sin recoger' in res['texto'] and 'OS-' in res['texto']

    import cron_servicio_tecnico as cron
    monkeypatch.setattr(sys, 'argv', ['cron', '--prueba'])
    assert cron.main() == 0
    assert '[PRUEBA] seguimientos para hoy o atrasados' in capsys.readouterr().out

    antes = len(correos)
    assert seg.enviar_vencidos_por_correo() >= 1        # el cliente tiene correo
    assert len(correos) > antes
    assert next(x for x in _segs(cursor, oid) if x['tipo'] == 'listo_sin_recoger')['estado'] == 'hecho'


def test_whatsapp_url_colombia():
    from services.servicio_tecnico_seguimiento import whatsapp_url
    assert whatsapp_url('300 123 4567', 'Hola') == 'https://wa.me/573001234567?text=Hola'
    assert whatsapp_url('+57 300 123 4567') == 'https://wa.me/573001234567'
    assert whatsapp_url('12345') is None


def test_roles_bandeja(modulo, client):
    _login(client, 4)
    assert client.get('/admin/servicio-tecnico/hoy').status_code == 200
    _login(client, 5)
    assert client.get('/admin/servicio-tecnico/hoy').status_code in (302, 403)
