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

from database import get_db_connection, get_db_cursor


# ─────────────────────────────────────────────────────────
# IDs de roles
# ─────────────────────────────────────────────────────────
ROL_SUPER_ADMIN = 1   # Administrador del sitio (desarrollador / control total)
ROL_PROPIETARIO = 2   # Dueño del negocio / cliente del software
ROL_CLIENTE     = 3   # Cliente final (comprador en la tienda)
ROL_EMPLEADO    = 4   # Empleado del negocio (ventas, productos, CRM)
ROL_CONTADOR    = 5   # Contador (solo módulos contabilidad y facturación)
ROL_MESERO      = 6   # Mesero del restaurante (toma pedidos en mesas)
ROL_CAJERO      = 7   # Cajero del restaurante (cobra y anula)

# ─────────────────────────────────────────────────────────
# Grupos de permisos reutilizables
# ─────────────────────────────────────────────────────────
ADMIN_FULL     = [ROL_SUPER_ADMIN, ROL_PROPIETARIO]
# Super Admin + Propietario: gestión de usuarios, configuración global

ADMIN_STAFF    = [ROL_SUPER_ADMIN, ROL_PROPIETARIO, ROL_EMPLEADO]
# + Empleado: productos, pedidos, POS, cotizaciones, CRM, soporte

ADMIN_CONTADOR = [ROL_SUPER_ADMIN, ROL_PROPIETARIO, ROL_CONTADOR]
# + Contador: contabilidad, facturación, historial POS

ROLES_CLIENTE  = [ROL_CLIENTE]
# Solo cliente final: portal de compras y soporte al cliente

# ─────────────────────────────────────────────────────────
# Restaurante: permisos operativos
# ─────────────────────────────────────────────────────────
RESTAURANT_OPERATIONAL = ADMIN_STAFF + [ROL_MESERO, ROL_CAJERO]
# Quién puede entrar a "Atender Mesas" y agregar consumos: mesero, cajero, staff

RESTAURANT_CHARGE      = ADMIN_FULL + [ROL_CAJERO]
# Quién puede cobrar/cerrar la cuenta de una mesa: cajero y dueño/admin

RESTAURANT_CANCEL      = ADMIN_FULL + [ROL_CAJERO]
# Quién puede anular consumos, cancelar mesas abiertas o anular ventas cerradas


# --- Control de acceso por rol ---

def _is_json_request():
    """Detecta si la peticion espera una respuesta JSON."""
    return (
        request.is_json
        or request.headers.get('Accept', '').startswith('application/json')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.path.endswith('/data')
    )


def rol_requerido(rol_id):
    """Decorador que restringe el acceso a una vista segun el rol del usuario.

    Acepta un ID numerico o una lista de IDs permitidos.

    Args:
        rol_id: ID numerico del rol permitido, o lista de IDs permitidos.
                Ejemplos: rol_requerido(1), rol_requerido(ADMIN_STAFF)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'rol_id' not in session:
                if _is_json_request():
                    return jsonify({'success': False, 'error': 'Sesión expirada. Inicia sesión de nuevo.'}), 401
                flash('No tienes permiso para acceder a esta página.', 'error')
                return redirect(url_for('auth.login'))
            permitidos = rol_id if isinstance(rol_id, list) else [rol_id]
            if session['rol_id'] not in permitidos:
                if _is_json_request():
                    return jsonify({'success': False, 'error': 'No tienes permiso para esta acción.'}), 403
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
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute('SELECT * FROM usuarios WHERE email = %s', (email,))
            usuario = cur.fetchone()
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
        from flask import current_app
        current_app.logger.error(f"Error al autenticar usuario: {e}")
        return None


def actualizar_ultima_conexion(user_id):
    """Registra la fecha y hora actual como ultima conexion del usuario.

    Args:
        user_id: ID del usuario en la tabla ``usuarios``.
    """
    try:
        with get_db_cursor() as cur:
            cur.execute('UPDATE usuarios SET ultima_conexion = CURRENT_TIMESTAMP WHERE id = %s', (user_id,))
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Error al actualizar última conexión: {e}")


# --- Rate limiting basico ---

request_log = {}
_MAX_IPS_TRACKED = 10000


def _purgar_request_log():
    """Elimina IPs expiradas para evitar crecimiento ilimitado del dict."""
    if len(request_log) <= _MAX_IPS_TRACKED:
        return
    current_time = time.time()
    ips_expiradas = [ip for ip, ts in request_log.items()
                     if not ts or current_time - ts[-1] > 300]
    for ip in ips_expiradas:
        del request_log[ip]


def controlar_tasa_solicitudes(ip, max_requests=10, interval=60):
    """Controla la tasa de solicitudes por direccion IP.

    Mantiene un registro en memoria de los timestamps de cada IP
    y rechaza solicitudes que excedan el limite en el intervalo.
    Purga automaticamente IPs inactivas cuando el registro supera
    el limite de _MAX_IPS_TRACKED.

    Args:
        ip: Direccion IP del cliente.
        max_requests: Maximo de solicitudes permitidas en el intervalo.
        interval: Ventana de tiempo en segundos.

    Returns:
        ``True`` si la solicitud esta permitida, ``False`` si excede el limite.
    """
    current_time = time.time()
    _purgar_request_log()

    if ip not in request_log:
        request_log[ip] = []

    request_log[ip] = [t for t in request_log[ip] if current_time - t < interval]

    if len(request_log[ip]) >= max_requests:
        return False

    request_log[ip].append(current_time)
    return True
