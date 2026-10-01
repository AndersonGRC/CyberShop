"""Cliente HTTP de la API interna del maestro (CyberShopAdmin).

El maestro corre en el MISMO servidor (127.0.0.1:5002, detrás de nginx con
allow-list para humanos; esta API interna solo es alcanzable desde localhost).
Autenticación: header X-Internal-Key con el secreto compartido INTERNAL_API_KEY
(presente en el env de ambas apps).
"""

import requests

from config import Config


class MasterError(Exception):
    """Error reportado por el maestro (mensaje apto para mostrar al usuario)."""


def _headers():
    key = (getattr(Config, 'INTERNAL_API_KEY', '') or '').strip()
    if not key:
        raise MasterError('Venta automática no configurada (falta INTERNAL_API_KEY).')
    return {'X-Internal-Key': key}


def _base():
    return (getattr(Config, 'MASTER_INTERNAL_URL', '') or 'http://127.0.0.1:5002').rstrip('/')


def crear_tenant_en_maestro(slug, nombre, email, master_plan):
    """Pide al maestro crear el cliente completo (BD + seed + instancia +
    dominio + SSL + módulos del plan). Tarda 30-90s por el SSL: llamar
    SIEMPRE desde un hilo, nunca en el request del usuario.

    Devuelve el dict del maestro: {tenant_id, domain, admin_email,
    admin_password, client_code, port, ...}. Lanza MasterError con mensaje
    claro (ej. slug ocupado)."""
    try:
        r = requests.post(
            f"{_base()}/internal/api/v1/tenants/create",
            json={'slug': slug, 'nombre': nombre, 'email': email, 'plan': master_plan},
            headers=_headers(),
            timeout=300,
        )
    except requests.RequestException as exc:
        raise MasterError(f'No se pudo contactar el servicio de creación: {exc}')
    if r.status_code == 201:
        return r.json()
    try:
        detalle = r.json().get('error', r.text)
    except Exception:
        detalle = r.text
    raise MasterError(detalle or f'Error {r.status_code} del maestro')


def _accion_tenant(tenant_id, accion):
    try:
        r = requests.post(
            f"{_base()}/internal/api/v1/tenants/{tenant_id}/{accion}",
            headers=_headers(),
            timeout=120,
        )
    except requests.RequestException as exc:
        raise MasterError(f'No se pudo contactar el maestro: {exc}')
    if r.status_code != 200:
        try:
            detalle = r.json().get('error', r.text)
        except Exception:
            detalle = r.text
        raise MasterError(detalle or f'Error {r.status_code}')
    return True


def suspender_tenant(tenant_id):
    """Suspende la instancia del cliente (no-pago). Reversible."""
    return _accion_tenant(tenant_id, 'suspend')


def reactivar_tenant(tenant_id):
    """Reactiva la instancia del cliente (renovación pagada)."""
    return _accion_tenant(tenant_id, 'reactivate')


def slug_disponible(slug):
    """¿Se puede crear un cliente con este subdominio? Solo lectura.
    Devuelve (disponible: bool|None, motivo). None = no se pudo consultar
    (el registro sigue; el maestro lo vuelve a validar al crear)."""
    try:
        r = requests.get(f"{_base()}/internal/api/v1/tenants/slug-disponible",
                         params={'slug': slug}, headers=_headers(), timeout=(1.5, 4))
        if r.status_code != 200:
            return None, ''
        data = r.json()
        return bool(data.get('disponible')), data.get('motivo') or ''
    except (requests.RequestException, ValueError, MasterError):
        return None, ''


def modo_prueba(tenant_id, activo=True):
    """Prueba gratis: apaga (activo) o devuelve las integraciones externas de
    la tienda (pagos, Google, Meta, DIAN). Lanza MasterError si falla."""
    try:
        r = requests.post(f"{_base()}/internal/api/v1/tenants/{tenant_id}/modo-prueba",
                          json={'activo': bool(activo)}, headers=_headers(), timeout=120)
    except requests.RequestException as exc:
        raise MasterError(f'No se pudo contactar el maestro: {exc}')
    if r.status_code != 200:
        try:
            detalle = r.json().get('error', r.text)
        except Exception:
            detalle = r.text
        raise MasterError(detalle or f'Error {r.status_code}')
    return r.json()
