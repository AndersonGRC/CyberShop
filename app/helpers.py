"""
helpers.py — Funciones auxiliares compartidas por toda la aplicacion.

Contiene la estructura de menus de navegacion (publico y admin),
formato de moneda colombiana y generacion de codigos de referencia.
"""

import locale
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

    return {
        'titulo': 'CyberShop',
        'MenuAppindex': MenuApp,
        'longMenuAppindex': len(MenuApp)
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
                {"nombre": "Mis Cuentas de Cobro", "url": "billing.listar_cuentas", "icono": "folder-open"}
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
                {"nombre": "Eliminar Productos", "url": "admin.eliminar_productos", "icono": "trash-alt"}
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
                {"nombre": "Config Secciones", "url": "admin.config_secciones", "icono": "sliders-h"}
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
        {"nombre": "Cerrar Sesion", "url": "auth.logout", "icono": "sign-out-alt"}
    ]
    return {
        'titulo': 'CyberShop',
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
