# -*- coding: utf-8 -*-
"""Correo de bienvenida pedido por el maestro (1.9.12.0).

Cuando el operador crea un cliente a mano en el maestro, el dueño no recibía nada:
la contraseña solo la veía CyberShop una vez. Ahora el maestro le pide a la tienda
de CyberShop (que envía los correos) mandar «¡Tu tienda está lista!» con la tienda,
el panel, el usuario y la contraseña temporal. Solo con el secreto compartido y
solo en la tienda del operador. Sin enviar correos de verdad."""
import pytest

from config import Config
from services import public_site_service as pss

CLAVE = 'pytest-clave-interna'
DATOS = {'admin_email': 'Duena@Ejemplo.com', 'admin_nombre': 'Dueña QA', 'dominio': 'panaderia-qa.cybershopcol.com',
         'admin_password': 'Temp-Abc123', 'plan': 'estandar', 'client_code': 'CS-1234'}


@pytest.fixture()
def operador(flask_app, monkeypatch):
    """La tienda de CyberShop con la clave interna; los correos se guardan aquí."""
    monkeypatch.setattr(Config, 'INTERNAL_API_KEY', CLAVE)
    enviados = []
    import services.venta_automatica_service as vas
    monkeypatch.setattr(vas, '_enviar', lambda destino, correo: enviados.append((destino, correo)) or True)
    with flask_app.test_request_context('/'):
        antes = pss.is_public_section_enabled('mostrar_modulo_software', False)

    def poner(valor):
        with flask_app.test_request_context('/'):
            pss.set_public_section('mostrar_modulo_software', valor)
    poner(True)
    yield poner, enviados
    poner(antes)


def _post(client, datos=None, clave=CLAVE):
    return client.post('/internal/api/v1/correo-bienvenida', json=DATOS if datos is None else datos,
                       headers={'X-Internal-Key': clave} if clave else {})


def test_envia_la_bienvenida_con_la_contrasena(client, operador):
    _, enviados = operador
    r = _post(client)
    assert r.status_code == 200 and r.get_json() == {'ok': True}
    destino, (asunto, texto, html) = enviados[0]
    assert destino == 'duena@ejemplo.com'
    assert 'panaderia-qa.cybershopcol.com' in asunto
    assert 'Temp-Abc123' in html and 'Temp-Abc123' in texto, 'la contraseña temporal va en el correo'
    assert 'https://panaderia-qa.cybershopcol.com/login' in html and 'Estándar' in html and 'CS-1234' in html
    assert 'Tu logo aquí' not in html, 'las tiendas del maestro no tienen el logo de muestra'


def test_sin_la_clave_no_se_envia(client, operador):
    _, enviados = operador
    assert _post(client, clave='otra-clave').status_code == 403
    assert _post(client, clave=None).status_code == 403
    assert enviados == []


def test_solo_la_tienda_de_cybershop_envia(client, operador):
    poner, enviados = operador
    poner(False)
    assert _post(client).status_code == 404 and enviados == []


def test_datos_incompletos(client, operador):
    _, enviados = operador
    assert _post(client, {**DATOS, 'admin_email': 'no-es-un-correo'}).status_code == 400
    assert _post(client, {**DATOS, 'admin_password': ''}).status_code == 400
    assert _post(client, {**DATOS, 'dominio': ''}).status_code == 400
    assert enviados == []


def test_la_ruta_no_pide_token_csrf(flask_app):
    """El maestro llama sin formulario: la ruta va exenta de CSRF (la protege la clave)."""
    from app import csrf
    exentos = getattr(csrf, '_exempt_blueprints', set())
    assert 'interno' in exentos or flask_app.blueprints['interno'] in exentos
