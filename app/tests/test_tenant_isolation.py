"""Regresiones de aislamiento entre instancias y cachés de clientes."""

from contextlib import contextmanager

from flask import Flask, g, session


def test_jwt_no_puede_elegir_base_de_otra_instancia(monkeypatch):
    import database
    from services import tenant_resolver
    from services.auth import jwt_handler

    own = {'id': 7, 'slug': 'tienda-a', 'db_name': 'cyber_t007'}
    monkeypatch.setattr(tenant_resolver, '_DEFAULT_TENANT', own)
    claims = {'tenant_id': 8, 'db_name': 'cyber_t008'}
    monkeypatch.setattr(jwt_handler, 'decode_access_token', lambda token: claims)

    app = Flask(__name__)
    app.secret_key = 'test-only'
    app.before_request(tenant_resolver.resolve_current_tenant)
    app.add_url_rule('/db', view_func=lambda: database._current_db_name())
    client = app.test_client()

    assert client.get('/db', headers={'Authorization': 'Bearer firmado'}).status_code == 403
    claims.update(tenant_id=7, db_name='cyber_t008')
    assert client.get('/db', headers={'Authorization': 'Bearer firmado'}).status_code == 403
    claims.update(db_name='cyber_t007')
    assert client.get('/db', headers={'Authorization': 'Bearer firmado'}).data == b'cyber_t007'


def test_sesion_local_no_cambia_base_de_instancia(monkeypatch):
    import database
    from services import tenant_resolver

    monkeypatch.setattr(tenant_resolver, '_DEFAULT_TENANT',
                        {'id': 7, 'slug': 'tienda-a', 'db_name': 'cyber_t007'})
    app = Flask(__name__)
    app.secret_key = 'test-only'
    app.before_request(tenant_resolver.resolve_current_tenant)
    app.add_url_rule('/db', view_func=lambda: database._current_db_name())
    client = app.test_client()

    with client.session_transaction() as state:
        state['tenant_id'] = 1  # id local de la BD, distinto del id global 7
    assert client.get('/db').data == b'cyber_t007'
    with client.session_transaction() as state:
        state['tenant_db_name'] = 'cyber_t008'
    assert client.get('/db').status_code == 403


def test_flags_de_modulo_se_cachean_por_base(monkeypatch):
    import tenant_features as features

    seen = []

    class Cursor:
        def execute(self, statement, params):
            seen.append(features._current_db_name())

        def fetchall(self):
            return [{'clave': 'ia_habilitado',
                     'valor': 'true' if features._current_db_name() == 'cyber_t007' else 'false'}]

    @contextmanager
    def fake_cursor(**kwargs):
        yield Cursor()

    monkeypatch.setattr(features, 'get_db_cursor', fake_cursor)
    features._clear_cache()
    app = Flask(__name__)
    try:
        for db, expected in [('cyber_t007', 'true'), ('cyber_t008', 'false'),
                             ('cyber_t007', 'true')]:
            with app.test_request_context('/'):
                g.current_tenant = {'db_name': db}
                assert features._get_module_config_rows()['ia_habilitado'] == expected
        assert seen == ['cyber_t007', 'cyber_t008']
    finally:
        features._clear_cache()


def test_sync_key_prevalece_sobre_cookie_web_en_cache_ia():
    import tenant_features as features
    from services import ai_service

    app = Flask(__name__)
    app.secret_key = 'test-only'
    with app.test_request_context('/api/v1/sync/ai/accion'):
        session['tenant_id'] = 1  # cookie web local de otro negocio
        g.sync_tenant_id = 8      # identidad autenticada por X-Sync-Key
        g.sync_db_name = 'cyber_t008'
        g.current_tenant = {'id': 8, 'db_name': 'cyber_t008'}
        assert features.get_current_tenant_id() == 8
        assert ai_service._cache_key('descripcion', 'producto').startswith('cyber_t008:8:')


def test_permisos_se_cachean_por_base(monkeypatch):
    from services import permisos_service as permisos

    seen = []

    class Cursor:
        def execute(self, statement):
            self.statement = statement
            if 'FROM roles' in statement:
                seen.append(permisos._current_db_name())

        def fetchall(self):
            if 'FROM roles' in self.statement:
                return [{'id': 4, 'nombre': permisos._current_db_name(),
                         'es_sistema': True, 'base_rol_id': None, 'activo': True}]
            return []

    @contextmanager
    def fake_cursor(**kwargs):
        yield Cursor()

    monkeypatch.setattr(permisos, 'get_db_cursor', fake_cursor)
    permisos.invalidar_cache()
    app = Flask(__name__)
    try:
        for db in ['cyber_t007', 'cyber_t008', 'cyber_t007']:
            with app.test_request_context('/'):
                g.current_tenant = {'db_name': db}
                roles, _ = permisos._estado()
                assert roles[4]['nombre'] == db
        assert seen == ['cyber_t007', 'cyber_t008']
    finally:
        permisos.invalidar_cache()


def test_login_api_no_autentica_usuario_de_otra_instancia(monkeypatch):
    from routes import api_auth

    class Cursor:
        def execute(self, statement, params):
            self.params = params

        def fetchone(self):
            # Único usuario global: pertenece al tenant 8. Sin filtro de tenant,
            # la búsqueda por email lo devolvería desde el dominio del 7.
            if len(self.params) == 1:
                return {'id': 80, 'email': 'otro@cliente.test',
                        'contraseña': 'hash', 'rol_id': 2, 'tenant_id': 8,
                        'estado': 'habilitado', 'db_name': 'cyber_t008',
                        'tenant_slug': 'tienda-b'}
            return None

    @contextmanager
    def fake_cp(**kwargs):
        yield Cursor()

    monkeypatch.setattr(api_auth, 'control_plane_cursor', fake_cp)
    monkeypatch.setattr(api_auth, 'check_password_hash', lambda *args: True)
    monkeypatch.setattr(api_auth, '_get_modules', lambda db: [])
    monkeypatch.setattr(api_auth, 'create_access_token', lambda **kwargs: 'token')
    monkeypatch.setattr(api_auth, 'generate_refresh_token', lambda: ('raw', 'hash'))

    app = Flask(__name__)
    app.before_request(lambda: setattr(g, 'current_tenant',
                                       {'id': 7, 'db_name': 'cyber_t007'}))
    app.register_blueprint(api_auth.api_auth_bp)
    response = app.test_client().post('/api/v1/auth/login',
                                      json={'email': 'otro@cliente.test', 'password': 'clave'})
    assert response.status_code == 401


def test_refresh_api_no_renueva_token_de_otra_instancia(monkeypatch):
    from routes import api_auth

    class Cursor:
        def execute(self, statement, params):
            self.params = params

        def fetchone(self):
            if len(self.params) == 1:
                from datetime import datetime, timedelta, timezone
                return {'user_id': 80, 'tenant_id': 8, 'rol_id': 2,
                        'db_name': 'cyber_t008', 'device_id': 'device',
                        'device_name': 'otro', 'revoked_at': None,
                        'expires_at': datetime.now(timezone.utc) + timedelta(days=1),
                        'estado': 'habilitado'}
            return None

    @contextmanager
    def fake_cp(**kwargs):
        yield Cursor()

    monkeypatch.setattr(api_auth, 'control_plane_cursor', fake_cp)
    monkeypatch.setattr(api_auth, 'hash_token', lambda raw: 'hash')
    monkeypatch.setattr(api_auth, '_get_modules', lambda db: [])
    monkeypatch.setattr(api_auth, 'create_access_token', lambda **kwargs: 'token')
    monkeypatch.setattr(api_auth, 'generate_refresh_token', lambda: ('raw2', 'hash2'))

    app = Flask(__name__)
    app.before_request(lambda: setattr(g, 'current_tenant',
                                       {'id': 7, 'db_name': 'cyber_t007'}))
    app.register_blueprint(api_auth.api_auth_bp)
    response = app.test_client().post('/api/v1/auth/refresh',
                                      json={'refresh_token': 'otro-token'})
    assert response.status_code == 401
