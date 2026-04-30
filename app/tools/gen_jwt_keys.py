"""
Genera el par de claves RSA para JWT RS256 de CyberShop.

Uso:
    python tools/gen_jwt_keys.py

Crea:
    app/keys/jwt_private.pem   (mantener SECRETO, permisos 600)
    app/keys/jwt_public.pem    (puede compartirse con clientes desktop en Fase 4)

Luego añadir al .cybershop.conf:
    JWT_PRIVATE_KEY_PATH=<ruta absoluta>/app/keys/jwt_private.pem
    JWT_PUBLIC_KEY_PATH=<ruta absoluta>/app/keys/jwt_public.pem
"""

import os
import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
except ImportError:
    print("ERROR: instala cryptography: pip install cryptography")
    sys.exit(1)

KEYS_DIR = Path(__file__).parent.parent / 'keys'
PRIVATE_PATH = KEYS_DIR / 'jwt_private.pem'
PUBLIC_PATH  = KEYS_DIR / 'jwt_public.pem'


def main():
    KEYS_DIR.mkdir(exist_ok=True)

    if PRIVATE_PATH.exists():
        answer = input(f"Ya existe {PRIVATE_PATH}. ¿Reemplazar? [s/N]: ").strip().lower()
        if answer != 's':
            print("Cancelado.")
            return

    print("Generando par de claves RSA 2048 bits...")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Guardar clave privada
    with open(PRIVATE_PATH, 'wb') as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    os.chmod(PRIVATE_PATH, 0o600)

    # Guardar clave pública
    with open(PUBLIC_PATH, 'wb') as f:
        f.write(private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ))

    print(f"  Privada : {PRIVATE_PATH}  (chmod 600 aplicado)")
    print(f"  Pública : {PUBLIC_PATH}")
    print()
    print("Añadir al .cybershop.conf:")
    print(f"  JWT_PRIVATE_KEY_PATH={PRIVATE_PATH.resolve()}")
    print(f"  JWT_PUBLIC_KEY_PATH={PUBLIC_PATH.resolve()}")


if __name__ == '__main__':
    main()
