# -*- coding: utf-8 -*-
"""routes/pwa.py — La tienda y el panel se instalan como una app (PWA, 1.9.20.0).

Rutas sin sesión (las pide el navegador solo): el manifiesto de la tienda, el del
panel, el service worker, el aviso de «sin conexión» y los íconos de la tienda.
Va en un blueprint aparte porque no debe quedar detrás de ningún inicio de sesión.
"""
import json

from flask import Blueprint, Response, abort, current_app, redirect, session, url_for

from services import pwa

pwa_bp = Blueprint('pwa', __name__)

_SIN_CACHE = 'no-cache, no-store, must-revalidate, max-age=0'


@pwa_bp.app_context_processor
def _pwa_en_plantillas():
    """`pwa_activa` solo existe con este código: una tienda que aún corre el código
    anterior lee las plantillas nuevas, no la encuentra y no ofrece instalar nada."""
    return {'pwa_activa': pwa.activa()}


def _manifiesto(tipo):
    if not pwa.activa():
        abort(404)
    cuerpo = json.dumps(pwa.manifiesto(tipo), ensure_ascii=False)
    respuesta = Response(cuerpo, mimetype='application/manifest+json')
    respuesta.headers['Cache-Control'] = _SIN_CACHE
    return respuesta


@pwa_bp.route('/manifest.webmanifest')
def manifiesto_tienda():
    return _manifiesto('tienda')


@pwa_bp.route('/manifest-panel.webmanifest')
def manifiesto_panel():
    return _manifiesto('panel')


@pwa_bp.route('/sw.js')
def service_worker():
    """Siempre responde (también con la app apagada, para retirar el que ya esté
    instalado). Sin caché: Cloudflare guarda los .js y dejaría uno viejo."""
    version = str(current_app.config.get('APP_VERSION') or '0')
    respuesta = Response(pwa.service_worker(version), mimetype='application/javascript')
    respuesta.headers['Cache-Control'] = _SIN_CACHE
    respuesta.headers['Service-Worker-Allowed'] = '/'
    return respuesta


@pwa_bp.route('/pwa/sin-conexion')
def sin_conexion():
    respuesta = Response(pwa.pagina_sin_conexion(), mimetype='text/html')
    respuesta.headers['Cache-Control'] = _SIN_CACHE
    respuesta.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return respuesta


@pwa_bp.route('/pwa/icono-<int:tamano>.png')
@pwa_bp.route('/pwa/icono-<variante>-<int:tamano>.png')
def icono(tamano, variante='normal'):
    png = pwa.icono_png(tamano, variante)
    if png is None:
        abort(404)
    respuesta = Response(png, mimetype='image/png')
    # Una hora: el manifiesto pide los íconos con ?v=<huella del logo>, así que un
    # logo nuevo se ve de inmediato en la app; esto solo cubre el ícono sin huella.
    respuesta.headers['Cache-Control'] = 'public, max-age=3600'
    return respuesta


@pwa_bp.route('/pwa/panel')
def entrar_al_panel():
    """Donde abre la app del panel: cada quien cae en su pantalla de trabajo, igual
    que al iniciar sesión; sin sesión, al inicio de sesión."""
    from security import ADMIN_STAFF, ROL_CAJERO, ROL_CLIENTE, ROL_CONTADOR, ROL_MESERO
    rol = session.get('rol_id')
    if rol is None:
        destino = url_for('auth.login', acceso=1)
    elif rol in ADMIN_STAFF:
        destino = url_for('admin.dashboard_admin')
    elif rol == ROL_CONTADOR:
        destino = url_for('contabilidad.dashboard')
    elif rol in (ROL_MESERO, ROL_CAJERO):
        destino = url_for('restaurant_tables.waiter_panel')
    elif rol == ROL_CLIENTE:
        destino = url_for('auth.dashboard_cliente')
    else:
        destino = url_for('admin.dashboard_admin')   # rol creado por el dueño
    respuesta = redirect(destino)
    respuesta.headers['Cache-Control'] = _SIN_CACHE
    return respuesta
