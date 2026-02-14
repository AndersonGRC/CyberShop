"""
security.py — Autenticacion, autorizacion y control de acceso.

Contiene el decorador ``rol_requerido`` para proteger rutas por rol,
las funciones de autenticacion de usuario contra la base de datos,
y un limitador basico de tasa de solicitudes por IP.
"""

from functools import wraps
import time

from flask import session, flash, redirect, url_for, request, jsonify
from werkzeug.security import check_password_hash
from psycopg2.extras import DictCursor

from database import get_db_connection


# --- Control de acceso por rol ---

def rol_requerido(rol_id):
    """Decorador que restringe el acceso a una vista segun el rol del usuario.

    Verifica que exista ``rol_id`` en la sesion Flask y que coincida
    con el valor esperado. Si no, redirige al login con mensaje de error.

    Args:
        rol_id: ID numerico del rol permitido (1=Admin, 2=Staff, 3=Cliente).
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'rol_id' not in session or session['rol_id'] != rol_id:
                flash('No tienes permiso para acceder a esta página.', 'error')
                return redirect(url_for('auth.login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# --- Autenticacion de usuario ---

def autenticar_usuario(email, password):
    """Autentica un usuario por email y contrasena.

    Busca el usuario en la base de datos, verifica la contrasena
    con bcrypt/werkzeug y comprueba que la cuenta este habilitada.
    Si la autenticacion es exitosa, actualiza la ultima conexion.

    Args:
        email: Correo electronico del usuario.
        password: Contrasena en texto plano a verificar.

    Returns:
        Diccionario con los datos del usuario si la autenticacion
        es exitosa, o ``None`` si falla.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
        usuario = cur.fetchone()
        cur.close()
        conn.close()
        if usuario and check_password_hash(usuario['contraseña'], password):
            if usuario['estado'] != 'habilitado':
                flash('Tu cuenta está inhabilitada.', 'error')
                return None
            else:
                actualizar_ultima_conexion(usuario['id'])
                return usuario
        else:
            flash('Correo o contraseña incorrectos.', 'error')
            return None
    except Exception as e:
        print(f"Error al autenticar usuario: {e}")
        return None


def actualizar_ultima_conexion(user_id):
    """Registra la fecha y hora actual como ultima conexion del usuario.

    Args:
        user_id: ID del usuario en la tabla ``usuarios``.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('UPDATE usuarios SET ultima_conexion = CURRENT_TIMESTAMP WHERE id = %s', (user_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error al actualizar última conexión: {e}")


# --- Rate limiting basico ---

request_log = {}


def controlar_tasa_solicitudes(ip, max_requests=10, interval=60):
    """Controla la tasa de solicitudes por direccion IP.

    Mantiene un registro en memoria de los timestamps de cada IP
    y rechaza solicitudes que excedan el limite en el intervalo.

    Args:
        ip: Direccion IP del cliente.
        max_requests: Maximo de solicitudes permitidas en el intervalo.
        interval: Ventana de tiempo en segundos.

    Returns:
        ``True`` si la solicitud esta permitida, ``False`` si excede el limite.
    """
    current_time = time.time()

    if ip not in request_log:
        request_log[ip] = []

    request_log[ip] = [t for t in request_log[ip] if current_time - t < interval]

    if len(request_log[ip]) >= max_requests:
        return False

    request_log[ip].append(current_time)
    return True
