"""Vencimiento del token CSRF por pantalla.

En todo el sistema el token de la página vence a la hora (WTF_CSRF_TIME_LIMIT,
valor por defecto de Flask-WTF) y así sigue. El restaurante y el POS (con su
caja) se dejan abiertos todo el turno: en sus rutas el token vale 2 horas
(decisión del dueño, 9-oct-2026). Se reconocen por la dirección:

    /admin/restaurante/...   mesas, consumos, cobro, salones
    /admin/pos/...           ventas, búsqueda por código, caja

Además «Atender» renueva el token sola en cada refresco del salón (ver
routes/restaurant_tables.py y static/js/restaurant_mesas.js).
"""
import logging

from flask import current_app, g, request
from flask_wtf.csrf import CSRFProtect, same_origin, validate_csrf
from wtforms import ValidationError

logger = logging.getLogger(__name__)

PREFIJOS_TURNO_LARGO = ('/admin/restaurante/', '/admin/pos/')
TIEMPO_TURNO_LARGO = 2 * 3600          # segundos; se puede cambiar con CSRF_TIEMPO_TURNO_LARGO


def limite_para(path):
    """Segundos que vale el token en esta ruta, o None = el general (1 h)."""
    if not path.startswith(PREFIJOS_TURNO_LARGO):
        return None
    general = current_app.config.get('WTF_CSRF_TIME_LIMIT', 3600)
    largo = current_app.config.get('CSRF_TIEMPO_TURNO_LARGO', TIEMPO_TURNO_LARGO)
    if general is None or general >= largo:
        return None                      # el general ya dura igual o más: no se acorta
    return largo


class CSRFProtectPorPantalla(CSRFProtect):
    """CSRFProtect con más tiempo solo en las rutas del restaurante y el POS."""

    def protect(self):
        limite = limite_para(request.path)
        if limite is None:
            return super().protect()
        # Lo mismo que CSRFProtect.protect de Flask-WTF 1.2.x, cambiando solo el
        # time_limit. tests/test_csrf_pantallas.py avisa si la librería cambia.
        if request.method not in current_app.config['WTF_CSRF_METHODS']:
            return None
        try:
            validate_csrf(self._get_csrf_token(), time_limit=limite)
        except ValidationError as e:
            logger.info(e.args[0])
            self._error_response(e.args[0])
        if request.is_secure and current_app.config['WTF_CSRF_SSL_STRICT']:
            if not request.referrer:
                self._error_response('The referrer header is missing.')
            good_referrer = f'https://{request.host}/'
            if not same_origin(request.referrer, good_referrer):
                self._error_response('The referrer does not match the host.')
        g.csrf_valid = True
        return None
