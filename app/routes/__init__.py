"""
routes/ — Paquete de blueprints Flask para CyberShop.

Cada modulo define un Blueprint con sus rutas agrupadas por
responsabilidad: autenticacion, paginas publicas, administracion
y pagos. ``register_blueprints()`` los registra todos en la app.
"""

from routes.auth import auth_bp
from routes.public import public_bp
from routes.admin import admin_bp
from routes.payments import payments_bp


def register_blueprints(app):
    """Registra todos los blueprints en la aplicacion Flask.

    Args:
        app: Instancia de Flask donde se registran las rutas.
    """
    app.register_blueprint(auth_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payments_bp)
