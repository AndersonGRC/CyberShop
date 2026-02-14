"""
routes/public.py — Blueprint de paginas publicas.

Rutas: /, /productos, /servicios, /quienes_somos, /contactenos,
       /carrito, /enviar-mensaje, error 404.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask import current_app as app
from flask_mail import Message

from database import get_db_connection
from helpers import get_common_data, formatear_moneda

public_bp = Blueprint('public', __name__)


@public_bp.route('/')
def index():
    """Pagina principal de CyberShop."""
    datosApp = get_common_data()
    return render_template('index.html', datosApp=datosApp)


@public_bp.route('/productos')
def productos():
    """Catalogo de productos con precios formateados en COP."""
    datosApp = get_common_data()
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT p.*, g.nombre AS genero FROM productos p JOIN generos g ON p.genero_id = g.id')
        raw_productos = cur.fetchall()
        cur.close()
        conn.close()
        productos_lista = []
        for p in raw_productos:
            prod = list(p)
            prod[3] = formatear_moneda(float(prod[3]))
            productos_lista.append(prod)
        datosApp['productos'] = productos_lista
    except Exception:
        datosApp['productos'] = []
    return render_template('productos.html', datosApp=datosApp)


@public_bp.route('/servicios')
def servicios():
    """Pagina de servicios."""
    datosApp = get_common_data()
    return render_template('servicios.html', datosApp=datosApp)


@public_bp.route('/quienes_somos')
def quienes_somos():
    """Redirige a la seccion 'Quienes somos' en la pagina principal."""
    return redirect(url_for('public.index', _anchor='quienes_somos'))


@public_bp.route('/contactenos')
def contactenos():
    """Redirige a la seccion de contacto en la pagina principal."""
    return redirect(url_for('public.index', _anchor='contactenos'))


@public_bp.route('/carrito')
def ver_carrito():
    """Muestra la pagina del carrito de compras."""
    datosApp = get_common_data()
    return render_template('carrito.html', datosApp=datosApp)


@public_bp.route('/enviar-mensaje', methods=['POST'])
def enviar_mensaje():
    """Envia un mensaje de contacto por email via SMTP."""
    try:
        if request.form.get('website'):
            return redirect(url_for('public.index'))
        from app import mail
        msg = Message(
            subject=f"Contacto: {request.form.get('name')}",
            sender=app.config['MAIL_USERNAME'],
            recipients=[app.config['MAIL_DEFAULT_SENDER']],
            body=f"Mensaje de {request.form.get('name')} ({request.form.get('email')}): \n\n {request.form.get('message')}"
        )
        with mail.connect() as conn:
            conn.send(msg)
        flash('Mensaje enviado.', 'success')
    except Exception:
        flash('Error enviando.', 'error')
    return redirect(url_for('public.index'))


@public_bp.app_errorhandler(404)
def pagina_no_encontrada(error):
    """Pagina de error 404 personalizada."""
    return render_template('404.html'), 404
