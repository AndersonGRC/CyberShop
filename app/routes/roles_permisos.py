"""
routes/roles_permisos.py — Página "Roles y Permisos" del Propietario.

El dueño del negocio configura, módulo por módulo, qué puede hacer cada rol
(Ver / Crear y modificar / Eliminar o anular) y crea roles nuevos. La lógica
vive en services/permisos_service.py; aquí solo hay endpoints delgados.

Protección: solo Admin/Propietario (ADMIN_FULL). Anti-bloqueo: el servicio
rechaza cualquier intento de tocar los roles 1/2/3.
"""
from flask import Blueprint, jsonify, render_template, request, session

from helpers import get_data_app
from security import ADMIN_FULL, rol_requerido
from services import permisos_service as ps

roles_permisos_bp = Blueprint('roles_permisos', __name__,
                              url_prefix='/admin/roles-permisos')


def _uid():
    return session.get('usuario_id')


@roles_permisos_bp.route('/')
@rol_requerido(ADMIN_FULL)
def pagina():
    """Página principal (la matriz se carga por AJAX desde /data)."""
    return render_template('roles_permisos.html', datosApp=get_data_app())


@roles_permisos_bp.route('/data')
@rol_requerido(ADMIN_FULL)
def data():
    """Matriz completa: módulos del plan + roles editables + estados."""
    try:
        return jsonify({'success': True, **ps.matriz_para_ui()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({'success': False, 'error': str(exc)[:200]}), 500


@roles_permisos_bp.route('/toggle', methods=['POST'])
@rol_requerido(ADMIN_FULL)
def toggle():
    """Aplica un interruptor: {rol_id, modulo, accion, valor}. Devuelve el
    estado normalizado de la celda (jerarquía ver ⊇ operar ⊇ eliminar)."""
    d = request.get_json(silent=True) or {}
    try:
        estado = ps.guardar_permiso(d.get('rol_id'), d.get('modulo'),
                                    d.get('accion'), d.get('valor'),
                                    updated_by=_uid())
        return jsonify({'success': True, 'estado': estado})
    except (ValueError, TypeError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({'success': False, 'error': str(exc)[:200]}), 500


@roles_permisos_bp.route('/restaurar', methods=['POST'])
@rol_requerido(ADMIN_FULL)
def restaurar():
    """Vuelve a lo recomendado: {modulo} (todos los roles de ese módulo) o
    {rol_id} (todos los módulos de ese rol) o ambos."""
    d = request.get_json(silent=True) or {}
    try:
        ps.restaurar_defaults(rol_id=d.get('rol_id'), modulo=d.get('modulo'),
                              updated_by=_uid())
        return jsonify({'success': True})
    except (ValueError, TypeError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({'success': False, 'error': str(exc)[:200]}), 500


# ── Roles personalizados ─────────────────────────────────────


@roles_permisos_bp.route('/rol', methods=['POST'])
@rol_requerido(ADMIN_FULL)
def crear_rol():
    """Crea un rol nuevo: {nombre, base_rol_id}. Empieza con los permisos del
    rol base (hereda hasta que el dueño ajuste algo)."""
    d = request.get_json(silent=True) or {}
    try:
        nuevo_id = ps.crear_rol(d.get('nombre'), d.get('base_rol_id'),
                                updated_by=_uid())
        return jsonify({'success': True, 'rol_id': nuevo_id})
    except (ValueError, TypeError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({'success': False, 'error': str(exc)[:200]}), 500


@roles_permisos_bp.route('/rol/<int:rol_id>/renombrar', methods=['POST'])
@rol_requerido(ADMIN_FULL)
def renombrar_rol(rol_id):
    d = request.get_json(silent=True) or {}
    try:
        ps.renombrar_rol(rol_id, d.get('nombre'), updated_by=_uid())
        return jsonify({'success': True})
    except (ValueError, TypeError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({'success': False, 'error': str(exc)[:200]}), 500


@roles_permisos_bp.route('/rol/<int:rol_id>/eliminar', methods=['POST'])
@rol_requerido(ADMIN_FULL)
def eliminar_rol(rol_id):
    try:
        ps.eliminar_rol(rol_id, updated_by=_uid())
        return jsonify({'success': True})
    except (ValueError, TypeError) as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({'success': False, 'error': str(exc)[:200]}), 500
