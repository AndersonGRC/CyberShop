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


def get_data_app():
    """Retorna los datos comunes para el panel de administracion.

    Incluye el titulo del sitio y la estructura del menu lateral
    con modulos, submodulos e iconos de Font Awesome.
    """
    from flask import session as _s

    from security import ADMIN_STAFF, ROL_SUPER_ADMIN
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
        get_active_module_codes,
    )

    active_modules = get_active_module_codes()
    rol_actual = _s.get('rol_id')

    App = [
        {"nombre": "Panel Principal", "url": "admin.dashboard_admin", "icono": "home"},
        
        {
            "nombre": "Ventas",
            "url": "#", # Grupo
            "icono": "cash-register",
            "submodulos": [
                {"nombre": "Punto de Venta", "url": "admin.facturacion_pos", "icono": "cash-register", "module_code": MODULE_POS},
                {"nombre": "Historial POS", "url": "admin.historial_pos", "icono": "receipt", "module_code": MODULE_POS},
                {"nombre": "Gestionar Pedidos", "url": "admin.gestion_pedidos", "icono": "truck", "module_code": MODULE_ORDERS},
                {"nombre": "Nueva Cotización", "url": "quotes.cotizar", "icono": "file-invoice-dollar", "module_code": MODULE_QUOTES},
                {"nombre": "Mis Cotizaciones", "url": "quotes.ver_cotizaciones", "icono": "history", "module_code": MODULE_QUOTES},
                {"nombre": "Nueva Cuenta de Cobro", "url": "billing.crear_cuenta", "icono": "file-invoice", "module_code": MODULE_BILLING},
                {"nombre": "Mis Cuentas de Cobro", "url": "billing.listar_cuentas", "icono": "folder-open", "module_code": MODULE_BILLING},
                {"nombre": "Cupones", "url": "cupones.gestion_cupones", "icono": "ticket-alt", "module_code": MODULE_COUPONS}
            ]
        },
        {
            "nombre": "Inventario",
            "url": "#", # Grupo
            "icono": "boxes",
            "module_code": MODULE_INVENTORY,
            "submodulos": [
                {"nombre": "Resumen / Stock", "url": "admin.gestion_inventario", "icono": "clipboard-list"},
                {"nombre": "Agregar Producto", "url": "admin.GestionProductos", "icono": "plus-circle"},
                {"nombre": "Editar Productos", "url": "admin.editar_productos", "icono": "edit"},
                {"nombre": "Eliminar Productos", "url": "admin.eliminar_productos", "icono": "trash-alt"},
                {"nombre": "Géneros", "url": "admin.gestion_generos", "icono": "tags"},
                {"nombre": "Reseñas", "url": "admin.gestion_resenas", "icono": "star"},
                {"nombre": "Wishlist Stats", "url": "wishlist.wishlist_estadisticas", "icono": "heart", "module_code": MODULE_WISHLIST}
            ]
        },
        {
            "nombre": "Contenido Web",
            "url": "#",
            "icono": "newspaper",
            "module_code": MODULE_CONTENT,
            "submodulos": [
                {"nombre": "Publicaciones", "url": "admin.gestion_publicaciones", "icono": "newspaper", "roles": ADMIN_STAFF},
                {"nombre": "Slides", "url": "admin.gestion_slides", "icono": "images", "roles": ADMIN_STAFF},
                {"nombre": "Servicios", "url": "admin.gestion_servicios", "icono": "concierge-bell", "roles": ADMIN_STAFF},
                {"nombre": "Sitio Público", "url": "admin.sitio_publico", "icono": "paint-brush", "roles": [ROL_SUPER_ADMIN]},
            ]
        },
        {
            "nombre": "Usuarios",
            "url": "#",
            "icono": "users",
            "module_code": MODULE_USERS,
            "submodulos": [
                {"nombre": "Gestión Usuarios", "url": "admin.gestion_usuarios", "icono": "user-cog"},
                {"nombre": "Crear Usuario", "url": "admin.crear_usuario", "icono": "user-plus"}
            ]
        },
        {
            "nombre": "Empleados",
            "url": "#",
            "icono": "id-card",
            "module_code": MODULE_PAYROLL,
            "submodulos": [
                {"nombre": "Dashboard Nomina", "url": "nomina.nomina_dashboard", "icono": "chart-line"},
                {"nombre": "Empleados", "url": "nomina.empleados_lista", "icono": "users"},
                {"nombre": "Contratistas", "url": "nomina.contratistas_lista", "icono": "user-tie"},
                {"nombre": "Periodos Nomina", "url": "nomina.periodos_lista", "icono": "calendar-alt"},
                {"nombre": "Novedades", "url": "nomina.novedades_lista", "icono": "clipboard-list"},
                {"nombre": "Liquidaciones", "url": "nomina.liquidaciones_lista", "icono": "file-invoice-dollar"},
                {"nombre": "Parametros", "url": "nomina.parametros_lista", "icono": "cogs"}
            ]
        },
        {
            "nombre": "CRM",
            "url": "#",
            "icono": "address-book",
            "module_code": MODULE_CRM,
            "submodulos": [
                {"nombre": "Dashboard CRM",  "url": "crm.crm_dashboard",      "icono": "chart-pie"},
                {"nombre": "Contactos",      "url": "crm.crm_contactos_lista", "icono": "address-card"},
                {"nombre": "Tareas",         "url": "crm.crm_tareas_lista",    "icono": "tasks"},
            ]
        },
        {
            "nombre": "Contabilidad",
            "url": "#",
            "icono": "chart-line",
            "module_code": MODULE_ACCOUNTING,
            "submodulos": [
                {"nombre": "Dashboard",    "url": "contabilidad.dashboard",    "icono": "tachometer-alt"},
                {"nombre": "Movimientos",  "url": "contabilidad.movimientos",  "icono": "exchange-alt"},
                {"nombre": "Plantillas",   "url": "contabilidad.plantillas",   "icono": "clone"},
                {"nombre": "Cierres",      "url": "contabilidad.cierres",      "icono": "flag-checkered"},
            ]
        },
        {
            "nombre": "Soporte",
            "url": "#",
            "icono": "headset",
            "module_code": MODULE_SUPPORT,
            "submodulos": [
                {"nombre": "Tickets clientes", "url": "soporte.admin_tickets",     "icono": "ticket-alt"},
                {"nombre": "Configuración",     "url": "soporte.admin_soporte_config", "icono": "sliders-h"},
            ]
        },
        {
            "nombre": "Compartir Archivos",
            "url": "#",
            "icono": "share-alt",
            "module_code": MODULE_SHARE,
            "submodulos": [
                {"nombre": "Carpetas",      "url": "share.gestion_carpetas", "icono": "folder-open"},
                {"nombre": "Nueva Carpeta", "url": "share.crear_carpeta",    "icono": "folder-plus"},
            ]
        },
        {
            "nombre": "Videollamadas",
            "url": "#",
            "icono": "video",
            "module_code": MODULE_VIDEO,
            "submodulos": [
                {"nombre": "Mis Salas",      "url": "video.admin_video_lista",  "icono": "door-open"},
                {"nombre": "Nueva Sala",     "url": "video.admin_video_crear",  "icono": "plus-circle"},
                {"nombre": "Configuración",  "url": "video.admin_video_config", "icono": "sliders-h"},
            ]
        },
        {
            "nombre": "Restaurante",
            "url": "#",
            "icono": "utensils",
            "module_code": MODULE_RESTAURANT_TABLES,
            "submodulos": [
                {"nombre": "Atención de Mesas", "url": "restaurant_tables.restaurant_tables_dashboard", "icono": "concierge-bell"},
                {"nombre": "Construcción de Plano", "url": "restaurant_tables.restaurant_tables_builder", "icono": "drafting-compass"},
                {"nombre": "Reportes de Mesas", "url": "restaurant_tables.restaurant_tables_reports", "icono": "chart-bar"},
            ]
        },
        {
            "nombre": "Configuración",
            "url": "#",
            "icono": "cog",
            "submodulos": [
                {"nombre": "Config. Cliente",   "url": "admin.configuracion_cliente", "icono": "paint-brush", "roles": [ROL_SUPER_ADMIN]},
                {"nombre": "Config. Secciones", "url": "admin.config_secciones",      "icono": "sliders-h", "roles": [ROL_SUPER_ADMIN]},
                {"nombre": "Módulos SaaS",      "url": "restaurant_tables.saas_modules_admin", "icono": "toggle-on", "roles": [ROL_SUPER_ADMIN]},
            ]
        },
        {
            "nombre": "Facturación DIAN",
            "url": "admin.facturacion_dian",
            "icono": "file-invoice",
            "module_code": MODULE_FACTURACION_ELECTRONICA
        },
        {"nombre": "Cerrar Sesion", "url": "auth.logout", "icono": "sign-out-alt"}
    ]
    from services.public_site_service import get_brand_config

    nombre_empresa = get_brand_config().get('empresa_nombre') or 'CyberShop'

    try:
        filtered_app = []
        for item in App:
            group_module = item.get('module_code')
            if group_module and group_module not in active_modules:
                continue
            if item.get('roles') and rol_actual not in item['roles']:
                continue

            item_copy = dict(item)
            submodulos = item_copy.get('submodulos')
            if submodulos is not None:
                item_copy['submodulos'] = [
                    dict(sub)
                    for sub in submodulos
                    if (not sub.get('module_code') or sub['module_code'] in active_modules)
                    and (not sub.get('roles') or rol_actual in sub['roles'])
                ]
                if not item_copy['submodulos']:
                    continue

            filtered_app.append(item_copy)

        App = filtered_app

        # Mesero (6) y Cajero (7): solo ven Restaurante y Cerrar Sesión
        if rol_actual in (6, 7):
            App = [item for item in App if item.get('nombre') in ('Restaurante', 'Ventas', 'Inventario', 'Cerrar Sesion')]
            if rol_actual == 6:
                for grupo in App:
                    if grupo.get('nombre') == 'Restaurante':
                        grupo['submodulos'] = [
                            sub for sub in grupo.get('submodulos', [])
                            if sub.get('url') == 'restaurant_tables.restaurant_tables_dashboard'
                        ]
                    elif grupo.get('nombre') == 'Ventas':
                        grupo['submodulos'] = [
                            sub for sub in grupo.get('submodulos', [])
                            if sub.get('url') in ('admin.facturacion_pos', 'admin.historial_pos')
                        ]
                    elif grupo.get('nombre') == 'Inventario':
                        grupo['submodulos'] = [
                            sub for sub in grupo.get('submodulos', [])
                            if sub.get('url') in (
                                'admin.gestion_inventario',
                                'admin.GestionProductos',
                                'admin.editar_productos',
                                'admin.gestion_generos',
                            )
                        ]
                App = [item for item in App if item.get('nombre') != 'Restaurante' or item.get('submodulos')]
                App = [item for item in App if item.get('nombre') != 'Ventas' or item.get('submodulos')]
                App = [item for item in App if item.get('nombre') != 'Inventario' or item.get('submodulos')]
            elif rol_actual == 7:
                for grupo in App:
                    if grupo.get('nombre') == 'Ventas':
                        grupo['submodulos'] = [
                            sub for sub in grupo.get('submodulos', [])
                            if sub.get('url') in ('admin.facturacion_pos', 'admin.historial_pos')
                        ]
                    elif grupo.get('nombre') == 'Inventario':
                        grupo['submodulos'] = [
                            sub for sub in grupo.get('submodulos', [])
                            if sub.get('url') in (
                                'admin.gestion_inventario',
                                'admin.GestionProductos',
                                'admin.editar_productos',
                                'admin.gestion_generos',
                            )
                        ]
                App = [item for item in App if item.get('nombre') != 'Restaurante' or item.get('submodulos')]
                App = [item for item in App if item.get('nombre') != 'Inventario' or item.get('submodulos')]
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
