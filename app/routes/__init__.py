"""
routes/ — Paquete de blueprints Flask para CyberShop.

Cada modulo define un Blueprint con sus rutas agrupadas por
responsabilidad: autenticacion, paginas publicas, administracion
y pagos. ``register_blueprints()`` los registra todos en la app.
"""

import os

from routes.auth import auth_bp
from routes.public import public_bp
from routes.admin import admin_bp
from routes.payments import payments_bp
from routes.quotes import quotes_bp
from routes.restaurant_tables import restaurant_tables_bp


def register_blueprints(app):
    """Registra todos los blueprints en la aplicacion Flask.

    Args:
        app: Instancia de Flask donde se registran las rutas.
    """
    app.register_blueprint(auth_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(restaurant_tables_bp)
    
    # Nomina
    from routes.nomina import nomina_bp
    app.register_blueprint(nomina_bp)

    # Cuentas de Cobro
    from routes.billing import billing_bp
    app.register_blueprint(billing_bp)

    # CRM
    from routes.crm import crm_bp
    app.register_blueprint(crm_bp)

    # Google Calendar
    from routes.google_calendar import google_bp
    app.register_blueprint(google_bp)

    # Soporte / Tickets
    from routes.soporte import soporte_bp
    app.register_blueprint(soporte_bp)

    # Contabilidad
    from routes.contabilidad import contabilidad_bp
    app.register_blueprint(contabilidad_bp)

    # Videollamadas
    from routes.video import video_bp
    app.register_blueprint(video_bp)

    # Cupones de descuento
    from routes.cupones import cupones_bp
    app.register_blueprint(cupones_bp)

    # Wishlist / Lista de deseos
    from routes.wishlist import wishlist_bp
    app.register_blueprint(wishlist_bp)

    # Compartir Archivos (carpetas con link publico)
    from routes.share import share_bp
    app.register_blueprint(share_bp)

    # API REST v1 (habilitada con CYBERSHOP_API_ENABLED=1)
    if os.getenv('CYBERSHOP_API_ENABLED', '0') == '1':
        from routes.api_auth import api_auth_bp
        from routes.api_health import api_health_bp
        app.register_blueprint(api_auth_bp)
        app.register_blueprint(api_health_bp)
        return (api_auth_bp, api_health_bp)
    return ()
