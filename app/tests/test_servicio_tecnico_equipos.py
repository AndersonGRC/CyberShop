# -*- coding: utf-8 -*-
"""Servicio Técnico: registrar equipos sin orden, fotos, validación de la ficha,
mantenimientos preventivos y correctivos, recordatorios, menú en «Soporte» y
la tarjeta de equipos en el CRM.

Contra la base de pruebas. Todo lo creado lleva la marca PYTEST-STE-<uuid> y se
borra al final; el interruptor del módulo vuelve a quedar como estaba."""
import io
import uuid
from datetime import date, timedelta

import pytest

from tests.conftest import _login
from tests.test_servicio_tecnico import IMEI_OK, modulo  # noqa: F401  (fixture)

MARCA = 'PYTEST-STE-' + uuid.uuid4().hex[:6]


@pytest.fixture()
def limpiar(cursor):
    yield
    with cursor() as cur:
        cur.execute("SELECT id FROM crm_contactos WHERE nombre LIKE %s", (MARCA + '%',))
        ids = [r['id'] for r in cur.fetchall()]
        if not ids:
            return
        cur.execute("SELECT id FROM st_ordenes WHERE crm_contacto_id = ANY(%s)", (ids,))
        ords = [r['id'] for r in cur.fetchall()]
        cur.execute("SELECT id FROM st_equipos WHERE crm_contacto_id = ANY(%s)", (ids,))
        eqs = [r['id'] for r in cur.fetchall()]
        cur.execute("DELETE FROM st_fotos WHERE equipo_id = ANY(%s)", (eqs,))
        cur.execute("DELETE FROM st_mantenimientos WHERE equipo_id = ANY(%s)", (eqs,))
        cur.execute("DELETE FROM st_seguimientos WHERE orden_id = ANY(%s) OR equipo_id = ANY(%s)", (ords, eqs))
        cur.execute("DELETE FROM st_eventos WHERE orden_id = ANY(%s) OR equipo_id = ANY(%s)", (ords, eqs))
        cur.execute("DELETE FROM st_cambios WHERE equipo_id = ANY(%s)", (eqs,))
        cur.execute("DELETE FROM st_ordenes WHERE id = ANY(%s)", (ords,))
        cur.execute("DELETE FROM st_equipos WHERE id = ANY(%s)", (eqs,))
        cur.execute("DELETE FROM crm_actividades WHERE contacto_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM crm_contactos WHERE id = ANY(%s)", (ids,))


@pytest.fixture()
def dueno(client):
    _login(client, 2)
    return client


def _imagen(formato='PNG', tamano=(64, 48), color=(200, 40, 40, 255), exif=None):
    from PIL import Image
    modo = 'RGBA' if formato == 'PNG' else 'RGB'
    img = Image.new(modo, tamano, color if modo == 'RGBA' else color[:3])
    salida = io.BytesIO()
    if exif is not None:
        img.save(salida, formato, exif=exif)
    else:
        img.save(salida, formato)
    return salida.getvalue()


def _form_equipo(**extra):
    datos = {
        'cliente_nombre': MARCA + ' Carla',
        'cliente_whatsapp': '300 765 4321',
        'cliente_email': 'pytest-ste@ejemplo.com',
        'equipo_tipo': 'celular',
        'equipo_marca': 'Xiaomi',
        'equipo_modelo': 'Redmi Note 13',
        'equipo_serial': 'SER-' + MARCA,
        'equipo_imei': IMEI_OK,
        'equipo_extra_bateria_salud': '88',
        'mant_cada_meses': '6',
    }
    datos.update(extra)
    return datos


def _registrar(dueno, fotos=(), **extra):
    datos = _form_equipo(**extra)
    if fotos:
        datos['fotos'] = [(io.BytesIO(b), n) for b, n in fotos]
    r = dueno.post('/admin/servicio-tecnico/equipos/nuevo', data=datos, content_type='multipart/form-data')
    assert r.status_code == 302, r.get_data(as_text=True)[:500]
    return int(r.headers['Location'].split('#')[0].rstrip('/').split('/')[-1])


# ── Registrar sin orden ─────────────────────────────────────────
def test_registrar_equipo_con_cliente_nuevo_fotos_y_plan(modulo, dueno, cursor, limpiar):
    from services import servicio_tecnico_seguimiento as seg
    from services import servicio_tecnico_service as st
    equipo_id = _registrar(dueno, fotos=[(_imagen(), 'frente.png'), (b'esto no es una imagen', 'falsa.jpg')])
    eq = st.obtener_equipo(equipo_id)
    assert eq['modelo'] == 'Redmi Note 13' and eq['imei'] == IMEI_OK
    assert eq['mant_cada_meses'] == 6 and eq['mant_proximo'] == seg._sumar_meses(date.today(), 6)
    with cursor() as cur:
        cur.execute('SELECT origen FROM crm_contactos WHERE id = %s', (eq['crm_contacto_id'],))
        assert cur.fetchone()['origen'] == 'servicio_tecnico'          # queda en el CRM
        cur.execute("SELECT asunto FROM crm_actividades WHERE contacto_id = %s", (eq['crm_contacto_id'],))
        assert any('equipo registrado' in r['asunto'] for r in cur.fetchall())
        cur.execute("""SELECT tipo, orden_id, fecha_programada FROM st_seguimientos
                       WHERE equipo_id = %s AND estado = 'pendiente'""", (equipo_id,))
        pend = cur.fetchall()
    assert [(p['tipo'], p['orden_id'], p['fecha_programada']) for p in pend] == [
        ('mantenimiento', None, eq['mant_proximo'])]
    # La foto válida se guarda reducida a JPEG; la falsa se rechaza sin tumbar el registro.
    fotos = st.fotos_de_equipo(equipo_id)
    assert len(fotos) == 1 and fotos[0]['momento'] == 'recepcion'
    mime, contenido = st.foto_contenido(fotos[0]['id'])
    assert mime == 'image/jpeg' and contenido[:2] == b'\xff\xd8'


def test_registrar_con_imei_invalido_no_crea_nada(modulo, dueno, cursor, limpiar):
    r = dueno.post('/admin/servicio-tecnico/equipos/nuevo', data=_form_equipo(equipo_imei='490154203237519'))
    assert r.status_code == 400 and 'IMEI' in r.get_data(as_text=True)
    with cursor() as cur:
        cur.execute('SELECT COUNT(*) AS n FROM crm_contactos WHERE nombre LIKE %s', (MARCA + '%',))
        assert cur.fetchone()['n'] == 0


def test_registrar_desde_el_crm_con_cliente_existente(modulo, dueno, cursor, limpiar):
    from services import servicio_tecnico_service as st
    with cursor() as cur:
        cur.execute("""INSERT INTO crm_contactos (tipo, nombre, whatsapp) VALUES ('cliente', %s, '3001112233')
                       RETURNING id""", (MARCA + ' Dario',))
        cid = cur.fetchone()['id']
    html = dueno.get(f'/admin/servicio-tecnico/equipos/nuevo?cliente={cid}').get_data(as_text=True)
    assert MARCA + ' Dario' in html and 'name="fotos"' in html and 'mant_cada_meses' in html
    equipo_id = _registrar(dueno, crm_contacto_id=str(cid), cliente_nombre='', equipo_tipo='ups',
                           equipo_imei='', equipo_marca='APC', equipo_modelo='BX1000', mant_cada_meses='',
                           mant_proximo=(date.today() + timedelta(days=20)).isoformat())
    eq = st.obtener_equipo(equipo_id)
    assert eq['crm_contacto_id'] == cid and eq['tipo'] == 'ups' and eq['mant_cada_meses'] is None
    assert eq['mant_proximo'] == date.today() + timedelta(days=20)
    # La ficha del contacto en el CRM muestra el equipo y los accesos.
    crm = dueno.get(f'/admin/crm/contactos/{cid}').get_data(as_text=True)
    assert 'Equipos en servicio técnico' in crm and 'APC BX1000' in crm
    assert f'/admin/servicio-tecnico/equipo/{equipo_id}' in crm
    assert f'/admin/servicio-tecnico/equipos/nuevo?cliente={cid}' in crm


def test_el_crm_no_muestra_equipos_con_el_modulo_apagado(modulo, dueno, cursor, limpiar):
    with cursor() as cur:
        cur.execute("""INSERT INTO crm_contactos (tipo, nombre) VALUES ('cliente', %s) RETURNING id""",
                    (MARCA + ' Elsa',))
        cid = cur.fetchone()['id']
    modulo(False)
    r = dueno.get(f'/admin/crm/contactos/{cid}')
    assert r.status_code == 200 and 'Equipos en servicio técnico' not in r.get_data(as_text=True)
    assert dueno.get('/admin/servicio-tecnico/equipos/nuevo').status_code == 302


# ── Fotos ───────────────────────────────────────────────────────
def test_preparar_foto_reduce_gira_y_quita_metadatos():
    from PIL import Image

    from services import servicio_tecnico_service as st
    exif = Image.Exif()
    exif[0x0112] = 6                       # orientación: girar 90°
    exif[0x010F] = 'CamaraDePrueba'        # marca de la cámara
    grande, mini, ancho, alto = st.preparar_foto(_imagen('JPEG', (3000, 1000), exif=exif))
    assert alto == 1600 and ancho in (533, 534)    # girada y reducida al lado mayor
    img = Image.open(io.BytesIO(grande))
    assert img.format == 'JPEG' and not img.getexif()
    assert max(Image.open(io.BytesIO(mini)).size) == 360
    with pytest.raises(st.ErrorServicio):
        st.preparar_foto(b'%PDF-1.4 no es imagen')
    with pytest.raises(st.ErrorServicio):
        st.preparar_foto(b'')


def test_fotos_en_la_ficha_solo_con_sesion_y_quitar_no_borra(modulo, dueno, client, cursor, limpiar, monkeypatch):
    from services import servicio_tecnico_service as st
    equipo_id = _registrar(dueno)
    r = dueno.post(f'/admin/servicio-tecnico/equipo/{equipo_id}/fotos', content_type='multipart/form-data',
                   data={'momento': 'etiqueta', 'descripcion': 'Etiqueta trasera',
                         'fotos': [(io.BytesIO(_imagen()), 'a.png'), (io.BytesIO(_imagen('JPEG')), 'b.jpg')]})
    assert r.status_code == 302 and r.headers['Location'].endswith('#fotos')
    fotos = st.fotos_de_equipo(equipo_id)
    assert len(fotos) == 2 and {f['momento'] for f in fotos} == {'etiqueta'}
    foto = fotos[0]['id']
    r = dueno.get(f'/admin/servicio-tecnico/foto/{foto}/mini')
    assert r.status_code == 200 and r.mimetype == 'image/jpeg' and 'private' in r.headers['Cache-Control']
    # Sin sesión no se ve.
    anon = client.application.test_client()
    assert anon.get(f'/admin/servicio-tecnico/foto/{foto}').status_code in (302, 401, 403)
    # Quitar: deja de verse pero queda guardada.
    dueno.post(f'/admin/servicio-tecnico/foto/{foto}/quitar')
    assert dueno.get(f'/admin/servicio-tecnico/foto/{foto}').status_code == 404
    with cursor() as cur:
        cur.execute('SELECT activo FROM st_fotos WHERE id = %s', (foto,))
        assert cur.fetchone()['activo'] is False
    # Límite de fotos por equipo.
    monkeypatch.setattr(st, 'FOTOS_MAX', 2)
    guardadas, errores = st.guardar_fotos(equipo_id, [_Archivo(_imagen(), 'c.png'), _Archivo(_imagen(), 'd.png')])
    assert guardadas == 1 and errores and 'ya tiene 2 fotos' in errores[0]


class _Archivo:
    def __init__(self, datos, nombre):
        self._datos, self.filename = datos, nombre

    def read(self, n=-1):
        return self._datos


# ── Mantenimientos ──────────────────────────────────────────────
def test_mantenimiento_preventivo_cierra_el_aviso_y_programa_el_siguiente(modulo, dueno, cursor, limpiar):
    from services import servicio_tecnico_seguimiento as seg
    from services import servicio_tecnico_service as st
    equipo_id = _registrar(dueno)            # plan cada 6 meses
    r = dueno.post(f'/admin/servicio-tecnico/equipo/{equipo_id}/mantenimiento',
                   data={'tipo': 'preventivo', 'descripcion': 'Limpieza y cambio de pasta térmica',
                         'hallazgos': 'Mucho polvo', 'costo': '60.000'})
    assert r.status_code == 302 and r.headers['Location'].endswith('#mantenimientos')
    siguiente = seg._sumar_meses(date.today(), 6)
    with cursor() as cur:
        cur.execute("""SELECT estado, fecha_programada FROM st_seguimientos
                       WHERE equipo_id = %s AND tipo = 'mantenimiento' ORDER BY id""", (equipo_id,))
        filas = [(f['estado'], f['fecha_programada']) for f in cur.fetchall()]
    assert filas[0][0] == 'hecho' and filas[-1] == ('pendiente', siguiente)
    assert sum(1 for e, _ in filas if e == 'pendiente') == 1
    eq = st.obtener_equipo(equipo_id)
    assert eq['mant_proximo'] == siguiente
    m = st.mantenimientos_de_equipo(equipo_id)
    assert m[0]['tipo'] == 'preventivo' and float(m[0]['costo']) == 60000 and m[0]['proxima_fecha'] == siguiente
    # Correctivo con fecha futura o próxima anterior: no.
    with pytest.raises(st.ErrorServicio):
        st.registrar_mantenimiento(equipo_id, {'tipo': 'correctivo', 'descripcion': 'x',
                                               'fecha': (date.today() + timedelta(days=1)).isoformat()})
    with pytest.raises(st.ErrorServicio):
        st.registrar_mantenimiento(equipo_id, {'tipo': 'correctivo', 'descripcion': 'x',
                                               'proxima_fecha': date.today().isoformat()})
    with pytest.raises(st.ErrorServicio):
        st.registrar_mantenimiento(equipo_id, {'tipo': 'otro', 'descripcion': 'x'})
    st.registrar_mantenimiento(equipo_id, {'tipo': 'correctivo', 'descripcion': 'Cambio de pin de carga'})
    html = dueno.get(f'/admin/servicio-tecnico/equipo/{equipo_id}').get_data(as_text=True)
    assert 'Historial del equipo' in html and 'Cambio de pin de carga' in html and 'Mantenimiento preventivo' in html


def test_plan_del_equipo_reemplaza_el_aviso_general_al_entregar(modulo, dueno, cursor, limpiar):
    from services import servicio_tecnico_service as st
    equipo_id = _registrar(dueno)
    eq = st.obtener_equipo(equipo_id)
    orden = dueno.post('/admin/servicio-tecnico/nueva', data={
        'crm_contacto_id': str(eq['crm_contacto_id']), 'equipo_id': str(equipo_id),
        'falla_reportada': 'No enciende', 'garantia_dias': '0'})
    orden_id = int(orden.headers['Location'].rstrip('/').split('/')[-1])
    for nuevo in ('reparacion', 'listo', 'entregado'):
        dueno.post(f'/admin/servicio-tecnico/orden/{orden_id}/estado', data={'estado': nuevo})
    with cursor() as cur:
        cur.execute("""SELECT orden_id FROM st_seguimientos
                       WHERE equipo_id = %s AND tipo = 'mantenimiento' AND estado = 'pendiente'""", (equipo_id,))
        assert [r['orden_id'] for r in cur.fetchall()] == [None]     # solo el del plan


def test_plan_por_equipo_no_se_pisa_entre_equipos(modulo, dueno, cursor, limpiar):
    a = _registrar(dueno)
    b = _registrar(dueno, cliente_nombre=MARCA + ' Fabio', equipo_serial='OTRO-' + MARCA, equipo_imei='')
    with cursor() as cur:
        cur.execute("""SELECT equipo_id FROM st_seguimientos WHERE equipo_id = ANY(%s)
                       AND tipo = 'mantenimiento' AND estado = 'pendiente' ORDER BY equipo_id""", ([a, b],))
        assert [r['equipo_id'] for r in cur.fetchall()] == sorted([a, b])


# ── Recordatorios ───────────────────────────────────────────────
def test_recordatorio_manual_en_la_bandeja_y_en_la_ficha(modulo, dueno, cursor, limpiar):
    from services import servicio_tecnico_seguimiento as seg
    equipo_id = _registrar(dueno, mant_cada_meses='')
    hoy = date.today().isoformat()
    dueno.post(f'/admin/servicio-tecnico/equipo/{equipo_id}/recordatorio',
               data={'fecha': hoy, 'motivo': 'Ofrecer cambio a SSD', 'canal': 'whatsapp'})
    dueno.post(f'/admin/servicio-tecnico/equipo/{equipo_id}/recordatorio',
               data={'fecha': hoy, 'motivo': 'Pedir el repuesto al proveedor', 'canal': 'interno'})
    r = dueno.post(f'/admin/servicio-tecnico/equipo/{equipo_id}/recordatorio',
                   data={'fecha': (date.today() - timedelta(days=1)).isoformat(), 'motivo': 'tarde'})
    pendientes, _ = seg.de_equipo(equipo_id)
    assert sorted(p['motivo'] for p in pendientes) == ['Ofrecer cambio a SSD', 'Pedir el repuesto al proveedor']
    cliente = next(p for p in pendientes if p['canal'] == 'whatsapp')
    interno = next(p for p in pendientes if p['canal'] == 'interno')
    assert 'Ofrecer cambio a SSD' in cliente['mensaje'] and cliente['wa_url'].startswith('https://wa.me/57300')
    assert interno['wa_url'] is None and not interno['tiene_correo'] and interno['tipo_nombre'] == 'Recordatorio interno'
    # Aparecen en «Hoy» y se atienden desde la ficha (vuelve a la ficha).
    html = dueno.get('/admin/servicio-tecnico/hoy').get_data(as_text=True)
    assert 'Ofrecer cambio a SSD' in html and 'Pedir el repuesto al proveedor' in html
    volver = f'/admin/servicio-tecnico/equipo/{equipo_id}#recordatorios'
    r = dueno.post(f"/admin/servicio-tecnico/seguimiento/{interno['id']}/completar", data={'volver': volver})
    assert r.headers['Location'].endswith(volver)
    assert [p['motivo'] for p in seg.de_equipo(equipo_id)[0]] == ['Ofrecer cambio a SSD']


# ── Validación de la ficha ──────────────────────────────────────
def test_validacion_de_la_ficha(modulo, dueno, limpiar):
    from services import servicio_tecnico_service as st
    equipo_id = _registrar(dueno, fotos=[(_imagen(), 'f.png')])
    v = st.validacion_equipo(st.obtener_equipo(equipo_id), fotos=1)
    textos = [t for _, t, _ in v['revisiones']]
    assert v['errores'] == 0 and 'IMEI correcto' in textos
    assert any(t.startswith('Mantenimiento programado') for t in textos)
    malo = dict(st.obtener_equipo(equipo_id), imei='490154203237519', marca=None, mant_proximo=None)
    v2 = st.validacion_equipo(malo, fotos=0)
    assert v2['errores'] == 1 and v2['puntaje'] < v['puntaje']
    # Lo que falta dice dónde arreglarlo.
    assert ('aviso', 'Falta la marca', 'editar') in v2['revisiones']
    assert ('aviso', 'No tiene fotos del equipo', 'fotos') in v2['faltan']
    assert ('error', 'El IMEI está mal escrito: revísalo', 'editar') in v2['faltan']
    html = dueno.get(f'/admin/servicio-tecnico/equipo/{equipo_id}').get_data(as_text=True)
    # Una sola página: lo que falta, el índice y las cuatro secciones.
    assert 'Para completar la ficha' in html and 'Pegar información' in html
    for seccion in ('id="datos"', 'id="fotos"', 'id="mantenimiento"', 'id="historial"'):
        assert seccion in html
    assert 'role="tablist"' not in html
    assert f'/admin/servicio-tecnico/foto/' in html and 'Recordatorios pendientes' in html


# ── Menú: el módulo vive en «Soporte» ───────────────────────────
def _menu(flask_app, client):
    from helpers import get_data_app
    with flask_app.test_request_context('/'):
        from flask import session
        session['rol_id'] = 2
        session['usuario_id'] = 1
        return {g['nombre']: [s['nombre'] for s in g.get('submodulos') or []]
                for g in get_data_app()['MenuAppindex']}


def test_menu_soporte_con_y_sin_servicio_tecnico(modulo, flask_app, client):
    import tenant_features as tf
    con = _menu(flask_app, client)
    assert 'Servicio Técnico' not in con
    # Tres entradas del taller: lo demás (recibir, registrar, ajustes) está dentro del módulo.
    taller = [n for n in con['Soporte'] if n not in ('Tickets clientes', 'Configuración')]
    assert taller[0] == 'Servicio técnico' and taller[1].startswith('Pendientes') and taller[2] == 'Equipos'
    assert len(taller) == 3
    modulo(False)
    sin = _menu(flask_app, client)
    soporte_activo = tf.is_module_active(tf.MODULE_SUPPORT)
    if soporte_activo:
        # Las demás tiendas ven Soporte igual que antes.
        assert sin['Soporte'] == ['Tickets clientes', 'Configuración']
    else:
        assert 'Soporte' not in sin
