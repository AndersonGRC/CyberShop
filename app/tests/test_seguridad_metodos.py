# -*- coding: utf-8 -*-
"""Regresiones de seguridad sobre métodos HTTP mutables."""

import pytest
from unittest.mock import Mock
from werkzeug.exceptions import MethodNotAllowed


def test_eliminar_producto_es_solo_post(flask_app):
    """Un GET nunca debe poder ejecutar el borrado de un producto."""
    regla = next(
        rule for rule in flask_app.url_map.iter_rules()
        if rule.endpoint == 'admin.eliminar_producto'
    )

    assert 'POST' in regla.methods
    assert 'GET' not in regla.methods
    assert 'HEAD' not in regla.methods


def test_get_eliminar_producto_resuelve_como_405(flask_app):
    """La comprobación de método no necesita conectarse a ninguna BD."""
    adapter = flask_app.url_map.bind('localhost')

    with pytest.raises(MethodNotAllowed):
        adapter.match('/eliminar-producto/1', method='GET')

    endpoint, values = adapter.match('/eliminar-producto/1', method='POST')
    assert endpoint == 'admin.eliminar_producto'
    assert values == {'id': 1}


def test_post_valido_conserva_el_borrado_fisico(flask_app, monkeypatch):
    """Ejercita la lógica con dobles; no abre conexión ni modifica filas."""
    from routes import admin as admin_routes

    cursor = Mock()
    connection = Mock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(admin_routes, 'get_db_connection', lambda: connection)

    with flask_app.test_request_context('/eliminar-producto/7', method='POST'):
        response = admin_routes.eliminar_producto.__wrapped__(7)

    cursor.execute.assert_called_once_with(
        'DELETE FROM productos WHERE id = %s', (7,),
    )
    connection.commit.assert_called_once_with()
    assert response.status_code == 302


def test_producto_con_historial_se_archiva(flask_app, monkeypatch):
    """Una FK conserva el historial y activa el fallback existente."""
    import psycopg2
    from routes import admin as admin_routes

    cursor = Mock()
    cursor.execute.side_effect = psycopg2.errors.ForeignKeyViolation()
    connection = Mock()
    connection.cursor.return_value = cursor
    archivar = Mock(return_value=True)
    contar = Mock(return_value=3)
    monkeypatch.setattr(admin_routes, 'get_db_connection', lambda: connection)
    monkeypatch.setattr(admin_routes, '_archivar_producto', archivar)
    monkeypatch.setattr(admin_routes, '_contar_dependencias_producto', contar)

    with flask_app.test_request_context('/eliminar-producto/9', method='POST'):
        response = admin_routes.eliminar_producto.__wrapped__(9)

    connection.rollback.assert_called_once_with()
    archivar.assert_called_once_with(9)
    contar.assert_called_once_with(9)
    connection.commit.assert_not_called()
    assert response.status_code == 302
