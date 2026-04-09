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
    from database import get_db_cursor

    MenuApp = [
        {"nombre": "Inicio", "url": "public.index"},
        {"nombre": "Productos", "url": "public.productos"},
        {"nombre": "Servicios", "url": "public.servicios"},
        {"nombre": "¿Quienes Somos?", "url": "public.quienes_somos"},
        {"nombre": "Contactanos", "url": "public.contactenos"},
        {"nombre": "Ingresar", "url": "auth.login"}
    ]

    # Filtrar menu segun config de secciones
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM config_secciones WHERE clave = 'mostrar_modulo_ventas'")
            row = cur.fetchone()
            if row and row['valor'] == 'false':
                MenuApp = [m for m in MenuApp if m['nombre'] != 'Productos']
    except Exception:
        pass

    # Leer nombre de empresa desde cliente_config
    nombre_empresa = 'CyberShop'
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'empresa_nombre'")
            row = cur.fetchone()
            if row and row['valor']:
                nombre_empresa = row['valor']
    except Exception:
        pass

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
    from database import get_db_cursor

    nombre_empresa = 'CyberShop'
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'empresa_nombre'")
            row = cur.fetchone()
            if row and row['valor']:
                nombre_empresa = row['valor']
    except Exception:
        pass

    # Verificar si el módulo de soporte está habilitado
    soporte_habilitado = True
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'soporte_habilitado'")
            row = cur.fetchone()
            if row and row['valor'] == 'false':
                soporte_habilitado = False
    except Exception:
        pass

    # Verificar si el módulo de wishlist está habilitado
    wishlist_habilitado = True
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'wishlist_habilitado'")
            row = cur.fetchone()
            if row and row['valor'] == 'false':
                wishlist_habilitado = False
    except Exception:
        pass

    menu = [
        {"nombre": "Mi Cuenta",    "url": "auth.dashboard_cliente", "icono": "user-circle"},
        {"nombre": "Mis Pedidos",  "url": "auth.mis_pedidos",       "icono": "shopping-bag"},
    ]
    if wishlist_habilitado:
        menu.append({"nombre": "Mis Favoritos", "url": "wishlist.mi_lista_deseos", "icono": "heart"})
    if soporte_habilitado:
        menu.append({"nombre": "Soporte", "url": "soporte.mis_tickets", "icono": "headset"})

    # Verificar si el módulo de videollamadas está habilitado
    video_habilitado = True
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'video_habilitado'")
            row = cur.fetchone()
            if row and row['valor'] == 'false':
                video_habilitado = False
    except Exception:
        pass

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


def get_data_app():
    """Retorna los datos comunes para el panel de administracion.

    Incluye el titulo del sitio y la estructura del menu lateral
    con modulos, submodulos e iconos de Font Awesome.
    """
    App = [
        {"nombre": "Panel Principal", "url": "admin.dashboard_admin", "icono": "home"},
        
        {
            "nombre": "Ventas",
            "url": "#", # Grupo
            "icono": "cash-register",
            "submodulos": [
                {"nombre": "Punto de Venta", "url": "admin.facturacion_pos", "icono": "cash-register"},
                {"nombre": "Historial POS", "url": "admin.historial_pos", "icono": "receipt"},
                {"nombre": "Gestionar Pedidos", "url": "admin.gestion_pedidos", "icono": "truck"},
                {"nombre": "Nueva Cotización", "url": "quotes.cotizar", "icono": "file-invoice-dollar"},
                {"nombre": "Mis Cotizaciones", "url": "quotes.ver_cotizaciones", "icono": "history"},
                {"nombre": "Nueva Cuenta de Cobro", "url": "billing.crear_cuenta", "icono": "file-invoice"},
                {"nombre": "Mis Cuentas de Cobro", "url": "billing.listar_cuentas", "icono": "folder-open"},
                {"nombre": "Cupones", "url": "cupones.gestion_cupones", "icono": "ticket-alt"}
            ]
        },
        {
            "nombre": "Inventario",
            "url": "#", # Grupo
            "icono": "boxes",
            "submodulos": [
                {"nombre": "Resumen / Stock", "url": "admin.gestion_inventario", "icono": "clipboard-list"},
                {"nombre": "Agregar Producto", "url": "admin.GestionProductos", "icono": "plus-circle"},
                {"nombre": "Editar Productos", "url": "admin.editar_productos", "icono": "edit"},
                {"nombre": "Eliminar Productos", "url": "admin.eliminar_productos", "icono": "trash-alt"},
                {"nombre": "Géneros", "url": "admin.gestion_generos", "icono": "tags"},
                {"nombre": "Reseñas", "url": "admin.gestion_resenas", "icono": "star"},
                {"nombre": "Wishlist Stats", "url": "wishlist.wishlist_estadisticas", "icono": "heart"}
            ]
        },
        {
            "nombre": "Contenido Web",
            "url": "#",
            "icono": "newspaper",
            "submodulos": [
                {"nombre": "Publicaciones", "url": "admin.gestion_publicaciones", "icono": "file-alt"},
                {"nombre": "Slides Carrusel", "url": "admin.gestion_slides", "icono": "images"},
                {"nombre": "Servicios", "url": "admin.gestion_servicios", "icono": "concierge-bell"},
            ]
        },
        {
            "nombre": "Usuarios",
            "url": "#",
            "icono": "users",
            "submodulos": [
                {"nombre": "Gestión Usuarios", "url": "admin.gestion_usuarios", "icono": "user-cog"},
                {"nombre": "Crear Usuario", "url": "admin.crear_usuario", "icono": "user-plus"}
            ]
        },
        {
            "nombre": "Empleados",
            "url": "#",
            "icono": "id-card",
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
            "submodulos": [
                {"nombre": "Tickets clientes", "url": "soporte.admin_tickets",     "icono": "ticket-alt"},
                {"nombre": "Configuración",     "url": "soporte.admin_soporte_config", "icono": "sliders-h"},
            ]
        },
        {
            "nombre": "Videollamadas",
            "url": "#",
            "icono": "video",
            "submodulos": [
                {"nombre": "Mis Salas",      "url": "video.admin_video_lista",  "icono": "door-open"},
                {"nombre": "Nueva Sala",     "url": "video.admin_video_crear",  "icono": "plus-circle"},
                {"nombre": "Configuración",  "url": "video.admin_video_config", "icono": "sliders-h"},
            ]
        },
        {
            "nombre": "Configuración",
            "url": "#",
            "icono": "cog",
            "submodulos": [
                {"nombre": "Config. Cliente",   "url": "admin.configuracion_cliente", "icono": "paint-brush"},
                {"nombre": "Config. Secciones", "url": "admin.config_secciones",      "icono": "sliders-h"},
            ]
        },
        {
            "nombre": "Facturación DIAN",
            "url": "admin.facturacion_dian",
            "icono": "file-invoice"
        },
        {"nombre": "Cerrar Sesion", "url": "auth.logout", "icono": "sign-out-alt"}
    ]
    # Leer nombre de empresa desde cliente_config
    nombre_empresa = 'CyberShop'
    try:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT valor FROM cliente_config WHERE clave = 'empresa_nombre'")
            row = cur.fetchone()
            if row and row['valor']:
                nombre_empresa = row['valor']
    except Exception:
        pass

    # El grupo "Configuración" solo es visible para el Super Admin (rol_id = 1)
    try:
        from flask import session as _s
        if _s.get('rol_id') != 1:
            App = [item for item in App if item.get('nombre') != 'Configuración']
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
