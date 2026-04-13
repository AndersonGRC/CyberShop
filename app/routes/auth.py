"""
routes/auth.py — Blueprint de autenticacion y registro de clientes.

Rutas: /registrar-cliente, /login, /logout, /cliente
"""

import secrets
import requests as http_requests

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app as app
from werkzeug.security import generate_password_hash
from psycopg2.extras import DictCursor
from google_auth_oauthlib.flow import Flow

from database import get_db_connection, get_db_cursor
from helpers import get_common_data, get_data_app, get_data_cliente
from security import (
    ROL_CAJERO,
    ROL_MESERO,
    rol_requerido,
    autenticar_usuario,
    controlar_tasa_solicitudes,
)
from tenant_features import bind_session_tenant

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/registrar-cliente', methods=['GET', 'POST'])
def registrar_cliente():
    """Muestra el formulario de registro y procesa nuevos clientes (rol 3)."""
    datosApp = get_common_data()
    if request.method == 'POST':
        if not controlar_tasa_solicitudes(request.remote_addr, max_requests=5, interval=300):
            flash('Demasiados intentos de registro. Espera unos minutos.', 'warning')
            return redirect(url_for('auth.registrar_cliente'))
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        fecha_nacimiento = request.form.get('fecha_nacimiento')
        telefono = request.form.get('telefono', '')
        direccion = request.form.get('direccion', '')

        if not nombre or not email or not password or not fecha_nacimiento:
            flash('Por favor, complete todos los campos obligatorios.', 'error')
            return redirect(url_for('auth.registrar_cliente'))

        try:
            with get_db_cursor(dict_cursor=True) as cur:
                cur.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
                usuario_existente = cur.fetchone()
                if usuario_existente:
                    flash('El correo electrónico ya está registrado.', 'error')
                    return redirect(url_for('auth.registrar_cliente'))

                hashed_password = generate_password_hash(password)
                cur.execute(
                    '''INSERT INTO usuarios
                       (nombre, email, contraseña, rol_id, fecha_nacimiento, telefono, direccion, estado)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'habilitado')''',
                    (nombre, email, hashed_password, 3, fecha_nacimiento, telefono, direccion)
                )
            # Email de bienvenida
            try:
                from helpers_email_templates import generar_email_bienvenida
                from helpers_gmail import enviar_email_gmail
                email_data = generar_email_bienvenida(nombre, email)
                if email_data:
                    asunto, texto, html = email_data
                    enviar_email_gmail(email, asunto, texto, html=html)
            except Exception as _be:
                app.logger.warning(f"Email bienvenida: {_be}")

            flash('Cliente registrado correctamente. Por favor, inicie sesión.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            app.logger.error(f"Error al registrar cliente: {e}")
            flash('Error al registrar el cliente. Intenta de nuevo.', 'error')

    return render_template('registrarcliente.html', datosApp=datosApp)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Muestra el formulario de login y autentica al usuario."""
    datosApp = get_common_data()
    if request.method == 'POST':
        # SECURITY M6: Rate limiting — máximo 10 intentos/minuto por IP
        ip = request.remote_addr
        if not controlar_tasa_solicitudes(ip, max_requests=10, interval=60):
            flash('Demasiados intentos de inicio de sesión. Espera un momento.', 'error')
            return render_template('login.html', datosApp=datosApp)
        email = request.form.get('email')
        password = request.form.get('password')
        usuario = autenticar_usuario(email, password)
        if usuario:
            session['usuario_id'] = usuario['id']
            session['email'] = usuario['email']
            session['rol_id'] = usuario['rol_id']
            session['username'] = usuario['nombre']
            bind_session_tenant(usuario=usuario)
            # Redirigir a la página pendiente (ej: checkout) si la hay
            next_url = session.pop('login_next', None)
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            if usuario['rol_id'] == 1: return redirect(url_for('admin.dashboard_admin'))
            elif usuario['rol_id'] == 2: return redirect(url_for('admin.dashboard_admin'))
            elif usuario['rol_id'] == 3: return redirect(url_for('auth.dashboard_cliente'))
            elif usuario['rol_id'] in (ROL_MESERO, ROL_CAJERO): return redirect(url_for('restaurant_tables.waiter_panel'))
            else: return redirect(url_for('auth.login'))
        else: return redirect(url_for('auth.login'))
    return render_template('login.html', datosApp=datosApp)


@auth_bp.route('/cliente')
@rol_requerido(3)
def dashboard_cliente():
    """Panel principal del cliente autenticado."""
    from database import get_db_cursor
    datosApp = get_data_cliente()
    email = session.get('email')
    resumen = {'total_pedidos': 0, 'pendientes': 0, 'aprobados': 0, 'ultimo': None}
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN estado_pago='PENDIENTE' THEN 1 ELSE 0 END) AS pendientes,
                       SUM(CASE WHEN estado_pago='APROBADO'  THEN 1 ELSE 0 END) AS aprobados
                FROM pedidos WHERE cliente_email = %s
            """, (email,))
            row = cur.fetchone()
            if row:
                resumen['total_pedidos'] = row['total'] or 0
                resumen['pendientes']    = row['pendientes'] or 0
                resumen['aprobados']     = row['aprobados'] or 0
            cur.execute("""
                SELECT referencia_pedido, estado_pago, monto_total, fecha_creacion
                FROM pedidos WHERE cliente_email = %s
                ORDER BY fecha_creacion DESC LIMIT 1
            """, (email,))
            resumen['ultimo'] = cur.fetchone()
    except Exception as e:
        app.logger.error(f"Error cargando resumen cliente: {e}")
    return render_template('dashboard_cliente.html', datosApp=datosApp, resumen=resumen)


@auth_bp.route('/cliente/mis-pedidos')
@rol_requerido(3)
def mis_pedidos():
    """Lista de pedidos del cliente autenticado."""
    from database import get_db_cursor
    datosApp = get_data_cliente()
    email = session.get('email')
    pedidos = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("""
                SELECT p.id, p.referencia_pedido, p.fecha_creacion, p.monto_total,
                       p.estado_pago, p.estado_envio, p.metodo_pago,
                       COUNT(dp.id) AS num_items
                FROM pedidos p
                LEFT JOIN detalle_pedidos dp ON dp.pedido_id = p.id
                WHERE p.cliente_email = %s
                GROUP BY p.id
                ORDER BY p.fecha_creacion DESC
            """, (email,))
            pedidos = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error listando pedidos cliente: {e}")
    return render_template('mis_pedidos.html', datosApp=datosApp, pedidos=pedidos)


@auth_bp.route('/cliente/mis-pedidos/<int:pedido_id>')
@rol_requerido(3)
def detalle_pedido_cliente(pedido_id):
    """Detalle de un pedido del cliente autenticado."""
    from database import get_db_cursor
    datosApp = get_data_cliente()
    email = session.get('email')
    pedido = None
    items = []
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM pedidos WHERE id = %s AND cliente_email = %s", (pedido_id, email))
            pedido = cur.fetchone()
            if pedido:
                cur.execute("SELECT * FROM detalle_pedidos WHERE pedido_id = %s", (pedido_id,))
                items = cur.fetchall()
    except Exception as e:
        app.logger.error(f"Error cargando detalle pedido {pedido_id}: {e}")
    if not pedido:
        flash("Pedido no encontrado.", "warning")
        return redirect(url_for('auth.mis_pedidos'))
    return render_template('detalle_pedido_cliente.html', datosApp=datosApp, pedido=pedido, items=items)


@auth_bp.route('/logout')
def logout():
    """Cierra la sesion del usuario y redirige al login."""
    session.clear()
    flash('Has cerrado sesión correctamente.', 'success')
    return redirect(url_for('auth.login'))


def _build_login_flow():
    """Construye el flujo OAuth 2.0 para login con Google."""
    cfg = app.config
    return Flow.from_client_config(
        {
            'web': {
                'client_id':     cfg['GOOGLE_CLIENT_ID'],
                'client_secret': cfg['GOOGLE_CLIENT_SECRET'],
                'auth_uri':      'https://accounts.google.com/o/oauth2/auth',
                'token_uri':     'https://oauth2.googleapis.com/token',
                'redirect_uris': [cfg['GOOGLE_LOGIN_REDIRECT_URI']],
            }
        },
        scopes=cfg['GOOGLE_LOGIN_SCOPES'],
        redirect_uri=cfg['GOOGLE_LOGIN_REDIRECT_URI'],
    )


@auth_bp.route('/google/login')
def google_login():
    """Inicia el flujo OAuth de Google para login/registro."""
    flow = _build_login_flow()
    auth_url, state = flow.authorization_url(
        access_type='offline',
        prompt='select_account',
    )
    session['google_login_state'] = state
    session['google_code_verifier'] = flow.code_verifier
    return redirect(auth_url)


@auth_bp.route('/google/login/callback')
def google_login_callback():
    """Callback de Google OAuth: crea o autentica al usuario."""
    # 1. Validar state
    state = session.get('google_login_state')
    if not state or state != request.args.get('state'):
        flash('Estado OAuth inválido. Intenta de nuevo.', 'error')
        return redirect(url_for('auth.login'))

    # 2. Intercambiar code por tokens
    flow = _build_login_flow()
    flow.code_verifier = session.get('google_code_verifier')
    flow.state = state
    try:
        auth_response = request.url.replace('http://', 'https://', 1)
        flow.fetch_token(authorization_response=auth_response)
    except Exception as e:
        app.logger.error(f"Error obteniendo token Google Login: {e}")
        flash('Error al autenticar con Google. Intenta de nuevo.', 'error')
        return redirect(url_for('auth.login'))

    # 3. Obtener datos del usuario desde Google
    credentials = flow.credentials
    resp = http_requests.get(
        'https://www.googleapis.com/oauth2/v3/userinfo',
        headers={'Authorization': f'Bearer {credentials.token}'}
    )
    if not resp.ok:
        flash('No se pudo obtener información de tu cuenta Google.', 'error')
        return redirect(url_for('auth.login'))

    userinfo = resp.json()
    google_sub = userinfo.get('sub')
    email      = userinfo.get('email')
    name       = userinfo.get('name', email)
    picture    = userinfo.get('picture')

    if not google_sub or not email:
        flash('Google no proporcionó los datos necesarios.', 'error')
        return redirect(url_for('auth.login'))

    # 4. Buscar o crear usuario
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            # Buscar por google_sub
            cur.execute('SELECT * FROM usuarios WHERE google_sub = %s', (google_sub,))
            usuario = cur.fetchone()

            if not usuario:
                # Buscar por email
                cur.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
                usuario = cur.fetchone()

            if usuario:
                # Actualizar google_sub si faltaba y ultima_conexion
                cur.execute(
                    'UPDATE usuarios SET google_sub = %s, fotografia = %s, ultima_conexion = NOW() WHERE id = %s',
                    (google_sub, picture, usuario['id'])
                )
            else:
                # Usuario no registrado: debe registrarse primero
                flash(f'El correo {email} no está registrado. Por favor regístrate para continuar.', 'error')
                return redirect(url_for('auth.registrar_cliente'))
    except Exception as e:
        app.logger.error(f"Error en Google Login callback BD: {e}")
        flash('Error interno al procesar tu cuenta. Intenta de nuevo.', 'error')
        return redirect(url_for('auth.login'))

    # 5. Verificar estado
    if usuario.get('estado') != 'habilitado':
        flash('Tu cuenta está deshabilitada. Contacta al administrador.', 'error')
        return redirect(url_for('auth.login'))

    # 6. Construir sesión
    session['usuario_id'] = usuario['id']
    session['email']      = usuario['email']
    session['rol_id']     = usuario['rol_id']
    session['username']   = usuario['nombre']
    bind_session_tenant(usuario=usuario)

    # 7. Redirigir según rol (o a página pendiente como checkout)
    next_url = session.pop('login_next', None)
    if next_url and next_url.startswith('/'):
        return redirect(next_url)
    rol = usuario['rol_id']
    if rol in (1, 2):
        return redirect(url_for('admin.dashboard_admin'))
    elif rol == 3:
        return redirect(url_for('auth.dashboard_cliente'))
    elif rol in (ROL_MESERO, ROL_CAJERO):
        return redirect(url_for('restaurant_tables.waiter_panel'))
    return redirect(url_for('auth.login'))
