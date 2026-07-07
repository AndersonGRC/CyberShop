"""
extensions.py — Instancias de extensiones compartidas (evita imports circulares).

El limiter se define aquí sin app; app.py hace limiter.init_app(app) y los
blueprints (auth, api_sync) importan `limiter` para decorar rutas sensibles.
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# key por IP (respeta ProxyFix ya configurado en app.py). Sin default_limits:
# SOLO se limita lo que se decore explícitamente (login, registro), para no
# arriesgar bloqueos accidentales de tráfico legítimo.
limiter = Limiter(key_func=get_remote_address)
