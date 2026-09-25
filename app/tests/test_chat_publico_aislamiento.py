# -*- coding: utf-8 -*-
"""Aislamiento multi-tenant de la caché de respuestas del chat público.

test_chat_publico_enrutamiento.py ya prueba que la CLAVE de caché es
distinta por tenant (motor._clave_cache). Esta prueba cierra el círculo con
dos "negocios" simulados de catálogos distintos (misma técnica: se simula
la identidad de tenant en vez de depender de una segunda base de datos real
con datos casualmente distintos — así se aísla con precisión la única
variable que importa: la identidad) y confirma el efecto real que protege a
un cliente de otro: ninguno puede leer la respuesta cacheada del otro, ni
aunque hagan la MISMA pregunta con el MISMO texto base.
"""
from services.chat_publico import motor


def _clave(monkeypatch, tenant_id, db_name, pregunta):
    monkeypatch.setattr('tenant_features.get_current_tenant_id', lambda: tenant_id)
    monkeypatch.setattr(motor, '_current_db_name', lambda: db_name)
    plan = {'pregunta': pregunta, 'texto_base': 'base'}
    return motor._clave_cache(plan)


def test_cada_negocio_solo_lee_su_propia_respuesta_cacheada(flask_app, monkeypatch):
    motor._CACHE.clear()
    pregunta = '¿tienen café?'  # misma pregunta literal para los dos negocios

    with flask_app.app_context():
        clave_a = _clave(monkeypatch, 101, 'cyber_negocioA', pregunta)
        motor._cache_guardar(clave_a, 'Sí, tenemos Café tinto a $3.000.')

        clave_b = _clave(monkeypatch, 202, 'cyber_negocioB', pregunta)
        assert clave_b != clave_a, 'dos negocios distintos no deberían compartir clave de caché'
        assert motor._cache_leer(clave_b) is None, \
            'el negocio B leyó una respuesta que nunca guardó — fuga de caché entre tenants'

        motor._cache_guardar(clave_b, 'No manejamos café, pero sí Tornillos 1/4.')

        # Con las dos respuestas guardadas, cada quien sigue viendo SOLO la suya.
        assert motor._cache_leer(clave_a) == 'Sí, tenemos Café tinto a $3.000.'
        assert motor._cache_leer(clave_b) == 'No manejamos café, pero sí Tornillos 1/4.'
        assert 'Tornillo' not in motor._cache_leer(clave_a)
        assert 'Café' not in motor._cache_leer(clave_b)

    motor._CACHE.clear()


def test_el_mismo_negocio_repite_su_propia_respuesta_cacheada(flask_app, monkeypatch):
    """Caso positivo: la caché sí debe funcionar DENTRO del mismo negocio."""
    motor._CACHE.clear()
    with flask_app.app_context():
        clave = _clave(monkeypatch, 303, 'cyber_negocioC', '¿tienen leche?')
        motor._cache_guardar(clave, 'Sí, leche entera y deslactosada.')

        clave_repetida = _clave(monkeypatch, 303, 'cyber_negocioC', '¿tienen leche?')
        assert clave_repetida == clave
        assert motor._cache_leer(clave_repetida) == 'Sí, leche entera y deslactosada.'

    motor._CACHE.clear()
