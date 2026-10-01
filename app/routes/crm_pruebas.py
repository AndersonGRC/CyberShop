"""CRM → Pruebas gratis: quién está probando el software, cuántos días le
quedan y cómo contactarlo (WhatsApp, correo, link de pago).

Solo lectura sobre `plan_compras` (BD de CyberShop). Blueprint aparte para no
tocar routes/crm.py; mismos permisos que el CRM (`crm` ver) y requiere el
módulo CRM activo.
"""
from flask import Blueprint, render_template, request

from helpers import get_data_app
from security import ADMIN_STAFF, registrar_guard_permiso, rol_requerido
from tenant_features import MODULE_CRM, module_required

crm_pruebas_bp = Blueprint('crm_pruebas', __name__, url_prefix='/admin/crm/pruebas-gratis')
registrar_guard_permiso(crm_pruebas_bp, 'crm')

FILTROS = (
    ('todas', 'Todas'), ('activas', 'Activas'), ('por_vencer', 'Por vencer (3 días o menos)'),
    ('vencida', 'Vencidas'), ('pendiente', 'Sin confirmar correo'),
    ('convertida', 'Ya son clientes'), ('error', 'Con error'),
)


@crm_pruebas_bp.route('/')
@rol_requerido(ADMIN_STAFF)
@module_required(MODULE_CRM)
def lista():
    from services.crm_pruebas_service import TOTAL_DIAS, listar
    filtro = request.args.get('f', 'activas')
    if filtro not in dict(FILTROS):
        filtro = 'activas'
    pruebas, conteo = listar(filtro)
    conteo['activas'] = conteo.get('activa', 0) + conteo.get('por_vencer', 0)
    conteo['todas'] = sum(v for k, v in conteo.items() if k not in ('activas', 'todas'))
    return render_template('crm_pruebas.html', datosApp=get_data_app(), pruebas=pruebas,
                           conteo=conteo, filtro=filtro, filtros=FILTROS, total_dias=TOTAL_DIAS,
                           crm_active='pruebas', crm_active_label='Pruebas gratis')
