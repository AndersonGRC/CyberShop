# -*- coding: utf-8 -*-
"""Servicio Técnico F3: lector de la información del sistema, propuestas de la
IA (simulada), privacidad de lo que recibe el modelo, sugerencias de mejora,
pre-diagnóstico, especificaciones y mensajes.

La IA real nunca se llama: `_chat` se reemplaza y se revisa lo que recibe."""
import json
from datetime import date

import pytest

from services import servicio_tecnico_ia as st_ia
from services import servicio_tecnico_lector as lector
from services.servicio_tecnico_clasificador import _por_ia as _POR_IA_REAL  # antes de que conftest la reemplace
from tests.test_servicio_tecnico import MARCA, _crear, dueno, limpiar, modulo  # noqa: F401  (fixtures)

WINDOWS = """Nombre de host:                            DESKTOP-ANA123
Nombre del sistema operativo:              Microsoft Windows 10 Pro
Versión del sistema operativo:             10.0.19045 N/D Compilación 19045
Fabricante del sistema operativo:          Microsoft Corporation
Propietario registrado:                    Ana Pérez
Id. del producto:                          00330-80000-00000-AA123
Fabricante del sistema:                    LENOVO
Modelo el sistema:                         81WE IdeaPad 3 15IIL05
Procesador(es):                            1 Procesadores instalados.
                                           [01]: Intel64 Family 6 Model 126 Stepping 5 GenuineIntel ~1190 Mhz
Memoria física total:                      7.987 MB
Dominio:                                   WORKGROUP
CPU-Z: Intel(R) Core(TM) i5-1035G1 CPU @ 1.00GHz
Ranuras de memoria: 2
Ranuras usadas: 1
Unidad de disco: WDC WD10SPZX HDD 1000 GB
DESIGN CAPACITY 45.000 mWh
FULL CHARGE CAPACITY 29.250 mWh
Correo: ana.perez@gmail.com  Celular 300 123 4567"""

ANDROID = """Nombre del modelo\tGalaxy A54 5G
Número de modelo\tSM-A546E
Número de serie\tR58W123ABC
IMEI (ranura 1)\t490154203237518
IMEI (ranura 2)\t356938035643809
Versión de Android\t14
RAM\t8 GB
Almacenamiento\t128 GB
Salud de la batería: 79 %"""

UPS = """APC Back-UPS 1500VA 900W
Batería: 12V 9Ah x2"""


@pytest.fixture()
def sin_ia(monkeypatch):
    monkeypatch.setattr(st_ia, 'estado', lambda: (False, 'IA apagada en la prueba.'))


@pytest.fixture()
def ia_falsa(monkeypatch):
    """IA simulada: guarda lo que recibe y responde lo que la prueba diga."""
    llamadas = []
    respuesta = {'texto': None}

    class _AI:
        @staticmethod
        def _chat(system, user, **kw):
            llamadas.append(system + '\n' + user)
            return respuesta['texto'], (None if respuesta['texto'] else 'sin respuesta')

        @staticmethod
        def estado_ia():
            return True, 'ok'
    monkeypatch.setattr(st_ia, '_ia', lambda: _AI)
    return llamadas, respuesta


# ── Lector fijo ─────────────────────────────────────────────────
def test_limpia_datos_personales():
    limpio = lector.limpiar_personales(WINDOWS)
    for dato in ('DESKTOP-ANA123', 'Ana Pérez', '00330-80000', 'WORKGROUP', 'ana.perez@gmail.com', '300 123 4567'):
        assert dato not in limpio
    assert 'LENOVO' in limpio and 'i5-1035G1' in limpio


def test_lector_windows():
    r = lector.leer(lector.limpiar_personales(WINDOWS), 'portatil')
    c, e = r['columnas'], r['extras']
    assert c['sistema_operativo'] == 'Windows 10 Pro'
    assert c['marca'] == 'LENOVO' and 'IdeaPad 3' in c['modelo']
    assert c['procesador'] == 'Intel Core i5-1035G1'
    assert c['ram'] == '8 GB'
    assert c['almacenamiento'] == 'HDD 1000 GB' and e['tipo_disco'] == 'HDD'
    assert e['ram_ranuras_total'] == '2' and e['ram_ranuras_libres'] == '1'
    assert e['bateria_desgaste'] == '35'
    titulos = {s['titulo'] for s in lector.sugerencias('portatil', c, e)}
    assert {'Ampliar la memoria RAM', 'Cambiar el disco duro por SSD', 'Cambiar la batería',
            'Actualizar a Windows 11'} <= titulos


def test_lector_android_y_ups():
    r = lector.leer(ANDROID, 'celular')
    assert r['columnas']['imei'] == '490154203237518' and r['extras']['imei2'] == '356938035643809'
    assert r['columnas']['serial'] == 'R58W123ABC' and r['columnas']['sistema_operativo'] == 'Android 14'
    assert r['columnas']['modelo'] == 'Galaxy A54 5G' and r['columnas']['ram'] == '8 GB'
    assert r['extras']['bateria_salud'] == '79'
    u = lector.leer(UPS, 'ups')['extras']
    assert u['capacidad_va'] == '1500' and u['capacidad_w'] == '900' and u['baterias_voltaje'] == '12 V 9 Ah'
    viejas = lector.sugerencias('ups', {}, {'baterias_ultimo_cambio': '2023-01-10'}, hoy=date(2026, 10, 5))
    assert viejas and 'UPS' in viejas[0]['titulo']
    assert lector.sugerencias('ups', {}, {'baterias_ultimo_cambio': '2026-01-10'}, hoy=date(2026, 10, 5)) == []


# ── Propuestas (con y sin IA) ───────────────────────────────────
def test_sin_ia_usa_el_lector(flask_app, sin_ia):
    with flask_app.test_request_context('/'):
        r = st_ia.leer_informacion({'tipo': 'celular', 'modelo': 'Galaxy A54 5G'}, ANDROID)
    campos = {p['campo']: p for p in r['propuestas']}
    assert 'modelo' not in campos                          # igual al actual: no se propone
    assert campos['imei']['sugerido'] == '490154203237518' and campos['imei']['fuente'] == 'lector'
    assert campos['extra_bateria_salud']['sugerido'] == '79'
    assert r['ia'] is False and 'lector automático' in r['aviso']
    assert any(s['titulo'] == 'Cambiar la batería' for s in r['sugerencias'])


def test_ia_completa_sin_pisar_lector_ni_inventar(flask_app, ia_falsa):
    llamadas, respuesta = ia_falsa
    respuesta['texto'] = 'Claro:\n```json\n' + json.dumps({
        'campos': {'imei': '111111111111111', 'serial': 'OTRO-SERIAL', 'color': 'Negro',
                   'extra.version_sistema': '14', 'extra.inventado': 'x', 'cliente': 'Ana'},
        'resumen': 'Galaxy A54 con batería al 79%.',
        'sugerencias': [{'titulo': 'Cambiar la batería', 'detalle': 'repetida'},
                        {'titulo': 'Cambiar el vidrio templado', 'detalle': 'Rayado'}]}) + '\n```'
    with flask_app.test_request_context('/'):
        r = st_ia.leer_informacion({'tipo': 'celular'}, ANDROID + '\nCorreo: ana@x.com')
    campos = {p['campo']: p for p in r['propuestas']}
    assert campos['imei']['sugerido'] == '490154203237518'          # el lector manda
    assert campos['serial']['sugerido'] == 'R58W123ABC'
    assert campos['color']['sugerido'] == 'Negro' and campos['color']['fuente'] == 'ia'
    assert 'extra_inventado' not in campos and 'cliente' not in campos
    assert r['ia'] and r['resumen'].startswith('Galaxy A54')
    titulos = [s['titulo'] for s in r['sugerencias']]
    assert titulos.count('Cambiar la batería') == 1 and 'Cambiar el vidrio templado' in titulos
    assert 'ana@x.com' not in llamadas[0]


def test_ia_no_recibe_datos_personales(flask_app, ia_falsa):
    llamadas, respuesta = ia_falsa
    respuesta['texto'] = '{"campos": {}}'
    with flask_app.test_request_context('/'):
        st_ia.leer_informacion({'tipo': 'portatil'}, WINDOWS)
    for dato in ('DESKTOP-ANA123', 'Ana Pérez', 'ana.perez@gmail.com', '300 123 4567', '00330-80000'):
        assert dato not in llamadas[0]


def test_mejorar_plantilla_conserva_variables(flask_app, ia_falsa):
    llamadas, respuesta = ia_falsa
    original = 'Hola {cliente}, tu {equipo} está listo en {negocio}.'
    respuesta['texto'] = '¡Hola {cliente}! 😊 Tu {equipo} ya está listo en {negocio}, te esperamos.'
    texto, err = st_ia.mejorar_plantilla('Listo', original, 'celular Samsung')
    assert err is None and '{cliente}' in texto
    assert 'Ana' not in llamadas[0]
    respuesta['texto'] = '¡Hola Ana! Tu equipo está listo.'                 # perdió las variables
    assert st_ia.mejorar_plantilla('Listo', original)[0] is None
    respuesta['texto'] = 'Hola {cliente}, {telefono_dueño} tu {equipo} en {negocio}.'
    assert st_ia.mejorar_plantilla('Listo', original)[0] is None


# ── Rutas ───────────────────────────────────────────────────────
def test_ficha_leer_y_aplicar(modulo, dueno, limpiar, sin_ia):
    from services import servicio_tecnico_service as st
    o = st.obtener_orden(_crear(dueno, equipo_tipo='portatil', equipo_imei='', equipo_modelo='',
                                equipo_serial='PF-' + MARCA))
    r = dueno.post('/admin/servicio-tecnico/api/leer-info', json={'equipo_id': o['equipo_id'], 'texto': WINDOWS})
    d = r.get_json()
    assert d['ok'] and 'DESKTOP-ANA123' not in d['texto_limpio']
    campos = {p['campo']: p['sugerido'] for p in d['propuestas']}
    assert campos['ram'] == '8 GB' and campos['extra_tipo_disco'] == 'HDD'

    # Solo se guardan los marcados
    r = dueno.post(f"/admin/servicio-tecnico/equipo/{o['equipo_id']}/aplicar-info", data={
        'aplicar': ['ram', 'extra_tipo_disco', 'extra_ram_ranuras_libres'],
        'valor_ram': '8 GB DDR4', 'valor_extra_tipo_disco': 'HDD', 'valor_extra_ram_ranuras_libres': '1',
        'valor_procesador': 'NO MARCADO',
        'texto': d['texto_limpio'], 'resumen': 'Portátil lento por disco HDD.',
        'sugerencias': json.dumps(d['sugerencias'])})
    assert r.status_code == 302
    eq = st.obtener_equipo(o['equipo_id'])
    assert eq['ram'] == '8 GB DDR4' and eq['procesador'] is None
    assert eq['extras']['tipo_disco'] == 'HDD' and eq['extras']['ram_ranuras_libres'] == '1'
    assert eq['resumen_ia'] == 'Portátil lento por disco HDD.' and 'Ana Pérez' not in eq['info_sistema_original']
    html = dueno.get(f"/admin/servicio-tecnico/equipo/{o['equipo_id']}").get_data(as_text=True)
    assert 'Mejoras sugeridas' in html and 'Cambiar el disco duro por SSD' in html


def test_asistente_guarda_info_limpia(modulo, dueno, limpiar, sin_ia):
    from services import servicio_tecnico_service as st
    r = dueno.post('/admin/servicio-tecnico/api/leer-info', json={'tipo': 'celular', 'texto': ANDROID})
    assert r.get_json()['ok']
    assert dueno.post('/admin/servicio-tecnico/api/leer-info', json={'texto': ANDROID}).status_code == 400
    oid = _crear(dueno, equipo_info_sistema=ANDROID + '\nCorreo: cliente@x.com', equipo_resumen_ia='Resumen corto')
    eq = st.obtener_equipo(st.obtener_orden(oid)['equipo_id'])
    assert 'R58W123ABC' in eq['info_sistema_original'] and 'cliente@x.com' not in eq['info_sistema_original']
    assert eq['resumen_ia'] == 'Resumen corto'


def test_prediagnostico_y_especificaciones(modulo, dueno, limpiar, ia_falsa, monkeypatch):
    llamadas, respuesta = ia_falsa
    from services import servicio_tecnico_service as st
    oid = _crear(dueno)
    respuesta['texto'] = 'Causas probables:\n- Pin de carga sucio\nPruebas a hacer:\n- Medir consumo'
    r = dueno.post(f'/admin/servicio-tecnico/orden/{oid}/prediagnostico')
    assert r.status_code == 302 and 'Pin de carga' in st.obtener_orden(oid)['prediagnostico_ia']
    assert MARCA not in llamadas[-1] and 'pytest-st@ejemplo.com' not in llamadas[-1] and 'patron' not in llamadas[-1]

    from services.chat_publico import busqueda_web
    monkeypatch.setattr(busqueda_web, 'buscar', lambda producto, categoria=None: [
        {'titulo': 'Ficha', 'url': 'https://ejemplo.com/a54', 'dominio': 'ejemplo.com', 'texto': 'Galaxy A54: 8 GB RAM, 128 GB'}])
    respuesta['texto'] = json.dumps({'campos': {'ram': '8 GB', 'serial': 'XYZ12345', 'pantalla': '6,4"'}})
    eq_id = st.obtener_orden(oid)['equipo_id']
    d = dueno.post(f'/admin/servicio-tecnico/equipo/{eq_id}/especificaciones').get_json()
    campos = {p['campo'] for p in d['propuestas']}
    assert d['ok'] and 'ram' in campos and 'pantalla' in campos and 'serial' not in campos
    assert d['fuentes'][0]['dominio'] == 'ejemplo.com'


def test_mejorar_mensaje_ruta(modulo, dueno, limpiar, ia_falsa):
    llamadas, respuesta = ia_falsa
    oid = _crear(dueno)
    respuesta['texto'] = '¡Hola {cliente}! Recibimos tu {equipo} en {negocio}. Orden {numero}: {enlace}'
    d = dueno.post('/admin/servicio-tecnico/api/mejorar-mensaje', json={'orden_id': oid}).get_json()
    assert d['ok'] and d['texto'].startswith(f'¡Hola {MARCA}!') and '/servicio/' in d['texto']
    assert d['wa_url'].startswith('https://wa.me/573001234567?text=')
    assert MARCA not in llamadas[-1] and '300 123 4567' not in llamadas[-1]


# ── Texto libre del técnico: sin datos personales antes de la IA ─
def test_texto_libre_sin_datos_personales():
    texto = ('Laura dice que no carga; llamar al 300 123 4567 o laura.gomez@gmail.com. CC 1.027.150.819. '
             'Fijo 601 234 5678. Luz Marina lo trajo. La luz del cargador no prende. Modelo SM-A546E serial R58W123ABC')
    limpio = lector.sin_datos_personales(texto, ('Laura Gómez', 'Luz Marina Peña'))
    for dato in ('Laura', '300 123 4567', 'laura.gomez', '1.027.150.819', '601 234 5678', 'Luz Marina'):
        assert dato not in limpio, dato
    # Lo técnico queda; «luz» del cargador no es un nombre.
    assert 'La luz del cargador' in limpio and 'SM-A546E' in limpio and 'R58W123ABC' in limpio
    assert lector.sin_datos_personales('Pantalla de Ana. Banana.', ('Ana Pérez',)) == 'Pantalla de [cliente]. Banana.'


def test_prediagnostico_no_manda_nombre_ni_celular(modulo, dueno, limpiar, ia_falsa):
    llamadas, respuesta = ia_falsa
    from services import servicio_tecnico_service as st
    oid = _crear(dueno, falla_reportada=f'{MARCA} Ana dice que no carga. Llamarla al 310 555 1234 o a ana@correo.com',
                 estado_fisico='Golpe en la esquina, lo trajo Ana')
    respuesta['texto'] = 'Causas probables:\n- Pin de carga'
    dueno.post(f'/admin/servicio-tecnico/orden/{oid}/prediagnostico')
    prompt = llamadas[-1]
    for dato in (MARCA, 'Ana', '310 555 1234', 'ana@correo.com'):
        assert dato not in prompt, dato
    assert 'no carga' in prompt and 'Golpe en la esquina' in prompt
    assert st.obtener_orden(oid)['prediagnostico_ia'].startswith('Causas probables')


def test_clasificador_no_manda_nombre_ni_celular(monkeypatch):
    import services.ai_service as ai
    enviado = []
    monkeypatch.setattr(ai, 'estado_ia', lambda: (True, 'ok'))
    monkeypatch.setattr(ai, '_chat', lambda system, user, **kw: (enviado.append(user) or
                        '{"falla_categoria": "carga", "componente": "pin_carga", "solucion_categoria": null}', None))
    caso = {'tipo': 'celular', 'marca': 'Samsung', 'modelo': 'A54', 'cliente': 'Carlos Pérez',
            'falla': 'Carlos dice que no carga, su número es 3001234567', 'diagnostico': 'Pin de carga sucio',
            'solucion': '', 'piezas': []}
    _POR_IA_REAL(caso, {'etiquetas': []})
    assert enviado and 'Carlos' not in enviado[0] and '3001234567' not in enviado[0]
    assert 'no carga' in enviado[0] and 'Pin de carga sucio' in enviado[0]


def test_mejorar_el_recordatorio_conserva_el_motivo(flask_app, ia_falsa):
    llamadas, respuesta = ia_falsa
    plantilla = 'Hola {cliente}, te escribimos de {negocio} sobre tu {equipo}: {motivo}.'
    respuesta['texto'] = '¡Hola {cliente}! 😊 En {negocio} queremos contarte algo de tu {equipo}: {motivo}.'
    texto, err = st_ia.mejorar_plantilla('Recordatorio programado', plantilla)
    assert err is None and '{motivo}' in texto and '{motivo}' in llamadas[-1]
    respuesta['texto'] = '¡Hola {cliente}! En {negocio} revisamos tu {equipo}.'      # se comió el motivo
    texto, err = st_ia.mejorar_plantilla('Recordatorio programado', plantilla)
    assert texto is None and 'original' in err


def test_respuesta_cortada_de_la_ia_avisa_y_usa_el_lector(flask_app, ia_falsa):
    llamadas, respuesta = ia_falsa
    respuesta['texto'] = '{"campos": {"marca": {"valor": "LENOVO", "linea": "Fabricante del sistema: LENOVO"'
    r = st_ia.leer_informacion({'tipo': 'portatil'}, WINDOWS)
    assert 'incompleta' in r['aviso'] and not r['ia']
    assert any(p['campo'] == 'marca' and p['fuente'] == 'lector' for p in r['propuestas'])
