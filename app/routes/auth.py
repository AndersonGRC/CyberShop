"""
routes/auth.py — Blueprint de autenticacion y registro de clientes.

Rutas: /registrar-cliente, /login, /logout, /cliente
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash
from psycopg2.extras import DictCursor
from flask import current_app as app

from database import get_db_connection
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
