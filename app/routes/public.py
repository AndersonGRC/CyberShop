"""
routes/public.py — Blueprint de paginas publicas.

Rutas: /, /productos, /servicios, /quienes_somos, /contactenos,
       /carrito, /enviar-mensaje, error 404.
"""

import re

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask import current_app as app
from helpers_gmail import enviar_email_gmail

from database import get_db_connection, get_db_cursor
from helpers import get_common_data, formatear_moneda
from security import controlar_tasa_solicitudes

public_bp = Blueprint('public', __name__)

# Paginación por defecto
PRODUCTOS_POR_PAGINA = 24


@public_bp.route('/')
def index():
    """Pagina principal de CyberShop."""
    datosApp = get_common_data()
    slides = []
    publicaciones = []
    config = {}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT imagen, titulo, descripcion, orden FROM slides_home WHERE activo = TRUE ORDER BY orden ASC, id ASC')
            slides = cur.fetchall()
            cur.execute('SELECT titulo, descripcion, imagen FROM publicaciones_home WHERE activo = TRUE ORDER BY fecha_creacion DESC')
            publicaciones = cur.fetchall()
            cur.execute('SELECT clave, valor FROM config_secciones')
            for row in cur.fetchall():
                config[row['clave']] = row['valor'] == 'true'
    except Exception as e:
        app.logger.error(f"Error cargando página principal: {e}")
    return render_template('index.html', datosApp=datosApp, slides=slides, publicaciones=publicaciones, config=config)


@public_bp.route('/productos')
def productos():
    """Catalogo de productos con filtros, busqueda y orden."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM config_secciones WHERE clave = 'mostrar_modulo_ventas'")
            row = cur.fetchone()
            if row and row['valor'] == 'false':
                return redirect(url_for('public.index'))
    except Exception as e:
        app.logger.warning(f"Error verificando config ventas: {e}")

    # Parámetros de filtro desde URL
    q          = request.args.get('q', '').strip()
    categoria  = request.args.get('categoria', '')
    orden      = request.args.get('orden', '')
    precio_min = request.args.get('precio_min', '')
    precio_max = request.args.get('precio_max', '')
    try:
        pagina = max(1, int(request.args.get('pagina', 1)))
    except (ValueError, TypeError):
        pagina = 1

    datosApp = get_common_data()
    generos = []
    total_productos = 0
    try:
        from collections import defaultdict

        with get_db_cursor(dict_cursor=True) as cur:
            # Categorías para el filtro
            cur.execute('SELECT id, nombre FROM generos ORDER BY nombre ASC')
            generos = cur.fetchall()

            # Construir WHERE dinámico
            condiciones = []
            params = []
            if q:
                condiciones.append("(p.nombre ILIKE %s OR p.descripcion ILIKE %s)")
                params += [f'%{q}%', f'%{q}%']
            if categoria:
                condiciones.append("p.genero_id = %s")
                params.append(int(categoria))
            if precio_min:
                condiciones.append("p.precio >= %s")
                params.append(float(precio_min))
            if precio_max:
                condiciones.append("p.precio <= %s")
                params.append(float(precio_max))

            where = ('WHERE ' + ' AND '.join(condiciones)) if condiciones else ''

            orden_sql = {
                'precio_asc':  'p.precio ASC',
                'precio_desc': 'p.precio DESC',
                'nombre':      'p.nombre ASC',
                'nuevo':       'p.id DESC',
            }.get(orden, 'p.nombre ASC')

            # Conteo total para paginación
            cur.execute(f'''
                SELECT COUNT(*) FROM productos p
                JOIN generos g ON p.genero_id = g.id
                {where}
            ''', params)
            total_productos = cur.fetchone()[0]

            offset = (pagina - 1) * PRODUCTOS_POR_PAGINA
            cur.execute(f'''
                SELECT p.*, g.nombre AS genero
                FROM productos p
                JOIN generos g ON p.genero_id = g.id
                {where}
                ORDER BY {orden_sql}
                LIMIT %s OFFSET %s
            ''', params + [PRODUCTOS_POR_PAGINA, offset])
            raw_productos = cur.fetchall()

            # Imágenes agrupadas
            cur.execute('''
                SELECT producto_id, imagen_url
                FROM producto_imagenes
                ORDER BY producto_id, es_principal DESC, orden ASC, id ASC
            ''')
            imgs_por_producto = defaultdict(list)
            for img in cur.fetchall():
                imgs_por_producto[img['producto_id']].append(img['imagen_url'])

            # Rating promedio por producto
            cur.execute('''
                SELECT producto_id,
                       ROUND(AVG(calificacion)::numeric, 1) AS promedio,
                       COUNT(*) AS total
                FROM producto_comentarios
                WHERE aprobado = TRUE
                GROUP BY producto_id
            ''')
            ratings = {r['producto_id']: r for r in cur.fetchall()}

        productos_lista = []
        for p in raw_productos:
            prod = dict(p)
            prod['precio_fmt'] = formatear_moneda(float(prod['precio']))
            pid = prod['id']
            imagenes = imgs_por_producto.get(pid, [])
            if not imagenes and prod.get('imagen'):
                imagenes = [prod['imagen']]
            prod['imagenes'] = imagenes
            r = ratings.get(pid)
            prod['rating_promedio'] = float(r['promedio']) if r else 0
            prod['rating_total']    = int(r['total'])    if r else 0
            productos_lista.append(prod)

        datosApp['productos'] = productos_lista
    except Exception as e:
        app.logger.error(f"Error cargando productos: {e}")
        datosApp['productos'] = []

    filtros_activos = bool(q or categoria or orden or precio_min or precio_max)
    import math
    total_paginas = math.ceil(total_productos / PRODUCTOS_POR_PAGINA) if total_productos > 0 else 1
    return render_template('productos.html', datosApp=datosApp,
                           generos=generos,
                           filtros=dict(q=q, categoria=categoria, orden=orden,
                                        precio_min=precio_min, precio_max=precio_max),
                           filtros_activos=filtros_activos,
                           pagina=pagina, total_paginas=total_paginas,
                           total_productos=total_productos)


@public_bp.route('/servicios')
def servicios():
    """Pagina de servicios."""
    datosApp = get_common_data()
    servicios_lista = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT titulo, descripcion, imagen, beneficios, orden FROM servicios_home WHERE activo = TRUE ORDER BY orden ASC, id ASC')
            servicios_lista = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando servicios: {e}")
    return render_template('servicios.html', datosApp=datosApp, servicios_db=servicios_lista)


@public_bp.route('/quienes_somos')
def quienes_somos():
    """Redirige a la seccion 'Quienes somos' en la pagina principal."""
    return redirect(url_for('public.index', _anchor='quienes_somos'))


@public_bp.route('/contactenos')
def contactenos():
    """Redirige a la seccion de contacto en la pagina principal."""
    return redirect(url_for('public.index', _anchor='contactenos'))


@public_bp.route('/producto/<int:producto_id>')
def detalle_producto(producto_id):
    """Página de detalle de un producto individual."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM config_secciones WHERE clave = 'mostrar_modulo_ventas'")
            row = cur.fetchone()
            if row and row['valor'] == 'false':
                return redirect(url_for('public.index'))
    except Exception:
        pass
    datosApp = get_common_data()
    producto = None
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('''
                SELECT p.*, g.nombre AS genero
                FROM productos p
                JOIN generos g ON p.genero_id = g.id
                WHERE p.id = %s
            ''', (producto_id,))
            producto = cur.fetchone()
            if not producto:
                return render_template('404.html'), 404
            producto = dict(producto)
            producto['precio_fmt'] = formatear_moneda(float(producto['precio']))
            cur.execute('''
                SELECT imagen_url
                FROM producto_imagenes
                WHERE producto_id = %s
                ORDER BY es_principal DESC, orden ASC, id ASC
            ''', (producto_id,))
            imagenes = [r['imagen_url'] for r in cur.fetchall()]
            if not imagenes and producto.get('imagen'):
                imagenes = [producto['imagen']]
            producto['imagenes'] = imagenes

            # Productos relacionados (misma categoría)
            cur.execute('''
                SELECT p.id, p.nombre, p.precio, p.imagen
                FROM productos p
                WHERE p.genero_id = %s AND p.id != %s AND p.stock > 0
                ORDER BY RANDOM() LIMIT 4
            ''', (producto['genero_id'], producto_id))
            relacionados = []
            for r in cur.fetchall():
                rp = dict(r)
                rp['precio_fmt'] = formatear_moneda(float(rp['precio']))
                relacionados.append(rp)

            # Comentarios y calificaciones
            cur.execute('''
                SELECT c.*, u.nombre AS usuario_nombre
                FROM producto_comentarios c
                LEFT JOIN usuarios u ON c.usuario_id = u.id
                WHERE c.producto_id = %s AND c.aprobado = TRUE
                ORDER BY c.fecha_creacion DESC
            ''', (producto_id,))
            comentarios = [dict(c) for c in cur.fetchall()]

            cur.execute('''
                SELECT ROUND(AVG(calificacion)::numeric, 1) AS promedio,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE calificacion = 5) AS c5,
                       COUNT(*) FILTER (WHERE calificacion = 4) AS c4,
                       COUNT(*) FILTER (WHERE calificacion = 3) AS c3,
                       COUNT(*) FILTER (WHERE calificacion = 2) AS c2,
                       COUNT(*) FILTER (WHERE calificacion = 1) AS c1
                FROM producto_comentarios
                WHERE producto_id = %s AND aprobado = TRUE
            ''', (producto_id,))
            stats_rating = dict(cur.fetchone() or {})

    except Exception as e:
        app.logger.error(f"Error cargando detalle producto {producto_id}: {e}")
        return render_template('404.html'), 404

    return render_template('producto_detalle.html', datosApp=datosApp,
                           producto=producto, relacionados=relacionados,
                           comentarios=comentarios, stats_rating=stats_rating)


@public_bp.route('/producto/<int:producto_id>/comentar', methods=['POST'])
def comentar_producto(producto_id):
    """Recibe y guarda un comentario/calificacion de producto."""
    # Rate limiting: máx 5 comentarios por minuto por IP
    if not controlar_tasa_solicitudes(request.remote_addr, max_requests=5, interval=60):
        flash('Demasiadas solicitudes. Espera un momento antes de intentar de nuevo.', 'warning')
        return redirect(url_for('public.detalle_producto', producto_id=producto_id) + '#resenas')

    from flask import session as flask_session
    autor   = request.form.get('autor_nombre', '').strip()[:100]
    cal_str = request.form.get('calificacion', '0')
    texto   = request.form.get('comentario', '').strip()[:2000]

    if not autor or not texto:
        flash('Por favor completa tu nombre y comentario.', 'warning')
        return redirect(url_for('public.detalle_producto', producto_id=producto_id) + '#resenas')

    try:
        calificacion = int(cal_str)
        if not 1 <= calificacion <= 5:
            raise ValueError
    except (ValueError, TypeError):
        flash('Selecciona una calificación entre 1 y 5 estrellas.', 'warning')
        return redirect(url_for('public.detalle_producto', producto_id=producto_id) + '#resenas')

    usuario_id = flask_session.get('usuario_id')
    try:
        with get_db_cursor() as cur:
            cur.execute('''
                INSERT INTO producto_comentarios
                    (producto_id, usuario_id, autor_nombre, calificacion, comentario)
                VALUES (%s, %s, %s, %s, %s)
            ''', (producto_id, usuario_id, autor, calificacion, texto))
        flash('¡Gracias por tu reseña!', 'success')
    except Exception as e:
        app.logger.error(f"Error guardando comentario: {e}")
        flash('No se pudo guardar tu comentario. Intenta de nuevo.', 'error')

    return redirect(url_for('public.detalle_producto', producto_id=producto_id) + '#resenas')


@public_bp.route('/carrito')
def ver_carrito():
    """Muestra la pagina del carrito de compras."""
    # Si el carrito esta desactivado, redirigir al home
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM config_secciones WHERE clave = 'mostrar_modulo_ventas'")
            row = cur.fetchone()
            if row and row['valor'] == 'false':
                flash('El carrito de compras no esta disponible en este momento.', 'warning')
                return redirect(url_for('public.index'))
    except Exception:
        pass
    datosApp = get_common_data()
    return render_template('carrito.html', datosApp=datosApp)


@public_bp.route('/enviar-mensaje', methods=['POST'])
def enviar_mensaje():
    """Envia un mensaje de contacto por email via SMTP."""
    try:
        # Honeypot anti-bot
        if request.form.get('website'):
            return redirect(url_for('public.index'))

        # Rate limiting: máx 3 mensajes por minuto por IP
        if not controlar_tasa_solicitudes(request.remote_addr, max_requests=3, interval=60):
            flash('Demasiadas solicitudes. Espera un momento.', 'warning')
            return redirect(url_for('public.index'))

        # Validar reCAPTCHA (obligatorio)
        recaptcha_response = request.form.get('g-recaptcha-response', '').strip()
        recaptcha_secret = app.config.get('RECAPTCHA_SECRET_KEY')
        if not recaptcha_secret:
            flash('El servicio de contacto no está configurado correctamente.', 'error')
            return redirect(url_for('public.index') + '#contactenos')
        if not recaptcha_response:
            flash('Por favor completa la verificación "No soy un robot".', 'warning')
            return redirect(url_for('public.index') + '#contactenos')
        try:
            import requests as http_requests
            verify = http_requests.post('https://www.google.com/recaptcha/api/siteverify', data={
                'secret': recaptcha_secret,
                'response': recaptcha_response,
                'remoteip': request.remote_addr
            }, timeout=5)
            result = verify.json()
        except Exception:
            flash('No se pudo verificar el reCAPTCHA. Intenta de nuevo.', 'error')
            return redirect(url_for('public.index') + '#contactenos')
        if not result.get('success'):
            flash('Verificación de seguridad fallida. Intenta de nuevo.', 'error')
            return redirect(url_for('public.index') + '#contactenos')

        # Sanitizar entrada (evitar email header injection)
        name = request.form.get('name', '').strip()[:200]
        email = request.form.get('email', '').strip()[:200]
        message_text = request.form.get('message', '').strip()[:5000]

        # Eliminar caracteres de control que podrían inyectar headers
        name = re.sub(r'[\r\n]', ' ', name)
        email = re.sub(r'[\r\n]', ' ', email)

        if not name or not email or not message_text:
            flash('Por favor completa todos los campos.', 'warning')
            return redirect(url_for('public.index'))

        from database import get_db_cursor
        email_destino = app.config.get('MAIL_DEFAULT_SENDER', '')
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute("SELECT valor FROM cliente_config WHERE clave='contacto_email_destino'")
                row = cur.fetchone()
                if row and row['valor']:
                    email_destino = row['valor']
        except Exception:
            pass
        html_body = f"""
        <div style="font-family:'Segoe UI',Arial,sans-serif;max-width:600px;margin:0 auto;border:1px solid #e0e0e0;border-radius:12px;overflow:hidden;">
            <div style="background:linear-gradient(135deg,#122C94,#091C5A);padding:24px 30px;">
                <h2 style="color:#fff;margin:0;font-size:20px;">
                    <span style="margin-right:8px;">&#9993;</span> Nuevo mensaje de contacto
                </h2>
            </div>
            <div style="padding:28px 30px;background:#fff;">
                <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
                    <tr>
                        <td style="padding:10px 14px;background:#f4f6fb;border-radius:8px 0 0 0;font-weight:600;color:#555;width:100px;vertical-align:top;">Nombre</td>
                        <td style="padding:10px 14px;background:#f4f6fb;border-radius:0 8px 0 0;color:#222;">{name}</td>
                    </tr>
                    <tr>
                        <td style="padding:10px 14px;font-weight:600;color:#555;vertical-align:top;">Email</td>
                        <td style="padding:10px 14px;color:#222;">
                            <a href="mailto:{email}" style="color:#122C94;text-decoration:none;">{email}</a>
                        </td>
                    </tr>
                </table>
                <div style="background:#f9fafb;border-left:4px solid #122C94;border-radius:0 8px 8px 0;padding:16px 20px;margin-top:8px;">
                    <p style="margin:0 0 6px;font-weight:600;color:#555;font-size:13px;text-transform:uppercase;letter-spacing:0.5px;">Mensaje</p>
                    <p style="margin:0;color:#333;line-height:1.6;white-space:pre-wrap;">{message_text}</p>
                </div>
            </div>
            <div style="background:#f4f6fb;padding:14px 30px;text-align:center;font-size:12px;color:#999;">
                Enviado desde el formulario de contacto del sitio web
            </div>
        </div>"""

        enviado = enviar_email_gmail(
            email_destino,
            f"Contacto: {name}",
            f"Mensaje de {name} ({email}):\n\n{message_text}",
            html=html_body
        )
        if enviado:
            flash('Mensaje enviado.', 'success')
        else:
            flash('No se pudo enviar el mensaje. Intenta más tarde.', 'error')
    except Exception:
        flash('Error enviando.', 'error')
    return redirect(url_for('public.index'))


@public_bp.app_errorhandler(404)
def pagina_no_encontrada(error):
    """Pagina de error 404 personalizada."""
    return render_template('404.html'), 404
