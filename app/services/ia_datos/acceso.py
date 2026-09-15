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


def puede_usar(h, ctx):
    if h.modulos:
        from tenant_features import is_module_active
        try:
            if not all(is_module_active(m) for m in h.modulos):
                return False
        except Exception:
            return False
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
