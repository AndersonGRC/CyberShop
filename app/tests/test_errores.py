# -*- coding: utf-8 -*-
"""Tests del manejo de errores 500 + request-id (B3)."""


def test_request_id_en_respuesta(client):
    r = client.get('/')
    assert r.headers.get('X-Request-Id'), "toda respuesta debe llevar X-Request-Id"


def test_500_handler_html(flask_app):
    """El handler de excepciones no controladas renderiza la pagina 500 (HTML)."""
    import app as appmod
    with flask_app.test_request_context('/alguna-ruta'):
        body, code = appmod._handle_unexpected(RuntimeError('boom de prueba'))
        assert code == 500
        html = body if isinstance(body, str) else body.decode('utf-8', 'ignore')
        assert '500' in html


def test_500_handler_json(flask_app):
    """En rutas /api o peticiones JSON responde JSON con request_id."""
    import app as appmod
    with flask_app.test_request_context('/api/x', headers={'Accept': 'application/json'}):
        resp, code = appmod._render_error_500()
        assert code == 500
        data = resp.get_json()
        assert data and data.get('success') is False and 'request_id' in data


def test_httpexception_pasa_de_largo(flask_app):
    """Las HTTPException (404/403) NO las captura el handler generico."""
    import app as appmod
    from werkzeug.exceptions import NotFound
    with flask_app.test_request_context('/'):
        exc = NotFound()
        assert appmod._handle_unexpected(exc) is exc  # se deja pasar tal cual
