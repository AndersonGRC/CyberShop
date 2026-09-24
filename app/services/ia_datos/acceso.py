"""Quién puede usar cada herramienta de datos.

Se aplica dos veces: al armar el catálogo que ve el enrutador (la IA ni se
entera de lo que el usuario no puede consultar) y otra vez al ejecutar (por si
el modelo nombra una herramienta que no estaba en su lista).
"""

from dataclasses import dataclass
from typing import Optional

CANAL_WEB = 'web'
CANAL_ESCRITORIO = 'escritorio'
CANAL_SISTEMA = 'sistema'
# Visitante anónimo del sitio público. NO se deduce de la sesión: lo declara
# explícitamente la ruta del chat público. Es lista blanca cerrada: solo corre
# lo que la capacidad declara para este canal (services/ia/intenciones.py).
CANAL_PUBLICO = 'publico'

# Datos sensibles → roles base que pueden verlos (super admin, propietario, contador).
# Se mira el rol BASE: un rol personalizado derivado de Empleado no los ve aunque
# el dueño le amplíe permisos en la matriz.
ROLES_SENSIBLES = {
    'nomina': {1, 2, 5},
}


@dataclass(frozen=True)
class Contexto:
    rol_id: Optional[int] = None
    usuario_id: Optional[int] = None
    canal: str = CANAL_WEB


def contexto_actual():
    """Quién pregunta. En la web: rol y usuario de la sesión. Sin sesión (API
    del escritorio, que se autentica con la llave del negocio y no con el
    usuario) → canal escritorio. Fuera de un request (cron, scripts) → sistema."""
    from flask import has_request_context, session
    if not has_request_context():
        return Contexto(canal=CANAL_SISTEMA)
    try:
        rol = int(session.get('rol_id'))
    except (TypeError, ValueError):
        return Contexto(canal=CANAL_ESCRITORIO)
    return Contexto(rol_id=rol, usuario_id=session.get('usuario_id'), canal=CANAL_WEB)


def _modulo_activo(code):
    """¿El plan del cliente incluye este módulo? Fuera de un request (cron o
    scripts) no hay sesión de la que sacar el tenant, así que se resuelve con el
    tenant por defecto de la instancia; si tampoco se puede, se niega."""
    from tenant_features import is_module_active
    try:
        return bool(is_module_active(code))
    except Exception:
        try:
            from tenant_features import get_default_tenant_id
            return bool(is_module_active(code, tenant_id=get_default_tenant_id()))
        except Exception:
            return False


def puede_usar(h, ctx):
    if h.modulos:
        if not all(_modulo_activo(m) for m in h.modulos):
            return False

    # El sitio público es lista blanca CERRADA: no hereda de "no exige permiso",
    # porque eso dejaría entrar a cualquier capacidad que se registre mañana sin
    # pensar en el público. Tiene que estar declarada para este canal.
    if ctx.canal == CANAL_PUBLICO:
        from services.ia.registro import CANAL_PUBLICO as DECLARADA_PUBLICA
        return DECLARADA_PUBLICA in getattr(h, 'canales', ()) and h.sensible is None

    publica = h.permiso is None and h.sensible is None
    if ctx.canal == CANAL_ESCRITORIO:
        return publica
    if ctx.canal == CANAL_SISTEMA:
        return h.sensible is None
    if publica:
        return True
    if ctx.rol_id is None:
        return False
    from services.permisos_service import rol_base_efectivo, tiene_permiso
    if h.permiso and not tiene_permiso(ctx.rol_id, h.permiso, 'ver'):
        return False
    if h.sensible is not None:
        return rol_base_efectivo(ctx.rol_id) in ROLES_SENSIBLES.get(h.sensible, set())
    return True


def permitidas(ctx, registro):
    return [h for h in registro.values() if puede_usar(h, ctx)]
