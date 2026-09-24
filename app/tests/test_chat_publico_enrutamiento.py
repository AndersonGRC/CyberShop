# -*- coding: utf-8 -*-
"""Preguntas informativas públicas no se confunden con productos."""

from services.ia_datos.base import Herramienta


def test_envio_usa_faq_y_servicio_usa_catalogo(flask_app, monkeypatch):
    import services.ai_tools as tools
    import services.ia_rag as rag
    from services.chat_publico import motor

    producto = Herramienta('buscar_productos', lambda **_: {}, 'Catálogo.', ('texto',),
                           disparadores=('cuanto cuesta', 'tienen'))
    servicio = Herramienta('servicios_publicos', lambda **_: {}, 'Servicios.',
                           disparadores=('tienen servicio de',))
    consultas = []
    monkeypatch.setattr(motor, 'config_publica', lambda: {'saludo': 'Hola'})
    monkeypatch.setattr(tools, 'permitidas', lambda _ctx: [producto, servicio])
    monkeypatch.setattr(tools, 'ejecutar',
                        lambda code, _params, _ctx: consultas.append(code) or
                        {'servicios': [{'servicio': 'Instalación'}]})
    monkeypatch.setattr(rag, 'buscar', lambda *_a, **_k: [
        {'fuente_id': 1, 'titulo': 'Envíos', 'texto': 'El envío se cotiza por WhatsApp.',
         'url': '/envios'}])

    with flask_app.app_context():
        plan_envio = motor.preparar('¿Cuánto cuesta el envío?')
        assert plan_envio['via'] == motor.VIA_RAG
        assert 'WhatsApp' in plan_envio['texto_base']
        assert consultas == []

        plan_servicio = motor.preparar('¿Tienen servicio de instalación?')
        assert plan_servicio['via'] == motor.VIA_KEYWORD
        assert consultas == ['servicios_publicos']


# ── Caché de respuestas: falla cerrado si no hay identidad de cliente ──
def test_clave_cache_es_none_sin_identidad_de_tenant(flask_app, monkeypatch):
    """Antes, si fallaba la resolución del tenant, la clave caía a "solo la
    huella del texto": dos clientes con la misma pregunta habrían compartido
    la respuesta en caché. Debe fallar CERRADO: sin identidad, no se cachea."""
    from services.chat_publico import motor

    plan = {'pregunta': '¿hacen domicilios?', 'texto_base': 'Sí, hacemos domicilios.'}

    with flask_app.app_context():
        # tenant_id resoluble normalmente
        monkeypatch.setattr('tenant_features.get_current_tenant_id', lambda: 7)
        monkeypatch.setattr(motor, '_current_db_name', lambda: 'cyber_t007')
        assert motor._clave_cache(plan) is not None

        # get_current_tenant_id explota (contexto sin resolver)
        def _revienta():
            raise RuntimeError('sin contexto de tenant')
        monkeypatch.setattr('tenant_features.get_current_tenant_id', _revienta)
        assert motor._clave_cache(plan) is None

        # _current_db_name devuelve vacío
        monkeypatch.setattr('tenant_features.get_current_tenant_id', lambda: 7)
        monkeypatch.setattr(motor, '_current_db_name', lambda: '')
        assert motor._clave_cache(plan) is None


def test_cache_no_guarda_ni_lee_con_clave_none(flask_app):
    from services.chat_publico import motor

    motor._CACHE.clear()
    motor._cache_guardar(None, 'respuesta que no debe quedar cacheada')
    assert motor._CACHE == {}
    assert motor._cache_leer(None) is None


def test_dos_clientes_con_la_misma_pregunta_no_comparten_cache(flask_app, monkeypatch):
    """Mismo texto, mismo texto_base, DOS bases distintas: deben ser dos
    entradas de caché separadas, nunca la misma."""
    from services.chat_publico import motor

    plan = {'pregunta': '¿hacen domicilios?', 'texto_base': 'Sí, hacemos domicilios.'}
    with flask_app.app_context():
        monkeypatch.setattr('tenant_features.get_current_tenant_id', lambda: 7)
        monkeypatch.setattr(motor, '_current_db_name', lambda: 'cyber_t007')
        clave_a = motor._clave_cache(plan)

        monkeypatch.setattr('tenant_features.get_current_tenant_id', lambda: 8)
        monkeypatch.setattr(motor, '_current_db_name', lambda: 'cyber_t008')
        clave_b = motor._clave_cache(plan)

    assert clave_a != clave_b
    assert clave_a.startswith('cyber_t007:7:')
    assert clave_b.startswith('cyber_t008:8:')
