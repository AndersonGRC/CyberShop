# -*- coding: utf-8 -*-
"""Token CSRF por pantalla: vence a la hora en todo el sistema y a las 2 horas
solo en el restaurante (/admin/restaurante/) y el POS con su caja (/admin/pos/),
que se dejan abiertos todo el turno (csrf_pantallas.py).

Para no esperar horas, el general se baja a 1 s. Ninguna prueba cambia datos:
las peticiones que pasan la protección terminan en un rechazo del negocio o en
una búsqueda."""
import hashlib
import inspect
import time

import pytest
from flask_wtf.csrf import CSRFProtect

from tests.test_restaurante_mesas import modulo_mesas  # noqa: F401  (fixture)

DATOS = '/admin/restaurante/mesas/data'        # entrega un token nuevo (campo «csrf»)
NADA_RESTAURANTE = ('/admin/restaurante/salones', {'accion': 'borrar-todo'})   # se rechaza: no cambia nada


@pytest.fixture()
def csrf_on(flask_app):
    """CSRF encendido y el vencimiento general en 1 s; se deja todo como estaba."""
    claves = ('WTF_CSRF_ENABLED', 'WTF_CSRF_TIME_LIMIT', 'CSRF_TIEMPO_TURNO_LARGO')
    previo = {k: flask_app.config.get(k) for k in claves}
    flask_app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_TIME_LIMIT=1)
    flask_app.config.pop('CSRF_TIEMPO_TURNO_LARGO', None)          # el de verdad: 2 h
    yield flask_app
    for clave, valor in previo.items():
        if valor is None:
            flask_app.config.pop(clave, None)
        else:
            flask_app.config[clave] = valor


def _token(cliente, **kw):
    r = cliente.get(DATOS, **kw)
    assert r.status_code == 200, r.status_code
    return r.get_json()['csrf']


def _es_error_csrf(r):
    return r.status_code == 400 and 'CSRF' in r.get_data(as_text=True)


def test_fuera_del_restaurante_y_el_pos_sigue_venciendo_como_siempre(as_propietario, modulo_mesas, csrf_on):
    """Misma área del código (módulos SaaS vive en el blueprint del restaurante)
    pero otra pantalla: conserva el vencimiento general."""
    token = _token(as_propietario)
    time.sleep(2)
    r = as_propietario.post('/admin/saas/modulos/1', headers={'X-CSRFToken': token, 'Accept': 'application/json'})
    assert _es_error_csrf(r) and 'expired' in r.get_json()['error']


def test_restaurante_y_pos_aceptan_el_token_por_mas_tiempo(as_propietario, modulo_mesas, csrf_on):
    token = _token(as_propietario)
    time.sleep(2)                                       # el general (1 s) ya venció
    ruta, cuerpo = NADA_RESTAURANTE
    r = as_propietario.post(ruta, json=cuerpo, headers={'X-CSRFToken': token})
    assert r.status_code == 400 and not _es_error_csrf(r)          # pasó la protección; el negocio lo rechaza
    r = as_propietario.post('/admin/pos/buscar-barcode', json={'barcode': 'QA-NO-EXISTE-0000'},
                            headers={'X-CSRFToken': token, 'Accept': 'application/json'})
    assert not _es_error_csrf(r)


def test_restaurante_rechaza_el_token_pasado_su_tiempo(as_propietario, modulo_mesas, csrf_on):
    csrf_on.config['CSRF_TIEMPO_TURNO_LARGO'] = 2       # (de verdad 2 h) más que el general de 1 s
    token = _token(as_propietario)
    time.sleep(3)
    ruta, cuerpo = NADA_RESTAURANTE
    r = as_propietario.post(ruta, json=cuerpo, headers={'X-CSRFToken': token})
    assert _es_error_csrf(r) and 'expired' in r.get_json()['error']


def test_restaurante_sin_token_o_con_uno_falso_se_rechaza(as_propietario, modulo_mesas, csrf_on):
    ruta, cuerpo = NADA_RESTAURANTE
    assert _es_error_csrf(as_propietario.post(ruta, json=cuerpo))
    assert _es_error_csrf(as_propietario.post(ruta, json=cuerpo, headers={'X-CSRFToken': 'falso.falso.falso'}))


def test_restaurante_conserva_la_revision_del_origen_en_https(as_propietario, modulo_mesas, csrf_on):
    https = {'base_url': 'https://localhost'}
    token = _token(as_propietario, **https)
    ruta, cuerpo = NADA_RESTAURANTE
    r = as_propietario.post(ruta, json=cuerpo, headers={'X-CSRFToken': token}, **https)
    assert _es_error_csrf(r) and 'referrer' in r.get_json()['error']
    r = as_propietario.post(ruta, json=cuerpo, **https,
                            headers={'X-CSRFToken': token, 'Referer': 'https://otro-sitio.com/x'})
    assert _es_error_csrf(r) and 'referrer' in r.get_json()['error']
    r = as_propietario.post(ruta, json=cuerpo, **https,
                            headers={'X-CSRFToken': token, 'Referer': 'https://localhost/admin/restaurante/mesas'})
    assert r.status_code == 400 and not _es_error_csrf(r)


def test_la_copia_de_protect_sigue_igual_a_la_libreria():
    """csrf_pantallas.CSRFProtectPorPantalla.protect copia el de Flask-WTF 1.2.2
    cambiando solo el tiempo. Si al actualizar Flask-WTF esto falla, revisar que
    la copia siga haciendo lo mismo que la nueva versión y actualizar la huella."""
    fuente = inspect.getsource(CSRFProtect.protect)
    assert hashlib.sha256(fuente.encode()).hexdigest()[:16] == '46f28509db183969'
