# -*- coding: utf-8 -*-
"""Servicio Técnico: solución de cada orden, su clasificación (tipo de falla,
pieza, tipo de solución) y las consultas del asistente sobre el historial de
casos; además, la lectura del texto largo de la ficha técnica con verificación.

La IA real nunca se llama (conftest la apaga para el clasificador; aquí se
simula cuando hace falta). Todo lo creado se borra al final."""
import json

import pytest

from services import servicio_tecnico_clasificador as clasif
from services.ia_datos.acceso import Contexto
from tests.test_servicio_tecnico import MARCA, _crear, dueno, limpiar, modulo  # noqa: F401  (fixtures)

DUENO = Contexto(rol_id=2, usuario_id=1)


# ── Reglas (sin IA) ─────────────────────────────────────────────
@pytest.mark.parametrize('caso, falla, componente, solucion', [
    (dict(tipo='portatil', falla='Está muy lento y se calienta', diagnostico='Disco HDD con sectores dañados',
          solucion='Se cambió el disco por SSD y se reinstaló Windows', piezas=['Disco SSD']),
     'almacenamiento', 'disco', 'cambio_pieza'),
    (dict(tipo='celular', falla='Pantalla rota después de una caída', diagnostico='Display quebrado',
          solucion='Cambio de pantalla completa', piezas=['Pantalla']), 'pantalla', 'pantalla', 'cambio_pieza'),
    (dict(tipo='celular', falla='No carga', diagnostico='Pin de carga sucio', solucion='Limpieza del pin de carga',
          piezas=[]), 'bateria_carga', 'pin_carga', 'limpieza'),
    (dict(tipo='ups', falla='Pita y se apaga sin luz', diagnostico='Baterías agotadas',
          solucion='Cambio de las 2 baterías', piezas=['Baterías de la UPS']), 'energia', 'baterias_ups', 'cambio_pieza'),
    (dict(tipo='portatil', falla='Le cayó café encima y no prende', diagnostico='Corto en la board por líquido',
          solucion='Microsoldadura y limpieza de la board', piezas=[]), 'liquido', 'board', 'reparacion_board'),
    (dict(tipo='computador', falla='Mucha publicidad', diagnostico='', solucion='Se eliminaron los virus', piezas=[]),
     'virus', 'sistema', 'virus'),
    (dict(tipo='celular', falla='Olvidó el patrón', diagnostico='', solucion='', piezas=[]), 'cuenta_bloqueo', None, None),
    (dict(tipo='portatil', falla='Se redujo la duración de la batería', diagnostico='',
          solucion='No tiene arreglo, el cliente no aprobó', piezas=[]), 'bateria_carga', 'bateria', 'sin_reparacion'),
])
def test_reglas_clasifican_casos_tipicos(caso, falla, componente, solucion):
    r = clasif.por_reglas(caso)
    assert (r['falla_categoria'], r['componente'], r['solucion_categoria']) == (falla, componente, solucion)


def test_palabras_cortas_no_dan_falsos_positivos():
    r = clasif.por_reglas(dict(tipo='portatil', falla='Se redujo el brillo', diagnostico='', solucion='', piezas=[]))
    assert r['falla_categoria'] != 'conectividad'      # «red» no está dentro de «redujo»


# ── Orden: solución y clasificación automática ──────────────────
def _orden(cursor, oid):
    with cursor() as cur:
        cur.execute("""SELECT solucion, falla_categoria, componente, solucion_categoria, resumen_caso,
                              clasificacion_fuente FROM st_ordenes WHERE id = %s""", (oid,))
        return cur.fetchone()


def test_solucion_al_marcar_listo_y_clasificacion(modulo, dueno, cursor, limpiar):
    oid = _crear(dueno, falla_reportada='Pantalla rota después de una caída')
    dueno.post(f'/admin/servicio-tecnico/orden/{oid}/estado', data={'estado': 'diagnostico'})
    assert _orden(cursor, oid)['falla_categoria'] == 'pantalla'
    dueno.post(f'/admin/servicio-tecnico/orden/{oid}/estado',
               data={'estado': 'listo', 'solucion': 'Cambio de pantalla completa original'})
    o = _orden(cursor, oid)
    assert o['solucion'] == 'Cambio de pantalla completa original'
    assert (o['falla_categoria'], o['solucion_categoria'], o['clasificacion_fuente']) == ('pantalla', 'cambio_pieza', 'reglas')
    assert 'Pantalla' in o['resumen_caso']
    html = dueno.get(f'/admin/servicio-tecnico/orden/{oid}').get_data(as_text=True)
    assert 'Cambio de pantalla completa original' in html and 'Cambio de pieza' in html


def test_clasificacion_manual_queda_fija(modulo, dueno, cursor, limpiar):
    oid = _crear(dueno, falla_reportada='No carga')
    dueno.post(f'/admin/servicio-tecnico/orden/{oid}/clasificacion',
               data={'falla_categoria': 'puertos', 'componente': 'puerto', 'solucion_categoria': 'cambio_pieza'})
    dueno.post(f'/admin/servicio-tecnico/orden/{oid}/editar', data={'diagnostico': 'Pin de carga sulfatado'})
    o = _orden(cursor, oid)
    assert (o['falla_categoria'], o['clasificacion_fuente']) == ('puertos', 'manual')
    r = dueno.post(f'/admin/servicio-tecnico/orden/{oid}/clasificacion', data={'falla_categoria': 'inventada'})
    assert r.status_code == 302 and _orden(cursor, oid)['falla_categoria'] == 'puertos'


def test_ia_clasifica_dentro_de_la_lista(modulo, dueno, cursor, limpiar, monkeypatch):
    oid = _crear(dueno, falla_reportada='Se calienta y se apaga')
    monkeypatch.undo()                                  # quita el «sin IA» del conftest para esta prueba…
    monkeypatch.setattr('services.ai_service.estado_ia', lambda: (True, 'ok'))
    vistos = []

    def _chat(system, user, **k):
        vistos.append(user)
        return json.dumps({'falla_categoria': 'sobrecalentamiento', 'componente': 'inventado',
                           'solucion_categoria': 'limpieza', 'etiquetas': ['ventilador', 'temperatura'],
                           'resumen': 'Se calentaba por polvo → limpieza y pasta térmica'}), None
    monkeypatch.setattr('services.ai_service._chat', _chat)
    with dueno.application.test_request_context('/'):
        st_sol = clasif.clasificar_orden(oid, usar_ia=True)
    assert st_sol['fuente'] == 'ia'
    o = _orden(cursor, oid)
    assert o['falla_categoria'] == 'sobrecalentamiento' and o['componente'] != 'inventado'
    assert MARCA not in vistos[0] and 'patron-L-1234' not in vistos[0]


def test_clasificar_historial(modulo, dueno, cursor, limpiar):
    oid = _crear(dueno, falla_reportada='Mucha publicidad y ventanas emergentes')
    with cursor() as cur:
        cur.execute('UPDATE st_ordenes SET falla_categoria = NULL, clasificacion_fuente = NULL WHERE id = %s', (oid,))
    dueno.post('/admin/servicio-tecnico/clasificar-historial')
    assert _orden(cursor, oid)['falla_categoria'] == 'virus'


def test_busqueda_de_ordenes_por_falla_y_solucion(modulo, dueno, limpiar):
    oid = _crear(dueno, falla_reportada='Le entró agua al celular')
    dueno.post(f'/admin/servicio-tecnico/orden/{oid}/editar', data={'solucion': 'Limpieza con ultrasonido'})
    html = dueno.get('/admin/servicio-tecnico/?q=ultrasonido').get_data(as_text=True)
    assert f'OS-{oid:06d}' in html


# ── Asistente: casos y fallas frecuentes ────────────────────────
@pytest.fixture()
def casos(modulo, dueno, limpiar):
    from services import servicio_tecnico_service as st
    a = _crear(dueno, equipo_tipo='portatil', equipo_marca='Lenovo', equipo_modelo='IdeaPad 3', equipo_imei='',
               equipo_serial='LEN-' + MARCA, falla_reportada='Muy lento al prender')
    st.cambiar_estado(a, 'diagnostico', datos={'diagnostico': 'Disco HDD dañado'})
    st.cambiar_estado(a, 'listo', datos={'solucion': 'Cambio de disco por SSD 480 GB y reinstalación de Windows'})
    b = _crear(dueno, equipo_tipo='celular', equipo_serial='SAM-' + MARCA, falla_reportada='Pantalla rota')
    st.cambiar_estado(b, 'diagnostico')
    st.cambiar_estado(b, 'listo', datos={'solucion': 'Cambio de pantalla'})
    for oid in (a, b):
        clasif.clasificar_orden(oid, usar_ia=False)
    return {'portatil': a, 'celular': b}


def _ej(code, params=None):
    import services.ia_datos as d
    return d.ejecutar(code, params or {}, DUENO)


def test_casos_por_cliente_tipo_y_falla(casos, flask_app):
    with flask_app.test_request_context('/'):
        r = _ej('taller_casos', {'texto': f'el portátil de {MARCA}'})
        assert r['casos'][0]['orden'] == f"OS-{casos['portatil']:06d}"
        assert 'SSD' in r['casos'][0]['solucion'] and r['casos'][0]['tipo_de_falla']
        pantalla = _ej('taller_casos', {'texto': 'pantalla rota'})
        assert pantalla['casos'][0]['orden'] == f"OS-{casos['celular']:06d}"
        assert pantalla['tipo_de_falla_buscado'] == 'Pantalla / display'
        assert 'Cambio de pieza' in pantalla['como_se_ha_solucionado_esta_falla']
        compus = _ej('taller_casos', {'texto': 'computadores'})
        assert all('Celular' not in c['equipo'] for c in compus['casos'])
        assert _ej('taller_casos')['casos']                      # sin texto: los últimos
        texto = json.dumps(r, ensure_ascii=False)
        assert 'patron-L-1234' not in texto


def test_fallas_frecuentes(casos, flask_app):
    with flask_app.test_request_context('/'):
        r = _ej('taller_fallas_frecuentes', {'periodo': 'todo'})
    assert r['ordenes'] >= 2 and 'Pantalla / display' in r['fallas_mas_comunes']
    assert MARCA not in json.dumps(r, ensure_ascii=False)          # solo cifras


def test_orden_e_historial_traen_la_solucion(casos, flask_app):
    with flask_app.test_request_context('/'):
        o = _ej('taller_orden', {'texto': f"OS-{casos['celular']:06d}"})['ordenes'][0]
        assert o['solucion'] == 'Cambio de pantalla' and o['tipo_de_falla']
        h = _ej('taller_equipo_historial', {'texto': 'LEN-' + MARCA})['equipos'][0]
        assert 'SSD' in h['servicios'][0]['solucion']


@pytest.mark.parametrize('pregunta, esperada, texto', [
    ('¿Qué novedad tuvo el portátil de Laura Gómez?', 'taller_casos', 'portátil de Laura Gómez'),
    ('¿Cómo se solucionó lo de la pantalla del Samsung?', 'taller_casos', 'lo de la pantalla del Samsung'),
    ('¿Qué computadores atendimos?', 'taller_casos', None),
    ('¿Cuál fue el último computador que atendimos?', 'taller_casos', 'computador que atendimos'),
    ('¿Cuáles son las fallas más comunes?', 'taller_fallas_frecuentes', None),
    ('¿Qué se daña más en los equipos?', 'taller_fallas_frecuentes', None),
])
def test_enrutamiento_de_casos(pregunta, esperada, texto):
    import services.ia_datos as d
    from services.ia.enrutador import enrutar_panel_seguro
    r = enrutar_panel_seguro(pregunta, list(d.REGISTRO.values()))
    assert r and r[0][0] == esperada, r
    if texto:
        assert r[0][1].get('texto') == texto


# ── Ficha técnica: texto largo y verificación ───────────────────
def test_texto_largo_lee_lo_tecnico_y_verifica(flask_app, monkeypatch):
    from services import servicio_tecnico_ia as st_ia
    parches = '\n'.join(f'                           [{i:02d}]: KB50{i:05d}' for i in range(1, 400))
    texto = ('Nombre del sistema operativo:   Microsoft Windows 11 Pro\n'
             'Revisiones:   398 revisiones instaladas.\n' + parches + '\n'
             'Fabricante del sistema:   ASUSTeK COMPUTER INC.\n'
             'Modelo el sistema:   VivoBook 15 X512JA\n'
             'Memoria física total:   15.791 MB\n'
             'Tarjeta de video: Intel UHD Graphics\n')
    recortado, info = st_ia.recortar_relevante(texto)
    assert 'VivoBook' in recortado and 'KB50' not in recortado and info['lineas_usadas'] < info['lineas_totales']

    vistos = []

    class _AI:
        @staticmethod
        def _chat(system, user, **k):
            vistos.append(user)
            return json.dumps({'campos': {
                'procesador': {'valor': 'Intel Core i7-1065G7', 'linea': 'inventada'},     # no está en el texto
                'extra.tarjeta_video': {'valor': 'Intel UHD Graphics', 'linea': 'Tarjeta de video: Intel UHD Graphics'},
            }}), None

        @staticmethod
        def estado_ia():
            return True, 'ok'
    monkeypatch.setattr(st_ia, '_ia', lambda: _AI)
    with flask_app.test_request_context('/'):
        r = st_ia.leer_informacion({'tipo': 'portatil'}, texto)
    assert 'KB50' not in vistos[0] and 'VivoBook' in vistos[0]
    props = {p['campo']: p for p in r['propuestas']}
    assert props['procesador']['verificado'] is False                  # la IA lo inventó
    assert props['extra_tarjeta_video']['verificado'] is True
    assert props['ram']['sugerido'] == '16 GB' and props['ram']['verificado'] is True
    assert 'líneas' in r['aviso'] and 'no aparecen tal cual' in r['aviso']


def test_verificado():
    from services.servicio_tecnico_ia import _plano, verificado
    t = _plano('Procesador: Intel(R) Core(TM) i5-1035G1 CPU @ 1.00GHz\nRAM 8 GB DDR4')
    assert verificado('Intel Core i5-1035G1', t)
    assert verificado('8 GB DDR4', t)
    assert not verificado('16 GB DDR4', t)
    assert not verificado('AMD Ryzen 7 5700U', t)


def test_solucion_con_varias_acciones_gana_la_de_mas_peso():
    r = clasif.por_reglas(dict(tipo='portatil', falla='Lento', diagnostico='',
                               solucion='Cambio de disco HDD por SSD, reinstalación de Windows y limpieza interna',
                               piezas=[]))
    assert r['solucion_categoria'] == 'cambio_pieza' and r['componente'] == 'disco'
