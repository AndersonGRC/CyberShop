"""
installer_packager.py — Empaqueta el instalador del POS Desktop personalizado por tenant.

Estrategia: una sola plantilla `CyberShopSetup_base.exe` (firmable, no cambia
por cliente) + un `bootstrap.json` corto con los datos del tenant. El asistente
de Inno Setup lee el JSON al lado del setup y pre-llena los campos del wizard.

build_personalized_zip(tenant_id, client_code, request_root) -> bytes
    Retorna el contenido binario de un ZIP listo para descargar:
        CyberShopSetup-<slug>.zip
          ├── CyberShopSetup.exe       <- copia del base, sin modificar
          └── bootstrap.json           <- {server_url, api_key, tenant_slug, tenant_nombre}

La api_key NO viaja en bootstrap.json. En su lugar, se entrega un
"download_token" de un solo uso vinculado al client_code, y el wizard la
canjea por la api_key real al primer arranque (vía /api/v1/sync/exchange-token).
Esto evita exponer el secreto en un archivo plano dentro del ZIP.

(En esta primera versión y por simplicidad, sí va la api_key directa. Cuando
se implemente exchange-token, cambiar build_bootstrap() para entregar token
en su lugar.)
"""

import io
import json
import zipfile
from pathlib import Path

from flask import current_app

from services.db_layer import control_plane_cursor


INSTALLER_FILENAME = 'CyberShopSetup.exe'
BASE_INSTALLER_NAME = 'CyberShopSetup_base.exe'


class InstallerNotBuiltError(Exception):
    """Se lanza cuando el .exe base no existe en static/installers/."""


class ClientCodeNotFoundError(Exception):
    """Se lanza cuando el client_code no existe o está inactivo."""


def installer_base_path():
    """Ruta al .exe base. None si no existe."""
    return Path(current_app.root_path) / 'static' / 'installers' / BASE_INSTALLER_NAME


def resolve_client_code(client_code):
    """Devuelve dict con info del tenant + api_key plana (lookup por client_code).

    NOTA DE SEGURIDAD: la api_key no se almacena en claro en la DB; lo que
    devolvemos aquí es información de lookup que requiere conocer el client_code.
    Para entregar la key real al instalador, el flujo correcto sería que el
    admin la registre en un secret store separado al crearla con
    crear_sync_key.py y este endpoint sirva un download_token.

    En esta versión MVP: el caller debe haber persistido la key en un campo
    cifrado de la tabla, o entregar al cliente la key en otro canal (email)
    y que él la pegue en el wizard. Para no romper el flujo, devolvemos
    api_key=None y el wizard pedirá al usuario pegarla manualmente.
    """
    code = (client_code or '').strip().upper()
    if not code:
        raise ClientCodeNotFoundError('client_code vacío')

    with control_plane_cursor() as cur:
        cur.execute("""
            SELECT k.id, k.tenant_id, k.key_prefix, k.label,
                   t.slug, t.nombre, t.estado
            FROM sync_api_keys k
            JOIN tenants t ON t.id = k.tenant_id
            WHERE k.client_code = %s AND k.active = TRUE
        """, (code,))
        row = cur.fetchone()

    if not row:
        raise ClientCodeNotFoundError(f"client_code '{code}' no encontrado o inactivo")

    if row['estado'] != 'activo':
        raise ClientCodeNotFoundError(f"tenant '{row['slug']}' no está activo")

    return {
        'tenant_id':     row['tenant_id'],
        'tenant_slug':   row['slug'],
        'tenant_nombre': row['nombre'] or row['slug'],
        'key_prefix':    row['key_prefix'],
        'label':         row['label'],
    }


def build_bootstrap(tenant_info, server_url, api_key=None):
    """Construye el dict bootstrap.json que va dentro del ZIP."""
    return {
        'server_url':    server_url.rstrip('/'),
        'api_key':       api_key or '',  # vacío → wizard lo pide manualmente
        'tenant_slug':   tenant_info['tenant_slug'],
        'tenant_nombre': tenant_info['tenant_nombre'],
        'key_prefix':    tenant_info['key_prefix'],
        'note':          (
            'Si api_key está vacío, péguelo en el campo correspondiente del asistente. '
            'Si está completo, el asistente lo usa automáticamente.'
        ),
    }


def build_personalized_zip(tenant_info, server_url, api_key=None):
    """Arma el ZIP en memoria. Retorna (filename, bytes)."""
    base = installer_base_path()
    if not base or not base.exists():
        raise InstallerNotBuiltError(
            f"No existe {base}. Correr CyberShopDesktop\\build_installer.bat primero."
        )

    bootstrap = build_bootstrap(tenant_info, server_url, api_key)
    bootstrap_bytes = json.dumps(bootstrap, ensure_ascii=False, indent=2).encode('utf-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(INSTALLER_FILENAME, base.read_bytes())
        zf.writestr('bootstrap.json', bootstrap_bytes)
        zf.writestr('LEEME.txt', _readme_text(tenant_info, server_url).encode('utf-8'))
    buf.seek(0)
    filename = f"CyberShopSetup-{tenant_info['tenant_slug']}.zip"
    return filename, buf.read()


def _readme_text(tenant_info, server_url):
    return (
        "CyberShop POS Desktop — Instalador personalizado\r\n"
        "================================================\r\n"
        f"Cliente: {tenant_info['tenant_nombre']}\r\n"
        f"Tenant:  {tenant_info['tenant_slug']}\r\n"
        f"Servidor: {server_url}\r\n"
        "\r\n"
        "Instrucciones:\r\n"
        "1. Extraer este ZIP en una carpeta temporal.\r\n"
        "2. Ejecutar CyberShopSetup.exe (mantener bootstrap.json al lado del .exe).\r\n"
        "3. El asistente leerá bootstrap.json y pre-llenará los campos.\r\n"
        "4. Confirmar cada paso con Siguiente y completar la instalación.\r\n"
        "\r\n"
        "Si el campo 'API key' aparece vacío en el asistente, péguelo manualmente\r\n"
        "(su proveedor se la entregó en un canal separado por seguridad).\r\n"
    )
