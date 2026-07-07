"""
routes/public.py — Blueprint de paginas publicas.

Rutas: /, /productos, /servicios, /quienes_somos, /contactenos,
       /carrito, /enviar-mensaje, error 404.
"""

import re

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from flask import current_app as app
from helpers_gmail import enviar_email_gmail


def _csrf_exempt(view):
    """Marca una vista como exenta de CSRF (mismo patron que routes/payments.py)."""
    view.csrf_exempt = True
    return view

from database import get_db_cursor
from helpers import get_common_data, formatear_moneda
from security import controlar_tasa_solicitudes
from services.public_site_service import (
    get_public_contact_destination_email,
    get_home_services,
    get_public_home_content,
    get_public_site_payload,
    is_public_section_enabled,
)

public_bp = Blueprint('public', __name__)


# Planes del Software CyberShop — administrables desde /admin/software-planes.
# La fuente de verdad es la tabla `software_planes` (services/software_planes_service);
# si la BD falla, el servicio cae a sus defaults para no dejar la página vacía.
def _get_planes():
    from services import software_planes_service
    return software_planes_service.get_planes(include_inactive=False)


def _get_plan(plan_id):
    """Devuelve el plan por su clave (slug) desde la BD, o None."""
    from services import software_planes_service
    return software_planes_service.get_plan(plan_id, include_inactive=False)


def _software_colors(brand):
    """Paleta de la landing /software y la página /descargar.

    Configurable desde /admin/sitio-publico (grupo "Software y Descarga").
    Usa defaults de marca azul para que NUNCA dependa de los colores
    generales del tenant (que pueden quedar mal definidos en blanco).
    """
    def pick(key, fallback):
        val = (brand.get(key) or '').strip() if brand else ''
        return val if val else fallback

    return {
        'sw_color_primario': pick('color_software_primario', '#122C94'),
        'sw_color_oscuro': pick('color_software_oscuro', '#091C5A'),
        'sw_color_acento': pick('color_software_acento', '#29A9E2'),
        'sw_color_acento_txt': pick('color_software_acento_texto', '#06263f'),
    }

# Paginación por defecto
PRODUCTOS_POR_PAGINA = 24
_PUBLIC_COLUMN_CACHE = {}


def _productos_tienen_columna(columna):
    """Indica si la tabla productos tiene la columna dada (con cache)."""
    cache_key = ('productos', columna)
    if cache_key in _PUBLIC_COLUMN_CACHE:
        return _PUBLIC_COLUMN_CACHE[cache_key]

    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'productos'
                  AND column_name = %s
                LIMIT 1
            """, (columna,))
            exists = cur.fetchone() is not None
    except Exception:
        exists = False

    _PUBLIC_COLUMN_CACHE[cache_key] = exists
    return exists


def _productos_tienen_visibilidad_online():
    return _productos_tienen_columna('visible_en_ecommerce')


def _productos_activos_sql(alias='p'):
    """Fragmento WHERE para excluir productos archivados (active=false)."""
    if _productos_tienen_columna('active'):
        return f'COALESCE({alias}.active, TRUE) = TRUE'
    return ''


@public_bp.route('/')
def index():
    """Pagina principal de CyberShop."""
    datosApp = get_common_data()
    payload = get_public_site_payload()
    return render_template(
        'index.html',
        datosApp=datosApp,
        slides=payload['slides'],
        publicaciones=payload['publications'],
        config=payload['sections'],
        public_content=payload['content'],
    )


@public_bp.route('/productos')
def productos():
    """Catalogo de productos con filtros, busqueda y orden."""
    if not is_public_section_enabled('mostrar_modulo_ventas', True):
        return redirect(url_for('public.index'))

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
            if _productos_tienen_visibilidad_online():
                condiciones.append("COALESCE(p.visible_en_ecommerce, TRUE) = TRUE")
            _activos = _productos_activos_sql('p')
            if _activos:
                condiciones.append(_activos)
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
    return render_template(
        'servicios.html',
        datosApp=datosApp,
        servicios_db=get_home_services(),
        public_content=get_public_home_content(),
    )


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
    if not is_public_section_enabled('mostrar_modulo_ventas', True):
        return redirect(url_for('public.index'))
    datosApp = get_common_data()
    producto = None
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('''
                SELECT p.*, g.nombre AS genero
                FROM productos p
                JOIN generos g ON p.genero_id = g.id
                WHERE p.id = %s
            ''' + (' AND COALESCE(p.visible_en_ecommerce, TRUE) = TRUE' if _productos_tienen_visibilidad_online() else '')
                + ((' AND ' + _productos_activos_sql('p')) if _productos_activos_sql('p') else ''), (producto_id,))
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
            ''' + (' AND COALESCE(p.visible_en_ecommerce, TRUE) = TRUE' if _productos_tienen_visibilidad_online() else '')
                + ((' AND ' + _productos_activos_sql('p')) if _productos_activos_sql('p') else '') + '''
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

    # --- Meta CAPI ViewContent (dedup vs pixel por mismo event_id) ---
    import uuid as _uuid
    from services import meta_capi as _meta_capi
    view_content_event_id = str(_uuid.uuid4())
    try:
        _meta_capi.send_event_async(
            event_name='ViewContent',
            event_id=view_content_event_id,
            user_data=_meta_capi.build_user_data(
                request,
                email=session.get('email'),
                external_id=str(session['usuario_id']) if session.get('usuario_id') else None,
            ),
            custom_data={
                'content_ids':  [str(producto['id'])],
                'content_name': producto.get('nombre', ''),
                'content_type': 'product',
                'currency':     'COP',
                'value':        float(producto.get('precio') or 0),
            },
            event_source_url=request.url,
        )
    except Exception as _exc:
        app.logger.warning(f"CAPI ViewContent: {_exc}")

    return render_template('producto_detalle.html', datosApp=datosApp,
                           producto=producto, relacionados=relacionados,
                           comentarios=comentarios, stats_rating=stats_rating,
                           fb_view_content_event_id=view_content_event_id)


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
    if not is_public_section_enabled('mostrar_modulo_ventas', True):
        flash('El carrito de compras no esta disponible en este momento.', 'warning')
        return redirect(url_for('public.index'))
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

        email_destino = get_public_contact_destination_email() or app.config.get('MAIL_DEFAULT_SENDER', '')
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

        # F1.1 — Capturar el contacto como lead en el CRM y registrar actividad
        try:
            from services.crm_service import upsert_contacto, registrar_actividad
            contacto_id = upsert_contacto(
                email=email, nombre=name, tipo='lead', origen='web',
                notas_append=None, tags_add=['web'],
            )
            if contacto_id:
                registrar_actividad(
                    contacto_id=contacto_id,
                    tipo='formulario_web',
                    asunto=f"Mensaje desde /contactenos",
                    descripcion=message_text,
                )
        except Exception as _e:
            app.logger.warning(f"No se pudo capturar lead CRM desde /enviar-mensaje: {_e}")

        if enviado:
            flash('Mensaje enviado.', 'success')
        else:
            flash('No se pudo enviar el mensaje. Intenta más tarde.', 'error')
    except Exception:
        flash('Error enviando.', 'error')
    return redirect(url_for('public.index'))


@public_bp.route('/software-pos')
@public_bp.route('/planes')
def software_alias():
    """Alias SEO-friendly → 301 a la URL canónica /software (evita contenido
    duplicado y consolida la autoridad de la página en una sola URL)."""
    return redirect(url_for('public.software'), code=301)


@public_bp.route('/software')
def software():
    """Landing de marketing del Software CyberShop (POS + Web) con planes y
    descarga del POS de escritorio. Optimizada para SEO."""
    # Módulo Software POS: apagado por defecto; solo sitios que comercializan
    # el software lo activan (sección 'mostrar_modulo_software').
    from services.public_site_service import is_public_section_enabled
    if not is_public_section_enabled('mostrar_modulo_software', False):
        return redirect(url_for('public.index'))
    datosApp = get_common_data()

    # Datos de marca para JSON-LD / contacto (con fallbacks seguros)
    try:
        from services.public_site_service import get_brand_config
        brand = get_brand_config() or {}
    except Exception:
        brand = {}

    empresa_nombre = brand.get('empresa_nombre') or datosApp.get('titulo') or 'CyberShop'
    empresa_website = brand.get('empresa_website') or request.url_root.rstrip('/')
    empresa_logo = brand.get('empresa_logo_url') or url_for('static', filename='img/Logo.PNG', _external=True)
    empresa_telefono = brand.get('empresa_telefono') or '+57 302 7974969'
    empresa_email = brand.get('empresa_email') or ''

    sw_colors = _software_colors(brand)

    # Planes administrables desde /admin/software-planes (HTML + JSON-LD + checkout)
    planes = _get_planes()

    # Características destacadas del software (para la sección de beneficios)
    caracteristicas = [
        {'icono': 'fa-globe', 'titulo': 'Página web propia + E-commerce',
         'desc': 'Tu propia tienda online con tu marca, tus colores y tu dominio independiente.'},
        {'icono': 'fa-credit-card', 'titulo': 'Pagos en línea con PayU',
         'desc': 'Cobra con tarjetas y PSE mediante la pasarela de pagos PayU integrada.'},
        {'icono': 'fa-sign-in-alt', 'titulo': 'Inicio de sesión con Google',
         'desc': 'Tus clientes entran con un clic usando su cuenta de Google.'},
        {'icono': 'fa-address-book', 'titulo': 'CRM integrado',
         'desc': 'Gestiona clientes, oportunidades y seguimiento desde el mismo sistema.'},
        {'icono': 'fa-bolt', 'titulo': 'Ventas 100% más ágiles',
         'desc': 'Procesa transacciones en segundos y elimina errores de cálculo manual.'},
        {'icono': 'fa-boxes', 'titulo': 'Inventario en tiempo real',
         'desc': 'Cada venta descuenta tu stock automáticamente, sin descuadres.'},
        {'icono': 'fa-mobile-alt', 'titulo': 'Movilidad total',
         'desc': 'Vende desde computador, tablet o móvil en cualquier rincón de tu local.'},
        {'icono': 'fa-chart-line', 'titulo': 'Reportes estratégicos',
         'desc': 'Accede a estadísticas de productos estrella y horas pico para decidir mejor.'},
        {'icono': 'fa-wifi', 'titulo': 'Funciona sin internet',
         'desc': 'La app de escritorio opera offline y sincroniza al recuperar conexión.'},
        {'icono': 'fa-utensils', 'titulo': 'Módulo de restaurante',
         'desc': 'Atención de mesas, comandas y cobro con flujo pensado para restaurantes.'},
        {'icono': 'fa-calculator', 'titulo': 'Contabilidad integrada',
         'desc': 'Ingresos, egresos, retenciones y cierres de período en un solo lugar.'},
        {'icono': 'fa-user-shield', 'titulo': 'Roles y permisos',
         'desc': 'Cada usuario ve solo lo que le corresponde: cajero, mesero, contador o admin.'},
    ]

    # Preguntas frecuentes (también alimentan el JSON-LD FAQPage para SEO)
    faqs = [
        {'q': '¿El software funciona sin internet?',
         'a': 'Sí. La app de escritorio de CyberShop funciona offline y sincroniza automáticamente con la nube cuando recuperas la conexión, para que nunca dejes de vender.'},
        {'q': '¿Sirve para restaurantes y tiendas?',
         'a': 'Sí. CyberShop incluye punto de venta para tiendas y un módulo de restaurante con atención de mesas, comandas y cobro, además de inventario y contabilidad.'},
        {'q': '¿Cómo descargo la aplicación de escritorio?',
         'a': 'Con tu código de cliente puedes descargar el instalador personalizado desde la sección de descarga. El servidor ya viene preconfigurado para tu negocio.'},
        {'q': '¿Incluye facturación e inventario?',
         'a': 'Sí. El plan de Software CyberShop incluye punto de venta, inventario en tiempo real, reportes, contabilidad y gestión de productos.'},
        {'q': '¿Puedo tener también una página web?',
         'a': 'Sí. El plan Software CyberShop ($150.000/mes) incluye tu propia página web con tus colores y un E-commerce con tu dominio. Si además quieres cobrar en línea con PayU, inicio de sesión con Google e integración con CRM, el plan Ultra ($200.000/mes) lo incluye todo.'},
    ]

    return render_template(
        'software.html',
        datosApp=datosApp,
        planes=planes,
        caracteristicas=caracteristicas,
        faqs=faqs,
        empresa_nombre=empresa_nombre,
        empresa_website=empresa_website,
        empresa_logo=empresa_logo,
        empresa_telefono=empresa_telefono,
        empresa_email=empresa_email,
        canonical_url=request.base_url,
        **sw_colors,
    )


@public_bp.route('/descargar', methods=['GET', 'POST'])
def descargar():
    """Portal público de descarga del POS Desktop.

    GET  → muestra form pidiendo client_code
    POST → valida code en sync_api_keys, arma ZIP personalizado y lo retorna
    """
    # Módulo Software POS: apagado por defecto; solo sitios que comercializan
    # el software lo activan (sección 'mostrar_modulo_software').
    from services.public_site_service import is_public_section_enabled
    if not is_public_section_enabled('mostrar_modulo_software', False):
        return redirect(url_for('public.index'))
    from flask import abort, send_file
    from io import BytesIO

    from services.installer_packager import (
        build_personalized_zip,
        ClientCodeNotFoundError,
        InstallerNotBuiltError,
        resolve_client_code,
    )

    datosApp = get_common_data()
    try:
        from services.public_site_service import get_brand_config
        sw_colors = _software_colors(get_brand_config() or {})
    except Exception:
        sw_colors = _software_colors({})

    if request.method == 'POST':
        ip = request.remote_addr or 'unknown'
        if not controlar_tasa_solicitudes(ip, max_requests=5, interval=600):
            flash('Demasiados intentos. Espera 10 minutos antes de reintentar.', 'error')
            return render_template('descargar.html', datosApp=datosApp, **sw_colors), 429

        client_code = (request.form.get('client_code') or '').strip().upper()
        if not client_code:
            flash('Ingresa tu código de cliente.', 'error')
            return render_template('descargar.html', datosApp=datosApp, **sw_colors)

        try:
            tenant_info = resolve_client_code(client_code)
        except ClientCodeNotFoundError:
            flash('Código de cliente inválido o inactivo. Verifica con tu proveedor.', 'error')
            return render_template('descargar.html', datosApp=datosApp, **sw_colors)

        try:
            server_url = request.url_root.rstrip('/')
            filename, zip_bytes = build_personalized_zip(tenant_info, server_url)
        except InstallerNotBuiltError as exc:
            flash(f'El instalador no está disponible aún. Contacta al administrador. ({exc})', 'error')
            return render_template('descargar.html', datosApp=datosApp, **sw_colors)

        return send_file(
            BytesIO(zip_bytes),
            mimetype='application/zip',
            as_attachment=True,
            download_name=filename,
        )

    return render_template('descargar.html', datosApp=datosApp, **sw_colors)


@public_bp.route('/comprar-plan/<plan_id>', methods=['GET', 'POST'])
def comprar_plan(plan_id):
    """Checkout de un plan de software vía PayU.

    GET  → muestra resumen del plan + formulario del comprador (pre-llenado
           si hay sesión).
    POST → valida el plan (precio server-side), crea el pedido y redirige a PayU.
    No toca inventario ni el carrito de productos: el plan no es stock.
    """
    # Módulo Software POS: apagado por defecto; solo sitios que comercializan
    # el software lo activan (sección 'mostrar_modulo_software').
    from services.public_site_service import is_public_section_enabled
    if not is_public_section_enabled('mostrar_modulo_software', False):
        return redirect(url_for('public.index'))
    plan = _get_plan(plan_id)
    if not plan or not plan.get('comprable'):
        flash('El plan solicitado no está disponible.', 'error')
        return redirect(url_for('public.software') + '#planes')

    datosApp = get_common_data()
    try:
        from services.public_site_service import get_brand_config
        sw_colors = _software_colors(get_brand_config() or {})
    except Exception:
        sw_colors = _software_colors({})

    # Requerir sesión para tener datos del comprador y trazabilidad
    if not session.get('usuario_id'):
        session['login_next'] = url_for('public.comprar_plan', plan_id=plan_id)
        flash('Inicia sesión o regístrate para adquirir tu plan.', 'info')
        return redirect(url_for('auth.login'))

    # Datos del usuario para pre-llenar
    usuario = None
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute(
                'SELECT nombre, email, telefono, direccion FROM usuarios WHERE id = %s',
                (session['usuario_id'],),
            )
            usuario = cur.fetchone()
    except Exception:
        pass

    if request.method == 'POST':
        if not controlar_tasa_solicitudes(request.remote_addr or 'unknown', max_requests=8, interval=300):
            flash('Demasiados intentos. Espera unos minutos.', 'error')
            return redirect(url_for('public.comprar_plan', plan_id=plan_id))

        nombre = (request.form.get('buyerFullName') or '').strip()[:200]
        email = (request.form.get('buyerEmail') or '').strip()[:200]
        tipo_doc = (request.form.get('payerDocumentType') or 'CC').strip()[:10]
        documento = (request.form.get('payerDocument') or '').strip()[:30]
        telefono = (request.form.get('buyerPhone') or '').strip()[:30]

        if not nombre or not email:
            flash('Por favor completa tu nombre y correo.', 'warning')
            return render_template('comprar_plan.html', datosApp=datosApp,
                                   plan=plan, usuario=usuario, **sw_colors)

        # Precio SIEMPRE desde el server (nunca del cliente)
        from helpers import generar_reference_code
        referencia = generar_reference_code()
        monto = float(plan['precio'])
        descripcion = f"Plan {plan['nombre']} ({plan['periodo']})"

        try:
            with get_db_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pedidos
                        (referencia_pedido, cliente_nombre, cliente_email,
                         cliente_tipo_documento, cliente_documento, cliente_telefono,
                         monto_total, estado_pago, estado_envio)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDIENTE', 'ESPERA_PAGO')
                    RETURNING id
                    """,
                    (referencia, nombre, email, tipo_doc, documento, telefono, monto),
                )
                pedido_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO detalle_pedidos
                        (pedido_id, producto_nombre, cantidad, precio_unitario, subtotal)
                    VALUES (%s, %s, 1, %s, %s)
                    """,
                    (pedido_id, f"Plan: {plan['nombre']}", monto, monto),
                )
            # Venta automática: registrar la compra del plan para que el
            # webhook de PayU dispare la activación al aprobarse el pago.
            from services.plan_compras_service import crear_compra
            crear_compra(pedido_id, referencia, plan['plan_key'],
                         nombre, email, periodo=plan.get('periodo') or 'mes')
        except Exception as e:
            app.logger.error(f"Error creando pedido de plan {plan_id}: {e}")
            flash('No se pudo iniciar el pago. Intenta de nuevo.', 'error')
            return render_template('comprar_plan.html', datosApp=datosApp,
                                   plan=plan, usuario=usuario, **sw_colors)

        from routes.payments import construir_redireccion_payu
        return construir_redireccion_payu(referencia, nombre, email, monto, descripcion)

    return render_template('comprar_plan.html', datosApp=datosApp,
                           plan=plan, usuario=usuario, **sw_colors)


# ════════════════════════════════════════════════════════════════
# VENTA AUTOMÁTICA: activación de tienda y renovación de planes
# ════════════════════════════════════════════════════════════════

@public_bp.route('/prueba-gratis', methods=['GET', 'POST'])
def prueba_gratis():
    """Registro self-service de la PRUEBA GRATIS de 15 días (plan Ultra, sin
    pago ni tarjeta). Verifica el email antes de crear nada: la tienda se crea
    al confirmar el enlace enviado al correo."""
    from services import plan_compras_service as pcs
    from services.venta_automatica_service import validar_slug

    if not is_public_section_enabled('mostrar_modulo_software', False):
        return redirect(url_for('public.index'))

    datosApp = get_common_data()
    try:
        from services.public_site_service import get_brand_config
        brand = get_brand_config() or {}
    except Exception:
        brand = {}
    sw_colors = _software_colors(brand)
    form = {}
    error = None

    if request.method == 'POST':
        # Antiabuso: honeypot + rate limit por IP (mismo patrón de /descargar)
        if (request.form.get('website2') or '').strip():
            return redirect(url_for('public.index'))
        from security import controlar_tasa_solicitudes
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '?').split(',')[0].strip()
        if not controlar_tasa_solicitudes(f"trial:{ip}", max_requests=5, interval=600):
            error = 'Demasiados intentos. Espera unos minutos e intenta de nuevo.'

        form = {k: (request.form.get(k) or '').strip()
                for k in ('nombre_negocio', 'buyer_nombre', 'buyer_email',
                          'buyer_telefono', 'subdominio')}
        slug, slug_err = validar_slug(form['subdominio'])
        if not error:
            if len(form['nombre_negocio']) < 3:
                error = 'Escribe el nombre de tu negocio (mínimo 3 caracteres).'
            elif len(form['buyer_nombre']) < 3:
                error = 'Escribe tu nombre.'
            elif '@' not in form['buyer_email'] or len(form['buyer_email']) < 6:
                error = 'Escribe un correo válido.'
            elif slug_err:
                error = slug_err

        if not error:
            compra_id, res = pcs.crear_trial(
                form['nombre_negocio'], form['buyer_nombre'],
                form['buyer_email'], slug, telefono=form['buyer_telefono'])
            if compra_id is None:
                error = res
            else:
                from helpers_email_templates import generar_email_confirmacion_trial
                from helpers_gmail import enviar_email_gmail
                compra = pcs.get_por_id(compra_id)
                confirmar_url = url_for('public.prueba_gratis_confirmar',
                                        token=res, _external=True)
                try:
                    asunto, texto, html = generar_email_confirmacion_trial(compra, confirmar_url)
                    enviar_email_gmail(form['buyer_email'], asunto, texto, html=html)
                except Exception as exc:  # noqa: BLE001
                    app.logger.error(f"trial: email de confirmación falló: {exc}")
                    error = 'No pudimos enviar el correo de confirmación. Intenta de nuevo.'
                if not error:
                    return render_template('prueba_gratis.html', datosApp=datosApp,
                                           enviado=True, email_destino=form['buyer_email'],
                                           form={}, error=None, **sw_colors)

    return render_template('prueba_gratis.html', datosApp=datosApp, enviado=False,
                           form=form, error=error, **sw_colors)


@public_bp.route('/prueba-gratis/confirmar/<token>')
def prueba_gratis_confirmar(token):
    """El usuario confirmó su correo: dispara la creación de la tienda trial
    (mismo camino que una compra pagada) y muestra el progreso en la página
    de activación existente."""
    from services import plan_compras_service as pcs
    from services.venta_automatica_service import activar_tienda_async

    compra = pcs.get_por_token(token)
    if not compra or not compra.get('es_trial'):
        flash('El enlace de confirmación no es válido.', 'error')
        return redirect(url_for('public.index'))

    if pcs.marcar_trial_verificado(compra['id']):
        # Ya tenemos slug y nombre del negocio desde el registro: activar directo
        if pcs.marcar_activando(compra['id'], compra['slug']):
            from flask import current_app
            activar_tienda_async(current_app._get_current_object(),
                                 compra['id'], compra['slug'],
                                 compra.get('nombre_negocio') or compra['slug'])
    # Reutiliza la página de activación (muestra ACTIVANDO → ACTIVADA / ERROR)
    return redirect(url_for('public.activar_tienda', token=token))


@public_bp.route('/activar-tienda/<token>', methods=['GET', 'POST'])
def activar_tienda(token):
    """Página de activación post-pago: el cliente elige nombre del negocio y
    subdominio; la creación corre en segundo plano (ver venta_automatica)."""
    from services import plan_compras_service as pcs
    from services.venta_automatica_service import validar_slug, activar_tienda_async
    from services.software_planes_service import get_plan

    datosApp = get_common_data()
    try:
        from services.public_site_service import get_brand_config
        brand = get_brand_config() or {}
    except Exception:
        brand = {}
    sw_colors = _software_colors(brand)

    compra = pcs.get_por_token(token)
    if not compra:
        flash('El enlace de activación no es válido o ya expiró.', 'error')
        return redirect(url_for('public.index'))
    plan = get_plan(compra['plan_key']) or {'nombre': compra['plan_key']}

    error = None
    if request.method == 'POST' and compra['estado'] in ('PAGADO', 'ERROR'):
        nombre_negocio = (request.form.get('nombre_negocio') or '').strip()
        slug, error = validar_slug(request.form.get('subdominio'))
        if not nombre_negocio or len(nombre_negocio) < 3:
            error = 'Escribe el nombre de tu negocio (mínimo 3 caracteres).'
        if not error:
            if pcs.marcar_activando(compra['id'], slug):
                from flask import current_app
                activar_tienda_async(current_app._get_current_object(),
                                     compra['id'], slug, nombre_negocio)
            compra = pcs.get_por_token(token)

    return render_template('activar_tienda.html', datosApp=datosApp,
                           compra=compra, plan=plan, error=error,
                           base_domain='cybershopcol.com', **sw_colors)


@public_bp.route('/renovar/<token>', methods=['GET', 'POST'])
def renovar_plan(token):
    """Renovación de un plan activo: muestra el plan y paga por PayU.
    El webhook extiende proximo_pago (y reactiva la tienda si estaba
    suspendida por no-pago)."""
    from services import plan_compras_service as pcs
    from services.software_planes_service import get_plan
    from helpers import generar_reference_code

    datosApp = get_common_data()
    try:
        from services.public_site_service import get_brand_config
        brand = get_brand_config() or {}
    except Exception:
        brand = {}
    sw_colors = _software_colors(brand)

    compra = pcs.get_por_token_renovacion(token)
    if not compra or compra['estado'] != 'ACTIVADA':
        flash('El enlace de renovación no es válido.', 'error')
        return redirect(url_for('public.index'))
    plan = get_plan(compra['plan_key'])
    if not plan:
        flash('El plan ya no está disponible; contáctanos.', 'error')
        return redirect(url_for('public.index'))

    if request.method == 'POST':
        referencia = generar_reference_code()
        monto = float(plan['precio'])
        try:
            with get_db_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pedidos
                        (referencia_pedido, cliente_nombre, cliente_email,
                         monto_total, estado_pago, estado_envio)
                    VALUES (%s, %s, %s, %s, 'PENDIENTE', 'ESPERA_PAGO')
                    RETURNING id
                    """,
                    (referencia, compra['buyer_nombre'], compra['buyer_email'], monto),
                )
                pedido_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO detalle_pedidos
                        (pedido_id, producto_nombre, cantidad, precio_unitario, subtotal)
                    VALUES (%s, %s, 1, %s, %s)
                    """,
                    (pedido_id, f"Renovación plan: {plan['nombre']}", monto, monto),
                )
            pcs.crear_compra(pedido_id, referencia, compra['plan_key'],
                             compra['buyer_nombre'], compra['buyer_email'],
                             periodo=compra.get('periodo') or 'mes',
                             renovacion_de=compra['id'])
        except Exception as e:
            app.logger.error(f"Error creando renovación {token}: {e}")
            flash('No se pudo iniciar el pago. Intenta de nuevo.', 'error')
            return render_template('renovar_plan.html', datosApp=datosApp,
                                   compra=compra, plan=plan, **sw_colors)
        from routes.payments import construir_redireccion_payu
        return construir_redireccion_payu(
            referencia, compra['buyer_nombre'], compra['buyer_email'], monto,
            f"Renovación plan {plan['nombre']} ({compra.get('periodo')})")

    return render_template('renovar_plan.html', datosApp=datosApp,
                           compra=compra, plan=plan, **sw_colors)


@public_bp.route('/robots.txt')
def robots_txt():
    """robots.txt para buscadores: permite el contenido público, bloquea
    rutas privadas/transaccionales y apunta al sitemap (SEO)."""
    from flask import Response

    root = request.url_root  # incluye el dominio del tenant actual + '/'
    contenido = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        "Disallow: /carrito\n"
        "Disallow: /metodos-pago\n"
        "Disallow: /respuesta-pago\n"
        "Disallow: /login\n"
        f"\nSitemap: {root}sitemap.xml\n"
    )
    return Response(contenido, mimetype='text/plain')


@public_bp.route('/sitemap.xml')
def sitemap_xml():
    """Sitemap XML dinámico con las páginas públicas indexables (SEO).

    Incluye productos visibles para que el catálogo se indexe. Tolerante a
    errores: si la BD falla, devuelve al menos las páginas estáticas.
    """
    from datetime import date
    from flask import Response
    from xml.sax.saxutils import escape

    hoy = date.today().isoformat()
    urls = []

    def add(loc, changefreq, priority, lastmod=None):
        urls.append({
            'loc': loc, 'changefreq': changefreq,
            'priority': priority, 'lastmod': lastmod or hoy,
        })

    # Páginas estáticas principales
    add(url_for('public.index', _external=True), 'weekly', '1.0')
    add(url_for('public.software', _external=True), 'weekly', '0.9')
    if is_public_section_enabled('mostrar_modulo_ventas', True):
        add(url_for('public.productos', _external=True), 'daily', '0.8')
    add(url_for('public.servicios', _external=True), 'monthly', '0.6')
    add(url_for('public.descargar', _external=True), 'monthly', '0.7')

    # Productos individuales (si el módulo de ventas está activo)
    if is_public_section_enabled('mostrar_modulo_ventas', True):
        try:
            with get_db_cursor(dict_cursor=True) as cur:
                _conds = []
                if _productos_tienen_visibilidad_online():
                    _conds.append('COALESCE(visible_en_ecommerce, TRUE) = TRUE')
                if _productos_tienen_columna('active'):
                    _conds.append('COALESCE(active, TRUE) = TRUE')
                visible = (' WHERE ' + ' AND '.join(_conds)) if _conds else ''
                cur.execute(f'SELECT id FROM productos{visible} ORDER BY id DESC LIMIT 5000')
                for row in cur.fetchall():
                    add(url_for('public.detalle_producto', producto_id=row['id'], _external=True),
                        'weekly', '0.6')
        except Exception as e:
            app.logger.warning(f"sitemap: no se pudieron listar productos: {e}")

    partes = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        partes.append(
            '<url>'
            f'<loc>{escape(u["loc"])}</loc>'
            f'<lastmod>{u["lastmod"]}</lastmod>'
            f'<changefreq>{u["changefreq"]}</changefreq>'
            f'<priority>{u["priority"]}</priority>'
            '</url>'
        )
    partes.append('</urlset>')
    return Response('\n'.join(partes), mimetype='application/xml')


@public_bp.route('/api/track/add-to-cart', methods=['POST'])
@_csrf_exempt
def track_add_to_cart():
    """Endpoint para mandar AddToCart a Meta CAPI desde el browser.

    El JS hace fbq('track', 'AddToCart', ..., {eventID}) y simultaneamente
    POST aqui con el mismo event_id — Meta deduplica los dos en su servidor.

    Body JSON: {event_id, product_id, product_name, price, quantity}
    Tolerante a errores: nunca devuelve 5xx (CAPI no debe romper el frontend).
    """
    try:
        data = request.get_json(silent=True) or {}
        event_id  = (data.get('event_id') or '').strip()
        prod_id   = data.get('product_id')
        prod_name = data.get('product_name') or ''
        price     = float(data.get('price') or 0)
        qty       = int(data.get('quantity') or 1)

        if not event_id or not prod_id:
            return jsonify({'ok': False, 'reason': 'missing event_id or product_id'}), 200

        from services import meta_capi as _meta_capi
        _meta_capi.send_event_async(
            event_name='AddToCart',
            event_id=event_id,
            user_data=_meta_capi.build_user_data(
                request,
                email=session.get('email'),
                external_id=str(session['usuario_id']) if session.get('usuario_id') else None,
            ),
            custom_data={
                'content_ids':  [str(prod_id)],
                'content_name': prod_name,
                'content_type': 'product',
                'currency':     'COP',
                'value':        price * qty,
                'contents':     [{'id': str(prod_id), 'quantity': qty, 'item_price': price}],
            },
            event_source_url=request.headers.get('Referer'),
        )
        return jsonify({'ok': True}), 200
    except Exception as exc:
        app.logger.warning(f"track_add_to_cart error: {exc}")
        return jsonify({'ok': False}), 200


@public_bp.app_errorhandler(404)
def pagina_no_encontrada(error):
    """Pagina de error 404 personalizada."""
    return render_template('404.html'), 404
