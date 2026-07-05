"""
helpers.py — Funciones auxiliares compartidas por toda la aplicacion.

Contiene la estructura de menus de navegacion (publico y admin),
formato de moneda colombiana y generacion de codigos de referencia.
"""

import locale
import os
import uuid
from datetime import datetime

# Configuracion regional para formato de moneda
try:
    locale.setlocale(locale.LC_ALL, 'es_CO.utf8')
except Exception:
    try:
        locale.setlocale(locale.LC_ALL, '')
    except Exception:
        pass


def get_common_data():
    """Retorna los datos comunes para las paginas publicas.

    Incluye el titulo del sitio y la estructura del menu principal
    con las rutas visibles para visitantes no autenticados.
    Filtra "Productos" si el modulo de ventas esta desactivado.
    """
    from services.public_site_service import get_brand_config, get_public_menu_items

    brand_config = get_brand_config()
    MenuApp = get_public_menu_items(include_login=True)
    nombre_empresa = brand_config.get('empresa_nombre') or 'CyberShop'

    # Si el usuario ya está logueado, quitar "Ingresar" del menú público
    try:
        from flask import session as _s
        if _s.get('usuario_id'):
            MenuApp = [m for m in MenuApp if m.get('url') != 'auth.login']
    except Exception:
        pass

    return {
        'titulo': nombre_empresa,
        'MenuAppindex': MenuApp,
        'longMenuAppindex': len(MenuApp)
    }


def get_data_cliente():
    """Retorna los datos del menú lateral para clientes (rol 3).

    Solo incluye secciones relevantes para el cliente:
    Mi Cuenta, Mis Pedidos, Soporte, Tienda y Cerrar Sesión.
    No expone ninguna opción administrativa.
    """
    from services.public_site_service import get_brand_config

    nombre_empresa = get_brand_config().get('empresa_nombre') or 'CyberShop'

    from tenant_features import MODULE_SUPPORT, MODULE_VIDEO, MODULE_WISHLIST, is_module_active

    soporte_habilitado = is_module_active(MODULE_SUPPORT)
    wishlist_habilitado = is_module_active(MODULE_WISHLIST)

    menu = [
        {"nombre": "Mi Cuenta",    "url": "auth.dashboard_cliente", "icono": "user-circle"},
        {"nombre": "Mis Pedidos",  "url": "auth.mis_pedidos",       "icono": "shopping-bag"},
    ]
    if wishlist_habilitado:
        menu.append({"nombre": "Mis Favoritos", "url": "wishlist.mi_lista_deseos", "icono": "heart"})
    if soporte_habilitado:
        menu.append({"nombre": "Soporte", "url": "soporte.mis_tickets", "icono": "headset"})

    video_habilitado = is_module_active(MODULE_VIDEO)

    if video_habilitado:
        menu.append({"nombre": "Videollamadas", "url": "video.mis_videollamadas", "icono": "video"})

    menu += [
        {"nombre": "Tienda",            "url": "public.productos",       "icono": "store"},
        {"nombre": "Cerrar Sesión",     "url": "auth.logout",            "icono": "sign-out-alt"},
    ]

    return {
        'titulo': nombre_empresa,
        'MenuAppindex': menu,
        'longMenuAppindex': len(menu),
    }


def get_data_restaurant_operator(can_view_reports=False):
    """Menú reducido para roles operativos del restaurante."""
    from services.public_site_service import get_brand_config

    nombre_empresa = get_brand_config().get('empresa_nombre') or 'CyberShop'

    menu = [
        {"nombre": "Panel Restaurante", "url": "restaurant_tables.waiter_panel", "icono": "utensils"},
        {"nombre": "Atender Mesas", "url": "restaurant_tables.restaurant_tables_service", "icono": "concierge-bell"},
        {"nombre": "Punto de Venta", "url": "admin.facturacion_pos", "icono": "cash-register"},
        {"nombre": "Historial POS", "url": "admin.historial_pos", "icono": "receipt"},
        {"nombre": "Inventario", "url": "admin.gestion_inventario", "icono": "boxes"},
        {"nombre": "Agregar Producto", "url": "admin.GestionProductos", "icono": "plus-circle"},
        {"nombre": "Editar Productos", "url": "admin.editar_productos", "icono": "edit"},
        {"nombre": "Géneros", "url": "admin.gestion_generos", "icono": "tags"},
    ]

    if can_view_reports:
        menu.append({"nombre": "Ventas", "url": "restaurant_tables.restaurant_tables_reports", "icono": "chart-bar"})

    menu.append({"nombre": "Cerrar Sesion", "url": "auth.logout", "icono": "sign-out-alt"})

    return {
        'titulo': nombre_empresa,
        'MenuAppindex': menu,
        'longMenuAppindex': len(menu),
    }


def _modulo_software_on():
    """El gestor de Planes de Software solo aparece si el sitio tiene activo
    el modulo Software POS (apagado por defecto)."""
    try:
        from services.public_site_service import is_public_section_enabled
        return is_public_section_enabled('mostrar_modulo_software', False)
    except Exception:
        return False


def get_data_app():
    """Retorna los datos comunes para el panel de administracion.

    Incluye el titulo del sitio y la estructura del menu lateral
    con modulos, submodulos e iconos de Font Awesome.
    """
    from flask import session as _s

    from security import (
        ADMIN_CONTADOR,
        ADMIN_FULL,
        ADMIN_STAFF,
        CATALOG_DELETE,
        CATALOG_OPERATIONAL,
        POS_OPERATIONAL,
        ROL_CAJERO,
        ROL_CONTADOR,
        ROL_MESERO,
        ROL_SUPER_ADMIN,
    )

    # Espejo de los grupos de restaurant_tables.py (no importables sin ciclo):
    # quién puede atender mesas vs quién administra plano/reportes.
    RESTAURANT_SERVICE = ADMIN_STAFF + [ROL_CONTADOR, ROL_MESERO, ROL_CAJERO]
    RESTAURANT_ADMIN = ADMIN_STAFF + [ROL_CONTADOR]
    from tenant_features import (
        MODULE_ACCOUNTING,
        MODULE_BILLING,
        MODULE_CONTENT,
        MODULE_COUPONS,
        MODULE_CRM,
        MODULE_FACTURACION_ELECTRONICA,
        MODULE_INVENTORY,
        MODULE_ORDERS,
        MODULE_PAYROLL,
        MODULE_POS,
        MODULE_QUOTES,
        MODULE_RESTAURANT_TABLES,
        MODULE_SHARE,
        MODULE_SUPPORT,
        MODULE_USERS,
        MODULE_VIDEO,
        MODULE_WISHLIST,
        MODULE_AI,
        MODULE_CAJA,
        get_active_module_codes,
    )

    active_modules = get_active_module_codes()
    rol_actual = _s.get('rol_id')

    # Regla de visibilidad: cada ítem lleva 'roles' = ESPEJO EXACTO del
    # @rol_requerido de su ruta destino. Así el menú nunca muestra módulos que
    # el rol no puede abrir (nada de "No tienes permiso" al hacer clic).
    # El gate por plan/licencia sigue siendo module_code (rol ∩ plan).
    App = [
        {"nombre": "Panel Principal", "url": "admin.dashboard_admin", "icono": "home", "roles": ADMIN_STAFF},

        {
            "nombre": "Ventas",
            "url": "#", # Grupo
            "icono": "cash-register",
            "submodulos": [
                {"nombre": "Punto de Venta", "url": "admin.facturacion_pos", "icono": "cash-register", "module_code": MODULE_POS, "permiso": ("pos", "ver")},
                {"nombre": "Caja / Arqueo", "url": "caja.caja_estado", "icono": "coins", "module_code": MODULE_CAJA, "permiso": ("caja", "ver")},
                {"nombre": "Historial POS", "url": "admin.historial_pos", "icono": "receipt", "module_code": MODULE_POS, "permiso": ("pos", "ver")},
                {"nombre": "Gestionar Pedidos", "url": "admin.gestion_pedidos", "icono": "truck", "module_code": MODULE_ORDERS, "permiso": ("orders", "ver")},
                {"nombre": "Nueva Cotización", "url": "quotes.cotizar", "icono": "file-invoice-dollar", "module_code": MODULE_QUOTES, "permiso": ("quotes", "operar")},
                {"nombre": "Mis Cotizaciones", "url": "quotes.ver_cotizaciones", "icono": "history", "module_code": MODULE_QUOTES, "permiso": ("quotes", "ver")},
                {"nombre": "Nueva Cuenta de Cobro", "url": "billing.crear_cuenta", "icono": "file-invoice", "module_code": MODULE_BILLING, "permiso": ("billing", "operar")},
                {"nombre": "Mis Cuentas de Cobro", "url": "billing.listar_cuentas", "icono": "folder-open", "module_code": MODULE_BILLING, "permiso": ("billing", "ver")},
                {"nombre": "Cupones", "url": "cupones.gestion_cupones", "icono": "ticket-alt", "module_code": MODULE_COUPONS, "permiso": ("coupons", "ver")}
            ]
        },
        {
            "nombre": "Inventario",
            "url": "#", # Grupo
            "icono": "boxes",
            "module_code": MODULE_INVENTORY,
            "submodulos": [
                {"nombre": "Resumen / Stock", "url": "admin.gestion_inventario", "icono": "clipboard-list", "permiso": ("inventory", "ver")},
                {"nombre": "Agregar Producto", "url": "admin.GestionProductos", "icono": "plus-circle", "permiso": ("inventory", "operar")},
                {"nombre": "Editar Productos", "url": "admin.editar_productos", "icono": "edit", "permiso": ("inventory", "operar")},
                {"nombre": "Eliminar Productos", "url": "admin.eliminar_productos", "icono": "trash-alt", "permiso": ("inventory", "eliminar")},
                {"nombre": "Géneros", "url": "admin.gestion_generos", "icono": "tags", "permiso": ("inventory", "operar")},
                {"nombre": "Reseñas", "url": "admin.gestion_resenas", "icono": "star", "roles": ADMIN_STAFF},
                {"nombre": "Wishlist Stats", "url": "wishlist.wishlist_estadisticas", "icono": "heart", "module_code": MODULE_WISHLIST, "permiso": ("wishlist", "ver")}
            ]
        },
        {
            "nombre": "Contenido Web",
            "url": "#",
            "icono": "newspaper",
            "module_code": MODULE_CONTENT,
            "submodulos": [
                {"nombre": "Publicaciones", "url": "admin.gestion_publicaciones", "icono": "newspaper", "permiso": ("content", "ver")},
                {"nombre": "Slides", "url": "admin.gestion_slides", "icono": "images", "permiso": ("content", "ver")},
                {"nombre": "Servicios", "url": "admin.gestion_servicios", "icono": "concierge-bell", "permiso": ("content", "ver")},
            ] + ([
                {"nombre": "Planes de Software", "url": "admin.software_planes", "icono": "layer-group", "roles": [ROL_SUPER_ADMIN]},
            ] if _modulo_software_on() else [])
        },
        {
            "nombre": "Usuarios",
            "url": "#",
            "icono": "users",
            "module_code": MODULE_USERS,
            "submodulos": [
                {"nombre": "Gestión Usuarios", "url": "admin.gestion_usuarios", "icono": "user-cog", "permiso": ("users", "ver")},
                {"nombre": "Crear Usuario", "url": "admin.crear_usuario", "icono": "user-plus", "permiso": ("users", "operar")},
                # Solo Admin/Propietario: el dueño configura qué ve/hace cada rol
                {"nombre": "Roles y Permisos", "url": "roles_permisos.pagina", "icono": "user-shield", "roles": ADMIN_FULL}
            ]
        },
        {
            "nombre": "Empleados",
            "url": "#",
            "icono": "id-card",
            "module_code": MODULE_PAYROLL,
            # PII/salarios: solo Admin y Contador (espejo del guard de nomina.py
            # y del manifiesto desktop).
            "submodulos": [
                {"nombre": "Dashboard Nomina", "url": "nomina.nomina_dashboard", "icono": "chart-line", "permiso": ("payroll", "ver")},
                {"nombre": "Empleados", "url": "nomina.empleados_lista", "icono": "users", "permiso": ("payroll", "ver")},
                {"nombre": "Contratistas", "url": "nomina.contratistas_lista", "icono": "user-tie", "permiso": ("payroll", "ver")},
                {"nombre": "Periodos Nomina", "url": "nomina.periodos_lista", "icono": "calendar-alt", "permiso": ("payroll", "ver")},
                {"nombre": "Novedades", "url": "nomina.novedades_lista", "icono": "clipboard-list", "permiso": ("payroll", "ver")},
                {"nombre": "Liquidaciones", "url": "nomina.liquidaciones_lista", "icono": "file-invoice-dollar", "permiso": ("payroll", "ver")},
                {"nombre": "Parametros", "url": "nomina.parametros_lista", "icono": "cogs", "permiso": ("payroll", "ver")}
            ]
        },
        {
            "nombre": "CRM",
            "url": "#",
            "icono": "address-book",
            "module_code": MODULE_CRM,
            "submodulos": [
                {"nombre": "Dashboard CRM",  "url": "crm.crm_dashboard",      "icono": "chart-pie", "permiso": ("crm", "ver")},
                {"nombre": "Contactos",      "url": "crm.crm_contactos_lista", "icono": "address-card", "permiso": ("crm", "ver")},
                {"nombre": "Tareas",         "url": "crm.crm_tareas_lista",    "icono": "tasks", "permiso": ("crm", "ver")},
            ]
        },
        {
            "nombre": "Contabilidad",
            "url": "#",
            "icono": "chart-line",
            "module_code": MODULE_ACCOUNTING,
            "submodulos": [
                {"nombre": "Dashboard",    "url": "contabilidad.dashboard",    "icono": "tachometer-alt", "permiso": ("accounting", "ver")},
                {"nombre": "Movimientos",  "url": "contabilidad.movimientos",  "icono": "exchange-alt", "permiso": ("accounting", "ver")},
                {"nombre": "Plantillas",   "url": "contabilidad.plantillas",   "icono": "clone", "permiso": ("accounting", "ver")},
                {"nombre": "Cierres",      "url": "contabilidad.cierres",      "icono": "flag-checkered", "permiso": ("accounting", "ver")},
            ]
        },
        {
            "nombre": "Soporte",
            "url": "#",
            "icono": "headset",
            "module_code": MODULE_SUPPORT,
            "submodulos": [
                {"nombre": "Tickets clientes", "url": "soporte.admin_tickets",     "icono": "ticket-alt", "permiso": ("support", "ver")},
                {"nombre": "Configuración",     "url": "soporte.admin_soporte_config", "icono": "sliders-h", "permiso": ("support", "ver")},
            ]
        },
        {
            "nombre": "Compartir Archivos",
            "url": "#",
            "icono": "share-alt",
            "module_code": MODULE_SHARE,
            "submodulos": [
                {"nombre": "Carpetas",      "url": "share.gestion_carpetas", "icono": "folder-open", "permiso": ("share", "ver")},
                {"nombre": "Nueva Carpeta", "url": "share.crear_carpeta",    "icono": "folder-plus", "permiso": ("share", "operar")},
            ]
        },
        {
            "nombre": "Asistente IA",
            "url": "ia.panel",
            "icono": "robot",
            "module_code": MODULE_AI,
            "permiso": ("ai_assistant", "ver"),
        },
        {
            "nombre": "Videollamadas",
            "url": "#",
            "icono": "video",
            "module_code": MODULE_VIDEO,
            "submodulos": [
                {"nombre": "Mis Salas",      "url": "video.admin_video_lista",  "icono": "door-open", "permiso": ("video", "ver")},
                {"nombre": "Nueva Sala",     "url": "video.admin_video_crear",  "icono": "plus-circle", "permiso": ("video", "operar")},
                {"nombre": "Configuración",  "url": "video.admin_video_config", "icono": "sliders-h", "permiso": ("video", "operar")},
            ]
        },
        {
            "nombre": "Restaurante",
            "url": "#",
            "icono": "utensils",
            "module_code": MODULE_RESTAURANT_TABLES,
            "submodulos": [
                {"nombre": "Atención de Mesas", "url": "restaurant_tables.restaurant_tables_dashboard", "icono": "concierge-bell", "permiso": ("restaurant_tables", "ver")},
                {"nombre": "Construcción de Plano", "url": "restaurant_tables.restaurant_tables_builder", "icono": "drafting-compass", "roles": RESTAURANT_ADMIN},
                {"nombre": "Reportes de Mesas", "url": "restaurant_tables.restaurant_tables_reports", "icono": "chart-bar", "roles": RESTAURANT_ADMIN},
            ]
        },
        {
            "nombre": "Configuración",
            "url": "#",
            "icono": "cog",
            "submodulos": [
                {"nombre": "Config. Cliente",   "url": "admin.configuracion_cliente", "icono": "paint-brush", "roles": [ROL_SUPER_ADMIN]},
                {"nombre": "Claves API Sync",   "url": "admin.sync_keys",             "icono": "key", "roles": [ROL_SUPER_ADMIN]},
                {"nombre": "Módulos SaaS",      "url": "restaurant_tables.saas_modules_admin", "icono": "toggle-on", "roles": [ROL_SUPER_ADMIN]},
            ]
        },
        {
            "nombre": "Facturación DIAN",
            "url": "admin.facturacion_dian",
            "icono": "file-invoice",
            "module_code": MODULE_FACTURACION_ELECTRONICA,
            "permiso": ("facturacion_electronica", "ver"),
        },
        {"nombre": "Mi Negocio", "url": "admin.mi_negocio", "icono": "store", "roles": ADMIN_FULL},
        {"nombre": "Cerrar Sesion", "url": "auth.logout", "icono": "sign-out-alt"}
    ]
    from services.public_site_service import get_brand_config

    nombre_empresa = get_brand_config().get('empresa_nombre') or 'CyberShop'

    try:
        # Visibilidad por ítem: 'permiso' = matriz DINÁMICA configurable por el
        # Propietario (services/permisos_service); 'roles' = gate estático
        # legacy (ítems sin módulo: Panel, Mi Negocio, Config SuperAdmin);
        # sin ambos = siempre visible (Cerrar Sesión).
        from services.permisos_service import tiene_permiso as _tp

        def _visible(entry):
            perm = entry.get('permiso')
            if perm:
                return _tp(rol_actual, perm[0], perm[1])
            if entry.get('roles'):
                return rol_actual in entry['roles']
            return True

        filtered_app = []
        for item in App:
            group_module = item.get('module_code')
            if group_module and group_module not in active_modules:
                continue
            if not _visible(item):
                continue

            item_copy = dict(item)
            submodulos = item_copy.get('submodulos')
            if submodulos is not None:
                item_copy['submodulos'] = [
                    dict(sub)
                    for sub in submodulos
                    if (not sub.get('module_code') or sub['module_code'] in active_modules)
                    and _visible(sub)
                ]
                if not item_copy['submodulos']:
                    continue

            filtered_app.append(item_copy)

        App = filtered_app
        # Nota: el antiguo recorte hard-coded para Mesero(6)/Cajero(7) se
        # eliminó — la clave 'roles' de cada ítem (espejo de @rol_requerido)
        # cubre todos los roles de forma uniforme.
    except Exception:
        pass

    return {
        'titulo': nombre_empresa,
        'MenuAppindex': App,
        'longMenuAppindex': len(App)
    }


def formatear_moneda(valor):
    """Formatea un valor numerico como moneda colombiana (COP).

    Intenta usar ``locale.currency``; si falla, aplica formato manual.
    """
    try:
        return locale.currency(valor, symbol=True, grouping=True)
    except Exception:
        return f"${valor:,.2f}"


def generar_reference_code():
    """Genera un codigo de referencia unico para pedidos.

    Formato: ``CYBERSHOP-YYYYMMDD-XXXXXX`` donde XXXXXX son
    6 caracteres hexadecimales aleatorios en mayuscula.
    """
    fecha = datetime.now().strftime("%Y%m%d")
    random_code = uuid.uuid4().hex[:6].upper()
    return f"CYBERSHOP-{fecha}-{random_code}"


# --- Utilidades PDF compartidas (quotes.py y billing.py) ---

def pdf_link_callback(uri, rel):
    """Resuelve URLs a rutas locales absolutas para xhtml2pdf.
    Evita peticiones HTTP durante la generacion del PDF."""
    from flask import current_app as _app
    if uri.startswith('file://'):
        return uri[7:]
    if 'static/' in uri:
        try:
            after_static = uri.split('static/')[-1].split('?')[0]
            local = os.path.join(_app.root_path, 'static', after_static)
            if os.path.isfile(local):
                return local
        except Exception:
            pass
    return uri


def logo_local_path(root_path):
    """Resuelve la ruta absoluta del logo por defecto.
    Prueba Logo.png primero, luego Logo.PNG como fallback."""
    for nombre in ('Logo.png', 'Logo.PNG'):
        path = os.path.join(root_path, 'static', 'img', nombre)
        if os.path.isfile(path):
            return path
    return os.path.join(root_path, 'static', 'img', 'Logo.png')
