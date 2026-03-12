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
from helpers import get_common_data, get_data_app
from security import rol_requerido, autenticar_usuario

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/registrar-cliente', methods=['GET', 'POST'])
def registrar_cliente():
    """Muestra el formulario de registro y procesa nuevos clientes (rol 3)."""
    datosApp = get_common_data()
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        fecha_nacimiento = request.form.get('fecha_nacimiento')
        telefono = request.form.get('telefono', '')
        direccion = request.form.get('direccion', '')

        if not nombre or not email or not password or not fecha_nacimiento:
            flash('Por favor, complete todos los campos obligatorios.', 'error')
            return redirect(url_for('auth.registrar_cliente'))

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        try:
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
            conn.commit()
            flash('Cliente registrado correctamente. Por favor, inicie sesión.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            app.logger.error(f"Error al registrar cliente: {e}")
            flash(f'Error al registrar el cliente: {str(e)}', 'error')
        finally:
            cur.close()
            conn.close()

    return render_template('registrarcliente.html', datosApp=datosApp)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Muestra el formulario de login y autentica al usuario."""
    datosApp = get_common_data()
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        usuario = autenticar_usuario(email, password)
        if usuario:
            session['usuario_id'] = usuario['id']
            session['email'] = usuario['email']
            session['rol_id'] = usuario['rol_id']
            session['username'] = usuario['nombre']
            if usuario['rol_id'] == 1: return redirect(url_for('admin.dashboard_admin'))
            elif usuario['rol_id'] == 2: return redirect(url_for('admin.dashboard_admin'))
            elif usuario['rol_id'] == 3: return redirect(url_for('auth.dashboard_cliente'))
            else: return redirect(url_for('auth.login'))
        else: return redirect(url_for('auth.login'))
    return render_template('login.html', datosApp=datosApp)


@auth_bp.route('/cliente')
@rol_requerido(3)
def dashboard_cliente():
    """Panel principal del cliente autenticado."""
    datosApp = get_data_app()
    return render_template('dashboard_cliente.html', datosApp=datosApp)


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
    flow.state = state
    try:
        flow.fetch_token(authorization_response=request.url)
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
                    'UPDATE usuarios SET google_sub = %s, foto_google = %s, ultima_conexion = NOW() WHERE id = %s',
                    (google_sub, picture, usuario['id'])
                )
            else:
                # Crear nuevo usuario cliente
                hash_aleatorio = generate_password_hash(secrets.token_hex(32))
                cur.execute(
                    '''INSERT INTO usuarios
                       (nombre, email, contraseña, rol_id, estado, google_sub, foto_google)
                       VALUES (%s, %s, %s, 3, 'habilitado', %s, %s)
                       RETURNING *''',
                    (name, email, hash_aleatorio, google_sub, picture)
                )
                usuario = cur.fetchone()
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

    # 7. Redirigir según rol
    rol = usuario['rol_id']
    if rol in (1, 2):
        return redirect(url_for('admin.dashboard_admin'))
    elif rol == 3:
        return redirect(url_for('auth.dashboard_cliente'))
    return redirect(url_for('auth.login'))
