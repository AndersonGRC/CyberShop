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
    """
    MenuApp = [
        {"nombre": "Inicio", "url": "public.index"},
        {"nombre": "Productos", "url": "public.productos"},
        {"nombre": "Servicios", "url": "public.servicios"},
        {"nombre": "¿Quienes Somos?", "url": "public.quienes_somos"},
        {"nombre": "Contactanos", "url": "public.contactenos"},
        {"nombre": "Ingresar", "url": "auth.login"}
    ]
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
        {"nombre": "Menu Principal", "url": "admin.dashboard_admin", "icono": "home"},
        {"nombre": "Dashboard", "url": "admin.dashboard_admin", "icono": "chart-line"},
        {
            "nombre": "Gestion Productos",
            "url": "admin.GestionProductos",
            "icono": "box",
            "submodulos": [
                {"nombre": "Agregar Producto", "url": "admin.GestionProductos", "icono": "plus"},
                {"nombre": "Editar Producto", "url": "admin.editar_productos", "icono": "edit"},
                {"nombre": "Eliminar Producto", "url": "admin.eliminar_productos", "icono": "trash"}
            ]
        },
        {
            "nombre": "Gestion Usuarios",
            "url": "admin.gestion_usuarios",
            "icono": "users",
            "submodulos": [
                {"nombre": "Lista de Usuarios", "url": "admin.gestion_usuarios", "icono": "list"},
            ]
        },
        {
            "nombre": "Gestión de Pedidos",
            "url": "admin.gestion_pedidos",
            "icono": "truck",
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
