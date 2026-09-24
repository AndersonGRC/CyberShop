# -*- coding: utf-8 -*-
"""El catálogo de módulos está DUPLICADO a propósito en dos repos:

  - `app/tenant_features.py`        → lo que el cliente lee para mostrar u ocultar
  - `CyberShopAdmin/module_service.py` → lo que el maestro ofrece como interruptor

Si uno se adelanta al otro, pasa una de dos: el módulo existe pero el maestro no
lo puede encender, o el maestro escribe una clave que el cliente nunca mira. Ya
ocurrió con los campos del sitio público.

Esta prueba compara los dos catálogos cuando el repo del maestro está al lado
(entorno de desarrollo). En el servidor, donde cada repo vive por su cuenta, se
salta sola.
"""

import os
import re

import pytest

import tenant_features as tf

_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CANDIDATOS = (
    os.path.join(_APP, '..', '..', 'CyberShopAdmin', 'module_service.py'),
    os.path.join(_APP, '..', 'CyberShopAdmin', 'module_service.py'),
    '/var/www/CyberShopAdmin/module_service.py',
)


def _catalogo_del_maestro():
    for ruta in _CANDIDATOS:
        ruta = os.path.normpath(ruta)
        if os.path.exists(ruta):
            with open(ruta, encoding='utf-8') as f:
                texto = f.read()
            # ('code', 'Nombre', 'Descripcion', 'categoria', 'config_key', default)
            filas = re.findall(
                r"^\s*\('([a-z_]+)',\s*'[^']*',\s*'[^']*',\s*'([a-z_]+)',\s*'([a-z_]+)',\s*(True|False)\),",
                texto, re.M)
            if filas:
                return {c: {'categoria': cat, 'config_key': ck, 'default': d == 'True'}
                        for c, cat, ck, d in filas}
    return None


@pytest.fixture(scope='module')
def maestro():
    catalogo = _catalogo_del_maestro()
    if not catalogo:
        pytest.skip('el repo del maestro no está al lado: nada que comparar')
    return catalogo


def test_los_dos_catalogos_tienen_los_mismos_modulos(maestro):
    aqui = set(tf.MODULE_DEFINITIONS)
    alla = set(maestro)
    assert not (aqui - alla), f'el maestro no puede encender: {sorted(aqui - alla)}'
    assert not (alla - aqui), f'el maestro ofrece módulos que el cliente no conoce: {sorted(alla - aqui)}'


def test_la_clave_de_configuracion_coincide(maestro):
    """Si no coincide, el maestro escribe una clave que el cliente nunca lee:
    el interruptor parece funcionar y no hace nada."""
    distintas = {c: (tf.MODULE_DEFINITIONS[c]['config_key'], maestro[c]['config_key'])
                 for c in tf.MODULE_DEFINITIONS if c in maestro
                 and tf.MODULE_DEFINITIONS[c]['config_key'] != maestro[c]['config_key']}
    assert not distintas, f'claves distintas entre repos: {distintas}'


def test_el_valor_por_defecto_coincide(maestro):
    distintos = {c: (tf.MODULE_DEFINITIONS[c]['default'], maestro[c]['default'])
                 for c in tf.MODULE_DEFINITIONS if c in maestro
                 and bool(tf.MODULE_DEFINITIONS[c]['default']) != maestro[c]['default']}
    assert not distintos, f'defaults distintos entre repos: {distintos}'


def test_el_chat_del_sitio_nace_apagado():
    """Es lo único que se asoma a los visitantes: no puede encenderse solo."""
    meta = tf.MODULE_DEFINITIONS[tf.MODULE_AI_PUBLIC]
    assert meta['default'] is False
    assert meta['config_key'] == 'chat_publico_habilitado'


def test_el_chat_del_sitio_no_se_enciende_al_aplicar_un_plan(maestro):
    """Ni siquiera con el plan más alto: lo enciende una persona, a propósito."""
    ruta = next((os.path.normpath(r) for r in _CANDIDATOS if os.path.exists(os.path.normpath(r))), None)
    with open(ruta, encoding='utf-8') as f:
        texto = f.read()
    linea_ultra = next(l for l in texto.splitlines() if "'ultra':" in l)
    assert 'ai_public' in linea_ultra, \
        'el chat del sitio debe estar excluido del plan ultra (se enciende a mano)'
