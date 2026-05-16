"""
crear_sync_key.py — Emite una nueva API key de sincronización para un tenant.

La key se imprime una sola vez en stdout y nunca se persiste en claro: solo
su SHA-256 hash queda en saas_control_plane.sync_api_keys.

Uso:
    python tools/crear_sync_key.py --tenant-slug cyber-t001 --label "POS Tienda Centro"

Salida:
    Tenant:        cyber-t001 (Cliente XYZ)
    Client code:   CYB-A3F2K9P1     <- entregar al cliente para /descargar
    API key:       cyb_live_a3f2k9p1xyz...   <- guardar en lugar seguro, no se vuelve a mostrar

La key real solo se entrega al cliente vía el bootstrap.json del instalador
(generado en /descargar) — el admin que corre este script no necesita pegarla
en ningún lado, basta el client code para el portal público.
"""

import argparse
import hashlib
import secrets
import sys
from pathlib import Path

# Cargar .cybershop.conf
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.cybershop.conf')

# Importar desde servicios
sys.path.insert(0, str(Path(__file__).parent.parent))
from services.db_layer import control_plane_cursor


KEY_PREFIX = 'cyb_live_'
CLIENT_CODE_PREFIX = 'CYB'


def generate_api_key():
    """Devuelve un api_key completo de la forma 'cyb_live_<32 chars urlsafe>'."""
    return KEY_PREFIX + secrets.token_urlsafe(24).replace('-', '').replace('_', '')[:32]


def generate_client_code():
    """Código corto para que el cliente teclee en /descargar.
    Formato: CYB-XXXXXXXX (8 chars alfanuméricos en mayúsculas)."""
    alphabet = '23456789ABCDEFGHJKMNPQRSTUVWXYZ'  # sin 0/O/1/I/L para evitar confusión
    code = ''.join(secrets.choice(alphabet) for _ in range(8))
    return f'{CLIENT_CODE_PREFIX}-{code}'


def hash_key(raw_key):
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant-slug', required=True,
                        help='Slug del tenant (ej. cyber-t001).')
    parser.add_argument('--label', default='',
                        help='Etiqueta descriptiva (ej. "POS Tienda Centro").')
    args = parser.parse_args()

    with control_plane_cursor() as cur:
        cur.execute(
            'SELECT id, nombre FROM tenants WHERE slug = %s',
            (args.tenant_slug,),
        )
        tenant = cur.fetchone()
        if not tenant:
            print(f"ERROR: tenant '{args.tenant_slug}' no existe.", file=sys.stderr)
            sys.exit(1)
        tenant_id = tenant['id']
        tenant_nombre = tenant['nombre']

        # Generar key con reintento si por azar el client_code colisiona
        for _ in range(5):
            api_key = generate_api_key()
            client_code = generate_client_code()
            try:
                cur.execute("""
                    INSERT INTO sync_api_keys
                      (tenant_id, key_hash, key_prefix, client_code, label)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    tenant_id,
                    hash_key(api_key),
                    api_key[:12],
                    client_code,
                    args.label.strip() or None,
                ))
                key_id = cur.fetchone()['id']
                break
            except Exception as exc:  # noqa: BLE001
                if 'unique' in str(exc).lower() or 'duplicate' in str(exc).lower():
                    cur.connection.rollback()
                    continue
                raise
        else:
            print('ERROR: no se pudo generar un client_code único tras 5 intentos.', file=sys.stderr)
            sys.exit(1)

    print()
    print('────────────────────────────────────────────────────────')
    print(f'  Tenant:      {args.tenant_slug} ({tenant_nombre})')
    print(f'  Key ID:      {key_id}')
    if args.label:
        print(f'  Etiqueta:    {args.label}')
    print(f'  Client code: {client_code}')
    print(f'  API key:     {api_key}')
    print('────────────────────────────────────────────────────────')
    print()
    print('IMPORTANTE: la API key NO se vuelve a mostrar. Copiala ahora.')
    print('Entrega al cliente solamente el client code para que descargue su instalador desde /descargar.')


if __name__ == '__main__':
    main()
