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

POS_OPERATIONAL = ADMIN_STAFF + [ROL_MESERO, ROL_CAJERO]
# Quién puede usar y consultar el POS: staff, mesero y cajero

POS_DELETE = ADMIN_FULL
# Quién puede anular/eliminar registros sensibles del POS: solo super admin y propietario

CATALOG_OPERATIONAL = ADMIN_STAFF + [ROL_MESERO, ROL_CAJERO]
# Quién puede crear/editar productos y operar inventario sin eliminar catálogo

CATALOG_DELETE = ADMIN_FULL
# Quién puede eliminar productos del catálogo: solo super admin y propietario

# ─────────────────────────────────────────────────────────
# Restaurante: permisos operativos
# ─────────────────────────────────────────────────────────
RESTAURANT_OPERATIONAL = ADMIN_STAFF + [ROL_MESERO, ROL_CAJERO]
# Quién puede entrar a "Atender Mesas" y agregar consumos: mesero, cajero, staff

RESTAURANT_CHARGE      = ADMIN_FULL + [ROL_MESERO, ROL_CAJERO]
# Quién puede cobrar/cerrar la cuenta de una mesa: mesero, cajero y dueño/admin

RESTAURANT_CANCEL      = ADMIN_FULL + [ROL_CAJERO]
# Quién puede anular consumos, cancelar mesas abiertas o anular ventas cerradas


# ─────────────────────────────────────────────────────────
# Manifiesto de permisos para el ESCRITORIO (offline-first)
# ─────────────────────────────────────────────────────────
# Deriva los permisos rol → módulo → acción desde los grupos de arriba (fuente
# única). El desktop lo descarga vía /api/v1/sync/config y lo respeta SIN tener
# su propia copia hardcodeada (evita drift). Las claves son los NOMBRES de rol
# del desktop; el desktop intersecta estos módulos con los del PLAN del tenant.
#
# Nota nómina: las rutas web de nómina no tienen decorador de rol; por la
# sensibilidad de los datos (salarios/PII) aquí se restringe a Administrador y
# Contador (endurecimiento deliberado respecto a la web).

_DESKTOP_ROLE_BY_ID = {
    1: "Administrador", 2: "Administrador", 3: "Cliente",
    4: "Empleado", 5: "Contador", 6: "Mesero", 7: "Cajero",
}


# Traducción módulo web (matriz 3 niveles) → nav keys y acciones del desktop.
# Cada entrada: modulo_web → [(nav_key_desktop, {accion_web: [acciones_desktop]})]
_DESKTOP_TRANSLATION = {
    'pos':               [('pos',          {'ver': ['view'], 'operar': ['create'], 'eliminar': ['delete']}),
                          ('sales',        {'ver': ['view']})],
    'inventory':         [('products',     {'ver': ['view'], 'operar': ['create', 'edit'], 'eliminar': ['delete']}),
                          ('inventory',    {'ver': ['view'], 'operar': ['create', 'edit'], 'eliminar': ['delete']})],
    'restaurant_tables': [('restaurant',   {'ver': ['view', 'create'], 'operar': ['charge'], 'eliminar': ['cancel']})],
    'quotes':            [('quotes',       {'ver': ['view'], 'operar': ['create', 'edit'], 'eliminar': ['delete', 'approve']})],
    'crm':               [('crm',          {'ver': ['view'], 'operar': ['create', 'edit'], 'eliminar': ['delete']})],
    'accounting':        [('contabilidad', {'ver': ['view'], 'operar': ['create', 'edit'], 'eliminar': ['delete']})],
    'billing':           [('cobros',       {'ver': ['view'], 'operar': ['create', 'edit'], 'eliminar': ['delete']})],
    'payroll':           [('payroll',      {'ver': ['view'], 'operar': ['create', 'edit'], 'eliminar': ['delete']})],
    'users':             [('users',        {'ver': ['view'], 'operar': ['create', 'edit'], 'eliminar': ['delete']})],
    'ai_assistant':      [('ia',           {'ver': ['view'], 'operar': ['use']})],
}


def _desktop_actions_for(rol_id, resolver=None):
    """Acciones permitidas por módulo del desktop para un rol_id.

    `resolver(rol_id, modulo, accion) -> bool` permite computar contra la
    matriz DINÁMICA del tenant (services/permisos_service.tiene_permiso con el
    cursor del tenant). Sin resolver usa los defaults estáticos del servicio
    (mismos grupos de siempre) — con la tabla de overrides vacía ambos caminos
    producen el mismo manifiesto."""
    if resolver is None:
        from services.permisos_service import tiene_permiso as resolver  # noqa: PLW0127

    m = {"dashboard": ["view"]}
    for modulo_web, targets in _DESKTOP_TRANSLATION.items():
        for nav_key, mapa in targets:
            acts = []
            for accion_web, acciones_desktop in mapa.items():
                try:
                    permitido = resolver(rol_id, modulo_web, accion_web)
                except Exception:
                    permitido = False
                if permitido:
                    acts.extend(acciones_desktop)
            if acts and 'view' in acts:
                prev = m.get(nav_key, [])
                m[nav_key] = sorted(set(prev) | set(acts))
    # Historial de ventas también para contador (ve contabilidad → ve ventas)
    try:
        if resolver(rol_id, 'accounting', 'ver'):
            m.setdefault('sales', ['view'])
    except Exception:
        pass
    # Módulos de sistema (sincronización/configuración): solo Admin/Propietario.
    if rol_id in ADMIN_FULL:
        m["sync"] = ["view"]
        m["config"] = ["view"]
    return m


def desktop_permissions_manifest(resolver=None, roles_tenant=None):
    """Manifiesto rol → {modules, actions} para el desktop, keyed por NOMBRE de
    rol. Con `resolver` + `roles_tenant` (lista de dicts {id, nombre} de la BD
    del tenant, incluyendo roles personalizados) computa el manifiesto DINÁMICO
    del tenant; sin argumentos usa los roles de sistema y los defaults (misma
    salida de siempre — fallback seguro).

    NO intersecta con el plan del tenant: eso lo hace el desktop con los flags
    de cliente_config."""
    pares = []          # (rol_id, nombre_desktop)
    if roles_tenant:
        for r in roles_tenant:
            rid = int(r['id'])
            nombre = _DESKTOP_ROLE_BY_ID.get(rid, (r.get('nombre') or '').strip())
            if not nombre:
                continue
            pares.append((rid, nombre))
        # Garantizar que Administrador (1/2) siempre exista aunque la tabla
        # roles del tenant tenga nombres viejos ('admin','usuario').
        pares = [(rid, n) for rid, n in pares if rid not in (1, 2)]
        pares = [(1, "Administrador"), (2, "Administrador")] + pares
    else:
        pares = [(rid, rname) for rid, rname in _DESKTOP_ROLE_BY_ID.items()]

    out = {}
    for rid, rname in pares:
        acts = _desktop_actions_for(rid, resolver=resolver)
        if rname in out:
            # Roles que colapsan al mismo nombre (1 y 2 -> Administrador): unir.
            merged = out[rname]["actions"]
            for mod, a in acts.items():
                merged[mod] = sorted(set(merged.get(mod, [])) | set(a))
            out[rname]["modules"] = sorted(merged.keys())
        else:
            out[rname] = {"modules": sorted(acts.keys()), "actions": acts}
    return out


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
            rol_sesion = session['rol_id']
            if rol_sesion not in permitidos:
                # Roles PERSONALIZADOS (creados por el Propietario): heredan la
                # pertenencia a grupos de su rol base. Así los decoradores
                # legacy siguen funcionando sin refactor; la matriz dinámica
                # (permiso_requerido/guards) aplica los ajustes finos encima.
                try:
                    from services.permisos_service import rol_base_efectivo
                    rol_sesion = rol_base_efectivo(rol_sesion)
                except Exception:
                    pass
            if rol_sesion not in permitidos:
                # AMPLIACIÓN del dueño: si el guard dinámico del blueprint ya
                # autorizó este módulo Y existe un override explícito (ver=True
                # configurado en Roles y Permisos), la decisión del dueño manda
                # sobre el grupo estático. Con solo defaults, se veta como
                # siempre. Las acciones sensibles siguen protegidas por
                # @permiso_requerido(..., 'operar'/'eliminar').
                try:
                    from flask import g as _g
                    from services.permisos_service import tiene_override_ver
                    mod = getattr(_g, '_rp_modulo_autorizado', None)
                    if mod and tiene_override_ver(session['rol_id'], mod):
                        return f(*args, **kwargs)
                except Exception:
                    pass
                if _is_json_request():
                    return jsonify({'success': False, 'error': 'No tienes permiso para esta acción.'}), 403
                flash('No tienes permiso para acceder a esta página.', 'error')
                return redirect(url_for('auth.login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ─────────────────────────────────────────────────────────
# Permisos dinámicos (matriz configurable por el Propietario)
# ─────────────────────────────────────────────────────────

def _denegar(json_status=403, mensaje='No tienes permiso para esta acción.'):
    """Respuesta uniforme de denegación (idéntica a rol_requerido)."""
    if _is_json_request():
        return jsonify({'success': False, 'error': mensaje}), json_status
    flash('No tienes permiso para acceder a esta página.', 'error')
    return redirect(url_for('auth.login'))


def permiso_requerido(modulo, accion='ver'):
    """Decorador de permisos DINÁMICOS: consulta la matriz configurable del
    tenant (services/permisos_service). Roles 1/2 siempre pasan (anti-bloqueo).
    Convive con @rol_requerido (defensa en profundidad)."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'rol_id' not in session:
                return _denegar(401, 'Sesión expirada. Inicia sesión de nuevo.')
            from services.permisos_service import tiene_permiso
            if not tiene_permiso(session['rol_id'], modulo, accion):
                return _denegar()
            return f(*args, **kwargs)
        return wrapped
    return decorator


def registrar_guard_permiso(bp, modulo, exempt_endpoints=frozenset(), solo_prefijos=None):
    """Guard before_request de blueprint: exige sesión + permiso 'ver' del
    módulo (las rutas nuevas quedan protegidas por defecto).

    - `exempt_endpoints`: endpoints (sin prefijo del blueprint) que se saltan
      el guard (p.ej. webhooks o rutas públicas por token).
    - `solo_prefijos`: si se da, el guard SOLO aplica a rutas cuyo path empieza
      por alguno de estos prefijos (para blueprints que mezclan rutas admin con
      rutas de cliente final o públicas, p.ej. video/soporte/share)."""
    @bp.before_request
    def _guard():  # noqa: ANN202
        endpoint = (request.endpoint or '').rsplit('.', 1)[-1]
        if endpoint in exempt_endpoints:
            return None
        if solo_prefijos is not None and not any(
                request.path.startswith(p) for p in solo_prefijos):
            return None
        if 'rol_id' not in session:
            return _denegar(401, 'Sesión expirada. Inicia sesión de nuevo.')
        from services.permisos_service import tiene_permiso
        if not tiene_permiso(session['rol_id'], modulo, 'ver'):
            return _denegar()
        # Marca el módulo autorizado dinámicamente: rol_requerido (legacy) cede
        # ante AMPLIACIONES explícitas del dueño (override ver=True) para las
        # rutas de este blueprint. Sin override, el decorador legacy sigue
        # vetando igual que siempre (defensa en profundidad intacta).
        from flask import g as _g
        _g._rp_modulo_autorizado = modulo
        return None
    return _guard


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
