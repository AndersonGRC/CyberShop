"""
services/permisos_service.py — Permisos por rol configurables por el Propietario.

Fuente de verdad:
- Los permisos "recomendados" viven AQUÍ (DEFAULT_MATRIX), derivados de los
  grupos de security.py — una sola expresión, sin duplicar listas de roles.
- La tabla `rol_permisos` (BD del tenant) guarda SOLO excepciones (overrides).
  Vacía = todo recomendado. "Restaurar recomendado" = DELETE.
- Roles personalizados (roles.es_sistema=FALSE) heredan los defaults de su
  `base_rol_id` mientras no tengan override propio.

Reglas de resolución (tiene_permiso):
  1. SuperAdmin(1) y Propietario(2): SIEMPRE True (anti-bloqueo, ni toca BD).
  2. Cliente(3): False (portal de compras, fuera de la matriz).
  3. Override en rol_permisos → manda la fila (normalizada al guardar).
  4. Sin override: rol sistema → DEFAULT_MATRIX; personalizado → default de
     su rol base.

Jerarquía de acciones (normalizada en cada escritura):
  eliminar=True ⇒ operar=True ⇒ ver=True ; ver=False ⇒ operar=eliminar=False.
"""
import time
from functools import lru_cache

from flask import current_app

from database import get_db_cursor
from security import (
    ADMIN_CONTADOR,
    ADMIN_FULL,
    ADMIN_STAFF,
    CATALOG_DELETE,
    CATALOG_OPERATIONAL,
    POS_DELETE,
    POS_OPERATIONAL,
    RESTAURANT_CANCEL,
    RESTAURANT_CHARGE,
    RESTAURANT_OPERATIONAL,
    ROL_CLIENTE,
    ROL_CONTADOR,
    ROL_PROPIETARIO,
    ROL_SUPER_ADMIN,
)

ACCIONES = ('ver', 'operar', 'eliminar')
ROLES_SIEMPRE_TODO = {ROL_SUPER_ADMIN, ROL_PROPIETARIO}
ROLES_BASE_VALIDOS = {4, 5, 6, 7}   # Empleado, Contador, Mesero, Cajero
_CACHE_TTL = 60  # seg — convergencia entre workers gunicorn del mismo tenant

# ─────────────────────────────────────────────────────────
# Matriz recomendada: module_code → acción → grupo de rol_ids.
# Acción ausente = no aplicable a ese módulo (la UI no la muestra
# y el resolver devuelve False).
# ─────────────────────────────────────────────────────────
DEFAULT_MATRIX = {
    'pos':          {'ver': POS_OPERATIONAL,      'operar': POS_OPERATIONAL,      'eliminar': POS_DELETE},
    'caja':         {'ver': POS_OPERATIONAL,      'operar': POS_OPERATIONAL},
    'orders':       {'ver': ADMIN_STAFF,          'operar': ADMIN_STAFF,          'eliminar': ADMIN_FULL},
    'quotes':       {'ver': ADMIN_STAFF,          'operar': ADMIN_STAFF,          'eliminar': ADMIN_FULL},
    'billing':      {'ver': ADMIN_CONTADOR,       'operar': ADMIN_CONTADOR,       'eliminar': ADMIN_CONTADOR},
    'coupons':      {'ver': ADMIN_STAFF,          'operar': ADMIN_STAFF,          'eliminar': ADMIN_FULL},
    'inventory':    {'ver': CATALOG_OPERATIONAL,  'operar': CATALOG_OPERATIONAL,  'eliminar': CATALOG_DELETE},
    'wishlist':     {'ver': ADMIN_STAFF},
    'content':      {'ver': ADMIN_STAFF,          'operar': ADMIN_STAFF,          'eliminar': ADMIN_FULL},
    'users':        {'ver': ADMIN_FULL,           'operar': ADMIN_FULL,           'eliminar': ADMIN_FULL},
    'payroll':      {'ver': ADMIN_CONTADOR,       'operar': ADMIN_CONTADOR,       'eliminar': ADMIN_CONTADOR},
    'crm':          {'ver': ADMIN_STAFF,          'operar': ADMIN_STAFF,          'eliminar': ADMIN_STAFF},
    'accounting':   {'ver': ADMIN_CONTADOR,       'operar': ADMIN_CONTADOR,       'eliminar': ADMIN_CONTADOR},
    'support':      {'ver': ADMIN_STAFF,          'operar': ADMIN_STAFF,          'eliminar': ADMIN_FULL},
    'video':        {'ver': ADMIN_STAFF,          'operar': ADMIN_STAFF,          'eliminar': ADMIN_STAFF},
    'restaurant_tables': {'ver': RESTAURANT_OPERATIONAL, 'operar': RESTAURANT_CHARGE, 'eliminar': RESTAURANT_CANCEL},
    'facturacion_electronica': {'ver': ADMIN_CONTADOR,   'operar': ADMIN_CONTADOR},
    'share':        {'ver': ADMIN_STAFF,          'operar': ADMIN_STAFF,          'eliminar': ADMIN_STAFF},
    'ai_assistant': {'ver': ADMIN_STAFF,          'operar': ADMIN_STAFF},
}

# Nómina web: endurecida a Admin+Contador (espejo del guard y del desktop),
# pero eliminar/liquidar queda para ADMIN_FULL+Contador — mismo criterio NOMINA
# del sync. (payroll ya está arriba con ADMIN_CONTADOR; nota para el lector.)

# Frases cotidianas para la UI (por defecto y excepciones por módulo).
ACCIONES_LABELS_DEFAULT = {
    'ver':      'Puede entrar y ver',
    'operar':   'Puede crear y modificar',
    'eliminar': 'Puede eliminar o anular',
}
ACCIONES_LABELS = {
    'restaurant_tables': {
        'ver':      'Puede atender mesas y tomar pedidos',
        'operar':   'Puede cobrar y cerrar la cuenta',
        'eliminar': 'Puede anular pedidos y ventas',
    },
    'quotes': {
        'eliminar': 'Puede aprobar o eliminar cotizaciones',
    },
    'pos': {
        'eliminar': 'Puede anular ventas',
    },
    'ai_assistant': {
        'operar': 'Puede usar el asistente',
    },
    'caja': {
        'ver':    'Puede ver el estado de la caja',
        'operar': 'Puede registrar movimientos y hacer arqueo',
    },
}

# Íconos Font Awesome por módulo (espejo del menú de helpers.py).
MODULO_ICONOS = {
    'pos': 'cash-register', 'caja': 'coins', 'orders': 'truck', 'quotes': 'file-invoice-dollar',
    'billing': 'file-invoice', 'coupons': 'ticket-alt', 'inventory': 'boxes',
    'wishlist': 'heart', 'content': 'newspaper', 'users': 'users',
    'payroll': 'id-card', 'crm': 'address-book', 'accounting': 'chart-line',
    'support': 'headset', 'video': 'video', 'restaurant_tables': 'utensils',
    'facturacion_electronica': 'file-invoice', 'share': 'share-alt',
    'ai_assistant': 'robot',
}


# ─────────────────────────────────────────────────────────
# Caché (patrón mono-tenant, como _get_module_config_rows)
# ─────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _load_estado(_bucket):
    """Carga completa de roles + overrides. `_bucket` cambia cada _CACHE_TTL seg
    para expirar solo (convergencia entre workers); invalidar_cache() fuerza.

    Tolerante a BD sin migrar: si `roles` no tiene aún las columnas nuevas
    (es_sistema...) se leen las básicas; si `rol_permisos` no existe todavía,
    overrides = {} (todo queda en los recomendados). Así la página funciona
    ANTES de aplicar las migraciones 0001/0002."""
    roles, overrides = {}, {}
    with get_db_cursor(dict_cursor=True) as cur:
        try:
            cur.execute("SELECT id, nombre, es_sistema, base_rol_id, activo FROM roles")
            filas = cur.fetchall()
            extendida = True
        except Exception:
            cur.connection.rollback()
            cur.execute("SELECT id, nombre FROM roles")
            filas = cur.fetchall()
            extendida = False
        for r in filas:
            rid = int(r['id'])
            roles[rid] = {
                'id': rid,
                'nombre': r['nombre'],
                'es_sistema': bool(r.get('es_sistema', True)) if extendida else True,
                'base_rol_id': (int(r['base_rol_id']) if extendida and r.get('base_rol_id') else None),
                'activo': bool(r.get('activo', True)) if extendida else True,
            }
        try:
            cur.execute("SELECT rol_id, modulo, ver, operar, eliminar FROM rol_permisos")
            for p in cur.fetchall():
                overrides[(int(p['rol_id']), p['modulo'])] = {
                    'ver': bool(p['ver']), 'operar': bool(p['operar']),
                    'eliminar': bool(p['eliminar']),
                }
        except Exception:
            cur.connection.rollback()   # tabla aún no migrada → recomendados
    return roles, overrides


def _estado():
    return _load_estado(int(time.time() // _CACHE_TTL))


def invalidar_cache():
    _load_estado.cache_clear()


def _estado_con_cursor(cur):
    """Variante para contextos que YA tienen cursor del tenant (api_sync):
    lee directo sin caché (el sync es poco frecuente y el cursor manda).
    Acceso por CLAVE: DictRow/RealDictRow de psycopg2 lo soportan (DictRow NO
    es instancia de dict, por eso no se usa isinstance)."""
    roles, overrides = {}, {}
    cur.execute("SELECT id, nombre, es_sistema, base_rol_id, activo FROM roles")
    for r in cur.fetchall():
        rid = int(r['id'])
        roles[rid] = {
            'id': rid,
            'nombre': r['nombre'],
            'es_sistema': bool(r['es_sistema'] if r['es_sistema'] is not None else True),
            'base_rol_id': int(r['base_rol_id']) if r['base_rol_id'] else None,
            'activo': bool(r['activo'] if r['activo'] is not None else True),
        }
    cur.execute("SELECT rol_id, modulo, ver, operar, eliminar FROM rol_permisos")
    for p in cur.fetchall():
        overrides[(int(p['rol_id']), p['modulo'])] = {
            'ver': bool(p['ver']), 'operar': bool(p['operar']),
            'eliminar': bool(p['eliminar']),
        }
    return roles, overrides


def tiene_override_ver(rol_id, modulo):
    """True SOLO si el dueño configuró explícitamente (override en BD) que este
    rol puede VER este módulo. Distingue 'ampliación deliberada del dueño' de
    los defaults — lo usa rol_requerido para ceder ante la decisión del dueño."""
    try:
        _, overrides = _estado()
    except Exception:
        return False
    fila = overrides.get((int(rol_id), modulo))
    return bool(fila and fila.get('ver'))


# ─────────────────────────────────────────────────────────
# Resolución
# ─────────────────────────────────────────────────────────
def _default_permite(rol_id, modulo, accion):
    grupo = (DEFAULT_MATRIX.get(modulo) or {}).get(accion)
    return grupo is not None and rol_id in grupo


def rol_base_efectivo(rol_id, roles=None):
    """Rol de sistema equivalente: sistema → mismo id; personalizado → su base.
    Si no se puede resolver, devuelve el mismo id."""
    try:
        rol_id = int(rol_id)
    except (TypeError, ValueError):
        return rol_id
    if rol_id in ROLES_SIEMPRE_TODO or rol_id == ROL_CLIENTE or rol_id in ROLES_BASE_VALIDOS:
        return rol_id
    try:
        if roles is None:
            roles, _ = _estado()
        info = roles.get(rol_id)
        if info and not info['es_sistema'] and info.get('base_rol_id'):
            return info['base_rol_id']
    except Exception:
        pass
    return rol_id


def _resolver(rol_id, modulo, accion, roles, overrides):
    """Núcleo de resolución sobre datos ya cargados (sin BD)."""
    fila = overrides.get((rol_id, modulo))
    if fila is not None:
        return bool(fila.get(accion))
    base = rol_base_efectivo(rol_id, roles=roles)
    return _default_permite(base, modulo, accion)


def tiene_permiso(rol_id, modulo, accion='ver', cur=None):
    """¿El rol puede `accion` en `modulo`? Ver docstring del módulo (orden 1-4)."""
    try:
        rol_id = int(rol_id)
    except (TypeError, ValueError):
        return False
    if rol_id in ROLES_SIEMPRE_TODO:
        return True                       # anti-bloqueo: ni consulta BD
    if rol_id == ROL_CLIENTE:
        return False
    if accion not in ACCIONES:
        return False
    try:
        roles, overrides = _estado_con_cursor(cur) if cur is not None else _estado()
    except Exception as exc:              # BD sin migrar aún → recomendados
        try:
            current_app.logger.warning(f"permisos: fallback a defaults ({exc})")
        except Exception:
            pass
        return _default_permite(rol_id, modulo, accion)
    return _resolver(rol_id, modulo, accion, roles, overrides)


def resolver_para_cursor(cur):
    """Callable (rol_id, modulo, accion) -> bool con los datos del tenant
    cargados UNA sola vez desde `cur` (para computar el manifiesto desktop
    sin una consulta por celda)."""
    roles, overrides = _estado_con_cursor(cur)

    def _fn(rol_id, modulo, accion):
        try:
            rol_id = int(rol_id)
        except (TypeError, ValueError):
            return False
        if rol_id in ROLES_SIEMPRE_TODO:
            return True
        if rol_id == ROL_CLIENTE:
            return False
        if accion not in ACCIONES:
            return False
        return _resolver(rol_id, modulo, accion, roles, overrides)
    return _fn


def permisos_de_rol(rol_id):
    """Matriz efectiva {modulo: {ver, operar, eliminar}} para un rol."""
    out = {}
    for modulo in DEFAULT_MATRIX:
        out[modulo] = {a: tiene_permiso(rol_id, modulo, a) for a in ACCIONES}
    return out


# ─────────────────────────────────────────────────────────
# Catálogo para la UI
# ─────────────────────────────────────────────────────────
def modulos_gestionables():
    """Módulos administrables por el dueño: DEFAULT_MATRIX ∩ MODULE_DEFINITIONS
    ∩ módulos activos del plan. Con nombre/descripcion en español, ícono, orden
    y las acciones aplicables (con su frase cotidiana)."""
    from tenant_features import MODULE_DEFINITIONS, get_active_module_codes
    activos = get_active_module_codes()
    out = []
    for code, meta in MODULE_DEFINITIONS.items():
        if code not in DEFAULT_MATRIX or code not in activos:
            continue
        labels = {**ACCIONES_LABELS_DEFAULT, **ACCIONES_LABELS.get(code, {})}
        out.append({
            'modulo': code,
            'nombre': meta.get('nombre') or code,
            'descripcion': meta.get('descripcion') or '',
            'categoria': meta.get('categoria') or '',
            'orden': meta.get('orden') or 999,
            'icono': MODULO_ICONOS.get(code, 'cube'),
            'acciones': [
                {'accion': a, 'label': labels[a]}
                for a in ACCIONES if a in DEFAULT_MATRIX[code]
            ],
        })
    out.sort(key=lambda m: m['orden'])
    return out


_ROLES_SISTEMA_SEED = {4: 'Empleado', 5: 'Contador', 6: 'Mesero', 7: 'Cajero'}


def _ensure_roles_sistema():
    """Autocuración: garantiza que los 4 roles operativos del sistema existen
    en la BD del tenant (hay BDs reales sin las filas 4/5 o 4-7 — sin ellas la
    página no puede configurarlos y el sync de usuarios por nombre falla).
    Idempotente. Se llama solo al abrir la página o crear un rol, nunca en el
    hot path de tiene_permiso. Espejo de la migración 0002."""
    try:
        roles, _ = _estado()
        faltantes = [rid for rid in _ROLES_SISTEMA_SEED if rid not in roles]
        if not faltantes:
            return
        with get_db_cursor() as cur:
            for rid in faltantes:
                cur.execute(
                    "INSERT INTO roles (id, nombre) SELECT %s, %s "
                    "WHERE NOT EXISTS (SELECT 1 FROM roles WHERE id = %s)",
                    (rid, _ROLES_SISTEMA_SEED[rid], rid),
                )
            cur.execute("SELECT setval(pg_get_serial_sequence('roles','id'), "
                        "GREATEST((SELECT COALESCE(MAX(id),1) FROM roles), 7))")
        invalidar_cache()
        try:
            current_app.logger.info(f"permisos: roles de sistema sembrados {faltantes}")
        except Exception:
            pass
    except Exception as exc:  # nunca romper la página por esto
        try:
            current_app.logger.warning(f"permisos: no se pudo sembrar roles ({exc})")
        except Exception:
            pass


def _usuarios_por_rol():
    """Conteo real de personas por rol en la BD del tenant."""
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT rol_id, COUNT(*) AS n FROM usuarios GROUP BY rol_id")
            return {int(r['rol_id']): int(r['n']) for r in cur.fetchall() if r['rol_id']}
    except Exception:
        return {}


def roles_editables(con_usuarios=False):
    """Roles que el dueño puede configurar: los 4 de sistema operativos +
    personalizados activos. Nunca 1, 2 ni 3. Con `con_usuarios` añade el
    conteo real de personas que tienen cada rol."""
    roles, _ = _estado()
    conteos = _usuarios_por_rol() if con_usuarios else {}
    out = []
    for rid in sorted(roles):
        info = roles[rid]
        if rid in ROLES_SIEMPRE_TODO or rid == ROL_CLIENTE or not info['activo']:
            continue
        if info['es_sistema'] and rid not in ROLES_BASE_VALIDOS:
            continue
        base = roles.get(info.get('base_rol_id') or 0)
        item = {
            'id': rid, 'nombre': info['nombre'], 'es_sistema': info['es_sistema'],
            'base_nombre': base['nombre'] if base else None,
        }
        if con_usuarios:
            item['usuarios'] = conteos.get(rid, 0)
        out.append(item)
    # sistema primero, luego personalizados por nombre
    out.sort(key=lambda r: (not r['es_sistema'] and 1 or 0, r['id']))
    return out


def matriz_para_ui():
    """Todo lo que la página necesita: módulos, roles y estados efectivos,
    marcando si cada celda viene de un override (personalizado por el dueño).
    Autocura los roles de sistema faltantes y trae el conteo real de personas
    por rol (la configuración refleja la BD de ESTE cliente)."""
    _ensure_roles_sistema()
    _, overrides = _estado()
    modulos = modulos_gestionables()
    roles = roles_editables(con_usuarios=True)
    permisos = {}
    for r in roles:
        for m in modulos:
            celda = {a['accion']: tiene_permiso(r['id'], m['modulo'], a['accion'])
                     for a in m['acciones']}
            permisos[f"{r['id']}:{m['modulo']}"] = {
                **celda,
                'personalizado': (r['id'], m['modulo']) in overrides,
            }
    return {'modulos': modulos, 'roles': roles, 'permisos': permisos}


# ─────────────────────────────────────────────────────────
# Escritura (siempre normaliza jerarquía e invalida caché)
# ─────────────────────────────────────────────────────────
def _validar_editable(rol_id):
    rol_id = int(rol_id)
    if rol_id in ROLES_SIEMPRE_TODO:
        raise ValueError('El Propietario y el Administrador siempre pueden hacer todo.')
    if rol_id == ROL_CLIENTE:
        raise ValueError('El rol Cliente no se puede configurar.')
    return rol_id


def _normalizar(ver, operar, eliminar):
    ver, operar, eliminar = bool(ver), bool(operar), bool(eliminar)
    if eliminar:
        operar = True
    if operar:
        ver = True
    if not ver:
        operar = eliminar = False
    return ver, operar, eliminar


def guardar_permiso(rol_id, modulo, accion, valor, updated_by=None):
    """Aplica un toggle. Parte del estado EFECTIVO actual, cambia `accion`,
    normaliza jerarquía y guarda como override. Devuelve el estado resultante."""
    rol_id = _validar_editable(rol_id)
    if modulo not in DEFAULT_MATRIX:
        raise ValueError(f'Módulo desconocido: {modulo}')
    if accion not in ACCIONES or accion not in DEFAULT_MATRIX[modulo]:
        raise ValueError(f'Acción no aplicable a este módulo: {accion}')
    actual = {a: tiene_permiso(rol_id, modulo, a) for a in ACCIONES}
    actual[accion] = bool(valor)
    # Jerarquía direccional: encender un nivel enciende los inferiores;
    # apagarlo apaga los superiores.
    if accion == 'ver' and not valor:
        actual['operar'] = actual['eliminar'] = False
    if accion == 'operar':
        if valor:
            actual['ver'] = True
        else:
            actual['eliminar'] = False
    if accion == 'eliminar' and valor:
        actual['ver'] = actual['operar'] = True
    ver, operar, eliminar = _normalizar(actual['ver'], actual['operar'], actual['eliminar'])
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO rol_permisos (rol_id, modulo, ver, operar, eliminar, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (rol_id, modulo) DO UPDATE SET
                ver = EXCLUDED.ver, operar = EXCLUDED.operar,
                eliminar = EXCLUDED.eliminar,
                updated_by = EXCLUDED.updated_by, updated_at = NOW()
            """,
            (rol_id, modulo, ver, operar, eliminar, updated_by),
        )
    invalidar_cache()
    try:
        current_app.logger.info(
            f"permisos: rol={rol_id} modulo={modulo} -> ver={ver} operar={operar} "
            f"eliminar={eliminar} (por usuario {updated_by})")
    except Exception:
        pass
    return {'ver': ver, 'operar': operar, 'eliminar': eliminar, 'personalizado': True}


def restaurar_defaults(rol_id=None, modulo=None, updated_by=None):
    """Borra overrides: de un rol+módulo, de todo un módulo, de todo un rol,
    o todos (ambos None)."""
    conds, params = [], []
    if rol_id is not None:
        conds.append('rol_id = %s'); params.append(_validar_editable(rol_id))
    if modulo is not None:
        conds.append('modulo = %s'); params.append(modulo)
    where = (' WHERE ' + ' AND '.join(conds)) if conds else ''
    with get_db_cursor() as cur:
        cur.execute(f'DELETE FROM rol_permisos{where}', tuple(params))
    invalidar_cache()
    try:
        current_app.logger.info(
            f"permisos: restaurado recomendado rol={rol_id} modulo={modulo} (por {updated_by})")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────
# Roles personalizados (Fase 2)
# ─────────────────────────────────────────────────────────
def crear_rol(nombre, base_rol_id, updated_by=None):
    _ensure_roles_sistema()   # el rol base debe existir en la BD del tenant
    nombre = (nombre or '').strip()
    if not (2 <= len(nombre) <= 50):
        raise ValueError('El nombre del rol debe tener entre 2 y 50 caracteres.')
    base_rol_id = int(base_rol_id)
    if base_rol_id not in ROLES_BASE_VALIDOS:
        raise ValueError('El rol base debe ser Empleado, Contador, Mesero o Cajero.')
    with get_db_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT 1 FROM roles WHERE LOWER(nombre) = LOWER(%s)', (nombre,))
        if cur.fetchone():
            raise ValueError('Ya existe un rol con ese nombre.')
        cur.execute(
            """
            INSERT INTO roles (nombre, es_sistema, base_rol_id, activo)
            VALUES (%s, FALSE, %s, TRUE) RETURNING id
            """,
            (nombre, base_rol_id),
        )
        nuevo_id = cur.fetchone()['id']
    invalidar_cache()
    try:
        current_app.logger.info(f"permisos: rol creado '{nombre}' (base {base_rol_id}) por {updated_by}")
    except Exception:
        pass
    return int(nuevo_id)


def _rol_personalizado(cur, rol_id):
    cur.execute('SELECT id, nombre, es_sistema FROM roles WHERE id = %s', (rol_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError('El rol no existe.')
    if row['es_sistema']:
        raise ValueError('Los roles del sistema no se pueden renombrar ni eliminar.')
    return row


def renombrar_rol(rol_id, nombre, updated_by=None):
    nombre = (nombre or '').strip()
    if not (2 <= len(nombre) <= 50):
        raise ValueError('El nombre del rol debe tener entre 2 y 50 caracteres.')
    with get_db_cursor(dict_cursor=True) as cur:
        _rol_personalizado(cur, int(rol_id))
        cur.execute('SELECT 1 FROM roles WHERE LOWER(nombre) = LOWER(%s) AND id <> %s',
                    (nombre, int(rol_id)))
        if cur.fetchone():
            raise ValueError('Ya existe un rol con ese nombre.')
        cur.execute('UPDATE roles SET nombre = %s WHERE id = %s', (nombre, int(rol_id)))
    invalidar_cache()


def eliminar_rol(rol_id, updated_by=None):
    with get_db_cursor(dict_cursor=True) as cur:
        _rol_personalizado(cur, int(rol_id))
        cur.execute('SELECT COUNT(*) AS n FROM usuarios WHERE rol_id = %s', (int(rol_id),))
        n = cur.fetchone()['n']
        if n:
            raise ValueError(
                f'Este rol lo usan {n} persona(s). Primero cambia de rol a esas personas.')
        cur.execute('DELETE FROM roles WHERE id = %s', (int(rol_id),))  # CASCADE borra permisos
    invalidar_cache()
    try:
        current_app.logger.info(f"permisos: rol {rol_id} eliminado por {updated_by}")
    except Exception:
        pass
