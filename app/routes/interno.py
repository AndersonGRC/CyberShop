# -*- coding: utf-8 -*-
"""Llamadas internas del panel maestro al sitio de CyberShop (el operador).

El maestro no envía correos: cuando crea un cliente a mano le pide a esta tienda
(la de CyberShop, que ya envía los de la prueba gratis y la compra en línea con su
Gmail) que mande el correo de bienvenida con los datos de acceso (1.9.12.0).

Protección: el secreto compartido INTERNAL_API_KEY en el header X-Internal-Key
(el mismo con que la web le habla al maestro) y solo en la tienda del operador;
en cualquier otra tienda la ruta no existe (404). La contraseña nunca se guarda
ni se escribe en el log."""
import hmac

from flask import Blueprint, abort, current_app, jsonify, request

from config import Config

interno_bp = Blueprint('interno', __name__)

_PLANES = {'basico': 'Básico', 'estandar': 'Estándar', 'ultra': 'Ultra'}


def _autorizado():
    clave = (getattr(Config, 'INTERNAL_API_KEY', '') or '').strip()
    recibido = (request.headers.get('X-Internal-Key') or '').strip()
    return bool(clave) and hmac.compare_digest(recibido.encode(), clave.encode())


def _texto(valor, maximo):
    return ' '.join(str(valor or '').split())[:maximo]


@interno_bp.route('/internal/api/v1/correo-bienvenida', methods=['POST'])
def correo_bienvenida():
    """Envía «¡Tu tienda está lista!» (tienda, panel, usuario y contraseña temporal)
    al dueño de una tienda recién creada desde el maestro."""
    from services.public_site_service import is_public_section_enabled
    if not is_public_section_enabled('mostrar_modulo_software', False):
        abort(404)                                    # solo la tienda de CyberShop envía
    if not _autorizado():
        return jsonify({'ok': False, 'error': 'no autorizado'}), 403

    from security import controlar_tasa_solicitudes
    if not controlar_tasa_solicitudes(f"interno-bienvenida:{request.remote_addr or '?'}",
                                      max_requests=30, interval=600):
        return jsonify({'ok': False, 'error': 'demasiadas solicitudes'}), 429

    datos = request.get_json(silent=True) or {}
    from services import correo_service
    correo, error = correo_service.validar(datos.get('admin_email'), comprobar_dominio=False)
    dominio = _texto(datos.get('dominio'), 120).lower().strip('/')
    clave = str(datos.get('admin_password') or '')
    if error or not dominio or ' ' in dominio or not clave or len(clave) > 128:
        return jsonify({'ok': False, 'error': error or 'faltan datos'}), 400

    from helpers_email_templates import generar_email_bienvenida_tienda
    plan_key = _texto(datos.get('plan'), 30).lower()
    correo_tuple = generar_email_bienvenida_tienda(
        {'buyer_nombre': _texto(datos.get('admin_nombre'), 120), 'es_trial': False, 'origen': 'maestro'},
        {'nombre': _PLANES.get(plan_key, plan_key.capitalize() or 'CyberShop'), 'tiene_app': True},
        {'domain': dominio, 'admin_email': correo, 'admin_password': clave,
         'client_code': _texto(datos.get('client_code'), 64)})

    from services.venta_automatica_service import _enviar
    enviado = bool(_enviar(correo, correo_tuple))
    current_app.logger.info(f"Bienvenida de tienda creada en el maestro ({dominio}): "
                            f"{'enviada' if enviado else 'NO enviada'} a {correo}")
    return jsonify({'ok': enviado}), (200 if enviado else 502)
