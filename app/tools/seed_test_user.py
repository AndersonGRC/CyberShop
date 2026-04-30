"""
Crea un usuario de pruebas en saas_control_plane.usuarios_globales.

Uso:
    python tools/seed_test_user.py --email test@cybershop.com --password TuPassword123

Requerido: saas_control_plane ya configurada + al menos 1 tenant en tenants.
"""

import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.cybershop.conf')

sys.path.insert(0, str(Path(__file__).parent.parent))
from services.db_layer import control_plane_cursor
from werkzeug.security import generate_password_hash


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--email',     required=True)
    p.add_argument('--password',  required=True)
    p.add_argument('--rol_id',    type=int, default=1, help='1=SuperAdmin, 2=Propietario, etc.')
    p.add_argument('--tenant_id', type=int, default=1)
    args = p.parse_args()

    hashed = generate_password_hash(args.password)

    try:
        with control_plane_cursor() as cur:
            cur.execute("SELECT id FROM tenants WHERE id = %s", (args.tenant_id,))
            if not cur.fetchone():
                print(f"ERROR: tenant_id={args.tenant_id} no existe en tenants.")
                sys.exit(1)

            cur.execute("SELECT id FROM usuarios_globales WHERE email = %s", (args.email,))
            if cur.fetchone():
                print(f"Usuario {args.email} ya existe. Actualizando contraseña...")
                cur.execute(
                    "UPDATE usuarios_globales SET contraseña = %s WHERE email = %s",
                    (hashed, args.email)
                )
            else:
                cur.execute(
                    """
                    INSERT INTO usuarios_globales (email, contraseña, tenant_id, rol_id)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (args.email, hashed, args.tenant_id, args.rol_id)
                )
                print(f"[NUEVO] Usuario {args.email} creado (rol_id={args.rol_id}, tenant_id={args.tenant_id}).")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
